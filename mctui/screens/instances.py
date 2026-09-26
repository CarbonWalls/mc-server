import curses
import time

from ..core import instances as instances_core
from ..core import procs, version
from ..ui import theme as th
from ..ui import widgets as w
from ._base import Screen


class instances(Screen):
    def enter(self):
        self.refresh()
        self.mode = None  # None | "clone" | "rename" | "versions" | "builds"
        self.edit = None
        self.confirm = None
        self.pending = None
        self.versions = []
        self.builds = []
        self.pick = w.ListView([])
        self.notice = ""
        self.notice_until = 0.0

    def refresh(self):
        index = instances_core.load_index()
        self.items = list(index.get("instances", []))
        active = instances_core.active_id()
        self.list = getattr(self, "list", w.ListView([]))
        labels = []
        for entry in self.items:
            marker = "*" if entry.get("id") == active else " "
            labels.append(f"{marker} {entry.get('id'):<18} "
                          f"{str(entry.get('paper_version') or '?'):<12} "
                          f"{entry.get('name', '')}")
        self.list.set_items(labels, keep_index=True)
        self.summaries = {
            entry.get("id", ""): instances_core.summary(entry) for entry in self.items
        }

    def _say(self, text, level="info", ttl=6.0):
        self.notice = text
        self.notice_until = time.time() + ttl
        self.ctx.notify(text, level, ttl)

    def current(self):
        if not self.items:
            return None
        return self.items[min(self.list.index, len(self.items) - 1)]

    def render(self, win):
        height, width = self.size(win)
        self.header(win, "instances", "instances/ + instances/active symlink")
        top = 3
        if self.mode in ("versions", "builds"):
            box_h = max(5, (height - 6) // 2)
        else:
            box_h = max(6, height - top - 5)
        if not self.items:
            self.frame(win, top, 1, box_h, width - 2, "instances")
            th.safe_addstr(win, top + 1, 3, "(none)", self.theme.dim)
        else:
            self.list.render(win, top, 1, box_h, width - 2, self.theme,
                             "instances (* = active)")

        row = top + box_h + 1
        entry = self.current()
        if entry:
            lines = [f"{label:<10}{value}"
                     for label, value in (self.summaries.get(entry.get("id", "")) or [])]
            detail_h = min(len(lines) + 2, height - row - 3)
            self.frame(win, row, 1, detail_h, width - 2, "detail")
            for i, line in enumerate(lines[: detail_h - 2]):
                th.safe_addstr(win, row + 1 + i, 3, th.trunc(line, width - 6),
                               self.theme.plain)
            row += detail_h + 1

        if self.mode in ("versions", "builds"):
            data = self.versions if self.mode == "versions" else self.builds
            labels = self._pick_labels()
            self.pick.set_items(labels, keep_index=False)
            pick_h = max(5, height - row - 3)
            title = "choose version (⏎, esc cancel)" if self.mode == "versions" \
                else "choose build (⏎, esc cancel)"
            self.pick.render(win, row, 1, pick_h, width - 2, self.theme, title)
        elif self.edit is not None:
            self.edit.render(win, row, 1, min(width - 2, 60), self.theme)
        elif time.time() < self.notice_until:
            th.safe_addstr(win, height - 2, 2, th.trunc(self.notice, width - 4),
                           self.theme.accent)

        self.footer(win, [
            ("⏎", "activate"), ("n", "new"), ("c", "clone"), ("r", "rename"),
            ("d", "delete"), ("p", "paper ver"), ("L", "reload"),
            ("?", "help"), ("q", "back"),
        ])
        if self.confirm is not None:
            self.confirm.render(win, self.theme)

    def _pick_labels(self) -> list:
        if self.mode == "versions":
            labels = []
            for entry in self.versions:
                marker = "" if entry.get("release") else "  (pre)"
                java = f"  java>={entry.get('min_java')}" if entry.get("min_java") else ""
                labels.append(f"{entry.get('key')}{marker}{java}")
            return labels
        labels = []
        for entry in self.builds:
            labels.append(f"build {entry.get('number')}  {entry.get('channel', '')}  "
                          f"{entry.get('createdAt', '')[:19]}  "
                          f"{procs.format_bytes(entry.get('size', 0))}")
        return labels

    # --- keys --------------------------------------------------------
    def handle_key(self, key):
        if self.confirm is not None:
            result = self.confirm.handle_key(key)
            action, self.pending = self.pending, None
            self.confirm = None
            if result == "yes" and action:
                getattr(self, action)()
            return None

        if self.mode in ("versions", "builds"):
            if key == 27 or key == ord("q"):
                self.mode = None
                return None
            action = self.pick.handle_key(key, height=max(4, self.size(self.ctx.stdscr)[0] // 2))
            if action == "select":
                if self.mode == "versions":
                    self._choose_version()
                else:
                    self._choose_build()
            return None

        if self.edit is not None:
            action = self.edit.handle_key(key)
            if action == "submit":
                self._submit_edit()
            elif key == 27:
                self.edit = None
                self.mode = None
            return None

        if key in (ord("q"), 27):
            return "back"
        action = self.list.handle_key(key, height=max(4, self.size(self.ctx.stdscr)[0] // 2))
        if action == "select":
            self._activate()
            return None
        entry = self.current()
        if key in (ord("n"), ord("N")):
            return "create"
        if entry is None:
            return None
        if key in (ord("L"), ord("l")):
            self.refresh()
        elif key in (ord("c"), ord("C")):
            self.mode = "clone"
            self.edit = w.TextEdit(f"{entry['id']}-copy", label="new instance id",
                                   validator=instances_core.validate_name)
        elif key in (ord("r"), ord("R")):
            self.mode = "rename"
            self.edit = w.TextEdit(entry["id"], label="new instance id",
                                   validator=instances_core.validate_name)
        elif key in (ord("d"), ord("D")):
            state = procs.server_status(entry["id"]).get("state")
            if state == "running":
                self._say("stop that instance first", "err")
                return None
            self.confirm = self.confirm_dialog(
                f"Delete instance '{entry['id']}' and its folder? A tar.gz copy is made "
                "into backups/ first.",
                title="delete instance", dangerous=True, yes_label="delete")
            self.pending = "_do_delete"
        elif key in (ord("p"), ord("P")):
            self._load_versions()
        return None

    def _activate(self):
        entry = self.current()
        if not entry:
            return
        outcome = instances_core.set_active(entry["id"])
        if outcome.get("ok"):
            self.ctx._status_cache = {"at": 0.0, "data": {}}
            self._say(f"active instance -> {entry['id']}", "ok")
            self.refresh()
        else:
            self._say(str(outcome.get("error")), "err")

    def _submit_edit(self):
        entry = self.current()
        edit, mode = self.edit, self.mode
        self.edit = None
        self.mode = None
        if not entry or not edit or not mode:
            return
        if mode == "clone":
            outcome = instances_core.clone(entry["id"], edit.value)
        elif mode == "rename":
            outcome = instances_core.rename(entry["id"], edit.value)
        else:
            return
        self.refresh()
        if outcome.get("ok"):
            self._say(str(outcome.get("message") or "done"), "ok")
        else:
            self._say(str(outcome.get("error", "failed")), "err")

    def _do_delete(self):
        entry = self.current()
        if not entry:
            return
        outcome = instances_core.delete(entry["id"], make_backup=True)
        self.refresh()
        if outcome.get("ok"):
            self._say(str(outcome.get("message") or "deleted"), "ok", 8.0)
        else:
            self._say(str(outcome.get("error", "failed")), "err", 8.0)

    # --- paper version flow ------------------------------------------
    def _load_versions(self):
        self._say("fetching paper versions...", "info", 10.0)

        def job_fn(job):
            job.update(0.2, "querying papermc")
            return version.paper_versions(limit=25)

        def on_done(job):
            result = job.result or []
            if not result:
                self._say("no versions returned (network?)", "err")
                return
            self.versions = result
            self.mode = "versions"
            self.pick = w.ListView([])
            self.pick.index = 0
            self._say(f"{len(result)} versions - pick one", "ok", 6.0)

        self.ctx.run_job("paper versions", job_fn, on_done=on_done)

    def _choose_version(self):
        entry = self.versions[self.pick.index]
        key = entry.get("key")
        self.mode = "builds"
        self.pick = w.ListView([])
        self._say(f"fetching builds for {key}...", "info", 10.0)

        def job_fn(job, version_key):
            job.update(0.2, f"querying builds for {version_key}")
            return version.paper_builds(version_key, limit=15)

        def on_done(job, version_key):
            result = job.result or []
            if not result:
                self._say("no builds returned", "err")
                self.mode = None
                return
            self.builds = result
            self.pending_version = version_key

        self.ctx.run_job("paper builds", job_fn, key, on_done=lambda j: on_done(j, key))

    def _choose_build(self):
        build = self.builds[self.pick.index]
        entry = self.current()
        if not entry:
            self.mode = None
            return
        self.mode = None
        need = build.get("min_java") or version.min_java_for(str(build.get("version", "")))
        installed = procs.java_major(self.ctx.settings.get("java", ""))
        if need and installed and installed < need:
            self._say(f"java {installed} < required {need} for this build - install a JDK first",
                      "err", 10.0)
            return
        self.confirm = self.confirm_dialog(
            f"Replace paper.jar of '{entry['id']}' with build {build.get('number')} "
            f"({build.get('version')})? The current jar is copied to backups/.",
            title="change paper version", dangerous=True, yes_label="upgrade")
        self.pending = "_do_change_paper"
        self.pending_build = build

    def _do_change_paper(self):
        entry = self.current()
        build = getattr(self, "pending_build", None)
        if not entry or not build:
            return

        def job_fn(job):
            return instances_core.change_paper_version(job, entry["id"], build)

        def on_done(job):
            result = job.result or {}
            if result.get("ok"):
                self._say(f"paper {result.get('build')} installed", "ok", 8.0)
            else:
                self._say(str(result.get("error", "change failed")), "err", 10.0)
            self.refresh()

        self.ctx.run_job("change paper", job_fn, on_done=on_done)
