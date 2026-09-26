import time

from ..core import instances, procs
from ..ui import theme as th
from ..ui import widgets as w
from ..ui.panels import ProgressBar, draw_wrapped, spinner_char
from ..ui.wizard import Wizard
from ._base import Screen
from .create_steps import BuildStep, NameStep, PerfStep, VersionStep
from .create_steps_config import (GameplayStep, NetworkStep, PluginsStep,
                                 ReviewStep)


class create_server(Screen):
    def enter(self):
        self.phase = "wizard"
        self.quit_at = 0.0
        self.result = None
        self.job = None
        self.confirm = None
        self.wiz = Wizard(
            [NameStep(), VersionStep(), BuildStep(), PerfStep(), GameplayStep(),
             NetworkStep(), PluginsStep(), ReviewStep()],
            data={}, title="create server", ctx=self.ctx)

    # --- build -------------------------------------------------------
    def _spec(self) -> dict:
        data = self.wiz.data
        build = dict(data.get("build") or {})
        net = data.get("net", {})
        props = dict(data.get("props") or {})
        server_port = int(net.get("server-port", 25565) or 25565)
        props["server-port"] = str(server_port)
        bedrock_on = net.get("bedrock") == "true"
        paper = {
            "url": build.get("url", ""),
            "size": build.get("size", 0),
            "sha256": build.get("sha256") or "",
            "version": str(build.get("version") or data.get("version_key", "")),
            "number": build.get("number"),
        }
        return {
            "id": str(data.get("name", "")),
            "name": str(data.get("display") or data.get("name", "")),
            "paper": paper,
            "properties": props,
            "server_port": server_port,
            "motd": props.get("motd", ""),
            "tunnel": net.get("tunnel", "none"),
            "perf": {"preset": data.get("perf", "balanced"),
                     "xms": data.get("xms", "512M"),
                     "xmx": data.get("xmx", "768M")},
            "geyser": {"install": bedrock_on,
                       "port": int(net.get("bedrock-port", 19132) or 19132),
                       "broadcast_port": int(net.get("bedrock-port", 19132) or 19132),
                       "auth_type": "offline", "transport": "raknet", "haproxy": True},
            "plugins": list(data.get("plugins") or []),
            "plugin_specs": list(data.get("specs") or []),
            "note": "",
        }

    def _start_build(self):
        spec = self._spec()
        if not spec["paper"].get("url"):
            self.wiz.set_error("no paper download url - go back to the build step")
            return
        self.phase = "building"
        preset = procs.PRESETS.get(self.wiz.data.get("perf", "balanced"), {})

        def job_fn(job):
            return instances.build_instance(job, spec)

        def on_done(job):
            self.result = job.result if isinstance(job.result, dict) else {}
            self.phase = "done" if (job.ok and self.result.get("ok")) else "failed"
            if self.phase == "done":
                instances.update_instance(spec["id"],
                                          xms=preset.get("xms", ""),
                                          xmx=preset.get("xmx", ""))
                self.ctx._status_cache = {"at": 0.0, "data": {}}

        self.job = self.ctx.run_job(f"create {spec['id']}", job_fn, on_done=on_done)

    # --- drawing -----------------------------------------------------
    def render(self, win):
        height, width = self.size(win)
        if self.phase == "wizard":
            self.wiz.render(win, self.theme)
            return
        if self.phase == "building":
            self.header(win, "create server", f"building {self.wiz.data.get('name')}")
            job = self.job
            bar = ProgressBar()
            frac = job.progress if job else 0.0
            bar.update(frac, (job.message if job else ""), active=True)
            bar.render(win, 4, 3, width - 6, self.theme, spinner_char(self.ctx.tick))
            lines = [
                "",
                "this runs in a worker thread; the UI stays responsive",
                "",
                "what happens now:",
                "  1. folders + eula.txt are created",
                "  2. paper.jar is downloaded and checksum-verified",
                "  3. server.properties and Geyser config are written",
                "  4. selected plugins are downloaded",
                "  5. the instance is registered in instances/index.json",
            ]
            for i, line in enumerate(lines):
                th.safe_addstr(win, 6 + i, 3, th.trunc(line, width - 6), self.theme.plain)
            self.footer(win, [("esc", "wait"), ("?", "help"), ("q", "back")])
            return

        title = "create server - finished" if self.phase == "done" \
            else "create server - failed"
        self.header(win, title, f"instance: {self.wiz.data.get('name')}")
        box_y, box_x, box_h, box_w = self.content_box(
            win, "result" if self.phase == "done" else "error", top=3)
        if self.phase == "done":
            rows = [
                ("instance", self.result.get("instance", {}).get("id", "")),
                ("path", self.result.get("path", "")),
                ("jar", self.result.get("jar", "")),
                ("plugins", ", ".join(
                    f"{p['id']}{'!' if not p.get('ok') else ''}"
                    for p in self.result.get("plugins", [])) or "none"),
            ]
            for i, (label, value) in enumerate(rows[: box_h - 2]):
                th.safe_addstr(win, box_y + i, box_x, th.trunc(label, 12), self.theme.dim)
                th.safe_addstr(win, box_y + i, box_x + 14,
                               th.trunc(str(value), box_w - 16), self.theme.plain)
            note = "next: activate it in instances, then start it in server control"
            th.safe_addstr(win, box_y + max(1, box_h - 3), box_x,
                           th.trunc(note, box_w), self.theme.ok)
        else:
            message = str(self.result.get("error") or (self.job.error if self.job else "")
                          or "unknown failure")
            draw_wrapped(win, box_y, box_x, box_w, message, self.theme,
                           attr=self.theme.err, max_lines=box_h - 2)
        self.footer(win, [
            ("⏎", "instances" if self.phase == "done" else "retry"),
            ("q", "back to dashboard"), ("?", "help"),
        ])

    # --- keys --------------------------------------------------------
    def handle_key(self, key):
        if self.phase == "wizard":
            if self.confirm is not None:
                result = self.confirm.handle_key(key)
                self.confirm = None
                if result == "yes":
                    return "back"
                return None
            action = self.wiz.handle_key(key)
            if action == "quit":
                now = time.time()
                if now - self.quit_at < 1.5:
                    return "back"
                self.quit_at = now
                self.confirm = self.confirm_dialog(
                    self.wiz.confirm_text(), title="leave wizard", dangerous=False,
                    yes_label="leave")
                return None
            if action == "done" and self.wiz.finished:
                self._start_build()
            return None
        if self.phase == "building":
            if key in (ord("q"), 27):
                self.ctx.notify("build thread cannot be cancelled - wait for it", "warn", 4.0)
            return None
        # done / failed
        if key in (10, 13, 9):
            if self.phase == "done":
                return "instances"
            self.phase = "wizard"
            self.wiz.finished = False
            return None
        if key in (ord("q"), 27):
            return "back" if len(self.ctx.stack) > 1 else "quit"
        return None
