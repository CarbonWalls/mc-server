import json
import os
import socket
import time

from . import paths

IPC_VERSION = 2
DEFAULT_TIMEOUT = 5.0


class PlayitError(Exception):
    pass


class PlayitNotRunning(PlayitError):
    pass


class PlayitRemoteError(PlayitError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class PlayitClient:
    def __init__(self, sock_path=None, timeout: float = DEFAULT_TIMEOUT):
        self.sock_path = str(sock_path or paths.playit_socket())
        self.timeout = timeout
        self._sock = None
        self._request_id = 0

    def connect(self) -> dict:
        if not os.path.exists(self.sock_path):
            raise PlayitNotRunning(
                f"IPC socket not found at {self.sock_path} (playitd not running)"
            )
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.sock_path)
        except OSError as exc:
            sock.close()
            raise PlayitNotRunning(f"cannot connect to {self.sock_path}: {exc}") from exc
        self._sock = sock
        hello = self._read_line()
        return hello.get("data", {})

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_exc):
        self.close()

    def _read_line(self) -> dict:
        buf = b""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout as exc:
                raise PlayitError("timed out waiting for playitd response") from exc
            if not chunk:
                raise PlayitError("playitd closed the connection")
            buf += chunk
            nl = buf.find(b"\n")
            if nl >= 0:
                line = buf[:nl]
                buf = buf[nl + 1:]
                if not line.strip():
                    continue
                try:
                    return json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
        raise PlayitError("no complete response from playitd")

    def request(self, req_type: str, params: dict | None = None) -> dict:
        if self._sock is None:
            self.connect()
        self._request_id += 1
        rid = self._request_id
        request = {"type": req_type}
        if params:
            request.update(params)
        payload = {"ipc_version": IPC_VERSION, "request_id": rid, "request": request}
        try:
            self._sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError as exc:
            raise PlayitError(f"send failed: {exc}") from exc
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            msg = self._read_line()
            data = msg.get("data", {})
            if msg.get("message_kind") != "response":
                continue
            if data.get("request_id") != rid:
                continue
            response = data.get("response", {})
            rtype = response.get("type")
            rdata = response.get("data", {})
            if rtype == "error":
                raise PlayitRemoteError(
                    str(rdata.get("code", "error")),
                    str(rdata.get("message", "unknown error")),
                )
            return rdata
        raise PlayitError(f"no response for request {req_type}")

    def status(self) -> dict:
        return self.request("get_status")

    def subscribe(self) -> dict:
        return self.request("subscribe")


def query(playitd_running: bool = True, timeout: float = DEFAULT_TIMEOUT) -> dict:
    client = PlayitClient(timeout=timeout)
    try:
        hello = client.connect()
        status = client.status()
        sub = client.subscribe()
    finally:
        client.close()
    snapshot = sub.get("snapshot", {})
    lifecycle = snapshot.get("lifecycle", {})
    lifecycle_data = lifecycle.get("data") or {}
    stats = snapshot.get("stats", {}) or {}
    return {
        "hello": hello,
        "status": status,
        "lifecycle_state": lifecycle.get("state"),
        "tunnels": lifecycle_data.get("tunnels", []),
        "pending_tunnels": lifecycle_data.get("pending_tunnels", []),
        "notices": lifecycle_data.get("notices", []),
        "account_status": lifecycle_data.get("account_status"),
        "agent_id": lifecycle_data.get("agent_id"),
        "login_link": lifecycle_data.get("login_link"),
        "stats": stats,
        "pid": status.get("pid"),
        "version": status.get("version"),
        "phase": status.get("phase"),
        "uptime_secs": status.get("uptime_secs"),
        "has_secret": status.get("has_secret"),
        "last_error": status.get("last_error"),
        "requested_by_playitd_running": playitd_running,
    }


def tunnel_rows(result: dict) -> list:
    rows = []
    for tunnel in result.get("tunnels", []):
        display = str(tunnel.get("display_address", "?"))
        dest = str(tunnel.get("destination", "?"))
        host, _, port = display.rpartition(":")
        if not host:
            host, port = display, ""
        rows.append(
            {
                "host": host,
                "port": port,
                "destination": dest,
                "disabled": bool(tunnel.get("is_disabled")),
                "reason": tunnel.get("disabled_reason"),
                "proto": "UDP" if _looks_udp(dest) else "TCP",
            }
        )
    return rows


def _looks_udp(destination: str) -> bool:
    return destination.endswith(":44041") or destination.endswith(":19132")


def format_uptime(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "-"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s"
