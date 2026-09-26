import os
import shutil
import tarfile
import time
from pathlib import Path

from . import paths

CHUNK = 65536
MIN_FREE = 256 * 1024 * 1024


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup_name(instance_id: str) -> str:
    return f"{instance_id}-{_stamp()}.tar.gz"


def estimate(source) -> int:
    total = 0
    base = Path(source)
    if not base.exists():
        return 0
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def check_space(need_bytes: int, path=None) -> dict:
    free = paths.free_bytes(path)
    ok = free > need_bytes + MIN_FREE
    return {"ok": ok, "free": free, "need": need_bytes,
            "message": f"free {paths_free(free)}, need {paths_free(need_bytes)} + headroom"}


def paths_free(value: int) -> str:
    from . import procs

    return procs.format_bytes(value)


def create(job, instance_id: str, source, dest_dir=None, exclude: set | None = None) -> dict:
    source = Path(source)
    if not source.exists():
        return {"ok": False, "error": f"{source} does not exist"}
    dest = Path(dest_dir) if dest_dir else paths.backups_dir()
    dest.mkdir(parents=True, exist_ok=True)
    size = estimate(source)
    space = check_space(size, dest)
    if not space["ok"]:
        return {"ok": False, "error": f"not enough free space: {space['message']}"}
    target = dest / backup_name(instance_id)
    job.update(0.02, "starting archive")
    total = max(size, 1)
    done = 0
    exclude = exclude or set()
    try:
        with tarfile.open(target, "w:gz", compresslevel=6) as tar:
            for entry in sorted(source.rglob("*")):
                if entry.name in exclude or any(part in exclude for part in entry.parts):
                    continue
                try:
                    size_entry = entry.stat().st_size if entry.is_file() else 0
                except OSError:
                    continue
                try:
                    tar.add(entry, arcname=f"{source.name}/{entry.relative_to(source)}", recursive=False)
                except OSError:
                    continue
                done += size_entry
                job.update(min(0.95, 0.05 + 0.9 * (done / total)), f"archiving {entry.name}")
    except (OSError, tarfile.TarError) as exc:
        try:
            target.unlink()
        except OSError:
            pass
        return {"ok": False, "error": f"archive failed: {exc}"}
    final = target.stat().st_size
    job.update(1.0, f"created {target.name}")
    return {
        "ok": True,
        "path": str(target),
        "name": target.name,
        "size": final,
        "source_size": size,
        "instance": instance_id,
    }


def list_backups(instance_id: str | None = None) -> list:
    out = []
    dest = paths.backups_dir()
    if not dest.is_dir():
        return out
    owners = _known_owners()
    for p in sorted(dest.glob("*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True):
        owner = _owner_of(p.name, owners)
        if instance_id and owner != instance_id:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        out.append({
            "path": p,
            "name": p.name,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "instance": owner,
            "stamp": _parse_stamp(p.name),
        })
    return out


def _known_owners() -> list:
    from . import instances

    try:
        index = instances.load_index()
        return sorted({inst["id"] for inst in index.get("instances", [])},
                      key=len, reverse=True)
    except Exception:
        return [paths.MAIN_INSTANCE_ID]


def _owner_of(name: str, owners: list) -> str:
    for owner in owners:
        if name.startswith(f"{owner}-"):
            return owner
    return name.split("-")[0]


def _parse_stamp(name: str) -> str:
    parts = name.replace(".tar.gz", "").split("-")
    for i in range(len(parts) - 1):
        if len(parts[i]) == 8 and parts[i].isdigit() and len(parts[i + 1]) == 6 and parts[i + 1].isdigit():
            return f"{parts[i]} {parts[i+1][:2]}:{parts[i+1][2:4]}:{parts[i+1][4:6]}"
    return ""


def delete(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "backup not found"}
    if p.parent.resolve() != paths.backups_dir().resolve():
        return {"ok": False, "error": "refusing to delete outside backups/"}
    try:
        size = p.stat().st_size
        p.unlink()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "freed": size, "name": p.name}


def restore(job, backup_path, target_dir) -> dict:
    backup_path = Path(backup_path)
    target_dir = Path(target_dir)
    if not backup_path.exists():
        return {"ok": False, "error": "backup not found"}
    try:
        size = backup_path.stat().st_size
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    space = check_space(size * 3, target_dir)
    if not space["ok"]:
        return {"ok": False, "error": f"not enough free space: {space['message']}"}
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = target_dir.parent / f"{target_dir.name}.restore-{_stamp()}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    job.update(0.05, "extracting backup")
    try:
        with tarfile.open(backup_path, "r:gz") as tar:
            members = tar.getmembers()
            total = len(members) or 1
            for i, member in enumerate(members):
                parts = Path(member.name).parts
                if member.name.startswith("/") or ".." in parts or not parts:
                    continue
                stripped = Path(*parts[1:]) if len(parts) > 1 else Path(parts[0])
                if str(stripped) in (".", ""):
                    continue
                member.name = str(stripped)
                tar.extract(member, path=staging, filter="data")
                if i % 25 == 0:
                    job.update(0.05 + 0.7 * (i / total), f"extracting {i}/{total}")
    except (OSError, tarfile.TarError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "error": f"extract failed: {exc}"}
    preexisting = target_dir.exists()
    archived = None
    if preexisting:
        job.update(0.8, "moving current instance aside")
        archived = target_dir.with_name(f"{target_dir.name}.pre-restore-{_stamp()}")
        try:
            os.replace(target_dir, archived)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            return {"ok": False, "error": f"could not move current aside: {exc}"}
    try:
        os.replace(staging, target_dir)
    except OSError as exc:
        if archived and not target_dir.exists():
            os.replace(archived, target_dir)
        shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "error": f"could not move restored copy in: {exc}"}
    job.update(1.0, "restore complete")
    return {
        "ok": True,
        "target": str(target_dir),
        "previous": str(archived) if archived else "",
        "backup": str(backup_path),
    }


def purge_previous(target_dir, keep: int = 1) -> int:
    base = Path(target_dir)
    entries = sorted(base.parent.glob(f"{base.name}.pre-restore-*"), key=lambda p: p.name, reverse=True)
    removed = 0
    for entry in entries[keep:]:
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1
    return removed
