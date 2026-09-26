import curses

PAIR_BORDER = 1
PAIR_TITLE = 2
PAIR_OK = 3
PAIR_WARN = 4
PAIR_ERR = 5
PAIR_DIM = 6
PAIR_SEL = 7
PAIR_ACCENT = 8
PAIR_HEAD = 9
PAIR_MUTED = 10

KEY_HELP = "?"
KEY_QUIT = "q"


def safe_addstr(win, y, x, text, attr=0, max_width=None) -> None:
    try:
        height, width = win.getmaxyx()
    except curses.error:
        return
    if y < 0 or y >= height or x >= width or x < 0:
        return
    room = width - x - 1
    if max_width is not None:
        room = min(room, max_width)
    if room <= 0:
        return
    data = str(text).replace("\t", "    ").replace("\n", " ")
    if len(data) > room:
        data = data[: max(0, room - 1)] + "…" if room > 1 else data[:room]
    try:
        win.addstr(y, x, data, attr)
    except curses.error:
        pass


def trunc(text, width) -> str:
    text = str(text)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


class Theme:
    def __init__(self, stdscr):
        self.colors = False
        self.stdscr = stdscr
        try:
            curses.start_color()
            curses.use_default_colors()
            self.colors = curses.has_colors()
        except curses.error:
            self.colors = False
        if self.colors:
            self._pair(PAIR_BORDER, curses.COLOR_WHITE, -1)
            self._pair(PAIR_TITLE, curses.COLOR_CYAN, -1)
            self._pair(PAIR_OK, curses.COLOR_GREEN, -1)
            self._pair(PAIR_WARN, curses.COLOR_YELLOW, -1)
            self._pair(PAIR_ERR, curses.COLOR_RED, -1)
            self._pair(PAIR_DIM, curses.COLOR_WHITE, -1)
            self._pair(PAIR_SEL, curses.COLOR_BLACK, curses.COLOR_CYAN)
            self._pair(PAIR_ACCENT, curses.COLOR_MAGENTA, -1)
            self._pair(PAIR_HEAD, curses.COLOR_BLACK, curses.COLOR_WHITE)
            self._pair(PAIR_MUTED, curses.COLOR_BLUE, -1)
        self.border = self._a(PAIR_BORDER, curses.A_NORMAL)
        self.title = self._a(PAIR_TITLE, curses.A_BOLD)
        self.ok = self._a(PAIR_OK, curses.A_BOLD)
        self.warn = self._a(PAIR_WARN, curses.A_BOLD)
        self.err = self._a(PAIR_ERR, curses.A_BOLD)
        self.dim = self._a(PAIR_DIM, curses.A_DIM)
        self.sel = self._a(PAIR_SEL, curses.A_BOLD)
        self.accent = self._a(PAIR_ACCENT, curses.A_BOLD)
        self.head = self._a(PAIR_HEAD, curses.A_BOLD)
        self.plain = curses.A_NORMAL

    def _pair(self, number, fg, bg) -> None:
        try:
            curses.init_pair(number, fg, bg)
        except curses.error:
            pass

    def _a(self, pair, extra) -> int:
        if not self.colors:
            return extra
        return curses.color_pair(pair) | extra

    def frame(self, win, y, x, height, width, title="") -> None:
        if height < 2 or width < 2:
            return
        attr = self.border
        try:
            win.attron(attr)
            win.hline(y, x, curses.ACS_HLINE, width - 2)
            win.hline(y + height - 1, x, curses.ACS_HLINE, width - 2)
            win.vline(y + 1, x, curses.ACS_VLINE, height - 2)
            win.vline(y + 1, x + width - 1, curses.ACS_VLINE, height - 2)
            for (yy, xx, ch) in (
                (y, x, curses.ACS_ULCORNER),
                (y, x + width - 1, curses.ACS_URCORNER),
                (y + height - 1, x, curses.ACS_LLCORNER),
                (y + height - 1, x + width - 1, curses.ACS_LRCORNER),
            ):
                try:
                    win.addch(yy, xx, ch)
                except curses.error:
                    pass
            win.attroff(attr)
        except curses.error:
            return
        if title:
            label = f" {title} "
            safe_addstr(win, y, x + 2, trunc(label, width - 4), self.title)

    def keybar(self, win, items) -> None:
        try:
            height, width = win.getmaxyx()
        except curses.error:
            return
        parts = []
        for key, desc in items:
            parts.append(f"{key} {desc}")
        line = "   ".join(parts)
        safe_addstr(win, height - 1, 0, trunc(line, width), self.dim | curses.A_BOLD)

    def statusbar(self, win, left="", right="") -> None:
        try:
            height, width = win.getmaxyx()
        except curses.error:
            return
        try:
            win.attron(self.head)
            win.hline(height - 1, 0, " ", width)
            win.attroff(self.head)
        except curses.error:
            pass
        safe_addstr(win, height - 1, 1, trunc(left, width - 4), self.head)
        if right:
            text = trunc(right, width - 4)
            safe_addstr(win, height - 1, max(1, width - len(text) - 2), text, self.head)

    def header(self, win, title, subtitle="") -> None:
        safe_addstr(win, 0, 1, trunc(title, 60), self.title | curses.A_BOLD)
        if subtitle:
            safe_addstr(win, 1, 1, trunc(subtitle, 80), self.dim)


HELP_LINES = [
    ("↑/↓ or j/k", "move selection"),
    ("⏎ Enter", "open / confirm"),
    ("←/→ or h/l", "switch step or option"),
    ("q", "back / quit"),
    ("Esc", "cancel dialog"),
    ("PgUp/PgDn", "page through lists and logs"),
    ("Home/End", "jump to start / end"),
    ("/", "filter or search (where available)"),
    ("t", "toggle follow (log viewer)"),
    ("?", "show / hide this help"),
    ("1-9", "jump straight to a menu item"),
]


def draw_help(win, theme) -> None:
    height, width = win.getmaxyx()
    box_h = min(height - 2, len(HELP_LINES) + 6)
    box_w = min(width - 4, 64)
    if box_h < 6 or box_w < 30:
        return
    y = max(1, (height - box_h) // 2)
    x = max(1, (width - box_w) // 2)
    try:
        win.attron(curses.color_pair(0) if False else 0)
    except curses.error:
        pass
    theme.frame(win, y, x, box_h, box_w, "help")
    safe_addstr(win, y + 1, x + 2, "Keyboard", theme.accent | curses.A_BOLD)
    for i, (key, desc) in enumerate(HELP_LINES[: box_h - 4]):
        safe_addstr(win, y + 2 + i, x + 2, trunc(key, 16), theme.warn)
        safe_addstr(win, y + 2 + i, x + 20, trunc(desc, box_w - 24), theme.plain)
    safe_addstr(win, y + box_h - 2, x + 2, "press ? to close", theme.dim)
    try:
        win.refresh()
    except curses.error:
        pass
