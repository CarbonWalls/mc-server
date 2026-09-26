import time

from ..core import instances, paths, playit_ipc, procs
from ..ui import theme as th
from ..ui import widgets as w
from ..ui.panels import draw_kv
from ._base import Screen


class dashboard(Screen):
    MENU = [
        ("server control", "control"),
        ("create a new server", "create"),
        ("instances", "instances"),
        ("players", "players"),
        ("logs", "logs"),
        ("backups", "backup"),
        ("diagnostics", "diag"),
        ("config editor", "config"),
        ("settings", "settings"),
        ("quit", "quit"),
    ]

    def enter(self):
        self.list = w.ListView([label for label, _ in self.MENU])
        self.java_line = ""
        self.java_at = 0.0
        self.tunnel_rows = []
        self.tunnel_at = 0.0
        self.tunnel_error = ""
        self.ping = None

    def tick(self):
        now = time.time()
        if now - self.java_at > 30:
            self.java_at = now
            self.java_line = procs.java_version(self.ctx.settings.get("java", ""))
        if now - self.tunnel_at > 8:
            self.tunnel_at = now
            try:
                result = playit_ipc.query(timeout=3.0)
                self.tunnel_rows = playit_ipc.tunnel_rows(result)
                self.tunnel_error = ""
            except Exception as exc:
                self.tunnel_rows = []
                self.tunnel_error = str(exc)

    def _state_line(self, status: dict) -> str:
        state = status.get("state", "unknown")
        if state == "running":
            return (f"running  pid {status.get('pid')}  "
                    f"up {procs.format_uptime(status.get('uptime'))}  "
                    f"rss {procs.format_bytes(status.get('rss', 0))}")
        if state == "stale":
            return f"stale pid file ({status.get('pid')}) - press q in control to clear"
        return "stopped"

    def render(self, win):
        height, width = self.size(win)
        instance = self.ctx.instance_id
        entry = instances.get_instance(instance) or {}
        self.header(win, f"mc-tui  /  {instance}",
                    entry.get("name", "") + (f"  -  {entry.get('motd', '')}" if entry.get("motd") else ""))
        data = self.ctx.status_data()
        server = data["server"]
        playitd = data["playitd"]
        free = data["free"]

        box_h = min(9, max(6, height - 16))
        self.frame(win, 2, 1, box_h, width - 2, "status")
        col_x = [3, max(width // 2 + 1, 40)]
        kv_w = max(20, width // 2 - 6)
        left = [
            ("server", self._state_line(server)),
            ("instance", f"{instance}  ->  {paths.relative(paths.instance_path(instance))}"),
            ("java", (self.java_line or "checking...")[:kv_w]),
            ("paper", f"{entry.get('paper_version', '?')} build {entry.get('build', '?')}"),
        ]
        right = [
            ("playitd", self._state_line(playitd) +
             ("  socket ok" if playitd.get("socket_exists") else "  no socket")),
            ("tunnel", self._tunnel_summary()),
            ("disk", f"{procs.format_bytes(free)} free  ({paths.relative(paths.backups_dir())})"),
            ("jobs", self.ctx.busy_line() or "idle"),
        ]
        for i in range(min(len(left), box_h - 2)):
            label, value = left[i]
            draw_kv(win, 3 + i, col_x[0], [(label, value)], self.theme, key_width=9, max_width=kv_w)
        for i in range(min(len(right), box_h - 2)):
            label, value = right[i]
            draw_kv(win, 3 + i, col_x[1], [(label, value)], self.theme, key_width=9, max_width=kv_w)

        list_top = 2 + box_h + 1
        list_h = max(5, height - list_top - 3)
        self.list.render(win, list_top, 1, list_h, width - 2, self.theme, "menu")
        if self.ping:
            attr = self.theme.ok if self.ping.get("ok") else self.theme.warn
            text = self.ping.get("text", "")
            th.safe_addstr(win, list_top - 1, 3, th.trunc(text, width - 6), attr)
        self.footer(win, [
            ("↑↓", "move"), ("⏎", "open"), ("p", "ping"), ("r", "refresh"),
            ("?", "help"), ("q", "quit"),
        ])

    def _tunnel_summary(self) -> str:
        if self.tunnel_error:
            return f"unavailable ({self.tunnel_error[:40]})"
        if not self.tunnel_rows:
            return "no tunnels"
        first = self.tunnel_rows[0]
        extra = f" (+{len(self.tunnel_rows) - 1} more)" if len(self.tunnel_rows) > 1 else ""
        return f"{first['host']} -> {first['destination']}{extra}"

    def handle_key(self, key):
        height, _ = self.size(self.ctx.stdscr)
        action = self.list.handle_key(key, max(1, height - 16))
        if action == "select":
            index = self.list.index
            if index >= len(self.MENU):
                return None
            label, target = self.MENU[index]
            if target == "quit":
                return "quit"
            return target
        if key in (ord("r"), ord("R")):
            self.ctx._status_cache = {"at": 0.0, "data": {}}
            self.java_at = 0.0
            self.tunnel_at = 0.0
            self.ctx.notify("refreshing status", "info", 2.0)
            return None
        if key in (ord("p"), ord("P")):
            self._ping()
            return None
        if key in (ord("q"), 27):
            return "quit"
        return None

    def _ping(self):
        from ..core import probes

        port = int(self.ctx.settings.get("server_port", 25565) or 25565)

        def job_fn(job, host, port):
            job.update(0.1, f"ping {host}:{port}")
            result = probes.java_status_ping(host, port, timeout=4.0)
            job.update(1.0, "done")
            return result

        def on_done(job):
            result = job.result or {}
            if isinstance(result, dict) and result.get("ok"):
                self.ping = {"ok": True,
                             "text": (f"online: {result.get('players_online')}/"
                                      f"{result.get('players_max')}  "
                                      f"{result.get('version', '')}  "
                                      f"{str(result.get('description', ''))[:40]}")}
            else:
                reason = result.get("error", "") if isinstance(result, dict) else ""
                self.ping = {"ok": False,
                             "text": f"no answer on 127.0.0.1:{port} {reason}"}

        self.ping = {"ok": True, "text": "pinging..."}
        self.ctx.run_job("ping", job_fn, "127.0.0.1", port, on_done=on_done)
