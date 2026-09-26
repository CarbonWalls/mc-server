import os
import re
import shutil
import time
from pathlib import Path

from . import backup, config, download, paths, procs, version

INDEX_NAME = "index.json"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
RESERVED = {paths.MAIN_INSTANCE_ID, "active", "index.json"}


def index_path() -> Path:
    return paths.instances_dir() / INDEX_NAME


def load_index() -> dict:
    data = config.read_json(index_path())
    if not isinstance(data, dict):
        data = {}
    instances = data.get("instances")
    if not isinstance(instances, list):
        instances = []
    main_entry = None
    for entry in instances:
        if entry.get("id") == paths.MAIN_INSTANCE_ID:
            main_entry = entry
            break
    if main_entry is None:
        main_entry = _main_entry()
        instances.insert(0, main_entry)
    data["version"] = 1
    data["instances"] = instances
    return data


def _main_entry() -> dict:
    return {
        "id": paths.MAIN_INSTANCE_ID,
        "name": "Main Server",
        "path": "server",
        "created": _now(),
        "paper_version": version.detect_paper_version(paths.server_dir()) or "26.2",
        "note": "original instance (this folder's server/ directory)",
        "builtin": True,
    }


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def save_index(index: dict) -> None:
    config.write_json(index_path(), index)


def get_instance(instance_id: str) -> dict | None:
    for entry in load_index().get("instances", []):
        if entry.get("id") == instance_id:
            return entry
    return None


def path_of(instance_id: str) -> Path:
    entry = get_instance(instance_id)
    if entry:
        return paths.PROJECT_ROOT / entry.get("path", "")
    if instance_id == paths.MAIN_INSTANCE_ID:
        return paths.server_dir()
    return paths.instances_dir() / instance_id


def validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "name is empty"
    if not NAME_RE.match(name):
        return "use letters, digits, - or _ (max 32, must start with a letter or digit)"
    if name.lower() in RESERVED:
        return f"'{name}' is reserved"
    existing = {e.get("id", "").lower() for e in load_index()["instances"]}
    if name.lower() in existing:
        return f"an instance named '{name}' already exists"
    if path_of(name).exists():
        return f"{path_of(name)} already exists"
    return ""


def add_instance(entry: dict) -> dict:
    index = load_index()
    index["instances"].append(entry)
    save_index(index)
    return entry


def update_instance(instance_id: str, **fields) -> bool:
    index = load_index()
    for entry in index["instances"]:
        if entry.get("id") == instance_id:
            entry.update(fields)
            save_index(index)
            return True
    return False


def set_active(instance_id: str) -> dict:
    entry = get_instance(instance_id)
    if not entry:
        return {"ok": False, "error": f"unknown instance '{instance_id}'"}
    settings = paths.load_settings()
    settings["active_instance"] = instance_id
    paths.save_settings(settings)
    target = paths.PROJECT_ROOT / entry.get("path", "")
    link = paths.active_link()
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
    except OSError as exc:
        return {"ok": True, "warning": f"active recorded but symlink failed: {exc}"}
    return {"ok": True, "instance": instance_id, "path": str(target)}


def active_id() -> str:
    return str(paths.load_settings().get("active_instance", paths.MAIN_INSTANCE_ID))


def build_instance(job, spec: dict) -> dict:
    instance_id = spec["id"]
    target = paths.instances_dir() / instance_id
    if target.exists():
        return {"ok": False, "error": f"{target} already exists"}
    error = validate_name(instance_id)
    if error:
        return {"ok": False, "error": error}
    paper = spec.get("paper") or {}
    paper_size = int(paper.get("size") or 0)
    plugin_specs = spec.get("plugin_specs") or []
    plugin_sizes = sum(int(p.get("size") or 0) for p in plugin_specs if "url" in p)
    need = paper_size + plugin_sizes + 96 * 1024 * 1024
    space = backup.check_space(need, target.parent)
    if not space["ok"]:
        return {"ok": False, "error": f"not enough free space: {space['message']}"}

    job.update(0.02, "creating folder tree")
    try:
        (target / "plugins").mkdir(parents=True, exist_ok=True)
        (target / "logs").mkdir(exist_ok=True)
        (target / "config").mkdir(exist_ok=True)
        (target / "eula.txt").write_text("eula=true\n")
    except OSError as exc:
        return {"ok": False, "error": f"could not create {target}: {exc}"}

    if paper.get("url"):
        def paper_progress(done, total):
            job.update(0.05 + 0.55 * (done / max(total, 1)),
                       f"paper {done // 1048576}/{(total or 0) // 1048576} MB")

        try:
            download.download(paper["url"], target / "paper.jar",
                              sha256=paper.get("sha256") or None,
                              expected_size=paper.get("size") or None,
                              on_progress=paper_progress, timeout=900)
        except download.DownloadError as exc:
            shutil.rmtree(target, ignore_errors=True)
            return {"ok": False, "error": f"paper download failed: {exc}"}
    else:
        shutil.rmtree(target, ignore_errors=True)
        return {"ok": False, "error": "no paper download URL selected"}

    job.update(0.62, "writing server.properties")
    props = dict(spec.get("properties") or {})
    props.setdefault("server-port", str(spec.get("server_port", 25565)))
    try:
        config.write_properties(target / "server.properties", props,
                                header="#Minecraft server properties (created by mc_tui)")
    except OSError as exc:
        return {"ok": False, "error": f"could not write server.properties: {exc}"}

    results = {"jar": str(target / "paper.jar"), "plugins": []}

    geyser = spec.get("geyser") or {}
    if geyser.get("install"):
        job.update(0.7, "installing Geyser + Floodgate")
        for pid in ("geyser", "floodgate"):
            entry = next((p for p in plugin_specs if p.get("id") == pid), None)
            if not entry or not entry.get("url"):
                results["plugins"].append({"id": pid, "ok": False, "error": "unresolved"})
                continue
            dest = target / "plugins" / entry.get("filename", f"{pid}.jar")
            try:
                res = download.download(entry["url"], dest,
                                        expected_size=entry.get("size") or None,
                                        timeout=900)
                results["plugins"].append({"id": pid, "ok": True, "size": res["size"],
                                           "verified": res["verified"]})
            except download.DownloadError as exc:
                results["plugins"].append({"id": pid, "ok": False, "error": str(exc)})
        job.update(0.8, "writing Geyser config")
        _write_geyser_config(target, geyser)

    wanted = spec.get("plugins") or []
    for entry in plugin_specs:
        if entry.get("id") in ("geyser", "floodgate"):
            continue
        if wanted and entry.get("id") not in wanted:
            continue
        if not entry.get("url"):
            results["plugins"].append({"id": entry.get("id"), "ok": False, "error": "unresolved"})
            continue
        dest = target / "plugins" / entry.get("filename", f"{entry['id']}.jar")
        job.update(0.85, f"downloading {entry.get('name', entry['id'])}")
        try:
            res = download.download(entry["url"], dest,
                                    sha512=entry.get("sha512") or None,
                                    expected_size=entry.get("size") or None,
                                    timeout=600)
            results["plugins"].append({"id": entry["id"], "ok": True, "size": res["size"],
                                       "verified": res["verified"]})
        except download.DownloadError as exc:
            results["plugins"].append({"id": entry["id"], "ok": False, "error": str(exc)})

    job.update(0.93, "registering instance")
    entry = {
        "id": instance_id,
        "name": spec.get("name") or instance_id,
        "path": f"instances/{instance_id}",
        "created": _now(),
        "paper_version": str((paper.get("version") or "")),
        "build": paper.get("number"),
        "motd": spec.get("motd", ""),
        "tunnel": spec.get("tunnel", "none"),
        "perf_preset": (spec.get("perf") or {}).get("preset", ""),
        "geyser": bool(geyser.get("install")),
        "bedrock_port": geyser.get("port") if geyser.get("install") else None,
        "note": spec.get("note", ""),
    }
    add_instance(entry)
    job.update(1.0, f"created {instance_id}")
    results.update({"ok": True, "instance": entry, "path": str(target)})
    return results


def _write_geyser_config(target: Path, geyser: dict) -> dict:
    template = paths.server_dir() / "plugins" / "Geyser-Spigot" / "config.yml"
    config_dir = target / "plugins" / "Geyser-Spigot"
    config_dir.mkdir(parents=True, exist_ok=True)
    dest = config_dir / "config.yml"
    if template.exists():
        shutil.copy2(template, dest)
    else:
        dest.write_text(
            "bedrock:\n  address: 0.0.0.0\n  port: 19132\n  transport: raknet\n"
            "java:\n  auth-type: offline\nadvanced:\n  java:\n    use-haproxy-protocol: false\n"
            "  bedrock:\n    broadcast-port: 0\nconfig-version: 8\n"
        )
    port = str(int(geyser.get("port", 19132)))
    broadcast = str(int(geyser.get("broadcast_port") or port))
    auth = str(geyser.get("auth_type", "offline"))
    transport = str(geyser.get("transport", "raknet"))
    haproxy = "true" if geyser.get("haproxy") else "false"
    try:
        config.yaml_set_file(dest, ["bedrock", "port"], port)
        config.yaml_set_file(dest, ["advanced", "bedrock", "broadcast-port"], broadcast)
        config.yaml_set_file(dest, ["java", "auth-type"], auth)
        config.yaml_set_file(dest, ["bedrock", "transport"], transport)
        config.yaml_set_file(dest, ["advanced", "java", "use-haproxy-protocol"], haproxy)
        config.yaml_set_file(dest, ["advanced", "bedrock", "use-haproxy-protocol"], haproxy)
        return {"ok": True, "path": str(dest)}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def clone(instance_id: str, new_id: str) -> dict:
    error = validate_name(new_id)
    if error:
        return {"ok": False, "error": error}
    source = path_of(instance_id)
    if not source.exists():
        return {"ok": False, "error": f"{source} does not exist"}
    need = backup.estimate(source)
    space = backup.check_space(need, paths.instances_dir())
    if not space["ok"]:
        return {"ok": False, "error": f"not enough free space: {space['message']}"}
    target = paths.instances_dir() / new_id
    if target.exists():
        return {"ok": False, "error": f"{target} already exists"}
    try:
        shutil.copytree(source, target, symlinks=True)
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True)
        return {"ok": False, "error": f"clone failed: {exc}"}
    original = get_instance(instance_id) or _main_entry()
    entry = dict(original)
    entry.update({
        "id": new_id,
        "name": new_id,
        "path": f"instances/{new_id}",
        "created": _now(),
        "note": f"clone of {instance_id}",
        "builtin": False,
    })
    add_instance(entry)
    return {"ok": True, "instance": entry, "size": need}


def rename(instance_id: str, new_id: str) -> dict:
    if instance_id == paths.MAIN_INSTANCE_ID:
        return {"ok": False, "error": "the built-in main instance cannot be renamed"}
    entry = get_instance(instance_id)
    if not entry:
        return {"ok": False, "error": "instance not found"}
    if new_id != instance_id:
        error = validate_name(new_id)
        if error:
            return {"ok": False, "error": error}
    source = path_of(instance_id)
    target = paths.instances_dir() / new_id
    if target.exists():
        return {"ok": False, "error": f"{target} already exists"}
    if procs.classify(procs.read_pid(paths.log_paths(instance_id)["server_pid"]), "paper.jar") == "running":
        return {"ok": False, "error": "stop the server before renaming"}
    if source.exists():
        try:
            os.replace(source, target)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
    update_instance(instance_id, id=new_id, name=new_id, path=f"instances/{new_id}")
    if active_id() == instance_id:
        set_active(new_id)
    return {"ok": True, "from": instance_id, "to": new_id}


def delete(instance_id: str, make_backup: bool = True) -> dict:
    if instance_id == paths.MAIN_INSTANCE_ID:
        return {"ok": False, "error": "the built-in main instance cannot be deleted"}
    entry = get_instance(instance_id)
    if not entry:
        return {"ok": False, "error": "instance not found"}
    pid = procs.read_pid(paths.log_paths(instance_id)["server_pid"])
    if procs.classify(pid, "paper.jar") == "running":
        return {"ok": False, "error": "stop the server before deleting"}
    target = path_of(instance_id)
    archived = None
    if make_backup and target.exists():
        result = backup.estimate(target)
        space = backup.check_space(result, paths.backups_dir())
        if not space["ok"]:
            return {"ok": False, "error": f"not enough free space for safety backup: {space['message']}"}

        class _Job:
            def update(self, *a, **k):
                pass

        made = backup.create(_Job(), instance_id, target)
        if not made.get("ok"):
            return {"ok": False, "error": f"safety backup failed: {made.get('error')}"}
        archived = made["path"]
    try:
        if target.exists():
            shutil.rmtree(target)
    except OSError as exc:
        return {"ok": False, "error": f"could not remove {target}: {exc}"}
    index = load_index()
    index["instances"] = [e for e in index["instances"] if e.get("id") != instance_id]
    save_index(index)
    if active_id() == instance_id:
        set_active(paths.MAIN_INSTANCE_ID)
    return {"ok": True, "deleted": instance_id, "backup": archived or ""}


def change_paper_version(job, instance_id: str, build: dict) -> dict:
    target = path_of(instance_id)
    jar = target / "paper.jar"
    if not target.exists():
        return {"ok": False, "error": f"{target} does not exist"}
    pid = procs.read_pid(paths.log_paths(instance_id)["server_pid"])
    if procs.classify(pid, "paper.jar") == "running":
        return {"ok": False, "error": "stop the server before changing Paper version"}
    if jar.exists():
        dest_dir = paths.backups_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        backup_jar = dest_dir / f"{instance_id}-paper-{time.strftime('%Y%m%d-%H%M%S')}.jar"
        try:
            shutil.copy2(jar, backup_jar)
        except OSError as exc:
            return {"ok": False, "error": f"could not back up current jar: {exc}"}
    else:
        backup_jar = None

    def progress(done, total):
        job.update(0.05 + 0.85 * (done / max(total, 1)),
                   f"{done // 1048576}/{(total or 0) // 1048576} MB")

    try:
        res = download.download(build["url"], jar.with_name("paper.jar.new"),
                                sha256=build.get("sha256") or None,
                                expected_size=build.get("size") or None,
                                on_progress=progress, timeout=900)
    except download.DownloadError as exc:
        if backup_jar and backup_jar.exists() and not jar.exists():
            shutil.copy2(backup_jar, jar)
        return {"ok": False, "error": f"download failed: {exc}"}
    os.replace(jar.with_name("paper.jar.new"), jar)
    job.update(1.0, f"paper {build.get('number')} installed")
    update_instance(instance_id, paper_version=str(build.get("version", "")), build=build.get("number"))
    return {"ok": True, "jar": str(jar), "size": res["size"], "verified": res["verified"],
            "previous_backup": str(backup_jar) if backup_jar else "",
            "build": build.get("number")}


def summary(entry: dict) -> list:
    target = path_of(entry["id"])
    exists = target.exists()
    size = backup.estimate(target) if exists else 0
    pid = procs.read_pid(paths.log_paths(entry["id"])["server_pid"])
    state = procs.classify(pid, "paper.jar")
    return [
        ("id", entry.get("id", "")),
        ("name", entry.get("name", "")),
        ("path", paths.relative(target)),
        ("exists", "yes" if exists else "MISSING"),
        ("size", procs.format_bytes(size)),
        ("paper", str(entry.get("paper_version") or "?")),
        ("build", str(entry.get("build") or "-")),
        ("tunnel", str(entry.get("tunnel") or "-")),
        ("bedrock", str(entry.get("bedrock_port") or "-")),
        ("state", state),
        ("created", str(entry.get("created") or "-")),
        ("note", str(entry.get("note") or "-")),
    ]
