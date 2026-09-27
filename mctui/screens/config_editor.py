import curses
import time
from pathlib import Path

from ..core import config, console as console_core, instances, paths, procs
from ..ui import theme as th
from ..ui import widgets as w
from ._base import Screen

TARGETS = [
    ("server.properties", "properties"),
    ("plugins/Geyser-Spigot/config.yml", "yaml"),
    ("eula.txt", "text"),
]


class config_editor(Screen):
    def enter(self):
        self.target_index = 0
        self.path = None
        self.kind = "properties"
        self.rows = []
        self.list = w.ListView([])
        self.edit = None
        self.mode = None  # None | "key" | "value"
        self.pending_key = ""
        self.notice = ""
        self.notice_until = 0.0
        self._load()

    def _load(self):
        name, kind = TARGETS[self.target_index]
        instance_dir = instances.path_of(self.ctx.instance_id)
        self.path = instance_dir / name
        self.kind = kind
        rows = []
        if not self.path.exists():
            rows = []
        elif kind == "properties":
            rows = sorted(config.read_properties(self.path).items())
        elif kind == "yaml":
            try:
                text = config.read_text(self.path)
            except OSError:
                text = ""
            for _idx, _raw, keys, rest in config._yaml_blocks(text.splitlines()):
                if not keys:
                    continue
                value = rest.split("#", 1)[0].strip() if "#" in rest else rest.strip()
                rows.append((".".join(keys), value.strip().strip("'\"")))
        else:
            rows = [(f"line {i}", line) for i, line in
                    enumerate(config.read_text(self.path).splitlines(), 1)] \
                if self.path.exists() else []
        self.rows = rows
        index = min(self.list.index, max(0, len(rows) - 1))
        self.list.set_items([f"{key:<34}{value}" for key, value in rows], keep_index=False)
        self.list.index = index

    def _say(self, text, level="info", ttl=5.0):
        self.notice = text
        self.notice_until = time.time() + ttl
        self.ctx.notify(text, level, ttl)

    def render(self, win):
        height, width = self.size(win)
        self.header(win, "config editor",
                    f"{self.ctx.instance_id}: {TARGETS[self.target_index][0]}  "
                    f"({len(self.rows)} keys, edited with .bak backup)")
        tabs = "  ".join(
            f"[{i + 1}] {name}" if i != self.target_index else f"[{i + 1}] <{name}>"
            for i, (name, _kind) in enumerate(TARGETS))
        th.safe_addstr(win, 2, 1, th.trunc(tabs, width - 2),
                       self.theme.warn if self.edit else self.theme.dim)

        list_top = 3
        if self.edit is not None:
            list_h = max(5, height - list_top - 8)
        else:
            list_h = max(5, height - list_top - 5)
        title = "key" if self.edit is None else "key (editing - ⏎ save)"
        if not self.rows:
            self.frame(win, list_top, 1, list_h, width - 2, title)
            th.safe_addstr(win, list_top + 1, 3, "(file missing or empty)", self.theme.dim)
        else:
            self.list.render(win, list_top, 1, list_h, width - 2, self.theme, title)

        if self.edit is not None:
            edit_y = list_top + list_h + 1
            self.edit.render(win, edit_y, 1, min(width - 2, 70), self.theme)
        elif time.time() < self.notice_until:
            th.safe_addstr(win, height - 2, 2, th.trunc(self.notice, width - 4),
                           self.theme.accent)

        self.footer(win, [
            ("1-3", "file"), ("↑↓", "move"), ("⏎", "edit value"), ("a", "add key"),
            ("r", "reload"), ("?", "help"), ("q", "back"),
        ])

    def handle_key(self, key):
        if self.edit is not None:
            action = self.edit.handle_key(key)
            if action == "submit":
                self._save_value(self.edit.value)
                self.edit = None
            elif key == 27:
                self.edit = None
                self.mode = None
                self.pending_key = ""
            return None

        if ord("1") <= key <= ord("3"):
            index = key - ord("1")
            if index < len(TARGETS):
                self.target_index = index
                self._load()
            return None
        if key in (ord("r"), ord("R")):
            self._load()
            self._say("reloaded", "ok", 2.0)
            return None
        if key in (ord("a"), ord("A")):
            if self.kind != "properties":
                self._say("adding keys only works for server.properties", "warn")
                return None
            if not self.path.exists():
                self._say("file does not exist yet", "warn")
                return None
            self.mode = "key"
            self.edit = w.TextEdit("", label="new key", validator=self._validate_key)
            return None
        if key in (ord("q"), 27):
            return "back"

        action = self.list.handle_key(key, height=max(4, self.size(self.ctx.stdscr)[0] - 8))
        if action == "select" and self.rows:
            key_name, value = self.rows[self.list.index]
            if self.kind == "text":
                self._say("text files are read-only here", "warn")
                return None
            self.mode = "value"
            restart = console_core.RESTART_KEYS.get(key_name)
            if restart:
                self.edit = w.TextEdit(value, label=f"{key_name} = "
                                                   f"[needs restart: {restart}]")
            else:
                self.edit = w.TextEdit(value, label=f"{key_name} =")
        return None

    def _validate_key(self, raw):
        value = raw.strip()
        if not value:
            return "key cannot be empty"
        if "=" in value or "\n" in value:
            return "key must not contain = or newline"
        return ""

    def _save_value(self, raw: str):
        value = raw.strip()
        if self.mode == "key":
            self.pending_key = value
            self.mode = "value"
            self.edit = w.TextEdit("", label=f"{value} =")
            return
        self.mode = None
        if self.kind == "properties":
            key_name = self.pending_key or self.rows[self.list.index][0]
            props = config.read_properties(self.path)
            props[key_name] = value
            result = config.write_properties(self.path, props)
            restart = console_core.RESTART_KEYS.get(key_name)
            message = f"saved {key_name}"
            if restart:
                message += f" - takes effect on the next start ({restart})"
                if procs.server_status(self.ctx.instance_id).get("state") == "running":
                    message += "; the running server is unchanged"
            self._say(message if result else "write failed",
                      "ok" if result else "err")
        elif self.kind == "yaml":
            key_name = self.rows[self.list.index][0]
            outcome = config.yaml_set_file(self.path, key_name.split("."), value)
            if outcome.get("changed"):
                self._say(f"saved {key_name} (backup {outcome.get('backup')})", "ok")
            else:
                self._say("no change or key not found", "warn")
        self.pending_key = ""
        self._load()
