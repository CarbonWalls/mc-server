import os
import re
import shutil
import time
from pathlib import Path

from . import backup, config, download, paths, procs, version

INDEX_NAME = "index.json"
ROOTS_NAME = "roots.json"
# The self-identifying marker dropped into every instance folder. The index is
# a cache of these; the marker is the identity. See read_marker()/rescan().
MARKER_NAME = ".mctui-instance.json"
MARKER_SCHEMA = 1
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
RESERVED = {paths.MAIN_INSTANCE_ID, "active", "index.json"}


class InstanceSchemaError(Exception):
    """A marker is newer than this code understands - refuse to misread it."""


def index_path() -> Path:
    return paths.instances_dir() / INDEX_NAME


def roots_path() -> Path:
    return paths.data_dir() / ROOTS_NAME


# --- marker: the identity of an instance -------------------------------------
def marker_path(instance_dir) -> Path:
    return Path(instance_dir) / MARKER_NAME


def write_marker(entry: dict, instance_dir) -> dict:
    """Write the marker that makes a folder recognisable as an instance.

    The marker holds the metadata (id, name, paper version, ...) but NOT the
    location: that comes from the folder the marker sits in, so a moved server
    is still found by a re-scan.
    """
    record = {k: v for k, v in (entry or {}).items()
              if k not in ("path", "missing", "unreadable")}
    record["schema"] = MARKER_SCHEMA
    try:
        config.write_json(marker_path(instance_dir), record, with_backup=False)
        return {"ok": True, "path": str(marker_path(instance_dir))}
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def read_marker(instance_dir):
    """Read an instance marker.

    Returns None when the folder holds no marker (not an instance). Raises
    InstanceSchemaError when the marker's schema is newer than this code
    understands - that must never be silently downgraded.
    """
    data = config.read_json(marker_path(instance_dir))
    if data is None:
        return None
    if not isinstance(data, dict):
        raise InstanceSchemaError(
            f"{marker_path(instance_dir)} is not a JSON object")
    schema = data.get("schema")
    try:
        schema = int(schema) if schema is not None else 0
    except (TypeError, ValueError):
        schema = 0
    if schema > MARKER_SCHEMA:
        raise InstanceSchemaError(
            f"{marker_path(instance_dir)} uses schema {schema}, this build "
            f"understands up to {MARKER_SCHEMA} - upgrade mc_tui before "
            f"touching this instance")
    return data


def _stored_location(instance_dir: Path) -> str:
    """How a resolved instance dir is stored in the index: relative to the
    project root when it lives inside it, absolute when it does not. This
    round-trips with paths.resolve_path()."""
    try:
        return str(Path(instance_dir).relative_to(paths.PROJECT_ROOT))
    except ValueError:
        return str(Path(instance_dir).resolve())


def _marker_to_entry(marker: dict, instance_dir: Path) -> dict:
    entry = dict(marker)
    entry.pop("schema", None)
    entry["path"] = _stored_location(instance_dir)
    return entry


# --- roots: the only list the tool is ever allowed to search ------------------
def known_roots() -> list:
    data = config.read_json(roots_path())
    out = []
    for raw in data if isinstance(data, list) else []:
        try:
            out.append(Path(str(raw)))
        except (TypeError, ValueError):
            pass
    return out


def remember_root(path) -> None:
    """Record a distinct parent directory an instance was created under. Only
    these are ever walked by rescan()."""
    parent = Path(path).parent
    roots = [p for p in known_roots() if p != parent]
    roots.append(parent)
    try:
        config.write_json(roots_path(), [str(p) for p in roots], with_backup=False)
    except OSError:
        pass


def _default_location(instance_id: str) -> Path:
    """The default home for a brand-new instance id."""
    return paths.resolve_path(f"instances/{instance_id}")


def resolve_location(spec_or_path) -> Path:
    """Where an instance will live, given a spec dict (with a 'path' key) or a
    raw location string. Empty/absent means the default instances/<id>."""
    if isinstance(spec_or_path, dict):
        instance_id = spec_or_path.get("id", "")
        loc = (spec_or_path.get("path") or "").strip()
        if not loc:
            return _default_location(str(instance_id))
        return paths.resolve_path(loc)
    loc = (str(spec_or_path or "")).strip()
    return paths.resolve_path(loc) if loc else paths.instances_dir()


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
    # Defect D: never synthesise a phantom main. Only the built-in server/
    # folder is implied, and only when it actually exists - otherwise an
    # empty checkout shows a dashboard pointing at nothing.
    if main_entry is None and paths.server_dir().is_dir():
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
        "paper_version": version.detect_paper_version(paths.server_dir()),
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
    """THE resolver: instance id -> absolute folder. Every caller that needs
    an instance on disk goes through here; nothing re-derives instances/<id>.
    """
    if instance_id == paths.MAIN_INSTANCE_ID:
        return paths.server_dir()
    entry = get_instance(instance_id)
    if entry and entry.get("path"):
        return paths.resolve_path(entry["path"])
    return _default_location(str(instance_id))


def validate_path(location: str, instance_id: str = "") -> str:
    """Validate a custom instance location. Empty means 'use the default'.

    Checks: resolvable, not a file, not already a non-empty folder, not inside
    another instance, parent exists and is writable.
    """
    loc = (location or "").strip()
    if not loc:
        return ""
    target = paths.resolve_path(loc)
    if target == paths.server_dir():
        return f"{target} is the built-in server folder"
    for entry in load_index()["instances"]:
        other = entry.get("id", "")
        if not other or other == instance_id or other == paths.MAIN_INSTANCE_ID:
            continue
        other_dir = path_of(other)
        try:
            target.relative_to(other_dir)
            return f"{target} is inside the existing instance '{other}'"
        except ValueError:
            pass
    if target.is_file():
        return f"{target} is a file, not a folder"
    if target.is_dir() and any(target.iterdir()):
        return f"{target} already exists and is not empty"
    parent = target.parent
    if not parent.exists():
        return f"parent folder {parent} does not exist"
    if not os.access(parent, os.W_OK):
        return f"cannot write to {parent}"
    return ""


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
    target = path_of(instance_id)
    link = paths.active_link()
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
    except OSError as exc:
        return {"ok": True, "warning": f"active recorded but symlink failed: {exc}"}
    return {"ok": True, "instance": instance_id, "path": str(target)}


# --- rescan / adopt: the index is a cache, the marker is the truth -----------
def _scan_dir(directory: Path) -> list:
    """Markers directly inside this directory (never recursive)."""
    out = []
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return out
    for child in entries:
        if not child.is_dir():
            continue
        marker_file = marker_path(child)
        if not marker_file.is_file():
            continue
        try:
            marker = read_marker(child)
        except InstanceSchemaError as exc:
            out.append({"ok": False, "error": str(exc), "path": str(child)})
            continue
        if not marker:
            continue
        out.append({"ok": True, "entry": _marker_to_entry(marker, child),
                    "path": str(child)})
    return out


def rescan() -> dict:
    """Rebuild index.json from the markers in the known roots.

    Never walks the filesystem outside those roots. Returns a report of found
    instances and any errors (a schema-too-new marker does not stop the scan).
    """
    found = []
    errors = []
    for root in known_roots():
        for hit in _scan_dir(root):
            if hit.get("ok"):
                found.append(hit["entry"])
            else:
                errors.append(hit)
    for hit in _scan_dir(paths.PROJECT_ROOT):
        # the built-in server/ is always checked, even if no root records it
        if hit.get("ok"):
            found.append(hit["entry"])
        else:
            errors.append(hit)

    # dedupe by id (a marker could sit in several scanned dirs), main first
    by_id = {}
    for entry in found:
        if entry.get("id") not in by_id:
            by_id[entry.get("id")] = entry
        else:
            errors.append({"ok": False,
                           "error": f"duplicate marker for {entry.get('id')}",
                           "path": entry.get("path", "")})
    # the built-in server/ is always part of the index when it exists; a
    # markerless one (set up before markers existed) still resolves to main
    if paths.server_dir().is_dir() and paths.MAIN_INSTANCE_ID not in by_id:
        by_id[paths.MAIN_INSTANCE_ID] = _main_entry()
    instances = sorted(by_id.values(), key=lambda e: (
        e.get("id") != paths.MAIN_INSTANCE_ID, str(e.get("id", ""))))
    index = {"version": 1, "instances": instances}
    save_index(index)
    return {"ok": not errors, "instances": instances,
            "count": len(instances), "errors": errors}


def adopt(folder: str, instance_id: str = "") -> dict:
    """Take over a folder that already holds an instance marker.

    Used for "I moved my server" (the marker travels with the folder) and
    "this folder already is one, register it". The marker is the identity - a
    folder without a marker is not adopted unless force_marker=True writes one.
    """
    target = paths.resolve_path(folder)
    if not target.is_dir():
        return {"ok": False, "error": f"{target} is not a folder"}
    try:
        marker = read_marker(target)
    except InstanceSchemaError as exc:
        return {"ok": False, "error": str(exc)}
    if not marker:
        return {"ok": False,
                "error": f"no {MARKER_NAME} in {target} - not an instance folder",
                "needs_marker": True, "path": str(target)}
    marker_id = str(marker.get("id") or instance_id or target.name)
    if marker_id != marker.get("id"):
        marker["id"] = marker_id
    error = validate_name(marker_id)
    if error and get_instance(marker_id) is None:
        return {"ok": False, "error": f"cannot register as '{marker_id}': {error}"}
    if not marker.get("created"):
        marker["created"] = _now()
    entry = _marker_to_entry(marker, target)
    remember_root(target)
    index = load_index()
    known = [e for e in index["instances"] if e.get("id") != entry["id"]]
    known.append(entry)
    index["instances"] = sorted(known, key=lambda e: (
        e.get("id") != paths.MAIN_INSTANCE_ID, str(e.get("id", ""))))
    save_index(index)
    return {"ok": True, "instance": entry, "path": str(target)}


def rebuild_index_if_missing() -> bool:
    """A deleted index.json is not a disaster: rebuild it from the markers."""
    if index_path().is_file():
        return False
    rescan()
    return True


def ensure_main_marker() -> dict:
    """Give the built-in server/ folder its marker, once. Idempotent, safe to
    call on every bootstrap. Does not touch the index (load_index synthesises
    the main entry in memory when server/ exists)."""
    server = paths.server_dir()
    if not server.is_dir():
        return {"ok": False, "error": "no server folder yet"}
    try:
        marker = read_marker(server)
    except InstanceSchemaError as exc:
        return {"ok": False, "error": str(exc)}
    if marker:
        return {"ok": True, "already": True}
    entry = _main_entry()
    out = write_marker(entry, server)
    out["entry"] = entry
    return out


def register_main() -> dict:
    """Make sure the built-in main instance is in the index. Idempotent."""
    index = load_index()
    if any(e.get("id") == paths.MAIN_INSTANCE_ID for e in index["instances"]):
        return {"ok": True, "already": True}
    entry = _main_entry()
    index["instances"].insert(0, entry)
    save_index(index)
    return {"ok": True, "entry": entry}


def active_id() -> str:
    return str(paths.load_settings().get("active_instance", paths.MAIN_INSTANCE_ID))


def _download_plugin(job, url, dest, entry, frac: float, span: float,
                     total_bytes: int) -> dict:
    """Download one plugin, reporting byte-level progress inside its slice
    [frac, frac+span] of the whole build (Phase 5: no silent downloads)."""
    label = entry.get("name") or entry.get("id") or Path(dest).stem
    size = int(entry.get("size") or 0) or total_bytes

    def progress(done, total):
        job.update(frac + span * (done / max(total or size or 1, 1)),
                   f"{label} {done // 1048576}/{(total or size or 0) // 1048576} MB")

    try:
        res = download.download(url, dest,
                                sha256=entry.get("sha256") or None,
                                sha512=entry.get("sha512") or None,
                                expected_size=entry.get("size") or None,
                                timeout=900, on_progress=progress)
        return {"id": entry.get("id"), "ok": True, "size": res["size"],
                "verified": res["verified"]}
    except download.DownloadError as exc:
        return {"id": entry.get("id"), "ok": False, "error": str(exc)}


def build_instance(job, spec: dict) -> dict:
    instance_id = spec["id"]
    target = resolve_location(spec)
    if target == paths.server_dir():
        return {"ok": False, "error": "the built-in server folder cannot be reused"}
    if target.exists():
        return {"ok": False, "error": f"{target} already exists"}
    error = validate_name(instance_id)
    if error:
        return {"ok": False, "error": error}
    loc_error = validate_path(str(spec.get("path") or ""), instance_id)
    if loc_error:
        return {"ok": False, "error": loc_error}
    paper = spec.get("paper") or {}
    paper_size = int(paper.get("size") or 0)
    plugin_specs = spec.get("plugin_specs") or []
    plugin_sizes = sum(int(p.get("size") or 0) for p in plugin_specs if "url" in p)
    need = paper_size + plugin_sizes + 96 * 1024 * 1024
    space = backup.check_space(need, target.parent)
    if not space["ok"]:
        return {"ok": False, "error": f"not enough free space: {space['message']}"}

    job.update(0.02, f"creating folder tree at {target}")
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
        job.update(0.70, "installing Geyser + Floodgate")
        span = 0.10 / 2.0
        for i, pid in enumerate(("geyser", "floodgate")):
            entry = next((p for p in plugin_specs if p.get("id") == pid), None)
            if not entry or not entry.get("url"):
                results["plugins"].append({"id": pid, "ok": False, "error": "unresolved"})
                continue
            dest = target / "plugins" / entry.get("filename", f"{pid}.jar")
            outcome = _download_plugin(job, entry["url"], dest, entry,
                                       0.70 + i * span, span, plugin_sizes)
            results["plugins"].append(outcome)
        job.update(0.80, "writing Geyser config")
        _write_geyser_config(target, geyser)

    wanted = spec.get("plugins")
    # Defect E: None means "unspecified" (install the resolved set), an empty
    # list means the user deselected every optional plugin (install none).
    if wanted is None:
        wanted = [p.get("id") for p in plugin_specs if p.get("url")]
    queue = [e for e in plugin_specs
             if e.get("id") not in ("geyser", "floodgate")
             and (not wanted or e.get("id") in wanted)]
    for i, entry in enumerate(queue):
        if not entry.get("url"):
            results["plugins"].append({"id": entry.get("id"), "ok": False,
                                       "error": "unresolved"})
            continue
        dest = target / "plugins" / entry.get("filename", f"{entry['id']}.jar")
        # each optional plugin gets an equal slice of 0.85..0.93
        span = 0.08 / max(len(queue), 1)
        outcome = _download_plugin(job, entry["url"], dest, entry,
                                   0.85 + i * span, span, plugin_sizes)
        results["plugins"].append(outcome)

    job.update(0.93, "registering instance")
    entry = {
        "id": instance_id,
        "name": spec.get("name") or instance_id,
        "path": _stored_location(target),
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
    # Phase 4a: the folder self-identifies, and its parent becomes a known
    # root so a future re-scan finds it again without searching the disk.
    write_marker(entry, target)
    remember_root(target)
    add_instance(entry)
    job.update(1.0, f"created {instance_id}")
    results.update({"ok": True, "instance": entry, "path": str(target)})
    return results


def _write_geyser_config(target: Path, geyser: dict) -> dict:
    """Write the Geyser config for a new instance.

    The whole config is generated rather than copied from a template and then
    patched: on a raw machine no template exists, and patching the thin
    fallback used to omit ``advanced.bedrock.use-haproxy-protocol`` and
    ``clone-remote-port`` entirely. Every key the contract needs is written
    here, so nothing has to be spliced in later (that splicing was what
    produced the duplicate ``advanced:`` root key).
    """
    port = int(geyser.get("port") or 19132)
    # broadcast-port is the public port the tunnel assigns. It is not known at
    # build time, so the local bedrock port stands in until a tunnel reports
    # one (apply_tunnel_port() rewrites it then).
    broadcast = int(geyser.get("broadcast_port") or 0) or port
    floodgate = bool(geyser.get("floodgate"))
    auth = str(geyser.get("auth_type") or ("floodgate" if floodgate else "offline"))
    transport = str(geyser.get("transport") or "raknet")
    # proxy-protocol v2 is spoken by the playit tunnel on the Bedrock side
    # (so Geyser sees the real player IP); the Paper server itself does not.
    java_haproxy = "true" if geyser.get("haproxy") else "false"
    text = (
        "# Geyser configuration - written by mc_tui.\n"
        "# See docs/PORT_SETUP.md for the playit tunnel settings this expects.\n"
        "bedrock:\n"
        "  address: 0.0.0.0\n"
        f"  port: {port}\n"
        f"  transport: {transport}\n"
        "  clone-remote-port: false\n"
        "java:\n"
        "  address: 127.0.0.1\n"
        "  port: 25565\n"
        f"  auth-type: {auth}\n"
        "advanced:\n"
        "  java:\n"
        f"    use-haproxy-protocol: {java_haproxy}\n"
        "  bedrock:\n"
        f"    broadcast-port: {broadcast}\n"
        "    use-haproxy-protocol: true\n"
        "config-version: 8\n"
    )
    config_dir = target / "plugins" / "Geyser-Spigot"
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        config.write_text(config_dir / "config.yml", text, with_backup=False)
        return {"ok": True, "path": str(config_dir / "config.yml")}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def apply_tunnel_port(instance_id: str, public_port: int) -> dict:
    """Write the port the tunnel actually assigned into Geyser's
    broadcast-port (Defect I). Returns whether anything changed."""
    if not instance_id or not (1 <= int(public_port or 0) <= 65535):
        return {"ok": False, "error": "invalid port"}
    target = path_of(instance_id)
    cfg = target / "plugins" / "Geyser-Spigot" / "config.yml"
    if not cfg.is_file():
        return {"ok": False, "error": f"no Geyser config at {cfg}"}
    res = config.yaml_set_file(cfg, ["advanced", "bedrock", "broadcast-port"],
                               str(int(public_port)))
    if res["changed"]:
        update_instance(instance_id, bedrock_port=int(public_port))
    return {"ok": True, "changed": res["changed"], "port": int(public_port),
            "path": str(cfg)}


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
    target = _default_location(new_id)
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
        "path": _stored_location(target),
        "created": _now(),
        "note": f"clone of {instance_id}",
        "builtin": False,
    })
    entry.pop("missing", None)
    write_marker(entry, target)
    remember_root(target)
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
    target = _default_location(new_id)
    if target.exists():
        return {"ok": False, "error": f"{target} already exists"}
    if procs.classify(procs.read_pid(paths.log_paths(instance_id)["server_pid"]), "paper.jar") == "running":
        return {"ok": False, "error": "stop the server before renaming"}
    if source.exists():
        try:
            os.replace(source, target)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        # the marker carries the id, so it must be rewritten for the new one
        try:
            marker = read_marker(target)
        except InstanceSchemaError as exc:
            return {"ok": False, "error": str(exc)}
        if marker:
            marker["id"] = new_id
            marker["name"] = new_id
            write_marker(marker, target)
    update_instance(instance_id, id=new_id, name=new_id,
                    path=_stored_location(target))
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
