import json
import os
import re
import shutil
from pathlib import Path

JAVA_UNESCAPE = re.compile(r"\\(.)")
JAVA_ESCAPE = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\\": "\\\\", "=": "\\=", ":": "\\:"}


def backup_of(path) -> Path:
    p = Path(path)
    return p.with_name(p.name + ".bak")


def make_backup(path) -> Path | None:
    p = Path(path)
    if not p.exists():
        return None
    bak = backup_of(p)
    try:
        shutil.copy2(p, bak)
    except OSError:
        return None
    return bak


def read_text(path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def write_text(path, text: str, with_backup: bool = True) -> Path | None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    bak = make_backup(p) if with_backup else None
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)
    return bak


def unescape(value: str) -> str:
    return JAVA_UNESCAPE.sub(lambda m: m.group(1), value)


def escape(value: str) -> str:
    out = []
    for ch in value:
        out.append(JAVA_ESCAPE.get(ch, ch))
    return "".join(out)


def read_properties(path) -> dict:
    props = {}
    for line in read_text(path).splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("!"):
            continue
        if "=" in s:
            k, v = s.split("=", 1)
        elif ":" in s:
            k, v = s.split(":", 1)
        else:
            continue
        props[unescape(k.strip())] = unescape(v)
    return props


def properties_text(props: dict, header: str = "#Minecraft server properties") -> str:
    lines = [header]
    for k in sorted(props):
        lines.append(f"{escape(k)}={escape(str(props[k]))}")
    return "\n".join(lines) + "\n"


def write_properties(path, props: dict, header: str | None = None) -> Path | None:
    existing_header = None
    try:
        for line in read_text(path).splitlines():
            if line.startswith("#"):
                existing_header = line
                break
    except OSError:
        pass
    text = properties_text(props, header or existing_header or "#Minecraft server properties")
    return write_text(path, text)


def write_json(path, data, with_backup: bool = True) -> Path | None:
    text = json.dumps(data, indent=2, sort_keys=False) + "\n"
    return write_text(path, text, with_backup=with_backup)


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


class YamlPathError(KeyError):
    pass


def _yaml_blocks(lines):
    stack = []
    for idx, raw in enumerate(lines):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        body = raw.strip()
        if ":" not in body:
            continue
        key, rest = body.split(":", 1)
        key = key.strip().strip("'\"")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
        yield idx, raw, [k for _i, k in stack], rest.strip()


def _yaml_inline_comment(rest: str) -> str:
    if " #" in rest:
        return rest[rest.index(" #"):].rstrip()
    return ""


def yaml_get(text: str, path: list) -> str | None:
    lines = text.splitlines()
    target = [str(p) for p in path]
    for _idx, _raw, keys, rest in _yaml_blocks(lines):
        if keys == target and rest:
            if rest.startswith("#"):
                return None
            value = rest
            comment = _yaml_inline_comment(rest)
            if comment:
                value = rest[: rest.index(comment)]
            return value.strip().strip("'\"")
    return None


def yaml_get_file(path, yaml_path: list) -> str | None:
    try:
        return yaml_get(read_text(path), yaml_path)
    except OSError:
        return None


def yaml_set(text: str, yaml_path: list, value: str) -> tuple:
    lines = text.splitlines()
    target = [str(p) for p in yaml_path]
    found = False
    for idx, raw, keys, rest in _yaml_blocks(lines):
        if keys == target:
            indent = raw[: len(raw) - len(raw.lstrip(" "))]
            comment = _yaml_inline_comment(rest)
            lines[idx] = f"{indent}{target[-1]}: {value}{comment}"
            found = True
            break
    if not found:
        for i, part in enumerate(target):
            pad = "  " * i
            if i == len(target) - 1:
                lines.append(f"{pad}{part}: {value}")
            else:
                lines.append(f"{pad}{part}:")
    joined = "\n".join(lines)
    if text.endswith("\n"):
        joined += "\n"
    return joined, found


def yaml_set_file(path, yaml_path: list, value: str) -> dict:
    text = read_text(path)
    new_text, found = yaml_set(text, yaml_path, value)
    if new_text == text:
        return {"found": found, "changed": False, "backup": None}
    backup = write_text(path, new_text)
    return {"found": found, "changed": True, "backup": backup}


def secret_present(path) -> bool:
    try:
        raw = read_text(path).strip()
    except OSError:
        return False
    return bool(raw)


def redact_secret(path) -> str:
    try:
        raw = read_text(path).strip()
    except OSError:
        return "(missing)"
    if not raw:
        return "(empty)"
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            return json.dumps({k: (v[:6] + "..." if isinstance(v, str) and len(v) > 8 else v) for k, v in data.items()})
        except ValueError:
            pass
    if "=" in raw and '"' in raw:
        key, _sep, val = raw.partition("=")
        val = val.strip().strip('"')
        return f"{key.strip()} = \"{val[:6]}...\" ({len(val)} chars)"
    return f"{raw[:6]}... ({len(raw)} chars, redacted)"


def disk_usage(path) -> int:
    total = 0
    base = Path(path)
    if not base.exists():
        return 0
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total
