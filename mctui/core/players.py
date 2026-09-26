import hashlib
import json
import time
import uuid as uuidlib
from pathlib import Path

from . import config, logs, paths

LIST_FILES = {
    "whitelist": "whitelist.json",
    "ops": "ops.json",
    "bans": "banned-players.json",
    "ip_bans": "banned-ips.json",
}


def offline_uuid(name: str) -> str:
    data = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    data[6] = (data[6] & 0x0F) | 0x30
    data[8] = (data[8] & 0x3F) | 0x80
    return str(uuidlib.UUID(bytes=bytes(data)))


def list_path(instance_id: str, kind: str) -> Path:
    return paths.instance_path(instance_id) / LIST_FILES[kind]


def read_list(instance_id: str, kind: str) -> list:
    path = list_path(instance_id, kind)
    data = config.read_json(path, [])
    if not isinstance(data, list):
        return []
    return data


def write_list(instance_id: str, kind: str, entries: list) -> dict:
    path = list_path(instance_id, kind)
    backup = config.write_json(path, entries)
    return {"ok": True, "path": str(path), "backup": str(backup) if backup else "",
            "count": len(entries)}


def names(entries: list) -> list:
    out = []
    for entry in entries:
        if isinstance(entry, dict):
            out.append(entry.get("name") or entry.get("ip") or "")
        else:
            out.append(str(entry))
    return [n for n in out if n]


def find(entries: list, name: str) -> int:
    wanted = name.lower()
    for idx, entry in enumerate(entries):
        if isinstance(entry, dict) and str(entry.get("name", "")).lower() == wanted:
            return idx
        if isinstance(entry, str) and entry.lower() == wanted:
            return idx
    return -1


def add_entry(instance_id: str, kind: str, name: str, level: int = 4,
              reason: str = "Banned by an operator", source: str = "Banned by an operator") -> dict:
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "empty name"}
    if kind not in LIST_FILES:
        return {"ok": False, "error": f"unknown list {kind}"}
    entries = read_list(instance_id, kind)
    if find(entries, name) >= 0:
        return {"ok": False, "error": f"'{name}' is already in the list"}
    if kind == "ip_bans":
        entry = {"ip": name, "created": _stamp(), "source": source,
                 "expires": "forever", "reason": reason}
    elif kind == "bans":
        entry = {"uuid": offline_uuid(name), "name": name, "created": _stamp(),
                 "source": source, "expires": "forever", "reason": reason}
    elif kind == "ops":
        entry = {"uuid": offline_uuid(name), "name": name, "level": int(level),
                 "bypassesPlayerLimit": False}
    else:
        entry = {"uuid": offline_uuid(name), "name": name}
    entries.append(entry)
    entries.sort(key=lambda e: (e.get("name") or e.get("ip") or "").lower() if isinstance(e, dict) else str(e).lower())
    result = write_list(instance_id, kind, entries)
    result.update({"ok": True, "entry": entry, "name": name})
    return result


def remove_entry(instance_id: str, kind: str, name: str) -> dict:
    entries = read_list(instance_id, kind)
    idx = find(entries, name)
    if idx < 0:
        return {"ok": False, "error": f"'{name}' is not in the list"}
    removed = entries.pop(idx)
    result = write_list(instance_id, kind, entries)
    result.update({"ok": True, "removed": removed, "name": name})
    return result


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def status(instance_id: str) -> dict:
    lp = paths.log_paths(instance_id)
    events = logs.scan_events(lp["server_log"], limit=300)
    online = logs.online_set(events)
    return {
        "online": sorted(online),
        "events": events,
        "whitelist_enabled": _prop(instance_id, "white-list") == "true",
        "online_mode": _prop(instance_id, "online-mode") == "true",
        "whitelist": read_list(instance_id, "whitelist"),
        "ops": read_list(instance_id, "ops"),
        "bans": read_list(instance_id, "bans"),
        "ip_bans": read_list(instance_id, "ip_bans"),
        "max_players": _prop(instance_id, "max-players"),
        "recent_players": _recent_players(events),
    }


def _recent_players(events: list) -> list:
    seen = []
    for event in events:
        player = event["player"]
        if player not in seen:
            seen.append(player)
    seen.reverse()
    return seen[:25]


def _prop(instance_id: str, key: str) -> str:
    path = paths.instance_path(instance_id) / "server.properties"
    if not path.exists():
        return ""
    props = config.read_properties(path)
    return str(props.get(key, ""))


def history(instance_id: str, limit: int = 200) -> list:
    lp = paths.log_paths(instance_id)
    events = logs.scan_events(lp["server_log"], limit=limit)
    events.reverse()
    return events


def entry_lines(entries: list, kind: str) -> list:
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            out.append(str(entry))
            continue
        if kind == "ops":
            out.append(f"{entry.get('name','?')}  (level {entry.get('level','?')})")
        elif kind == "bans":
            out.append(f"{entry.get('name','?')}  - {entry.get('reason','')}")
        elif kind == "ip_bans":
            out.append(f"{entry.get('ip','?')}  - {entry.get('reason','')}")
        elif kind == "whitelist":
            out.append(str(entry.get("name", "?")))
        else:
            out.append(json.dumps(entry))
    return out


def summary(instance_id: str) -> list:
    return [
        ("whitelist entries", str(len(read_list(instance_id, "whitelist")))),
        ("ops", str(len(read_list(instance_id, "ops")))),
        ("banned players", str(len(read_list(instance_id, "bans")))),
        ("banned ips", str(len(read_list(instance_id, "ip_bans")))),
    ]
