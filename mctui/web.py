"""HTTP backend for webui/index.html (Phase 8).

Serves the frozen single-file UI and the JSON API it talks to, using only the
Python standard library (``http.server.ThreadingHTTPServer``). The UI is the
contract: every endpoint and every shape here exists because
``webui/index.html`` fetches it, and the mock dataset in that file is the
reference for what "presentable" looks like.

Contract notes the UI documents as TODOs, implemented here:

  * ``GET /api/players`` returns ``bans: [{name, reason, created}]`` — the
    Players screen renders a Bans card from it.
  * ``POST /api/instances/settings`` persists runtime settings (memory, ports,
    tunnel, java override). The Settings screen marks every field
    "requires restart" and the properties file is what a start reads.
  * ``GET /api/plugins/catalogue`` enumerates installable plugins so the create
    wizard does not have to hardcode them.

Live updates: ``GET /api/events`` is an SSE stream with named events
``status``, ``log``, ``players`` and ``job`` — the same four things the TUI
polls for. The UI reconnects on its own if the stream drops.

Security: binds to 127.0.0.1 by default. Binding to 0.0.0.0 exposes an
unauthenticated server console to the network, so that is refused unless the
caller sets MCTUI_WEB_ALLOW_PUBLIC=1, and even then a warning is printed.
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core import (backup, config, console as console_core, instances, logs,
                   paths, playit_ipc, players, procs, version)

WEBUI_FILE = Path(__file__).resolve().parent.parent / "webui" / "index.html"

DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"

# how often each SSE client is told the world (seconds)
EVENT_TICK = 2.0


def _json(handler, payload, status=200) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _ok(handler, extra=None) -> None:
    payload = {"ok": True}
    if extra:
        payload.update(extra)
    _json(handler, payload)


def _fail(handler, message, status=400) -> None:
    _json(handler, {"ok": False, "error": str(message)}, status=status)


def _read_body(handler) -> dict:
    length = handler.headers.get("Content-Length")
    if not length:
        return {}
    try:
        raw = handler.rfile.read(int(length))
    except (OSError, ValueError):
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _instance_id(handler, body=None) -> str:
    """The instance an action targets: the request body's, else the active one."""
    body = body if body is not None else {}
    candidate = str(body.get("instance") or "").strip()
    if candidate:
        return candidate
    return handler.server.active_instance()


def _player_names(entries) -> list:
    return [str(e.get("name", "")) for e in entries if isinstance(e, dict)]


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "mc_tui-web/1.0"
    protocol_version = "HTTP/1.1"

    # quiet the default stderr access log; the manager's own logs are enough
    def log_message(self, fmt, *args):
        pass

    # --- routing -----------------------------------------------------
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html", "/webui", "/webui/"):
            return self._serve_ui()
        if path == "/api/status":
            return _json(self, self._status())
        if path == "/api/instances":
            return _json(self, self._instances())
        if path == "/api/logs":
            return _json(self, self._logs(_param(query, "instance"),
                                          _int(_param(query, "lines"), 200)))
        if path == "/api/players":
            return _json(self, self._players(_param(query, "instance")))
        if path == "/api/backups":
            return _json(self, self._backups(_param(query, "instance")))
        if path == "/api/tunnels":
            return _json(self, self._tunnels())
        if path == "/api/jobs":
            return _json(self, {"jobs": [j.snapshot()
                                         for j in self.server.jobs.recent(20)]})
        if path == "/api/plugins/catalogue":
            return _json(self, self._plugin_catalogue())
        if path == "/api/events":
            return self._events()
        return _fail(self, f"unknown endpoint: {path}", status=404)

    def do_POST(self):
        path = self.path.partition("?")[0]
        body = _read_body(self)
        route = ROUTES.get(path)
        if route is None:
            return _fail(self, f"unknown endpoint: {path}", status=404)
        try:
            route(self, body)
        except Exception as exc:
            _fail(self, f"{type(exc).__name__}: {exc}", status=500)

    # --- the frozen UI ------------------------------------------------
    def _serve_ui(self):
        try:
            data = WEBUI_FILE.read_bytes()
        except OSError as exc:
            return _fail(self, f"webui not found: {exc}", status=404)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # --- GET shapes (match the UI's expectations exactly) --------------
    def _status(self):
        active = self.server.active_instance()
        instance = instances.get_instance(active) or {}
        server = procs.server_status(active)
        return {
            "instance": active,
            "name": instance.get("name") or active,
            "server": {
                "state": server.get("state"),
                "pid": server.get("pid"),
                "uptime": server.get("uptime", 0),
                "rss": server.get("rss", 0),
            },
            "playitd": procs.playitd_status(),
            "tunnel": procs.tunnel_status(),
            "disk": {"free": paths.free_bytes()},
            "java": procs.java_version(paths.load_settings().get("java", "")),
            "paper": {
                "version": instance.get("paper_version") or "",
                "build": instance.get("build"),
            },
        }

    def _instances(self):
        index = instances.load_index()
        active = self.server.active_instance()
        out = []
        for entry in index.get("instances", []):
            instance_id = str(entry.get("id") or "")
            target = instances.path_of(instance_id)
            state = procs.classify(procs.read_pid(
                paths.log_paths(instance_id)["server_pid"]), "paper.jar")
            out.append({
                "id": instance_id,
                "name": entry.get("name") or instance_id,
                "path": str(target),
                "exists": bool(target.is_dir()),
                "paper_version": entry.get("paper_version") or "",
                "build": entry.get("build"),
                "tunnel": entry.get("tunnel") or "none",
                "bedrock_port": entry.get("bedrock_port"),
                "state": state if state != "missing" else "stopped",
                "created": entry.get("created") or "",
                "note": entry.get("note") or "",
            })
        return {"active": active, "instances": out}

    def _logs(self, instance_id: str, lines: int):
        path = paths.log_paths(instance_id)["server_log"]
        return {"lines": logs.tail(path, lines=lines)}

    def _players(self, instance_id: str):
        status = players.status(instance_id)
        bans = [{"name": b.get("name", ""), "reason": b.get("reason", ""),
                 "created": b.get("created", "")}
                for b in status.get("bans", []) if isinstance(b, dict)]
        max_players = status.get("max_players") or ""
        return {
            "online": status.get("online", []),
            "recent": status.get("recent_players", []),
            "whitelist": _player_names(status.get("whitelist", [])),
            "ops": _player_names(status.get("ops", [])),
            "bans": bans,
            "whitelist_enabled": bool(status.get("whitelist_enabled")),
            "online_mode": bool(status.get("online_mode")),
            "max_players": max_players,
        }

    def _backups(self, instance_id: str):
        rows = backup.list_backups(instance_id or None)
        out = []
        for row in rows:
            out.append({
                "name": row.get("name") or Path(str(row.get("path", ""))).name,
                "instance": row.get("instance") or instance_id,
                "size": row.get("size") or 0,
                "stamp": row.get("stamp") or "",
                "path": str(row.get("path", "")),
            })
        return {"backups": out}

    def _tunnels(self):
        running = procs.playitd_status().get("state") == "running"
        try:
            result = playit_ipc.query(playitd_running=running, timeout=4.0)
        except Exception:
            return {"tunnels": [], "account": None}
        account = None
        if result.get("account_status"):
            account = {
                "status": result.get("account_status"),
                "login_link": result.get("login_link"),
            }
        return {"tunnels": playit_ipc.tunnel_rows(result), "account": account}

    def _plugin_catalogue(self):
        """The installable plugins the create wizard offers."""
        out = []
        for plugin in version.PLUGINS:
            out.append({"id": plugin.get("id"), "name": plugin.get("name"),
                        "desc": plugin.get("desc") or ""})
        return {"plugins": out}

    # --- SSE -----------------------------------------------------------
    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        client = self.server.subscribe()
        try:
            self._send_event("status", self._status())
            while not self.server.stop_event.is_set():
                event = client.next(timeout=EVENT_TICK)
                if event is None:
                    # no news in a while: a status tick keeps the dashboard
                    # (uptime, memory) honest without a client-side poll
                    self._send_event("status", self._status())
                    continue
                kind, payload = event
                self._send_event(kind, payload)
        except (OSError, ValueError):
            pass
        finally:
            self.server.unsubscribe(client)

    def _send_event(self, kind: str, payload) -> None:
        data = json.dumps(payload, default=str)
        chunk = f"event: {kind}\ndata: {data}\n\n".encode("utf-8")
        try:
            self.wfile.write(chunk)
            self.wfile.flush()
        except OSError:
            raise ValueError("client gone")

    # --- POST routes ---------------------------------------------------
    def instances_active(self, body):
        instance_id = str(body.get("id") or "").strip()
        outcome = instances.set_active(instance_id)
        if outcome.get("ok"):
            self.server.set_active_instance(instance_id)
            self.server.broadcast("status", self._status())
            _ok(self)
        else:
            _fail(self, outcome.get("error", "unknown instance"))

    def instances_create(self, body):
        instance_id = str(body.get("id") or "").strip()
        if not instance_id:
            return _fail(self, "Missing instance id")
        if instances.get_instance(instance_id):
            return _fail(self, "An instance with that id already exists")
        wanted = list(body.get("plugins") or [])
        if body.get("geyser"):
            for needed in ("geyser", "floodgate"):
                if needed not in wanted:
                    wanted.append(needed)
        game_version = str(body.get("version") or "")

        def job_fn(job):
            job.update(0.02, "resolving the paper download")
            builds = self._resolve_paper(job, game_version,
                                         int(body.get("build") or 0))
            if not builds:
                raise RuntimeError("no paper build found for "
                                   f"{game_version or 'the latest version'}")
            build = builds[0]
            paper = {"url": build.get("url", ""), "size": build.get("size") or 0,
                     "sha256": build.get("sha256") or "",
                     "version": str(build.get("version") or game_version),
                     "number": build.get("number")}
            job.update(0.15, "resolving plugin downloads")
            specs = version.resolve_all_plugins(game_version, wanted=set(wanted))
            properties = dict(body.get("properties") or {})
            properties.setdefault("server-port", "25565")
            spec = {
                "id": instance_id,
                "name": str(body.get("name") or instance_id),
                "path": str(body.get("path") or ""),
                "paper": paper,
                "properties": properties,
                "server_port": int(properties.get("server-port") or 25565),
                "motd": properties.get("motd", ""),
                "tunnel": str(body.get("tunnel") or "none"),
                "perf": {"preset": "balanced", "xms": "512M", "xmx": "768M"},
                "geyser": {"install": bool(body.get("geyser")), "port": 19132,
                           "broadcast_port": 0, "auth_type": "floodgate",
                           "transport": "raknet", "haproxy": True,
                           "floodgate": bool(body.get("geyser"))},
                "plugins": wanted,
                "plugin_specs": specs,
                "note": "",
            }
            result = instances.build_instance(job, spec)
            if result.get("ok"):
                self.server.set_active_instance(instance_id)
                self.server.broadcast("status", self._status())
            return result

        job = self.server.run_job(f"create {instance_id}", job_fn)
        _ok(self, {"job": str(job.id)})

    def _resolve_paper(self, job, game_version: str, build_number: int) -> list:
        """Pick the paper build for a version: the named build if we know it,
        else the newest the API offers."""
        try:
            if game_version:
                builds = version.paper_builds(game_version, limit=8, job=job)
            else:
                versions = version.paper_versions(limit=8, job=job)
                builds = []
                for entry in versions:
                    if entry.get("build"):
                        builds.append(entry["build"])
                    if len(builds) >= 3:
                        break
        except Exception as exc:
            raise RuntimeError(f"could not look up paper builds: {exc}")
        if build_number:
            for build in builds:
                if int(build.get("number") or 0) == build_number:
                    return [build]
        return builds[:1]

    def instances_delete(self, body):
        instance_id = _instance_id(self, body)
        outcome = instances.delete(instance_id, make_backup=False)
        if outcome.get("ok"):
            self.server.broadcast("status", self._status())
            _ok(self)
        else:
            _fail(self, outcome.get("error", "could not delete"))

    def instances_rename(self, body):
        instance_id = _instance_id(self, body)
        new_id = str(body.get("new_id") or "").strip()
        outcome = instances.rename(instance_id, new_id)
        if outcome.get("ok"):
            self.server.broadcast("status", self._status())
            _ok(self)
        else:
            _fail(self, outcome.get("error", "could not rename"))

    def instances_clone(self, body):
        instance_id = _instance_id(self, body)
        new_id = str(body.get("new_id") or "").strip()

        def job_fn(job):
            return instances.clone(instance_id, new_id)

        self.server.run_job(f"clone {new_id}", job_fn)
        _ok(self)

    def instances_settings(self, body):
        """Persist runtime settings (memory / ports / tunnel / java override).

        These are read when the server starts, so a running server is
        unaffected - the UI already labels every field 'requires restart'.
        """
        instance_id = _instance_id(self, body)
        entry = instances.get_instance(instance_id)
        if not entry:
            return _fail(self, f"unknown instance {instance_id!r}")
        changed = []

        def set_field(key, value):
            if value in (None, ""):
                return
            if str(entry.get(key, "")) != str(value):
                changed.append(key)
                instances.update_instance(instance_id, **{key: value})

        memory = str(body.get("memory") or "").strip()
        if memory:
            set_field("xms", memory)
            set_field("xmx", memory)
        set_field("tunnel", str(body.get("tunnel") or "").strip() or "none")
        java = str(body.get("java") or "").strip()
        if java:
            set_field("java_override", java)
        bedrock = body.get("bedrock_port")
        if bedrock:
            set_field("bedrock_port", int(bedrock))

        # ports live in server.properties, which is what a start reads
        props_path = paths.instance_path(instance_id) / "server.properties"
        if props_path.exists():
            props = config.read_properties(props_path)
            for key in ("server-port", "max-players"):
                value = body.get(key)
                if value not in (None, ""):
                    props[key] = str(value)
                    changed.append(key)
            config.write_properties(props_path, props)

        # the global settings file holds the java override the launcher reads
        settings = paths.load_settings()
        if java:
            settings["java"] = java
            paths.save_settings(settings)
        if not changed:
            return _ok(self, {"unchanged": True})
        self.server.broadcast("status", self._status())
        _ok(self, {"changed": changed})

    def server_start(self, body):
        instance_id = _instance_id(self, body)
        settings = paths.load_settings()
        env = paths.env_overrides(settings)
        entry = instances.get_instance(instance_id) or {}

        def job_fn(job):
            job.update(0.1, "launching java")
            return procs.start_server(
                instance_id, jar_name="paper.jar",
                xms=str(entry.get("xms") or settings.get("xms") or "512M"),
                xmx=str(entry.get("xmx") or settings.get("xmx") or "768M"),
                env=env)

        self.server.run_job(f"start {instance_id}", job_fn)
        _ok(self)

    def server_stop(self, body):
        instance_id = _instance_id(self, body)

        def job_fn(job):
            return procs.stop_server(instance_id, timeout=60.0,
                                     on_progress=lambda p, m: job.update(p, m))

        self.server.run_job(f"stop {instance_id}", job_fn)
        _ok(self)

    def server_kill(self, body):
        instance_id = _instance_id(self, body)
        status = procs.server_status(instance_id)
        pid = status.get("pid")
        if not pid:
            return _fail(self, "no running process to kill")
        import signal as _signal
        try:
            os.kill(int(pid), _signal.SIGKILL)
        except OSError as exc:
            return _fail(self, f"kill failed: {exc}")
        time.sleep(0.5)
        self.server.broadcast("status", self._status())
        _ok(self)

    def console_send(self, body):
        instance_id = _instance_id(self, body)
        command = str(body.get("command") or "")
        outcome = console_core.send(instance_id, command)
        if outcome.get("ok"):
            # the server's own log will carry the echo; push it to the clients
            lp = paths.log_paths(instance_id)
            lines = logs.tail(lp["server_log"], lines=2)
            self.server.broadcast("log", {"lines": lines})
            _ok(self)
        else:
            _fail(self, outcome.get("error", "command failed"))

    def _player_list_action(self, body, kind, add: bool):
        instance_id = _instance_id(self, body)
        name = str(body.get("name") or "").strip()
        if not name:
            return _fail(self, "Missing name")
        outcome = (players.add_entry if add else players.remove_entry)(
            instance_id, kind, name)
        if outcome.get("ok"):
            self.server.broadcast("players", self._players(instance_id))
            _ok(self)
        else:
            _fail(self, outcome.get("error", "list update failed"))

    def whitelist_add(self, body):
        self._player_list_action(body, "whitelist", add=True)

    def whitelist_remove(self, body):
        self._player_list_action(body, "whitelist", add=False)

    def op_add(self, body):
        self._player_list_action(body, "ops", add=True)

    def op_remove(self, body):
        self._player_list_action(body, "ops", add=False)

    def player_ban(self, body):
        instance_id = _instance_id(self, body)
        name = str(body.get("name") or "").strip()
        if not name:
            return _fail(self, "Missing name")
        reason = str(body.get("reason") or "Banned by an operator").strip()
        outcome = players.add_entry(instance_id, "bans", name, reason=reason)
        if outcome.get("ok"):
            # a banned player is kicked from the server and leaves the list
            console_core.send(instance_id, f"kick {name}")
            players.remove_entry(instance_id, "whitelist", name)
            self.server.broadcast("players", self._players(instance_id))
            _ok(self)
        else:
            _fail(self, outcome.get("error", "ban failed"))

    def player_kick(self, body):
        instance_id = _instance_id(self, body)
        name = str(body.get("name") or "").strip()
        if not name:
            return _fail(self, "Missing name")
        outcome = console_core.send(instance_id, f"kick {name}")
        if outcome.get("ok"):
            _ok(self)
        else:
            _fail(self, outcome.get("error", "kick failed"))

    def backups_create(self, body):
        instance_id = _instance_id(self, body)
        source = paths.instance_path(instance_id)
        if not source.is_dir():
            return _fail(self, f"instance folder missing: {source}")

        def job_fn(job):
            return backup.create(job, instance_id, source)

        self.server.run_job(f"backup {instance_id}", job_fn)
        _ok(self)

    def backups_restore(self, body):
        instance_id = _instance_id(self, body)
        name = str(body.get("name") or "").strip()
        if not name:
            return _fail(self, "Missing backup name")
        target = paths.instance_path(instance_id)

        def job_fn(job):
            for row in backup.list_backups(instance_id):
                if str(row.get("name")) == name:
                    return backup.restore(job, row.get("path"), target)
            return {"ok": False, "error": f"no backup named {name}"}

        self.server.run_job(f"restore {name}", job_fn)
        _ok(self)

    def backups_delete(self, body):
        name = str(body.get("name") or "").strip()
        if not name:
            return _fail(self, "Missing backup name")
        instance_id = _instance_id(self, body)
        for row in backup.list_backups(instance_id):
            if str(row.get("name")) == name:
                outcome = backup.delete(row.get("path"))
                if outcome.get("ok"):
                    return _ok(self)
                return _fail(self, outcome.get("error", "delete failed"))
        _fail(self, f"no backup named {name}")


ROUTES = {
    "/api/instances/active": ApiHandler.instances_active,
    "/api/instances/create": ApiHandler.instances_create,
    "/api/instances/delete": ApiHandler.instances_delete,
    "/api/instances/rename": ApiHandler.instances_rename,
    "/api/instances/clone": ApiHandler.instances_clone,
    "/api/instances/settings": ApiHandler.instances_settings,
    "/api/server/start": ApiHandler.server_start,
    "/api/server/stop": ApiHandler.server_stop,
    "/api/server/kill": ApiHandler.server_kill,
    "/api/console": ApiHandler.console_send,
    "/api/players/whitelist/add": ApiHandler.whitelist_add,
    "/api/players/whitelist/remove": ApiHandler.whitelist_remove,
    "/api/players/op/add": ApiHandler.op_add,
    "/api/players/op/remove": ApiHandler.op_remove,
    "/api/players/ban": ApiHandler.player_ban,
    "/api/players/kick": ApiHandler.player_kick,
    "/api/backups/create": ApiHandler.backups_create,
    "/api/backups/restore": ApiHandler.backups_restore,
    "/api/backups/delete": ApiHandler.backups_delete,
}


def _param(query: str, key: str) -> str:
    for pair in (query or "").split("&"):
        if not pair:
            continue
        name, _, value = pair.partition("=")
        if name == key:
            return value
    return ""


def _int(value: str, default: int) -> int:
    try:
        return max(1, min(2000, int(value)))
    except (TypeError, ValueError):
        return default


class EventClient:
    """One SSE subscriber. ``next`` blocks until an event or the timeout."""

    def __init__(self):
        self._queue = []
        self._cond = threading.Condition()

    def push(self, kind: str, payload):
        with self._cond:
            self._queue.append((kind, payload))
            self._cond.notify()

    def next(self, timeout: float):
        with self._cond:
            if not self._queue:
                self._cond.wait(timeout)
            if self._queue:
                return self._queue.pop(0)
        return None


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 jobs=None):
        super().__init__((host, port), ApiHandler)
        from .core.jobs import JobRunner
        self.jobs = jobs if jobs is not None else JobRunner()
        self.stop_event = threading.Event()
        self._clients = []
        self._clients_lock = threading.Lock()
        self._active = instances.active_id()
        self._last_log = {}
        self._watcher = threading.Thread(target=self._watch_loop,
                                         name="web-event-watcher", daemon=True)
        self._watcher.start()

    # --- jobs: the runner forwards **kwargs to the job function, so the
    #         completion broadcast lives here rather than in a callback ----
    def run_job(self, name: str, fn, *args):
        def wrapper(job, *a):
            try:
                return fn(job, *a)
            finally:
                self.broadcast("job", {"jobs": [j.snapshot()
                                                for j in self.jobs.recent(20)]})
                self.broadcast("status", self._status_snapshot())
        return self.jobs.run(name, wrapper, *args)

    # --- active instance (kept here so the web UI and TUI agree) --------
    def active_instance(self) -> str:
        return instances.active_id()

    def set_active_instance(self, instance_id: str) -> None:
        self._active = instance_id

    # --- event fan-out ---------------------------------------------------
    def subscribe(self) -> EventClient:
        client = EventClient()
        with self._clients_lock:
            self._clients.append(client)
        return client

    def unsubscribe(self, client) -> None:
        with self._clients_lock:
            if client in self._clients:
                self._clients.remove(client)

    def broadcast(self, kind: str, payload) -> None:
        with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            client.push(kind, payload)

    def _watch_loop(self) -> None:
        """Notice the world changing and tell every subscriber.

        The POST handlers broadcast the interesting state changes directly;
        this loop covers the ones nothing in this process triggers (a server
        started or stopped from the TUI or the command line, new log lines,
        a finished job)."""
        last_status = None
        last_players = None
        while not self.stop_event.is_set():
            time.sleep(EVENT_TICK)
            try:
                if self._clients:
                    self._push_logs()
                status = self._status_snapshot()
                if status != last_status:
                    last_status = status
                    self.broadcast("status", status)
                instance = instances.active_id()
                payload = None
                try:
                    payload = self._players(instance)
                except Exception:
                    payload = None
                if payload is not None and payload != last_players:
                    last_players = payload
                    self.broadcast("players", payload)
                for job in self.jobs.poll():
                    self.broadcast("job", {"jobs": [j.snapshot()
                                                    for j in self.jobs.recent(20)]})
            except Exception:
                # a watcher crash must not take the server down
                pass

    def _status_snapshot(self):
        active = instances.active_id()
        server = procs.server_status(active)
        playitd = procs.playitd_status()
        tunnel = procs.tunnel_status()
        return {
            "instance": active,
            "server": {"state": server.get("state"), "pid": server.get("pid"),
                       "uptime": server.get("uptime", 0),
                       "rss": server.get("rss", 0)},
            "playitd": {"state": playitd.get("state"), "pid": playitd.get("pid")},
            "tunnel": {"state": tunnel.get("state")},
        }

    def _push_logs(self) -> None:
        instance = instances.active_id()
        lp = paths.log_paths(instance)
        path = lp["server_log"]
        try:
            stamp = path.stat().st_mtime if path.exists() else 0.0
        except OSError:
            stamp = 0.0
        if stamp and stamp == self._last_log.get(instance):
            return
        lines = logs.tail(path, lines=12)
        self._last_log[instance] = stamp
        if lines:
            self.broadcast("log", {"lines": lines})

    # --- the players payload the SSE stream sends ------------------------
    def _players(self, instance_id: str):
        status = players.status(instance_id)
        return {
            "online": status.get("online", []),
            "recent": status.get("recent_players", []),
            "whitelist": _player_names(status.get("whitelist", [])),
            "ops": _player_names(status.get("ops", [])),
            "bans": [{"name": b.get("name", ""), "reason": b.get("reason", ""),
                      "created": b.get("created", "")}
                     for b in status.get("bans", []) if isinstance(b, dict)],
            "whitelist_enabled": bool(status.get("whitelist_enabled")),
            "online_mode": bool(status.get("online_mode")),
            "max_players": status.get("max_players") or "",
        }

    def shutdown(self) -> None:
        self.stop_event.set()
        super().shutdown()


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          jobs=None) -> WebServer:
    """Start the backend. Refuses a public bind unless explicitly allowed."""
    if host in ("0.0.0.0", "::") and not os.environ.get("MCTUI_WEB_ALLOW_PUBLIC"):
        raise SystemExit(
            f"refusing to bind the web UI to {host}: it exposes an "
            "unauthenticated server console to the network. Set "
            "MCTUI_WEB_ALLOW_PUBLIC=1 to override, and then only on a trusted "
            "network.")
    server = WebServer(host, port, jobs=jobs)
    if host in ("0.0.0.0", "::"):
        print("WARNING: the web UI is public on this machine. Anyone who can "
              "reach this port can send console commands to your server.",
              flush=True)
    return server
