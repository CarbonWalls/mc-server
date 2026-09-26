import time

from ..core import paths, probes, procs
from ..ui import theme as th
from ..ui import widgets as w
from ._base import Screen


class server_control(Screen):
    def enter(self):
        self.confirm = None
        self.pending_action = ""
        self.heap = ""
        self.heap_at = 0.0
        self.tail_lines = []
        self.tail_at = 0.0
        self.notice = ""
        self.notice_until = 0.0
        self.scroll = w.ScrollView(maxlen=40)

    def _say(self, text, level="info", ttl=6.0):
        self.notice = text
        self.notice_until = time.time() + ttl
        self.ctx.notify(text, level, ttl)

    def tick(self):
        now = time.time()
        if now - self.tail_at > 1.0:
            self.tail_at = now
            lp = paths.log_paths(self.ctx.instance_id)
            if lp["server_log"].exists():
                from ..core import logs as logs_core
                self.tail_lines = logs_core.tail(lp["server_log"], lines=8)
                self.scroll.set_lines(self.tail_lines)
        if now - self.heap_at > 15:
            self.heap_at = now
            status = self.ctx.status_data()["server"]
            if status.get("state") == "running" and status.get("pid"):
                self.heap = procs.heap_info(status["pid"])
            else:
                self.heap = ""

    def render(self, win):
        height, width = self.size(win)
        self.header(win, "server control", f"instance: {self.ctx.instance_id}")
        data = self.ctx.status_data()
        server = data["server"]
        playitd = data["playitd"]
        settings = self.ctx.settings

        state = server.get("state", "unknown")
        color = self.theme.ok if state == "running" else (
            self.theme.warn if state == "stale" else self.theme.dim)
        rows = [
            ("server", f"{state}   pid {server.get('pid') or '-'}"),
            ("uptime", procs.format_uptime(server.get("uptime", 0))),
            ("memory", procs.format_bytes(server.get("rss", 0)) + " resident"),
            ("heap", (self.heap or "n/a")[: max(10, width - 24)]),
            ("xms/xmx", f"{settings.get('xms')} / {settings.get('xmx')}"),
            ("log", f"{paths.relative(server.get('log_file'))} "
                    f"({procs.format_bytes(server.get('log_size', 0))})"),
            ("playitd", f"{playitd.get('state')}  "
                        f"pid {playitd.get('pid') or '-'}  "
                        f"socket {'ok' if playitd.get('socket_exists') else 'missing'}"),
            ("tunnel proc", f"{data['tunnel'].get('state')}  "
                            f"pid {data['tunnel'].get('pid') or '-'}"),
        ]
        box_h = len(rows) + 2
        self.frame(win, 2, 1, box_h, width - 2, "status")
        for i, (label, value) in enumerate(rows):
            attr = color if label == "server" else self.theme.plain
            th.safe_addstr(win, 3 + i, 3, th.trunc(label, 12), self.theme.dim)
            th.safe_addstr(win, 3 + i, 16, th.trunc(value, width - 20), attr)

        actions = self._actions(state, playitd.get("state"), data["tunnel"].get("state"))
        act_top = 2 + box_h + 1
        act_h = len(actions) + 2
        self.frame(win, act_top, 1, act_h, width - 2, "actions")
        for i, (key, label) in enumerate(actions):
            th.safe_addstr(win, act_top + 1 + i, 3, f"[{key}]", self.theme.warn)
            th.safe_addstr(win, act_top + 1 + i, 7, th.trunc(label, width - 10), self.theme.plain)

        tail_top = act_top + act_h + 1
        tail_h = max(4, height - tail_top - 3)
        self.scroll.render(win, tail_top, 1, tail_h, width - 2, self.theme,
                      "recent log (l for full viewer)", lines=self.tail_lines)

        if self.confirm is not None:
            self.confirm.render(win, self.theme)
        elif time.time() < self.notice_until:
            th.safe_addstr(win, height - 2, 3, th.trunc(self.notice, width - 6),
                           self.theme.accent)

        self.footer(win, [
            ("s", "start"), ("x", "stop"), ("k", "kill"), ("c", "clear stale"),
            ("d", "playitd"), ("t", "tunnel"), ("l", "logs"), ("p", "ping"),
            ("?", "help"), ("q", "back"),
        ])

    def _actions(self, server_state, playitd_state, tunnel_state) -> list:
        actions = []
        actions.append(("s", "start the Minecraft server" if server_state != "running"
                        else "already running"))
        actions.append(("x", "stop cleanly (save + shutdown)" if server_state == "running"
                        else "nothing to stop"))
        actions.append(("k", "force kill the java process" if server_state == "running"
                        else "-"))
        actions.append(("c", "clear stale pid file" if server_state == "stale" else "-"))
        actions.append(("d", "stop playitd" if playitd_state == "running" else "start playitd"))
        actions.append(("t", "stop tunnel attach" if tunnel_state == "running"
                        else "start tunnel attach"))
        actions.append(("l", "open full log viewer"))
        actions.append(("p", "ping 127.0.0.1 and show player count"))
        return actions

    # --- actions -----------------------------------------------------
    def handle_key(self, key):
        if self.confirm is not None:
            result = self.confirm.handle_key(key)
            if result == "yes":
                action, self.confirm = self.pending_action, None
                self._run(action)
            elif result == "no":
                self.confirm = None
            return None
        if key in (ord("q"), 27):
            return "back"
        if key == ord("s"):
            self._start()
        elif key == ord("x"):
            if self.ctx.status_data()["server"].get("state") == "running":
                self.confirm = self.confirm_dialog(
                    "Stop the server now? Players will be kicked and the world saved.",
                    title="stop server")
                self.pending_action = "stop"
        elif key == ord("k"):
            self.confirm = self.confirm_dialog(
                "Force kill the java process? Unsaved progress since the last save is lost.",
                title="force kill", dangerous=True, yes_label="kill")
            self.pending_action = "kill"
        elif key == ord("c"):
            message = procs.clear_stale(self.ctx.instance_id)
            self.ctx._status_cache = {"at": 0.0, "data": {}}
            self._say(message, "ok")
        elif key == ord("d"):
            self._toggle_playitd()
        elif key == ord("t"):
            self._toggle_tunnel()
        elif key == ord("l"):
            return "logs"
        elif key == ord("p"):
            self._ping()
        return None

    def _start(self):
        settings = self.ctx.settings
        instance = self.ctx.instance_id
        env = paths.env_overrides(settings)

        def job_fn(job):
            job.update(0.1, "launching java")
            result = procs.start_server(
                instance, jar_name="paper.jar",
                xms=str(settings.get("xms", "512M")),
                xmx=str(settings.get("xmx", "768M")),
                env=env,
            )
            return result

        def on_done(job):
            result = job.result or {}
            if result.get("ok"):
                self._say(f"started pid {result.get('pid')}", "ok")
            else:
                self._say(result.get("error", "start failed"), "err", 8.0)
            self.ctx._status_cache = {"at": 0.0, "data": {}}

        self.ctx.run_job("start server", job_fn, on_done=on_done)

    def _run(self, action):
        instance = self.ctx.instance_id
        if action == "stop":
            def job_fn(job):
                return procs.stop_server(instance, timeout=60.0,
                                         on_progress=lambda p, m: job.update(p, m))

            def on_done(job):
                self._say(str((job.result or {}).get("message", "stopped")), "ok")
                self.ctx._status_cache = {"at": 0.0, "data": {}}

            self.ctx.run_job("stop server", job_fn, on_done=on_done)
        elif action == "kill":
            import os as _os
            import signal as _signal
            status = self.ctx.status_data()["server"]
            pid = status.get("pid")
            if not pid:
                self._say("no running process", "warn")
                return
            try:
                _os.kill(int(pid), _signal.SIGKILL)
                self._say(f"SIGKILL sent to {pid}", "ok")
            except Exception as exc:
                self._say(f"kill failed: {exc}", "err")
            self.ctx._status_cache = {"at": 0.0, "data": {}}

    def _toggle_playitd(self):
        status = self.ctx.status_data()["playitd"]
        running = status.get("state") == "running"

        def job_fn(job):
            job.update(0.2, "stopping" if running else "starting playitd")
            if running:
                return procs.stop_playitd(timeout=15.0, on_progress=lambda p, m: job.update(p, m))
            return procs.start_playitd(verbose=True)

        def on_done(job):
            result = job.result or {}
            self._say(str(result.get("message") or result.get("error") or "done"),
                      "ok" if result.get("ok", True) else "err")
            self.ctx._status_cache = {"at": 0.0, "data": {}}

        self.ctx.run_job("playitd", job_fn, on_done=on_done)

    def _toggle_tunnel(self):
        status = self.ctx.status_data()["tunnel"]
        running = status.get("state") == "running"

        def job_fn(job):
            job.update(0.2, "toggling tunnel attach")
            return procs.stop_tunnel_attach() if running else procs.start_tunnel_attach()

        def on_done(job):
            result = job.result or {}
            self._say(str(result.get("message") or result.get("error") or "done"),
                      "ok" if result.get("ok", True) else "err")
            self.ctx._status_cache = {"at": 0.0, "data": {}}

        self.ctx.run_job("tunnel", job_fn, on_done=on_done)

    def _ping(self):
        port = int(self.ctx.settings.get("server_port", 25565) or 25565)

        def job_fn(job, host, port):
            job.update(0.2, "pinging")
            return probes.java_status_ping(host, port, timeout=4.0)

        def on_done(job):
            result = job.result or {}
            if result.get("ok"):
                self._say(f"online {result.get('players_online')}/"
                          f"{result.get('players_max')} ({result.get('ms')} ms)", "ok")
            else:
                self._say(f"no answer on 127.0.0.1:{port} "
                          f"{result.get('error', '')}", "warn")

        self.ctx.run_job("ping", job_fn, "127.0.0.1", port, on_done=on_done)
