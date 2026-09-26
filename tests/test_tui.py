#!/usr/bin/env python3
"""Headless smoke tests: drive mc_tui.py through a pty and check every screen.

Uses a pseudo-terminal so curses runs for real.  A state file written by the
app (MCTUI_STATE_FILE) lets the test observe which screen/step is active.
"""
import fcntl
import json
import os
import pathlib
import select
import shutil
import struct
import subprocess
import sys
import termios
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = pathlib.Path("/tmp/opencode/tui-tests")
TMP.mkdir(parents=True, exist_ok=True)


def keyseq(name: str) -> bytes:
    """Terminal-defined key sequence (application cursor mode)."""
    import curses
    try:
        curses.setupterm("xterm-256color")
        seq = curses.tigetstr(name)
    except Exception:
        seq = None
    return seq or b""


UP, DOWN, LEFT, RIGHT = keyseq("kcuu1"), keyseq("kcud1"), keyseq("kcub1"), keyseq("kcuf1")
if not UP:
    UP, DOWN, LEFT, RIGHT = b"\x1bOA", b"\x1bOB", b"\x1bOD", b"\x1bOC"

SCREENS = {
    "dashboard": ["mc-tui"],
    "control": ["server control"],
    "logs": ["logs"],
    "backup": ["backups"],
    "diag": ["diagnostics"],
    "config": ["config editor"],
    "settings": ["settings"],
    "instances": ["instances"],
    "players": ["players"],
    "create": ["create server"],
}


def spawn(screen, rows=34, cols=110):
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    state = TMP / f"{screen}-{os.getpid()}-{time.time_ns()}.json"
    if state.exists():
        state.unlink()
    env = dict(os.environ, TERM="xterm-256color", MCTUI_FORCE_TTY="1",
               MCTUI_STATE_FILE=str(state), LINES=str(rows), COLUMNS=str(cols))
    proc = subprocess.Popen(
        [sys.executable, "mc_tui.py", "--screen", screen],
        cwd=ROOT, stdin=slave, stdout=slave, stderr=subprocess.PIPE, env=env,
        close_fds=True)
    os.close(slave)
    return proc, master, state


def pump(master, seconds=1.0, out=None):
    out = out if out is not None else []
    deadline = time.time() + seconds
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 0.1)
        if ready:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            out.append(data)
    return out


def read_state(path) -> dict:
    try:
        return json.loads(path.read_text().splitlines()[-1])
    except (OSError, ValueError, IndexError):
        return {}


def wait_state(path, seconds: float = 15.0, **want) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        state = read_state(path)
        if state and all(state.get(k) == v for k, v in want.items()):
            return True
        time.sleep(0.2)
    return False


def wait_text(out, needle: str, seconds: float = 8.0, master=None) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if needle.encode() in b"".join(out):
            return True
        if master is not None:
            pump(master, 0.4, out)
        else:
            time.sleep(0.3)
    return needle.encode() in b"".join(out)


def visible(out) -> str:
    import re
    return re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", b"".join(out)).decode("utf-8", "replace")


def quit_loop(proc, master, out, rounds=8):
    for _ in range(rounds):
        if proc.poll() is not None:
            return
        os.write(master, b"\x1b")
        pump(master, 0.35, out)
        if proc.poll() is not None:
            return
        os.write(master, b"q")
        pump(master, 0.35, out)


def finish(proc, master, out, state, errors, tag: str):
    quit_loop(proc, master, out)
    if proc.poll() is None:
        os.write(master, b"\x03")
        pump(master, 0.5, out)
    if proc.poll() is None:
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            errors.append(f"{tag}: did not exit (killed)")
            proc.kill()
            proc.wait(timeout=4)
    else:
        proc.wait(timeout=4)
    try:
        os.close(master)
    except OSError:
        pass
    stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if "Traceback" in stderr:
        errors.append(f"{tag}: stderr traceback:\n{stderr[-3000:]}")
    if "Traceback" in visible(out):
        idx = visible(out).rindex("Traceback")
        errors.append(f"{tag}: visible traceback:\n{visible(out)[idx:idx + 1200]}")
    if proc.returncode not in (0, -9, None):
        errors.append(f"{tag}: exit code {proc.returncode}\n{stderr[-1500:]}")
    if state.exists():
        state.unlink()


def run_screen(screen, expect):
    proc, master, state = spawn(screen)
    out = pump(master, 1.0)
    errors = []
    for needle in expect:
        if not wait_text(out, needle, 10.0, master):
            errors.append(f"{screen}: expected {needle!r} not on screen; "
                          f"visible: {visible(out)[:300]!r}")
    if not wait_state(state, 8.0, screen=screen):
        errors.append(f"{screen}: state file never reported this screen: {read_state(state)}")
    for keys in (DOWN, RIGHT, UP, LEFT, b"\t", b"\r", b"/", b"?"):
        os.write(master, keys)
        pump(master, 0.25, out)
    finish(proc, master, out, state, errors, screen)
    return errors, len(b"".join(out))


def test_create_wizard():
    """Walk the create-server wizard to the review step, then leave (no download)."""
    errors = []
    proc, master, state = spawn("create")
    out = pump(master, 2.0)

    if b"create server" not in b"".join(out):
        errors.append("wizard header missing")

    os.write(master, b"tuidemo")
    pump(master, 0.4, out)
    os.write(master, b"\r")
    if not wait_state(state, 10.0, step=2):
        errors.append(f"name step did not advance: {read_state(state)}")

    def tap_until(step: int, key: bytes, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if read_state(state).get("step") == step:
                return True
            os.write(master, key)
            pump(master, 1.0, out)
        return read_state(state).get("step") == step

    if not errors:
        if not tap_until(3, b"\r", 30):          # version list loads, then pick it
            errors.append(f"build step not reached: {read_state(state)}")
        elif not tap_until(4, b"\r", 10):        # build is preselected
            errors.append(f"perf step not reached: {read_state(state)}")
        elif not tap_until(5, b"\r", 10):        # pick perf preset
            errors.append(f"gameplay step not reached: {read_state(state)}")
        elif not tap_until(6, RIGHT, 10):        # gameplay -> network
            errors.append(f"network step not reached: {read_state(state)}")
        elif not tap_until(7, RIGHT, 30):        # network -> plugins (resolve over net)
            errors.append(f"plugins step not reached: {read_state(state)}")
        elif not tap_until(8, RIGHT, 30):        # plugins -> review
            errors.append(f"review step not reached: {read_state(state)}")
        else:
            if "tuidemo" not in visible(out):
                errors.append("review summary missing the instance id")
            if read_state(state).get("phase") == "building":
                errors.append("build started unexpectedly")

    finish(proc, master, out, state, errors, "create-wizard")
    stray = pathlib.Path(ROOT) / "instances" / "tuidemo"
    if stray.exists():
        shutil.rmtree(stray, ignore_errors=True)
        errors.append("wizard created a stray instance folder (a build ran)")
    if not errors:
        print("ok create wizard (reached review, no download)")
    for err in errors:
        print("   " + err.replace("\n", "\n   "))
    return errors


def main():
    only = sys.argv[1:] or list(SCREENS)
    all_errors = []
    for name in only:
        errors, size = run_screen(name, SCREENS[name])
        if errors:
            all_errors.extend(errors)
            print(f"FAIL {name} ({size} bytes)")
            for err in errors:
                print("   " + err.replace("\n", "\n   "))
        else:
            print(f"ok {name} ({size} bytes)")
    if "create" in only and not os.environ.get("MCTUI_SKIP_WIZARD"):
        all_errors.extend(test_create_wizard())
    if all_errors:
        print(f"FAILED ({len(all_errors)} problems)")
        return 1
    print("PASS tui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
