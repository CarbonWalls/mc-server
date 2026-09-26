import curses
import time

from ..core import logs as logs_core
from ..core import paths, procs
from ..ui import theme as th
from ..ui import widgets as w
from ._base import Screen


class logs(Screen):
    def enter(self):
        self.files = []
        self.file_index = 0
        self.tail = None
        self.scroll = w.ScrollView(maxlen=2000)
        self.focus = "log"
        self.filter = ""
        self.filter_edit = None
        self.confirm = None
        self.files_at = 0.0
        self.notice = ""
        self.notice_until = 0.0
        self._refresh_files(first=True)

    def _refresh_files(self, first: bool = False):
        instance = self.ctx.instance_id
        files = logs_core.log_files(instance)
        if not files:
            files = [paths.log_paths(instance)["server_log"]]
        self.files = files
        if first:
            self.file_index = 0
        else:
            self.file_index = min(self.file_index, max(0, len(self.files) - 1))
        self._load()

    def _load(self):
        if not self.files:
            self.tail = None
            return
        path = self.files[self.file_index]
        self.tail = logs_core.LiveTail(path, maxlen=2000)
        self.tail.load(keep=400)
        self.scroll.follow = True
        self.scroll.scroll = 0

    def _say(self, text, level="info", ttl=5.0):
        self.notice = text
        self.notice_until = time.time() + ttl
        self.ctx.notify(text, level, ttl)

    def tick(self):
        if self.tail is not None:
            self.tail.refresh()
        self.files_at += 1
        if self.files_at < 50:
            return
        self.files_at = 0
        current = str(self.files[self.file_index]) if self.files else ""
        files = logs_core.log_files(self.ctx.instance_id)
        if not files or [str(f) for f in files] == [str(f) for f in self.files]:
            return
        self.files = files
        for i, path in enumerate(self.files):
            if str(path) == current:
                self.file_index = i
                break
        else:
            self.file_index = min(self.file_index, len(self.files) - 1)
        self._load()

    def _visible_lines(self) -> list:
        if self.tail is None:
            return ["(no log file yet - start the server)"]
        lines = self.tail.apply_filter(self.filter)
        if self.tail.missing:
            lines = [f"(file missing: {self.tail.path})"] + lines
        return lines or ["(no lines match the filter)"]

    def render(self, win):
        height, width = self.size(win)
        self.header(win, "logs",
                    f"instance: {self.ctx.instance_id}   filter: {self.filter or '-'}")
        side_w = min(30, max(18, width // 3))
        list_h = max(5, height - 6)
        items = []
        for path in self.files:
            size = procs.format_bytes(path.stat().st_size) if path.exists() else "missing"
            items.append(f"{path.name}  {size}")
        side_title = "log files" if self.focus == "files" else "log files (tab)"
        side = w.ListView(items, selectable=False)
        side.index = self.file_index
        side.offset = max(0, self.file_index - (list_h - 3))
        side.render(win, 3, 1, list_h, side_w, self.theme, side_title)

        pane_x = side_w + 2
        pane_w = width - pane_x - 1
        scroll_h = max(4, height - 6)
        if self.filter_edit is not None:
            scroll_h = max(3, scroll_h - 2)
        mode = "[follow]" if self.scroll.follow else f"[paused -{self.scroll.scroll}]"
        self.scroll.render(win, 3, pane_x, scroll_h, pane_w, self.theme,
                           f"output {mode}", lines=self._visible_lines(),
                           highlight=self.filter)
        if self.filter_edit is not None:
            self.filter_edit.render(win, 3 + scroll_h, pane_x, pane_w, self.theme)
        elif time.time() < self.notice_until:
            th.safe_addstr(win, height - 2, 2, th.trunc(self.notice, width - 4),
                           self.theme.accent)

        self.footer(win, [
            ("tab", "pane"), ("↑↓", "scroll"), ("t", "follow"), ("/", "filter"),
            ("s", "snapshot"), ("c", "clear"), ("r", "reload"), ("?", "help"),
            ("q", "back"),
        ])
        if self.confirm is not None:
            self.confirm.render(win, self.theme)

    def handle_key(self, key):
        if self.confirm is not None:
            result = self.confirm.handle_key(key)
            if result == "yes":
                path = self.tail.path if self.tail else None
                self.confirm = None
                if path is not None:
                    saved = logs_core.snapshot(path)
                    outcome = logs_core.clear(path)
                    detail = saved.get("path") if saved.get("ok") else str(saved)
                    self._say(f"{outcome.get('message') or outcome} (snapshot {detail})",
                              "ok" if outcome.get("ok") else "err")
                    self._load()
            elif result == "no":
                self.confirm = None
            return None

        if self.filter_edit is not None:
            action = self.filter_edit.handle_key(key)
            if action == "submit":
                self.filter = self.filter_edit.value.strip()
                self.filter_edit = None
                self.scroll.scroll = 0
                self.scroll.follow = True
                self._say(f"filter: {self.filter or 'cleared'}", "ok", 3.0)
            elif key == 27:
                self.filter_edit = None
            return None

        if key == 9:
            self.focus = "files" if self.focus == "log" else "log"
            return None
        if key == curses.KEY_LEFT and self.focus == "log":
            self.focus = "files"
            return None
        if key == curses.KEY_RIGHT and self.focus == "files":
            self.focus = "log"
            return None

        if self.focus == "files":
            if key in (10, 13, curses.KEY_ENTER) and self.files:
                self.file_index = min(max(0, self.file_index), len(self.files) - 1)
                self._load()
                self._say(f"opened {self.files[self.file_index].name}", "ok", 3.0)
                self.focus = "log"
                return None
            if key in (curses.KEY_UP, ord("k")):
                self.file_index = max(0, self.file_index - 1)
                return None
            if key in (curses.KEY_DOWN, ord("j")):
                self.file_index = min(len(self.files) - 1, self.file_index + 1)
                return None
            if key in (ord("q"), 27):
                self.focus = "log"
                return None
            return None

        if key == ord("/"):
            self.filter_edit = w.TextEdit(self.filter, label="filter")
            return None
        if key in (ord("q"), 27):
            if self.filter:
                self.filter = ""
                self._say("filter cleared", "ok", 2.0)
                return None
            return "back"
        if key == ord("t"):
            self.scroll.handle_key(ord("t"))
            return None
        if key == ord("c"):
            if self.tail is not None:
                self.confirm = self.confirm_dialog(
                    f"Clear {self.tail.path.name}? A snapshot is saved first.",
                    title="clear log", dangerous=True, yes_label="clear")
            return None
        if key == ord("s"):
            if self.tail is not None:
                outcome = logs_core.snapshot(self.tail.path)
                self._say(str(outcome.get("message") or outcome),
                          "ok" if outcome.get("ok") else "err")
            return None
        if key == ord("r"):
            if self.tail is not None:
                self.tail.load(keep=400)
                self._say("reloaded", "ok", 2.0)
            return None
        page = max(4, self.size(self.ctx.stdscr)[0] - 8)
        self.scroll.handle_key(key, page=page)
        return None
