"""Live server console: send commands to a running Paper server's stdin.

The mechanism (Phase 6): ``procs.start_server`` launches java with
``stdin=subprocess.PIPE`` and then hands the *write end* of that pipe to a
detached relay process. The relay's only job is to keep the write end open for
the server's entire life and to forward lines it receives on a Unix socket.

Why a separate process instead of a writer thread inside the TUI?

  * The server runs in its own session (``start_new_session=True``) so it
    already outlives the TUI. But a thread lives only as long as the TUI
    process; when the TUI exited, its copy of the pipe write end would close
    and the server's console reader would see EOF.
  * The relay is in its own session too, so the write end stays open after the
    TUI is gone. A later TUI reconnects to the same socket and keeps typing.

Exit policy (decided, documented, implemented):

  * Exiting the TUI NEVER stops a running server. The server is in its own
    process group; only an explicit stop (the TUI's stop action, which sends
    SIGTERM via the pid file, or ``./stop.sh``) shuts it down.
  * When the TUI exits, the relay keeps the console pipe open, so the server
    keeps accepting commands. Any commands typed are simply queued until a
    console reconnects.
  * When the server exits, the relay notices (its pid goes away) and exits on
    its own, removing the socket. Nothing is left behind.

Which settings can change while the server runs (vanilla Paper console) and
which need a restart is recorded in RUNTIME_COMMANDS / RESTART_KEYS; the
console screen shows the label *before* the user commits a change.
"""

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import paths

RELAY_ACK = b"ok\n"
RELAY_DEADLINE = 8.0

# Real Paper console commands: the change is live the moment the server echoes
# it back. The console screen sends these straight to stdin.
RUNTIME_COMMANDS = {
    "whitelist add <player>": "whitelist add",
    "whitelist remove <player>": "whitelist remove",
    "op <player>": "op",
    "deop <player>": "deop",
    "gamemode <survival|creative|adventure|spectator>": "gamemode",
    "difficulty <peaceful|easy|normal|hard>": "difficulty",
    "save-all": "save-all",
    "stop": "stop",
    "list": "list",
    "say <message>": "say",
    "time set <day|night|...>": "time set",
}

# server.properties keys that vanilla Paper only reads at startup. Changing
# these in the config editor takes effect on the next start, not now - the
# console says so before the user commits.
RESTART_KEYS = {
    "server-port": "the port is bound once at startup",
    "online-mode": "authentication mode is fixed at startup",
    "level-type": "world generation type is fixed once the world exists",
    "level-name": "the world folder is chosen at startup",
    "level-seed": "a seed only applies to a fresh world",
    "max-world-size": "read at startup",
    "generate-structures": "read at world generation",
    "hardcore": "read at startup",
    "force-gamemode": "read at startup",
    "enable-query": "the query service starts with the server",
    "enable-rcon": "the rcon service starts with the server",
    "white-list": "toggled with 'whitelist on/off' at runtime instead",
    "view-distance": "Paper applies this at chunk-load time - restart to be safe",
    "simulation-distance": "applied at startup",
    "pvp": "applied at startup",
    "motd": "shown to clients on the next ping (restart to be certain)",
    "enforce-secure-profile": "read at startup",
    "max-players": "applied at startup",
    "network-compression-threshold": "applied at startup",
    "sync-chunk-writes": "applied at startup",
}


def relay_socket_path(instance_id: str) -> Path:
    return paths.data_dir() / f"console-{instance_id}.sock"


def relay_pid_path(instance_id: str) -> Path:
    return paths.data_dir() / f"console-{instance_id}.pid"


_RELAY_CODE = r'''
import os
import socket
import sys
import time

write_fd = int(sys.argv[1])
sock_path = sys.argv[2]
server_pid = int(sys.argv[3])
pid_path = sys.argv[4] if len(sys.argv) > 4 else ""


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    # a zombie is gone for our purposes: its stdin is closed and it will never
    # read another command. os.kill(pid, 0) still succeeds on a zombie because
    # the entry exists until its parent reaps it.
    try:
        state = open(f"/proc/{pid}/stat").read().split()[2]
        if state == "Z":
            return False
    except (OSError, IndexError, ValueError):
        pass
    return True


def main():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        os.unlink(sock_path)
    except OSError:
        pass
    try:
        sock.bind(sock_path)
    except OSError:
        return
    try:
        sock.listen(1)
        sock.settimeout(2.0)
        while alive(server_pid):
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                _serve(conn, write_fd)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
    finally:
        try:
            sock.close()
        except OSError:
            pass
        for path in (sock_path, pid_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        try:
            os.close(write_fd)
        except OSError:
            pass


def _serve(conn, write_fd):
    conn.settimeout(1.0)
    buf = b""
    while True:
        try:
            data = conn.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            break
        if not data:
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                os.write(write_fd, line + b"\n")
                conn.sendall(b"ok\n")
            except OSError:
                conn.sendall(b"gone\n")
                return


main()
'''


def spawn_relay(proc, instance_id: str) -> dict:
    """Move the server's stdin write end into a detached relay that outlives
    this process. After this returns, the caller must close its own copy of
    ``proc.stdin`` so the relay is the sole writer."""
    if proc.stdin is None:
        return {"ok": False, "error": "server has no stdin pipe"}
    write_fd = proc.stdin.fileno()
    sock = relay_socket_path(instance_id)
    pid_file = relay_pid_path(instance_id)
    try:
        sock.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"cannot create {sock.parent}: {exc}"}
    args = [sys.executable, "-c", _RELAY_CODE, str(write_fd), str(sock),
            str(proc.pid), str(pid_file)]
    try:
        relay = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
            pass_fds=(write_fd,), close_fds=True)
    except OSError as exc:
        return {"ok": False, "error": f"cannot spawn console relay: {exc}"}
    try:
        pid_file.write_text(f"{relay.pid}\n", encoding="utf-8")
    except OSError:
        pass
    return {"ok": True, "pid": relay.pid, "socket": str(sock)}


def relay_alive(instance_id: str) -> bool:
    pid_path = relay_pid_path(instance_id)
    try:
        pid = int(pid_path.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class ConsoleClient:
    """Talks to the relay over a Unix socket: send a console command line."""

    def __init__(self, instance_id: str, timeout: float = 3.0):
        self.instance_id = instance_id
        self.sock_path = relay_socket_path(instance_id)
        self.timeout = timeout
        self._sock = None

    def connect(self) -> dict:
        if self._sock is not None:
            return {"ok": True}
        if not self.sock_path.exists():
            # NOTE: a Unix socket is not a regular file, so is_file() is
            # always False here - exists() is the right test
            return {"ok": False,
                    "error": f"console not available (no relay at "
                             f"{self.sock_path}) - is the server running?"}
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(str(self.sock_path))
        except OSError as exc:
            sock.close()
            return {"ok": False, "error": f"cannot reach the console relay: {exc}"}
        self._sock = sock
        return {"ok": True}

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send(self, command: str) -> dict:
        line = (command or "").strip()
        if not line:
            return {"ok": False, "error": "empty command"}
        if "\n" in line:
            return {"ok": False, "error": "one command at a time"}
        outcome = self.connect()
        if not outcome.get("ok"):
            return outcome
        try:
            self._sock.sendall(line.encode("utf-8") + b"\n")
            reply = self._sock.recv(256)
        except OSError as exc:
            self.close()
            return {"ok": False, "error": f"console send failed: {exc}"}
        if reply.strip() == b"ok":
            # record at the choke point so every caller (the TUI screen, the
            # web UI, one-shot scripts) gets the same history
            try:
                append_history(self.instance_id, line)
            except Exception:
                pass
            return {"ok": True, "command": line}
        self.close()
        return {"ok": False, "error": "the server is not reading its console "
                                      "(it may have exited)"}


def send(instance_id: str, command: str) -> dict:
    """One-shot convenience: send a single console command."""
    client = ConsoleClient(instance_id)
    try:
        return client.send(command)
    finally:
        client.close()


def history_path(instance_id: str) -> Path:
    return paths.data_dir() / f"console-{instance_id}.history"


def append_history(instance_id: str, command: str, limit: int = 200) -> None:
    path = history_path(instance_id)
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
    except OSError:
        lines = []
    lines.append(f"[{time.strftime('%H:%M:%S')}] {command.strip()}")
    lines = lines[-limit:]
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def read_history(instance_id: str, limit: int = 50) -> list:
    try:
        lines = history_path(instance_id).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return lines[-limit:]
