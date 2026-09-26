"""Small drawing helpers that sit on top of widgets: bars, popups, kv rows."""
import curses
import textwrap

from . import theme as th
from .widgets import (is_back, is_down, is_enter, is_pgdn, is_pgup, is_up)


class ProgressBar:
    def __init__(self):
        self.frac = 0.0
        self.label = ""
        self.active = False

    def update(self, frac=None, label=None, active: bool = True):
        if frac is not None:
            self.frac = max(0.0, min(1.0, float(frac)))
        if label is not None:
            self.label = str(label)
        self.active = active

    def render(self, win, y: int, x: int, width: int, theme, spinner: str = "") -> None:
        if width < 12:
            return
        bar_w = max(6, width - 14)
        filled = int(bar_w * self.frac)
        bar = "█" * filled + "░" * (bar_w - filled)
        pct = f"{int(self.frac * 100):3d}%"
        th.safe_addstr(win, y, x, f"{bar} {pct}", theme.accent if self.active else theme.dim)
        if self.label:
            th.safe_addstr(win, y + 1, x, th.trunc(f"{spinner} {self.label}", width), theme.plain)


class Popup:
    def __init__(self, title: str, lines, width: int = 70):
        self.title = title
        self.lines = list(lines)
        self.width = width

    def handle_key(self, key):
        wrapped = getattr(self, "_wrapped", [])
        if is_up(key):
            self.scroll = max(0, getattr(self, "scroll", 0) - 1)
            return None
        if is_down(key):
            limit = max(0, len(wrapped) - 1)
            self.scroll = min(limit, getattr(self, "scroll", 0) + 1)
            return None
        if is_pgup(key):
            self.scroll = max(0, getattr(self, "scroll", 0) - 10)
            return None
        if is_pgdn(key):
            limit = max(0, len(wrapped) - 1)
            self.scroll = min(limit, getattr(self, "scroll", 0) + 10)
            return None
        if is_back(key) or is_enter(key) or key == ord("?"):
            return "close"
        return None

    def render(self, win, theme) -> None:
        height, width = win.getmaxyx()
        wrapped = []
        for line in self.lines:
            wrapped.extend(textwrap.wrap(str(line), max(20, self.width - 6)) or [""])
        self._wrapped = wrapped
        box_h = min(height - 2, len(wrapped) + 4)
        box_w = min(width - 4, self.width)
        if box_h < 4 or box_w < 24:
            return
        y = max(1, (height - box_h) // 2)
        x = max(1, (width - box_w) // 2)
        theme.frame(win, y, x, box_h, box_w, self.title)
        page = max(1, box_h - 3)
        scroll = max(0, min(getattr(self, "scroll", 0), max(0, len(wrapped) - page)))
        self.scroll = scroll
        for i, line in enumerate(wrapped[scroll:scroll + page]):
            th.safe_addstr(win, y + 1 + i, x + 2, th.trunc(line, box_w - 4), theme.plain)
        if len(wrapped) > page:
            th.safe_addstr(win, y + box_h - 2, x + 2,
                           f"{scroll + 1}-{min(len(wrapped), scroll + page)} of {len(wrapped)}",
                           theme.dim)
        try:
            win.refresh()
        except curses.error:
            pass


def draw_kv(win, y: int, x: int, pairs, theme, key_width: int = 18, max_width: int = 60) -> int:
    row = y
    for key, value in pairs:
        th.safe_addstr(win, row, x, th.trunc(str(key), key_width), theme.dim)
        th.safe_addstr(win, row, x + key_width + 2, th.trunc(str(value), max_width), theme.plain)
        row += 1
    return row - y


def draw_wrapped(win, y: int, x: int, width: int, text, theme, attr=None, max_lines: int = 0) -> int:
    attr = theme.plain if attr is None else attr
    row = y
    for paragraph in str(text).splitlines() or [""]:
        wrapped = textwrap.wrap(paragraph, max(10, width)) or [""]
        for line in wrapped:
            if max_lines and row - y >= max_lines:
                return row - y
            th.safe_addstr(win, row, x, line, attr)
            row += 1
    return row - y

SPINNER = "|/-\\"


def spinner_char(tick: int) -> str:
    return SPINNER[tick % len(SPINNER)]
