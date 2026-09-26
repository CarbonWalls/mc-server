import curses
import re
import time

from ..core import config, instances, paths, procs
from ..ui import theme as th
from ..ui import widgets as w
from ._base import Screen

FIELDS = [
    ("xms", "initial java heap, e.g. 512M", "memory"),
    ("xmx", "maximum java heap, e.g. 768M", "memory"),
    ("server_port", "java edition port (default 25565)", "port"),
    ("bedrock_port", "bedrock/Geyser port (default 44041)", "port"),
    ("tunnel", "bore | playit | none", "choice"),
    ("active_instance", "instance start.sh launches", "instance"),
    ("java", "java override path, blank = bundled JDK", "text"),
]

MEMORY_RE = re.compile(r"^\d{1,5}[MmGg]$")


class settings(Screen):
    def enter(self):
        self.ctx.reload_settings()
        self.list = w.ListView([f"{key:<18}{value}" for (key, _hint, _kind), value in
                                self._rows()])
        self.edit = None
        self.choice = None
        self.choice_index = 0
        self.notice = ""
        self.notice_until = 0.0

    def _rows(self):
        out = []
        for key, hint, kind in FIELDS:
            value = self.ctx.settings.get(key, "")
            out.append(((key, hint, kind), str(value)))
        return out

    def _value(self, key):
        return str(self.ctx.settings.get(key, ""))

    def _say(self, text, level="info", ttl=5.0):
        self.notice = text
        self.notice_until = time.time() + ttl
        self.ctx.notify(text, level, ttl)

    def _validate(self, kind, key, raw):
        value = raw.strip()
        if kind == "memory":
            if not MEMORY_RE.match(value):
                return "use digits + M or G, e.g. 512M or 2G"
            mb = int(value[:-1]) * (1024 if value[-1].upper() == "G" else 1)
            if mb < 128:
                return "minimum 128M"
        elif kind == "port":
            if not value.isdigit() or not (1 <= int(value) <= 65535):
                return "port must be 1-65535"
        elif kind == "choice":
            if value not in ("bore", "playit", "none"):
                return "choose bore, playit or none"
        elif kind == "instance":
            if not instances.get_instance(value):
                return f"unknown instance '{value}'"
        elif kind == "text" and value:
            from pathlib import Path
            if not Path(value).exists():
                return f"no such path: {value}"
        return ""

    def _save(self, key, value):
        data = dict(self.ctx.settings)
        data[key] = int(value) if key in ("server_port", "bedrock_port") and str(value).isdigit() else value
        config.write_json(paths.settings_path(), data, with_backup=True)
        self.ctx.reload_settings()
        return data

    def render(self, win):
        height, width = self.size(win)
        self.header(win, "settings", "data/tui_settings.json  (saved with .bak backup)")
        rows = self._rows()
        self.list.set_items([f"{key[0]:<18}{value}" for key, value in rows])
        left_w = min(52, max(34, width // 2))
        list_h = len(rows) + 2
        self.list.render(win, 3, 1, list_h, left_w, self.theme,
                         "setting" if self.edit is None else "setting (editing)")
        right_x = left_w + 3
        right_w = width - right_x - 1
        key, hint, kind = rows[self.list.index][0]
        info = [
            f"key      {key}",
            f"help     {hint}",
            f"current  {self._value(key)}",
            f"kind     {kind}",
            "",
            "enter to edit, q to go back",
        ]
        box_h = list_h
        self.frame(win, 3, right_x, box_h, right_w, "detail")
        for i, line in enumerate(info[: box_h - 2]):
            th.safe_addstr(win, 4 + i, right_x + 2, th.trunc(line, right_w - 4),
                           self.theme.plain if i != 1 else self.theme.dim)

        if self.edit is not None:
            edit_y = 3 + list_h + 1
            self.edit.label = f"edit {key}"
            self.edit.render(win, edit_y, 1, min(width - 2, 60), self.theme)
        elif self.choice is not None:
            choice_y = 3 + list_h + 1
            label = "  ".join(
                f"[{i + 1}] {c}" if i != self.choice_index else f"[{i + 1}] <{c}>"
                for i, c in enumerate(self.choice))
            th.safe_addstr(win, choice_y, 1, th.trunc(label, width - 2), self.theme.warn)
        elif time.time() < self.notice_until:
            th.safe_addstr(win, height - 2, 2, th.trunc(self.notice, width - 4),
                           self.theme.accent)

        self.footer(win, [
            ("↑↓", "move"), ("⏎", "edit"), ("1-3", "pick choice"),
            ("d", "reset field"), ("?", "help"), ("q", "back"),
        ])

    def handle_key(self, key):
        if self.edit is not None:
            action = self.edit.handle_key(key)
            if action == "submit":
                field_key, hint, kind = FIELDS[self.list.index]
                error = self._validate(kind, field_key, self.edit.value)
                if error:
                    self.edit.error = error
                    return None
                self._save(field_key, self.edit.value.strip())
                self._say(f"saved {field_key} = {self.edit.value.strip()}", "ok")
                self.edit = None
            elif key == 27:
                self.edit = None
            return None

        if self.choice is not None:
            if key in (27, ord("q")):
                self.choice = None
                return None
            if ord("1") <= key <= ord("9"):
                index = key - ord("1")
                if index < len(self.choice):
                    field_key = FIELDS[self.list.index][0]
                    self._save(field_key, self.choice[index])
                    self._say(f"saved {field_key} = {self.choice[index]}", "ok")
                    self.choice = None
                return None
            if key in (curses.KEY_LEFT, ord("h")):
                self.choice_index = (self.choice_index - 1) % len(self.choice)
            elif key in (curses.KEY_RIGHT, ord("l")):
                self.choice_index = (self.choice_index + 1) % len(self.choice)
            elif key in (10, 13, curses.KEY_ENTER):
                field_key = FIELDS[self.list.index][0]
                self._save(field_key, self.choice[self.choice_index])
                self.choice = None
            return None

        action = self.list.handle_key(key, height=len(FIELDS) + 2)
        if action == "select":
            self._begin_edit()
            return None
        if key in (ord("d"), ord("D")):
            field_key, _hint, _kind = FIELDS[self.list.index]
            default = paths.DEFAULT_SETTINGS.get(field_key, "")
            self._save(field_key, default)
            self._say(f"{field_key} reset to {default!r}", "ok")
            return None
        return super().handle_key(key)

    def _begin_edit(self):
        field_key, _hint, kind = FIELDS[self.list.index]
        current = self._value(field_key)
        if kind == "choice":
            self.choice = ["bore", "playit", "none"]
            self.choice_index = max(0, self.choice.index(current)) if current in self.choice else 0
            return
        if kind == "instance":
            self.choice = [entry["id"] for entry in instances.load_index().get("instances", [])]
            if not self.choice:
                self._say("no instances", "warn")
                return
            self.choice_index = max(0, self.choice.index(current)) if current in self.choice else 0
            return
        self.edit = w.TextEdit(current, label=field_key,
                               validator=lambda raw: self._validate(kind, field_key, raw))
