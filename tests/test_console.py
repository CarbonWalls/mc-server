"""Phase 6 tests: the live console (relay, sends, history, cleanup).

A fake java stands in for the server: it reads its stdin and echoes every line
back to the log file, which is exactly what a real Paper console does. The tests
send commands through the TUI's own machinery and check the server actually saw
them.
"""
import fcntl
import os
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

import mctui_test_env

ROOT = mctui_test_env.activate()
mctui_test_env.seed(ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctui.core import console as console_core  # noqa: E402
from mctui.core import instances, paths, procs  # noqa: E402

INSTANCE = "consoletest"
FAKE = ROOT / "fakejava_console"


def cleanup():
    procs.stop_server(INSTANCE, timeout=5)
    for path in (console_core.relay_socket_path(INSTANCE),
                 console_core.relay_pid_path(INSTANCE),
                 console_core.history_path(INSTANCE)):
        try:
            path.unlink()
        except OSError:
            pass
    inst = paths.instance_path(INSTANCE)
    if inst.exists():
        shutil.rmtree(inst, ignore_errors=True)


def make_fake_java():
    FAKE.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, threading, time\n"
        "def reader():\n"
        "    for line in sys.stdin:\n"
        "        print('CMD: ' + line.strip(), flush=True)\n"
        "threading.Thread(target=reader, daemon=True).start()\n"
        "time.sleep(300)\n")
    FAKE.chmod(0o755)
    procs._resolve_jdk = lambda: FAKE


def test_relay_send_and_cleanup():
    """start -> send -> server sees it -> stop -> relay removes its socket."""
    cleanup()
    make_fake_java()
    inst = paths.instance_path(INSTANCE)
    inst.mkdir(parents=True, exist_ok=True)
    (inst / "paper.jar").write_bytes(b"fakejar")
    log = paths.log_paths(INSTANCE)["server_log"]
    log.parent.mkdir(parents=True, exist_ok=True)

    started = procs.start_server(INSTANCE, xms="64M", xmx="128M")
    assert started.get("ok"), started
    assert started.get("console"), "start_server should report the relay socket"
    time.sleep(0.8)

    assert console_core.relay_alive(INSTANCE), "relay should be alive"
    sock = console_core.relay_socket_path(INSTANCE)
    assert sock.exists(), "relay socket should exist"

    first = console_core.send(INSTANCE, "whitelist add Steve")
    assert first.get("ok"), first
    second = console_core.send(INSTANCE, "op Notch")
    assert second.get("ok"), second
    time.sleep(0.6)

    text = log.read_text()
    assert "CMD: whitelist add Steve" in text, f"server never saw command: {text!r}"
    assert "CMD: op Notch" in text

    history = console_core.read_history(INSTANCE)
    assert "whitelist add Steve" in " ".join(history), history

    stopped = procs.stop_server(INSTANCE, timeout=10)
    assert stopped.get("ok"), stopped
    # the relay polls the server pid every 2s, so give it time to notice
    deadline = time.time() + 8.0
    while console_core.relay_alive(INSTANCE) and time.time() < deadline:
        time.sleep(0.3)
    assert not console_core.relay_alive(INSTANCE), \
        "relay must exit once the server is gone"
    assert not sock.exists(), "relay must remove its socket on exit"
    assert not console_core.relay_pid_path(INSTANCE).exists(), \
        "relay must remove its pid file on exit"
    cleanup()
    print("ok relay send cleanup")


def test_send_without_relay():
    """Sending with no relay running says so in terms a user can act on."""
    cleanup()
    outcome = console_core.send(INSTANCE, "list")
    assert not outcome.get("ok")
    message = outcome.get("error", "")
    assert "console not available" in message or "relay" in message.lower(), message
    assert "running" in message.lower(), f"error should hint at the cause: {message}"
    cleanup()
    print("ok send without relay")


def test_runtime_and_restart_labels():
    """The labels the screens show must exist and be non-empty."""
    assert "stop" in console_core.RUNTIME_COMMANDS
    assert "whitelist add <player>" in console_core.RUNTIME_COMMANDS
    assert console_core.RUNTIME_COMMANDS["list"] == "list"
    assert "server-port" in console_core.RESTART_KEYS
    for key, reason in console_core.RESTART_KEYS.items():
        assert reason.strip(), f"RESTART_KEYS[{key!r}] has no explanation"
    print("ok runtime and restart labels")


def test_tui_console_screen():
    """The console screen renders and delivers typed commands to the server."""
    cleanup()
    make_fake_java()
    inst = paths.instance_path(INSTANCE)
    inst.mkdir(parents=True, exist_ok=True)
    (inst / "paper.jar").write_bytes(b"fakejar")
    log = paths.log_paths(INSTANCE)["server_log"]
    log.parent.mkdir(parents=True, exist_ok=True)
    # the screen talks to the ACTIVE instance, so this one must be registered
    # (marker + index entry) and made active, exactly as build_instance would
    entry = {"id": INSTANCE, "name": "console test", "paper": "test"}
    write = instances.write_marker(entry, inst)
    assert write.get("ok"), write
    instances.add_instance(instances._marker_to_entry(
        instances.read_marker(inst), inst))
    outcome = instances.set_active(INSTANCE)
    assert outcome.get("ok"), outcome
    assert instances.active_id() == INSTANCE

    started = procs.start_server(INSTANCE, xms="64M", xmx="128M")
    assert started.get("ok"), started
    time.sleep(0.8)

    tmp = Path("/tmp/opencode/console-tests")
    tmp.mkdir(parents=True, exist_ok=True)
    state = tmp / f"s-{os.getpid()}-{time.time_ns()}.json"
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 34, 110, 0, 0))
    tui = subprocess.Popen(
        [sys.executable, "mc_tui.py", "--screen", "console"],
        cwd=mctui_test_env.PROJECT, stdin=slave, stdout=slave,
        stderr=subprocess.PIPE,
        env=dict(os.environ, TERM="xterm-256color", MCTUI_FORCE_TTY="1",
                 MCTUI_STATE_FILE=str(state), LINES="34", COLUMNS="110"),
        close_fds=True)
    os.close(slave)
    out = []

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                out.append(data)

    try:
        pump(2.0)
        os.write(master, b"list\r")
        pump(1.5)
        os.write(master, b"say hello\r")
        pump(2.0)
        visible = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", b"".join(out))
        visible = visible.decode("utf-8", "replace")
        assert "console" in visible, "console header missing"
        assert "send a command" in visible, "command line missing"
        assert "sent:" in visible, "send confirmation missing"
        time.sleep(0.5)
        text = log.read_text()
        assert "CMD: list" in text, f"command lost on the way: {text!r}"
        assert "CMD: say hello" in text
        # a command that starts with 'q': the prompt is always focused, so the
        # q must type rather than leave the screen (the pre-fix behaviour sent
        # you back to the dashboard and swallowed the whole line)
        os.write(master, b"query-thing\r")
        pump(1.5)
        assert "CMD: query-thing" in log.read_text(), \
            "a command starting with q never reached the server"
    finally:
        for _ in range(8):
            if tui.poll() is not None:
                break
            os.write(master, b"\x1b")
            pump(0.3)
            os.write(master, b"q")
            pump(0.3)
        if tui.poll() is None:
            os.write(master, b"\x03")
            pump(0.5)
        try:
            tui.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tui.kill()
            tui.wait(timeout=5)
        try:
            os.close(master)
        except OSError:
            pass
        stderr = tui.stderr.read().decode("utf-8", "replace") if tui.stderr else ""
        assert "Traceback" not in stderr, f"tui stderr: {stderr[-1500:]}"
        if state.exists():
            state.unlink()
    cleanup()
    print("ok tui console screen")


def main():
    cleanup()
    failures = []
    for fn in (test_send_without_relay, test_runtime_and_restart_labels,
               test_relay_send_and_cleanup, test_tui_console_screen):
        try:
            fn()
        except AssertionError as exc:
            failures.append(f"{fn.__name__}: {exc}")
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a test helper failing is a failure
            failures.append(f"{fn.__name__}: {type(exc).__name__}: {exc}")
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
    cleanup()
    if failures:
        print(f"FAILED ({len(failures)})")
        return 1
    print("PASS console")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
