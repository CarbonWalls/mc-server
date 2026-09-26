import time
from datetime import datetime

from ..core import backup, instances, paths, procs
from ..ui import theme as th
from ..ui import widgets as w
from ._base import Screen


class backups(Screen):
    def enter(self):
        self.show_all = False
        self.list = w.ListView([])
        self.confirm = None
        self.pending = None
        self.notice = ""
        self.notice_until = 0.0
        self.refresh()

    def refresh(self):
        instance_id = None if self.show_all else self.ctx.instance_id
        self.items = backup.list_backups(instance_id)
        self.source = instances.path_of(self.ctx.instance_id)
        try:
            self.projected = backup.estimate(self.source)
        except OSError:
            self.projected = 0
        self.list.set_items(
            [f"{item['name']}   {procs.format_bytes(item['size']):>9}   "
             f"{datetime.fromtimestamp(item['mtime']):%Y-%m-%d %H:%M}   {item['instance']}"
             for item in self.items],
            keep_index=True)

    def _say(self, text, level="info", ttl=6.0):
        self.notice = text
        self.notice_until = time.time() + ttl
        self.ctx.notify(text, level, ttl)

    def current(self):
        if not self.items:
            return None
        index = min(self.list.index, len(self.items) - 1)
        return self.items[index]

    def render(self, win):
        height, width = self.size(win)
        instance = self.ctx.instance_id
        source = getattr(self, "source", instances.path_of(instance))
        projected = getattr(self, "projected", 0)
        free = paths.free_bytes()
        scope = "all instances" if self.show_all else instance
        self.header(win, "backups",
                    f"scope: {scope}   source {paths.relative(source)} "
                    f"({procs.format_bytes(projected)})   free {procs.format_bytes(free)}")
        list_top = 3
        list_h = max(6, height - list_top - 5)
        title = "backups (newest first)"
        if not self.items:
            self.frame(win, list_top, 1, list_h, width - 2, title)
            th.safe_addstr(win, list_top + 1, 3, "(none yet - press b to create)",
                           self.theme.dim)
        else:
            self.list.render(win, list_top, 1, list_h, width - 2, self.theme, title)

        detail = ""
        item = self.current()
        if item:
            detail = (f"{item['name']}  {procs.format_bytes(item['size'])}  "
                      f"{datetime.fromtimestamp(item['mtime']):%Y-%m-%d %H:%M:%S}  "
                      f"owner {item['instance']}")
        th.safe_addstr(win, 2, 1, th.trunc(detail, width - 2), self.theme.dim)
        if time.time() < self.notice_until:
            th.safe_addstr(win, height - 2, 2, th.trunc(self.notice, width - 4),
                           self.theme.accent)
        self.footer(win, [
            ("b", "create"), ("x", "delete"), ("r", "restore"), ("u", "purge old"),
            ("a", "scope"), ("L", "reload"), ("?", "help"), ("q", "back"),
        ])
        if self.confirm is not None:
            self.confirm.render(win, self.theme)

    # --- actions -----------------------------------------------------
    def handle_key(self, key):
        if self.confirm is not None:
            result = self.confirm.handle_key(key)
            action, self.pending = self.pending, None
            self.confirm = None
            if result == "yes" and action:
                getattr(self, action)()
            return None
        if key in (ord("q"), 27):
            return "back"
        if key in (ord("b"), ord("B")):
            self._ask_create()
        elif key in (ord("x"), ord("X")):
            item = self.current()
            if item:
                self.confirm = self.confirm_dialog(
                    f"Delete {item['name']} ({procs.format_bytes(item['size'])})? "
                    "This cannot be undone.",
                    title="delete backup", dangerous=True, yes_label="delete")
                self.pending = "_do_delete"
        elif key in (ord("r"), ord("R")):
            item = self.current()
            if item:
                server = procs.server_status(self.ctx.instance_id)
                warn = (" The server is RUNNING - stop it first." if server.get("state") == "running"
                        else "")
                self.confirm = self.confirm_dialog(
                    f"Restore {item['name']} onto {self.ctx.instance_id}? "
                    f"Current data is copied to a .pre-restore-* file first.{warn}",
                    title="restore backup", dangerous=True, yes_label="restore")
                self.pending = "_do_restore"
        elif key in (ord("u"), ord("U")):
            self.confirm = self.confirm_dialog(
                "Delete older backups, keeping only the newest per instance?",
                title="purge old backups", dangerous=True, yes_label="purge")
            self.pending = "_do_purge"
        elif key in (ord("a"), ord("A")):
            self.show_all = not self.show_all
            self.refresh()
            self._say(f"scope: {'all instances' if self.show_all else self.ctx.instance_id}",
                      "ok", 3.0)
        elif key in (ord("L"), ord("l")):
            self.refresh()
        return None

    def _ask_create(self):
        instance = self.ctx.instance_id
        source = instances.path_of(instance)
        projected = backup.estimate(source)
        free = paths.free_bytes()
        space = backup.check_space(projected, paths.backups_dir())
        if projected > free // 2:
            self.confirm = self.confirm_dialog(
                f"Estimated archive {procs.format_bytes(projected)} is more than half of the "
                f"{procs.format_bytes(free)} free. Continue anyway?",
                title="tight on space", dangerous=True, yes_label="create")
            self.pending = "_do_create"
            return
        if not space["ok"]:
            self._say(space["message"], "err", 8.0)
            return
        self._do_create()

    def _do_create(self):
        instance = self.ctx.instance_id
        source = instances.path_of(instance)

        def job_fn(job):
            return backup.create(job, instance, source)

        def on_done(job):
            result = job.result or {}
            if result.get("ok"):
                self._say(f"created {result['name']} "
                          f"({procs.format_bytes(result['size'])})", "ok")
            else:
                self._say(str(result.get("error", "backup failed")), "err", 8.0)
            self.refresh()

        self.ctx.run_job("backup", job_fn, on_done=on_done)

    def _do_delete(self):
        item = self.current()
        if not item:
            return
        outcome = backup.delete(item["path"])
        self._say(str(outcome.get("message") or outcome.get("error") or "deleted"),
                  "ok" if outcome.get("ok") else "err")
        self.refresh()

    def _do_restore(self):
        item = self.current()
        if not item:
            return
        instance = self.ctx.instance_id
        target = instances.path_of(instance)
        server = procs.server_status(instance)
        if server.get("state") == "running":
            self._say("server is running - stop it before restoring", "err", 8.0)
            return

        def job_fn(job):
            job.update(0.05, "restoring")
            return backup.restore(job, item["path"], target)

        def on_done(job):
            result = job.result or {}
            if result.get("ok"):
                self._say(str(result.get("message", "restored")), "ok", 8.0)
            else:
                self._say(str(result.get("error", "restore failed")), "err", 10.0)

        self.ctx.run_job("restore", job_fn, on_done=on_done)

    def _do_purge(self):
        target = instances.path_of(self.ctx.instance_id)
        removed = backup.purge_previous(target, keep=1)
        self._say(f"purged {removed} older backups", "ok")
        self.refresh()
