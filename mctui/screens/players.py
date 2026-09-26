import curses
import json
import time

from ..core import config, instances, paths, players as players_core
from ..ui import theme as th
from ..ui import widgets as w
from ..ui.panels import Popup
from ._base import Screen

TABS = [
    ("online", "online"),
    ("whitelist", "whitelist"),
    ("ops", "ops"),
    ("bans", "bans"),
    ("ip-bans", "ip_bans"),
]


class players(Screen):
    def enter(self):
        self.tab = 0
        self.list = w.ListView([])
        self.edit = None
        self.confirm = None
        self.pending = None
        self.notice = ""
        self.notice_until = 0.0
        self.popup = None
        self.status = {}
        self.refresh()

    def refresh(self):
        self.status = players_core.status(self.ctx.instance_id)
        kind = TABS[self.tab][1]
        if kind == "online":
            entries = self.status.get("online", [])
            lines = entries or ["(nobody online)"]
            self.entries = entries
        else:
            entries = self.status.get(kind, [])
            self.entries = entries
            lines = players_core.entry_lines(entries, kind) or ["(empty)"]
        self.list.set_items(lines, keep_index=True)

    def _say(self, text, level="info", ttl=6.0):
        self.notice = text
        self.notice_until = time.time() + ttl
        self.ctx.notify(text, level, ttl)

    def current_name(self) -> str:
        if not self.entries:
            return ""
        index = min(self.list.index, len(self.entries) - 1)
        entry = self.entries[index]
        if isinstance(entry, dict):
            return str(entry.get("name") or entry.get("ip") or "")
        return str(entry)

    def render(self, win):
        height, width = self.size(win)
        instance = self.ctx.instance_id
        self.header(win, "players", f"instance: {instance}")
        tabs = "  ".join(
            f"[{i + 1}] {label}" if i != self.tab else f"[{i + 1}] <{label}>"
            for i, (label, _kind) in enumerate(TABS))
        th.safe_addstr(win, 2, 1, th.trunc(tabs, width - 2), self.theme.warn)
        flags = []
        flags.append("whitelist ON" if self.status.get("whitelist_enabled") else "whitelist off")
        flags.append("online-mode ON" if self.status.get("online_mode") else "online-mode off")
        flags.append(f"max {self.status.get('max_players', '?')}")
        flags.append(f"online {len(self.status.get('online', []))}")
        th.safe_addstr(win, 3, 1, th.trunc("   ".join(flags), width - 2), self.theme.dim)

        list_top = 4
        list_h = max(5, height - list_top - 5)
        if self.entries == [] and self.tab > 0:
            self.frame(win, list_top, 1, list_h, width - 2, TABS[self.tab][0])
            th.safe_addstr(win, list_top + 1, 3, "(empty)", self.theme.dim)
        else:
            self.list.render(win, list_top, 1, list_h, width - 2, self.theme,
                             TABS[self.tab][0])
        if self.edit is not None:
            self.edit.render(win, list_top + list_h + 1, 1, min(width - 2, 56), self.theme)
        elif time.time() < self.notice_until:
            th.safe_addstr(win, height - 2, 2, th.trunc(self.notice, width - 4),
                           self.theme.accent)

        self.footer(win, [
            ("1-5", "tab"), ("a", "add"), ("d", "remove"), ("⏎", "detail"),
            ("w", "toggle wl"), ("o", "op"), ("b", "ban"), ("r", "reload"),
            ("?", "help"), ("q", "back"),
        ])
        if self.confirm is not None:
            self.confirm.render(win, self.theme)
        elif self.popup is not None:
            self.popup.render(win, self.theme)

    # --- keys --------------------------------------------------------
    def handle_key(self, key):
        if self.popup is not None:
            if self.popup.handle_key(key) == "close":
                self.popup = None
            return None
        if self.confirm is not None:
            result = self.confirm.handle_key(key)
            action, self.pending = self.pending, None
            self.confirm = None
            if result == "yes" and action:
                getattr(self, action)()
            return None

        if self.edit is not None:
            action = self.edit.handle_key(key)
            if action == "submit":
                name = self.edit.value.strip()
                kind = TABS[self.tab][1]
                self.edit = None
                self._add(kind, name)
            elif key == 27:
                self.edit = None
            return None

        if ord("1") <= key <= ord("5"):
            index = key - ord("1")
            if index < len(TABS):
                self.tab = index
                self.refresh()
            return None
        if key in (9,):
            self.tab = (self.tab + 1) % len(TABS)
            self.refresh()
            return None

        kind = TABS[self.tab][1]
        if key in (ord("q"), 27):
            if self.tab != 0:
                self.tab = 0
                self.refresh()
                return None
            return "back"
        if key in (ord("r"), ord("R")):
            self.refresh()
            return None
        if key in (ord("a"), ord("A")):
            self.edit = w.TextEdit("", label="player name",
                                   validator=self._validate_name)
            return None
        if key in (ord("d"), ord("D")):
            name = self.current_name()
            if not name:
                return None
            if kind == "online":
                self._say("online players cannot be removed here", "warn")
                return None
            self.confirm = self.confirm_dialog(
                f"Remove {name} from {TABS[self.tab][0]}?",
                title="remove entry", dangerous=True, yes_label="remove")
            self.pending = "_do_remove"
            return None
        if key in (10, 13, curses.KEY_ENTER):
            name = self.current_name()
            if name:
                self._detail(name, kind)
            return None
        if key in (ord("w"), ord("W")):
            self._toggle_whitelist()
            return None
        if key in (ord("o"), ord("O")):
            name = self.current_name()
            if name and kind in ("online", "whitelist", "ops"):
                self._add("ops", name, level=4)
            return None
        if key in (ord("b"), ord("B")):
            name = self.current_name()
            if name and kind in ("online", "whitelist", "ops"):
                self.confirm = self.confirm_dialog(
                    f"Ban {name}? They are kicked and cannot rejoin until unbanned.",
                    title="ban player", dangerous=True, yes_label="ban")
                self.pending = "_do_ban"
            return None
        action = self.list.handle_key(key, height=max(4, self.size(self.ctx.stdscr)[0] - 8))
        return None

    def _validate_name(self, raw):
        value = raw.strip()
        if not value:
            return "enter a name"
        if len(value) > 16:
            return "max 16 characters"
        if not all(c.isalnum() or c == "_" for c in value):
            return "letters, digits and _ only"
        return ""

    def _add(self, kind, name, level=4):
        if not name:
            return
        outcome = players_core.add_entry(self.ctx.instance_id, kind, name, level=level)
        self.refresh()
        if outcome.get("ok"):
            self._say(f"added {name} to {kind}", "ok")
        else:
            self._say(str(outcome.get("error", "failed")), "err")

    def _do_remove(self):
        kind = TABS[self.tab][1]
        name = self.current_name()
        if not name:
            return
        outcome = players_core.remove_entry(self.ctx.instance_id, kind, name)
        self.refresh()
        if outcome.get("ok"):
            self._say(f"removed {name}", "ok")
        else:
            self._say(str(outcome.get("error", "failed")), "err")

    def _do_ban(self):
        name = self.current_name()
        if not name:
            return
        self._add("bans", name)

    def _toggle_whitelist(self):
        instance = self.ctx.instance_id
        path = paths.instance_path(instance) / "server.properties"
        if not path.exists():
            self._say("server.properties missing", "err")
            return
        props = config.read_properties(path)
        enabled = str(props.get("white-list", "false")).lower() == "true"
        props["white-list"] = "false" if enabled else "true"
        config.write_properties(path, props)
        self.refresh()
        self._say(f"whitelist {'enabled' if not enabled else 'disabled'}", "ok")

    def _detail(self, name, kind):
        lines = [f"name   {name}", f"list   {TABS[self.tab][0]}"]
        entries = self.status.get(kind, []) if kind != "online" else []
        for entry in entries:
            if isinstance(entry, dict) and str(entry.get("name", "")) == name:
                lines.append("")
                lines.append(json.dumps(entry, indent=2))
                break
        uuid = players_core.offline_uuid(name)
        lines.append("")
        lines.append(f"offline uuid  {uuid}")
        lines.append(f"file          {paths.relative(players_core.list_path(self.ctx.instance_id, kind if kind != 'online' else 'whitelist'))}")
        self.popup = Popup(name, lines, width=72)
        self.popup.scroll = 0
