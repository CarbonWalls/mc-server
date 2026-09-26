import curses

from ..ui import theme as th
from ..ui import widgets as w


class Screen:
    name = ""
    title = ""

    def __init__(self, ctx, **kwargs):
        self.ctx = ctx
        self.theme = ctx.theme
        self.kwargs = kwargs
        self.tick_ms = 10  # ticks between refresh work (100ms each)

    # --- lifecycle ---------------------------------------------------
    def enter(self):
        pass

    def leave(self):
        pass

    def tick(self):
        pass

    # --- drawing -----------------------------------------------------
    @staticmethod
    def size(win):
        try:
            return win.getmaxyx()
        except curses.error:
            return 24, 80

    def header(self, win, title: str = "", subtitle: str = "") -> None:
        height, width = self.size(win)
        title = title or self.title or self.ctx.title_of(self.name)
        title = f"{title:<{max(4, width - 2)}}"[: max(4, width - 2)]
        th.safe_addstr(win, 0, 1, title, self.theme.title | curses.A_BOLD)
        if subtitle:
            th.safe_addstr(win, 1, 1, th.trunc(subtitle, width - 2), self.theme.dim)

    def footer(self, win, items) -> None:
        busy = self.ctx.busy_line()
        self.theme.keybar(win, items)
        if busy:
            height, width = self.size(win)
            th.safe_addstr(win, height - 1, max(1, width - len(busy) - 4),
                           th.trunc(busy, width // 2), self.theme.accent)

    def frame(self, win, y, x, h, w_, title: str = "") -> None:
        self.theme.frame(win, y, x, h, w_, title)

    def content_box(self, win, title: str = "", top: int = 2):
        height, width = self.size(win)
        box_h = max(5, height - top - 3)
        self.theme.frame(win, top, 1, box_h, width - 2, title)
        return (top + 1, 3, box_h - 2, width - 6)

    # --- common keys -------------------------------------------------
    def handle_key(self, key):
        if key in (ord("q"), 27) or key == curses.KEY_BACKSPACE:
            return "back"
        return None

    def confirm_dialog(self, message: str, title: str = "confirm",
                       dangerous: bool = True, yes_label: str = "yes") -> w.Confirm:
        return w.Confirm(message, title=title, dangerous=dangerous, yes_label=yes_label)
