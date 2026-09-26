import platform
import sys
import time

from ..core import instances, paths, playit_ipc, probes, procs, version
from ..ui import theme as th
from ..ui import widgets as w
from ._base import Screen


class diagnostics(Screen):
    def enter(self):
        self.scroll = w.ScrollView(maxlen=1500)
        self.lines = []
        self.java_line = ""
        self.focus_at = 0.0
        self.notice = ""
        self.notice_until = 0.0
        self.rebuild()

    def _say(self, text, level="info", ttl=5.0):
        self.notice = text
        self.notice_until = time.time() + ttl
        self.ctx.notify(text, level, ttl)

    def rebuild(self):
        lines = []
        instance = self.ctx.instance_id
        settings = self.ctx.settings
        entry = instances.get_instance(instance) or {}
        lines.append(f"== host ==")
        lines.append(f"platform    {platform.platform()}")
        lines.append(f"machine     {platform.machine()}  python {sys.version.split()[0]}")
        lines.append(f"cwd         {paths.relative(paths.root())}")
        lines.append(f"free disk   {procs.format_bytes(paths.free_bytes())}")
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                mem = dict(line.split(":", 1) for line in fh.read().splitlines() if ":" in line)
            avail = int(mem.get("MemAvailable", "0 kB").split()[0]) * 1024
            total = int(mem.get("MemTotal", "0 kB").split()[0]) * 1024
            lines.append(f"memory      {procs.format_bytes(avail)} available of "
                         f"{procs.format_bytes(total)}")
        except OSError:
            pass
        lines.append("")
        lines.append(f"== java ==")
        lines.append(f"bundled     {paths.relative(paths.java_bin())} "
                     f"({'ok' if paths.java_bin().exists() else 'MISSING'})")
        lines.append(f"override    {settings.get('java') or '(none)'}")
        if not self.java_line:
            self.java_line = procs.java_version(settings.get("java", ""))
        lines.append(f"version     {self.java_line}")
        lines.append("")
        lines.append(f"== instance {instance} ==")
        for label, value in instances.summary(entry) or []:
            lines.append(f"{label:<12}{value}")
        lines.append("")
        lines.append(f"== processes ==")
        status = procs.server_status(instance)
        lines.append(f"server      {status['state']} pid {status.get('pid') or '-'} "
                     f"rss {procs.format_bytes(status.get('rss', 0))}")
        playitd = procs.playitd_status()
        lines.append(f"playitd     {playitd['state']} pid {playitd.get('pid') or '-'} "
                     f"socket {'ok' if playitd.get('socket_exists') else 'missing'}")
        tunnel = procs.tunnel_status()
        lines.append(f"tunnel      {tunnel['state']} pid {tunnel.get('pid') or '-'}")
        lines.append("")
        lines.append(f"== settings ==")
        for key in sorted(settings):
            lines.append(f"{key:<16}{settings[key]}")
        lines.append("")
        lines.append("press p/b/w/e/i for network probes, r to reload, ? help")
        self.lines = lines
        self.scroll.set_lines(lines)

    def tick(self):
        self.focus_at += 1
        if self.focus_at >= 100:
            self.focus_at = 0
            self.rebuild()

    def render(self, win):
        height, width = self.size(win)
        self.header(win, "diagnostics", f"instance: {self.ctx.instance_id}")
        lines = list(self.lines)
        if self.notice and time.time() < self.notice_until:
            lines.append("")
            lines.append(f"!! {self.notice}")
        self.scroll.render(win, 3, 1, max(5, height - 6), width - 2, self.theme,
                           "report", lines=lines, highlight="!!")
        self.footer(win, [
            ("p", "java ping"), ("b", "bedrock ping"), ("w", "status API (java)"),
            ("e", "status API (bedrock)"), ("i", "playit ipc"), ("r", "reload"),
            ("?", "help"), ("q", "back"),
        ])

    def handle_key(self, key):
        if key in (ord("q"), 27):
            return "back"
        if key in (ord("r"), ord("R")):
            self.rebuild()
            self._say("reloaded", "ok", 2.0)
            return None
        if key in (ord("p"), ord("P")):
            self._probe("java ping", self._java_ping)
            return None
        if key in (ord("b"), ord("B")):
            self._probe("bedrock ping", self._bedrock_ping)
            return None
        if key in (ord("w"), ord("W")):
            self._probe("status API (java)", self._api_java)
            return None
        if key in (ord("e"), ord("E")):
            self._probe("status API (bedrock)", self._api_bedrock)
            return None
        if key in (ord("i"), ord("I")):
            self._probe("playit ipc", self._playit)
            return None
        page = max(4, self.size(self.ctx.stdscr)[0] - 8)
        self.scroll.handle_key(key, page=page)
        return None

    # --- probes ------------------------------------------------------
    def _probe(self, name, fn):
        def job_fn(job, target):
            job.update(0.2, f"running {name}")
            return target()

        def on_done(job):
            for line in job.result or []:
                self.lines.append(line)
            self.scroll.set_lines(self.lines)
            self._say(f"{name}: done", "ok", 3.0)

        self.ctx.run_job(name, job_fn, fn, on_done=on_done)

    def _java_ping(self):
        port = int(self.ctx.settings.get("server_port", 25565) or 25565)
        out = [f"-- java ping 127.0.0.1:{port} --"]
        try:
            result = probes.java_status_ping("127.0.0.1", port, timeout=4.0)
            out.append(f"ok: {result.get('ok')} in {result.get('ms')} ms  "
                       f"{result.get('players_online')}/{result.get('players_max')} online  "
                       f"version {result.get('version')}")
            out.append(f"motd: {result.get('description')}")
            if not result.get("ok"):
                out.append(f"error: {result.get('error')}")
        except Exception as exc:
            out.append(f"failed: {type(exc).__name__}: {exc}")
        return out

    def _bedrock_ping(self):
        port = int(self.ctx.settings.get("bedrock_port", 44041) or 44041)
        out = [f"-- raknet ping 127.0.0.1:{port} --"]
        try:
            result = probes.raknet_probe("127.0.0.1", port, timeout=4.0)
            out.append(str(result))
        except Exception as exc:
            out.append(f"failed: {type(exc).__name__}: {exc}")
        return out

    def _api_java(self):
        port = int(self.ctx.settings.get("server_port", 25565) or 25565)
        out = ["-- mcstatus.io java --"]
        try:
            out.append(str(probes.mcstatus_java("127.0.0.1", port, timeout=15)))
        except Exception as exc:
            out.append(f"failed: {type(exc).__name__}: {exc}")
        return out

    def _api_bedrock(self):
        port = int(self.ctx.settings.get("bedrock_port", 44041) or 44041)
        out = ["-- mcstatus.io bedrock --"]
        try:
            out.append(str(probes.mcstatus_bedrock("127.0.0.1", port, timeout=15)))
        except Exception as exc:
            out.append(f"failed: {type(exc).__name__}: {exc}")
        return out

    def _playit(self):
        out = ["-- playit ipc --"]
        try:
            result = playit_ipc.query(timeout=4.0)
            out.append(f"version {result.get('version')} phase {result.get('phase')} "
                       f"uptime {playit_ipc.format_uptime(result.get('uptime_secs'))}")
            out.append(f"account {result.get('account_status')} "
                       f"agent {result.get('agent_id')}")
            if result.get("last_error"):
                out.append(f"last error: {result['last_error']}")
            for row in playit_ipc.tunnel_rows(result):
                flag = " (disabled)" if row["disabled"] else ""
                out.append(f"  {row['proto']:<3} {row['host']} -> {row['destination']}{flag}")
            for notice in (result.get("notices") or [])[:5]:
                out.append(f"notice: {notice}")
        except Exception as exc:
            out.append(f"failed: {type(exc).__name__}: {exc}")
            out.append(f"socket: {paths.relative(paths.playit_socket())}")
        return out
