import os
import re
import shutil
import time
from collections import deque
from pathlib import Path

PREFIX = r"\]:?\s+"
JOIN_RE = re.compile(PREFIX + r"([A-Za-z0-9_]{1,16}) joined the game")
LEFT_RE = re.compile(PREFIX + r"([A-Za-z0-9_]{1,16}) left the game")
LOGIN_RE = re.compile(PREFIX + r"([A-Za-z0-9_]{1,16})\[/[^\]]*\] logged in with")
LOGOUT_RE = re.compile(PREFIX + r"([A-Za-z0-9_]{1,16}) lost connection")
KICK_RE = re.compile(PREFIX + r"([A-Za-z0-9_]{1,16}) was kicked")
TIME_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})(?:\s|\])")

READ_CHUNK = 65536


def log_files(instance_id: str = "main") -> list:
    from . import paths

    out = []
    seen = set()
    lp = paths.log_paths(instance_id)
    for key in ("server_log", "paper_log", "tunnel_log", "playitd_log", "playitd_verbose_log", "bore_log"):
        p = lp.get(key)
        if p and Path(p).exists() and str(p) not in seen:
            seen.add(str(p))
            out.append(Path(p))
    snapshot_dir = lp["snapshots"]
    if snapshot_dir.is_dir():
        for p in sorted(snapshot_dir.glob("*.log"), reverse=True):
            if str(p) not in seen:
                seen.add(str(p))
                out.append(p)
    for p in paths.known_log_files():
        if str(p) not in seen:
            seen.add(str(p))
            out.append(p)
    return out


def describe(path) -> dict:
    p = Path(path)
    try:
        st = p.stat()
        return {"path": p, "name": p.name, "size": st.st_size, "mtime": st.st_mtime, "exists": True}
    except OSError:
        return {"path": p, "name": p.name, "size": 0, "mtime": 0, "exists": False}


def tail(path, lines: int = 300, max_bytes: int = 512 * 1024) -> list:
    p = Path(path)
    if not p.exists():
        return []
    try:
        size = p.stat().st_size
    except OSError:
        return []
    out = []
    try:
        with open(p, "rb") as fh:
            block = 4096
            data = b""
            pos = size
            while pos > 0 and data.count(b"\n") <= lines and len(data) < max_bytes:
                step = min(block, pos)
                pos -= step
                fh.seek(pos)
                data = fh.read(step) + data
            text = data.decode("utf-8", "replace")
            out = text.splitlines()[-lines:]
    except OSError:
        return []
    if pos > 0 and out:
        out[0] = "... (earlier lines truncated)"
    return out


def iter_new_lines(path, offset: int = 0, max_read: int = 4 * 1024 * 1024) -> tuple:
    p = Path(path)
    if not p.exists():
        return offset, []
    try:
        size = p.stat().st_size
    except OSError:
        return offset, []
    if size < offset:
        offset = 0
    if size == offset:
        return offset, []
    try:
        with open(p, "rb") as fh:
            fh.seek(offset)
            data = fh.read(max_read)
    except OSError:
        return offset, []
    if len(data) >= max_read and b"\n" not in data:
        return offset + len(data), []
    idx = data.rfind(b"\n")
    if idx < 0:
        return offset, []
    consumed = data[: idx + 1]
    new_offset = offset + len(consumed)
    return new_offset, consumed.decode("utf-8", "replace").splitlines()


class LiveTail:
    def __init__(self, path, maxlen: int = 1500, follow: bool = True):
        self.path = Path(path)
        self.lines = deque(maxlen=maxlen)
        self.offset = 0
        self.follow = follow
        self.maxlen = maxlen
        self.missing = not self.path.exists()

    def reset(self):
        self.lines.clear()
        self.offset = 0

    def load(self, keep: int = 300):
        self.reset()
        for line in tail(self.path, keep):
            self.lines.append(line)
        try:
            self.offset = self.path.stat().st_size if self.path.exists() else 0
        except OSError:
            self.offset = 0

    def refresh(self) -> int:
        if not self.path.exists():
            self.missing = True
            return 0
        self.missing = False
        try:
            size = self.path.stat().st_size
        except OSError:
            return 0
        if size < self.offset:
            self.lines.clear()
            self.offset = 0
        if not self.lines and self.offset == 0:
            self.load()
            return len(self.lines)
        new_offset, new_lines = iter_new_lines(self.path, self.offset)
        added = 0
        for line in new_lines:
            self.lines.append(line)
            added += 1
        self.offset = new_offset
        return added

    def apply_filter(self, keyword: str) -> list:
        if not keyword:
            return list(self.lines)
        needle = keyword.lower()
        return [ln for ln in self.lines if needle in ln.lower()]


def filter_stream(path, keyword: str, limit: int = 500) -> list:
    p = Path(path)
    if not p.exists():
        return []
    needle = keyword.lower()
    out = []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not needle or needle in line.lower():
                    out.append(line.rstrip("\n"))
                    if len(out) >= limit:
                        break
    except OSError:
        return []
    return out


def snapshot(path, dest_dir=None) -> dict:
    from . import paths as _paths

    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"{p} does not exist"}
    dest = Path(dest_dir) if dest_dir else _paths.log_paths("main")["snapshots"]
    dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = dest / f"{p.stem}-{stamp}.log"
    counter = 1
    while target.exists():
        target = dest / f"{p.stem}-{stamp}-{counter}.log"
        counter += 1
    try:
        size = p.stat().st_size
        with open(p, "rb") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst, READ_CHUNK)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": str(target), "size": size}


def clear(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"{p} does not exist"}
    try:
        with open(p, "w"):
            pass
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": str(p)}


def scan_events(path, limit: int = 200) -> list:
    events = []
    p = Path(path)
    if not p.exists():
        return events
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                event = classify_line(line)
                if event:
                    events.append(event)
                    if len(events) >= limit * 4:
                        break
    except OSError:
        return []
    return events[-limit:]


def classify_line(line: str) -> dict | None:
    stamp = ""
    match = TIME_RE.match(line)
    if match:
        stamp = match.group(1)
    for pattern, kind in (
        (JOIN_RE, "join"),
        (LEFT_RE, "leave"),
        (LOGIN_RE, "login"),
        (LOGOUT_RE, "logout"),
        (KICK_RE, "kick"),
    ):
        found = pattern.search(line)
        if found:
            return {"kind": kind, "player": found.group(1), "time": stamp, "line": line.rstrip()}
    return None


def online_set(events: list) -> set:
    online = set()
    for event in events:
        if event["kind"] in ("join", "login"):
            online.add(event["player"])
        elif event["kind"] in ("leave", "logout", "kick"):
            online.discard(event["player"])
    return online


def file_age_line(path) -> str:
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return "missing"
    delta = int(time.time() - mtime)
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def tail_annotated(path, lines: int = 300, keyword: str = "") -> list:
    out = tail(path, lines)
    if keyword:
        needle = keyword.lower()
        out = [ln for ln in out if needle in ln.lower()]
    return out
