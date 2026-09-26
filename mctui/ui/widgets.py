import curses
import textwrap
from collections import deque

from . import theme as th


def is_up(key) -> bool:
    return key in (curses.KEY_UP, ord("k"))


def is_down(key) -> bool:
    return key in (curses.KEY_DOWN, ord("j"))


def is_pgup(key) -> bool:
    return key in (curses.KEY_PPAGE, ord("K"))


def is_pgdn(key) -> bool:
    return key in (curses.KEY_NPAGE, ord("J"))


def is_left(key) -> bool:
    return key in (curses.KEY_LEFT, ord("h"))


def is_right(key) -> bool:
    return key in (curses.KEY_RIGHT, ord("l"))


def is_enter(key) -> bool:
    return key in (curses.KEY_ENTER, 10, 13)


def is_back(key) -> bool:
    return key in (27, ord("q"), curses.KEY_BACKSPACE, 127)


def is_home(key) -> bool:
    return key in (curses.KEY_HOME, ord("g"))


def is_end(key) -> bool:
    return key in (curses.KEY_END, ord("G"))


class ListView:
    def __init__(self, items=None, selectable: bool = True):
        self.items = list(items or [])
        self.index = 0
        self.offset = 0
        self.selectable = selectable

    def set_items(self, items, keep_index: bool = True):
        old = self.index
        self.items = list(items)
        if not keep_index:
            self.index = 0
        self.index = max(0, min(self.index if keep_index else 0, len(self.items) - 1))
        if old > len(self.items) - 1:
            self.index = max(0, len(self.items) - 1)
        self.offset = min(self.offset, self.index)

    def current(self):
        if not self.items:
            return None
        return self.items[self.index]

    def handle_key(self, key, height: int = 10) -> str | None:
        if not self.items:
            return None
        if is_up(key):
            self.index = max(0, self.index - 1)
            return "up"
        if is_down(key):
            self.index = min(len(self.items) - 1, self.index + 1)
            return "down"
        if is_pgup(key):
            self.index = max(0, self.index - max(1, height - 1))
            return "up"
        if is_pgdn(key):
            self.index = min(len(self.items) - 1, self.index + max(1, height - 1))
            return "down"
        if is_home(key):
            self.index = 0
            return "up"
        if is_end(key):
            self.index = len(self.items) - 1
            return "down"
        if isinstance(key, int) and ord("1") <= key <= ord("9"):
            candidate = key - ord("1")
            if candidate < len(self.items):
                self.index = candidate
                return "down"
        if is_enter(key) and self.selectable:
            return "select"
        return None

    def render(self, win, y: int, x: int, height: int, width: int, theme, title: str = ""):
        if height < 3 or width < 6:
            return 0
        theme.frame(win, y, x, height, width, title)
        inner_h = height - 2
        inner_w = width - 2
        if self.index < self.offset:
            self.offset = self.index
        if self.index >= self.offset + inner_h:
            self.offset = self.index - inner_h + 1
        self.offset = max(0, min(self.offset, max(0, len(self.items) - inner_h)))
        visible = self.items[self.offset:self.offset + inner_h]
        for i, item in enumerate(visible):
            absolute = self.offset + i
            label = item if isinstance(item, str) else str(item)
            selected = absolute == self.index and self.selectable
            attr = theme.sel if selected else theme.plain
            try:
                win.attron(attr)
                th.safe_addstr(win, y + 1 + i, x + 1, " " * (inner_w - 1))
                th.safe_addstr(win, y + 1 + i, x + 1,
                               th.trunc(("▸ " if selected else "  ") + label, inner_w - 1), attr)
                win.attroff(attr)
            except curses.error:
                pass
        if len(self.items) > inner_h:
            total = len(self.items)
            bar_len = max(1, int(inner_h * inner_h / total))
            pos = int((self.index / max(1, total - 1)) * (inner_h - bar_len))
            for i in range(inner_h):
                ch = "█" if pos <= i < pos + bar_len else "│"
                th.safe_addstr(win, y + 1 + i, x + width - 2, ch, theme.dim)
        return inner_h


class TextEdit:
    def __init__(self, value: str = "", label: str = "", validator=None, width: int = 40):
        self.value = str(value)
        self.cursor = len(self.value)
        self.label = label
        self.validator = validator
        self.width = width
        self.error = ""
        self.active = True

    def handle_key(self, key) -> str | None:
        self.error = ""
        if is_enter(key):
            if self.validator:
                message = self.validator(self.value)
                if message:
                    self.error = message
                    return None
            return "submit"
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.cursor > 0:
                self.value = self.value[: self.cursor - 1] + self.value[self.cursor:]
                self.cursor -= 1
            return "edit"
        if key == curses.KEY_DC:
            self.value = self.value[: self.cursor] + self.value[self.cursor + 1:]
            return "edit"
        if key == curses.KEY_LEFT:
            self.cursor = max(0, self.cursor - 1)
            return None
        if key == curses.KEY_RIGHT:
            self.cursor = min(len(self.value), self.cursor + 1)
            return None
        if key == curses.KEY_HOME:
            self.cursor = 0
            return None
        if key == 21:
            self.value = ""
            self.cursor = 0
            return "edit"
        if key == curses.KEY_END:
            self.cursor = len(self.value)
            return None
        if isinstance(key, int) and 32 <= key < 127:
            char = chr(key)
            if len(self.value) < 240:
                self.value = self.value[: self.cursor] + char + self.value[self.cursor:]
                self.cursor += 1
                return "edit"
        return None

    def render(self, win, y: int, x: int, width: int, theme, show_label: bool = True) -> int:
        row = y
        if show_label and self.label:
            th.safe_addstr(win, row, x, th.trunc(self.label, width), theme.accent)
            row += 1
        field = " " + self.value + " "
        field = th.trunc(field, width - 2)
        attr = theme.err if self.error else theme.border
        try:
            win.attron(attr)
            th.safe_addstr(win, row, x, field.ljust(width - 1), attr)
            win.attroff(attr)
        except curses.error:
            pass
        cursor_x = x + 1 + min(self.cursor, max(0, width - 4))
        try:
            win.move(row, cursor_x)
        except curses.error:
            pass
        row += 1
        if self.error:
            th.safe_addstr(win, row, x, th.trunc(self.error, width), theme.err)
            row += 1
        return row - y


class Confirm:
    def __init__(self, message: str, title: str = "confirm", dangerous: bool = True,
                 yes_label: str = "yes", no_label: str = "cancel"):
        self.message = message
        self.title = title
        self.dangerous = dangerous
        self.yes_label = yes_label
        self.no_label = no_label
        self.choice = 0

    def handle_key(self, key) -> str | None:
        if is_left(key) or is_right(key) or key == ord("\t"):
            self.choice = 1 - self.choice
            return None
        if key in (ord("y"), ord("Y")):
            return "yes"
        if key in (ord("n"), ord("N")):
            return "no"
        if is_enter(key):
            return "yes" if self.choice == 0 else "no"
        if is_back(key):
            return "no"
        return None

    def render(self, win, theme) -> None:
        height, width = win.getmaxyx()
        lines = []
        for chunk in self.message.splitlines() or [self.message]:
            lines.extend(textwrap.wrap(chunk, max(20, width - 10)) or [""])
        box_h = min(height - 2, len(lines) + 6)
        box_w = min(width - 4, max(44, max(len(l) for l in lines) + 6))
        if box_h < 6 or box_w < 30:
            return
        y = max(1, (height - box_h) // 2)
        x = max(1, (width - box_w) // 2)
        theme.frame(win, y, x, box_h, box_w, self.title)
        attr = theme.warn if self.dangerous else theme.accent
        th.safe_addstr(win, y + 1, x + 2, th.trunc("⚠ " if self.dangerous else "", box_w - 4), attr)
        for i, line in enumerate(lines[: box_h - 4]):
            th.safe_addstr(win, y + 2 + i, x + 2, th.trunc(line, box_w - 4), theme.plain)
        buttons = [(self.yes_label, 0), (self.no_label, 1)]
        bx = x + 4
        for label, idx in buttons:
            text = f"[ {label} ]"
            active = self.choice == idx
            attr = theme.err if (active and self.dangerous) else (theme.sel if active else theme.border)
            th.safe_addstr(win, y + box_h - 2, bx, text, attr)
            bx += len(text) + 3
        try:
            win.refresh()
        except curses.error:
            pass


class ScrollView:
    def __init__(self, maxlen: int = 2000):
        self.lines = deque(maxlen=maxlen)
        self.scroll = 0
        self.follow = True

    def set_lines(self, lines) -> None:
        self.lines = deque(list(lines)[-self.lines.maxlen:], maxlen=self.lines.maxlen)
        if self.follow:
            self.scroll = 0

    def append(self, line) -> None:
        self.lines.append(line)

    def total(self) -> int:
        return len(self.lines)

    def handle_key(self, key, page: int = 10) -> None:
        if is_up(key):
            self.scroll = min(len(self.lines) - 1, self.scroll + 1)
            self.follow = False
        elif is_down(key):
            self.scroll = max(0, self.scroll - 1)
            if self.scroll == 0:
                self.follow = True
        elif is_pgup(key):
            self.scroll = min(len(self.lines) - 1, self.scroll + page)
            self.follow = False
        elif is_pgdn(key):
            self.scroll = max(0, self.scroll - page)
            if self.scroll == 0:
                self.follow = True
        elif is_home(key):
            self.scroll = max(0, len(self.lines) - 1)
            self.follow = False
        elif is_end(key):
            self.scroll = 0
            self.follow = True
        elif key == ord("t"):
            self.follow = not self.follow
            if self.follow:
                self.scroll = 0

    def visible(self, height: int) -> list:
        if height <= 0:
            return []
        end = len(self.lines) - self.scroll
        start = max(0, end - height)
        return list(self.lines[start:end])

    def render(self, win, y: int, x: int, height: int, width: int, theme,
               title: str = "", lines=None, highlight: str = "") -> None:
        if height < 3 or width < 6:
            return
        theme.frame(win, y, x, height, width, title)
        inner_h = height - 2
        inner_w = width - 2
        data = lines if lines is not None else self.visible(inner_h)
        if lines is None:
            pass
        else:
            data = list(lines)
            end = len(data) - self.scroll
            start = max(0, end - inner_h)
            data = data[start:end]
        needle = highlight.lower()
        for i, line in enumerate(data[:inner_h]):
            text = th.trunc(line, inner_w - 1)
            attr = theme.plain
            if needle and needle in str(line).lower():
                attr = theme.warn
            if " ERROR" in str(line) or "SEVERE" in str(line):
                attr = theme.err
            elif " WARN" in str(line):
                attr = theme.warn
            th.safe_addstr(win, y + 1 + i, x + 1, text, attr)
        marker = "follow" if self.follow else f"paused -{self.scroll}"
        th.safe_addstr(win, y, x + max(1, width - len(marker) - 3), marker, theme.dim)

    def snapshot(self) -> list:
        return list(self.lines)
