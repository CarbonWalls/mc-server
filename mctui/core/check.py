"""Readiness check: can this tree host a server *right now*?

``--check`` is the honest answer to "does it work here". It never imports
curses-only code paths, touches the network, or writes to disk - it only
reads, so it is safe to run anywhere, including on an empty checkout.

Each component is reported as ``ok`` / ``warn`` / ``fail``. ``run()`` exits 0
only when no component failed; warnings (tunnel binaries, playit secret) never
block the exit because the server still starts without them.

Component 4 is deliberately "index.json present and valid, **or absent**": an
absent index is fine, the built-in ``main`` instance is implied. A present but
unreadable index is a hard failure, because every screen trusts it.
"""

import os
import shutil
from pathlib import Path

from . import bootstrap, instances, paths, procs

OK, WARN, FAIL = "ok", "warn", "fail"

_FIX_HINT = "run: python3 mc_tui.py --bootstrap  (or ./setup.sh)"


def _java_detail() -> tuple[str, str, str]:
    """(status, detail, fix) for the JVM component."""
    bundled = paths.java_bin()
    if bundled.is_file():
        return OK, f"bundled JDK at {paths.relative(bundled)}", ""
    on_path = shutil.which("java")
    if on_path:
        return OK, f"no bundled JDK, using java on PATH ({on_path})", ""
    return (FAIL, f"no bundled JDK at {paths.relative(bundled)} and no "
                  f"'java' on PATH", _FIX_HINT)


def components() -> list:
    """(status, component, detail, fix). fix is empty unless status is fail."""
    out = []

    # 1. python + curses (the TUI is unusable without curses; --check itself
    #    does not need it, but nothing else in the tool can tell the user)
    try:
        import curses  # noqa: F401
        out.append((OK, "python + curses", "", ""))
    except ImportError as exc:
        out.append((FAIL, "python + curses", f"import failed: {exc}",
                    "install the python3 curses/ncurses package"))

    # 2. root writable
    root = paths.root()
    if os.access(root, os.W_OK):
        out.append((OK, "root writable", str(root), ""))
    else:
        out.append((FAIL, "root writable", f"cannot write to {root}",
                    "pick a folder you own"))

    # 3. a usable JVM
    status, detail, fix = _java_detail()
    out.append((status, "java runtime", detail, fix))

    # 4. instances/index.json present+valid, or absent
    index_file = instances.index_path()
    if not index_file.is_file():
        out.append((OK, "instance index", "absent (the built-in main is implied)",
                    ""))
    else:
        import json
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            ids = [e.get("id") for e in (data.get("instances") or [])]
            if not isinstance(data, dict) or not isinstance(ids, list):
                raise ValueError("not an object with an instances list")
            dupes = [i for i in set(ids) if ids.count(i) > 1]
            if dupes:
                raise ValueError(f"duplicate ids {dupes}")
            out.append((OK, "instance index",
                        f"{index_file.name} valid ({len(ids)} instance(s))", ""))
        except (ValueError, OSError) as exc:
            out.append((FAIL, "instance index",
                        f"{paths.relative(index_file)} is unreadable: {exc}",
                        "delete it so it is rebuilt from instance markers"))

    # 5. the active instance directory exists
    active = instances.active_id()
    active_dir = instances.path_of(active)
    if active_dir.is_dir():
        out.append((OK, "active instance", f"{active} -> {paths.relative(active_dir)}",
                    ""))
    else:
        out.append((FAIL, "active instance",
                    f"{active} points at {paths.relative(active_dir)}, which does "
                    f"not exist", f"create it with the wizard, or {_FIX_HINT}"))

    # 6. paper.jar for the active instance
    jar = active_dir / "paper.jar"
    if jar.is_file():
        size = procs.format_bytes(jar.stat().st_size)
        out.append((OK, "paper.jar", f"{paths.relative(jar)} ({size})", ""))
    else:
        out.append((FAIL, "paper.jar",
                    f"missing {paths.relative(jar)} for instance '{active}'",
                    _FIX_HINT))

    # 7. tunnel binaries (optional: server still starts LAN-only)
    missing = []
    for name, label in (("bore-bin", "bore"), ("playit", "playit"),
                        ("playitd", "playitd")):
        if not (paths.bin_dir() / name).is_file():
            missing.append(label)
    if missing:
        out.append((WARN, "tunnel binaries",
                    f"missing {', '.join(missing)} (public address unavailable)",
                    "re-run the bootstrap, or keep playing on LAN"))
    else:
        out.append((OK, "tunnel binaries", "bore + playit present", ""))

    # 8. playit secret (optional: only needed for the playit tunnel)
    if paths.playit_secret().is_file():
        out.append((OK, "playit secret", "claimed", ""))
    else:
        out.append((WARN, "playit secret", "not claimed (TUNNEL=playit needs a "
                                          "one-time browser claim)",
                    "TUNNEL=playit ./start.sh prints the claim link"))

    return out


def report() -> tuple:
    """(exit_code, text) - text is the full per-component report."""
    lines = []
    fails = 0
    warns = 0
    for status, name, detail, fix in components():
        tag = {"ok": "[ok  ]", "warn": "[WARN]", "fail": "[FAIL]"}[status]
        suffix = f" - {detail}" if detail else ""
        lines.append(f"{tag} {name}{suffix}")
        if status == FAIL:
            fails += 1
            if fix:
                lines.append(f"       -> {fix}")
        elif status == WARN:
            warns += 1
    lines.append("")
    if fails:
        lines.append(f"NOT READY: {fails} component(s) missing"
                     + (f", {warns} warning(s)" if warns else ""))
        lines.append("fix the [FAIL] lines above, then re-run --check")
    else:
        lines.append(f"READY: this tree can start a server"
                     + (f" ({warns} warning(s))" if warns else ""))
    return (1 if fails else 0), "\n".join(lines)


def run() -> int:
    code, text = report()
    print(text)
    return code
