import curses

from . import theme as th
from . import widgets as w
from .widgets import is_back, is_enter, is_left, is_right


class Step:
    key = ""
    title = ""
    hint = ""

    def on_enter(self, wiz) -> None:
        pass

    def render(self, wiz, win, y: int, x: int, height: int, width: int, theme) -> None:
        th.safe_addstr(win, y, x, self.hint, theme.dim)

    def handle_key(self, wiz, key) -> str | None:
        return None

    def validate(self, wiz) -> str:
        return ""

    def summary(self, wiz) -> list:
        return []

    def text_edit(self):
        """The focused TextEdit on this step, or None.

        A step that is editing text must win every printable key (see
        Wizard.handle_key): the wizard's q/h/l/b/S navigation would otherwise
        steal characters instead of inserting them.
        """
        for attr in (getattr(self, "widget", None), getattr(self, "edit", None)):
            if isinstance(attr, w.TextEdit) and attr.active:
                return attr
        return None


class Wizard:
    def __init__(self, steps, data: dict | None = None, title: str = "wizard",
                 ctx=None):
        self.steps = list(steps)
        self.data = data if data is not None else {}
        self.index = 0
        self.title = title
        self.error = ""
        self.info = ""
        self.finished = False
        self.cancelled = False
        self.ctx = ctx
        if self.steps:
            self.steps[0].on_enter(self)

    @property
    def step(self) -> Step:
        return self.steps[self.index]

    @property
    def is_last(self) -> bool:
        return self.index >= len(self.steps) - 1

    @property
    def is_first(self) -> bool:
        return self.index == 0

    def set_error(self, message: str) -> None:
        self.error = message
        self.info = ""

    def set_info(self, message: str) -> None:
        self.info = message
        self.error = ""

    def goto(self, index: int) -> None:
        self.index = max(0, min(index, len(self.steps) - 1))
        self.error = ""
        self.info = ""
        self.step.on_enter(self)

    def next(self) -> bool:
        message = self.step.validate(self)
        if message:
            self.set_error(message)
            return False
        if self.is_last:
            self.finished = True
            return True
        self.goto(self.index + 1)
        return True

    def back(self) -> bool:
        if self.is_first:
            return False
        self.goto(self.index - 1)
        return True

    def handle_key(self, key) -> str | None:
        edit = self.step.text_edit()
        if edit is not None:
            # A focused field gets first refusal on the whole key. Every
            # printable key (q, h, l, b, S included), backspace/delete and the
            # arrows belong to it; without this the wizard's navigation ate
            # letters mid-word (typing 'q' popped the leave-dialog instead of
            # inserting a q). Esc is the one exception, handled below.
            action = self.step.handle_key(self, key)
            if action == "next":
                if self.next():
                    return "done" if self.finished else "next"
                return None
            if action in ("back", "skip", "done"):
                return action
            if key == 27:
                # Esc closes an inline edit if the step keeps one open
                # (gameplay / network), and leaves the wizard otherwise.
                return None if self.step.text_edit() is None else "quit"
            return None
        if key == ord("S"):
            if self.is_last:
                self.finished = True
                return "done"
            self.goto(self.index + 1)
            return "skip"
        if is_right(key) or (is_enter(key) and not self._step_handles_enter()):
            if self.next():
                return "done" if self.finished else "next"
            return None
        if is_left(key) or key == ord("b"):
            if self.back():
                return "back"
            return "start"
        if is_back(key):
            return "quit"
        action = self.step.handle_key(self, key)
        if action == "next":
            if self.next():
                return "done" if self.finished else "next"
        elif action == "back":
            self.back()
            return "back"
        elif action in ("skip", "done"):
            return action
        elif action == "validate":
            message = self.step.validate(self)
            if message:
                self.set_error(message)
            else:
                self.set_info("looks good")
        return None

    def _step_handles_enter(self) -> bool:
        handler = getattr(self.step, "handles_enter", False)
        return bool(handler)

    def cancel(self) -> None:
        self.cancelled = True
        self.finished = True

    def summary(self) -> list:
        rows = []
        for step in self.steps:
            for label, value in step.summary(self):
                rows.append((label, value))
        return rows

    def render(self, win, theme, spinner: str = "", extra_footer: list | None = None) -> None:
        try:
            height, width = win.getmaxyx()
        except curses.error:
            return
        head = f"{self.title}  -  step {self.index + 1}/{len(self.steps)}: {self.step.title}"
        head = f"{head:<{max(4, width - 2)}}"[: max(4, width - 2)]
        th.safe_addstr(win, 0, 1, head, theme.title | curses.A_BOLD)
        bar_w = max(10, width - 4)
        filled = int(bar_w * (self.index + 1) / max(1, len(self.steps)))
        th.safe_addstr(win, 1, 2, "█" * filled + "░" * (bar_w - filled), theme.accent)
        percent = f"{int(100 * (self.index + 1) / max(1, len(self.steps)))}%"
        th.safe_addstr(win, 1, max(2, width - len(percent) - 2), percent, theme.dim)

        box_y = 3
        box_h = max(5, height - box_y - 3)
        theme.frame(win, box_y, 1, box_h, width - 2, self.step.title)
        inner_y = box_y + 1
        inner_h = box_h - 2
        inner_w = width - 4
        if self.step.hint:
            th.safe_addstr(win, inner_y, 3, th.trunc(self.step.hint, inner_w), theme.dim)
            inner_y += 1
            inner_h -= 1
        self.step.render(self, win, inner_y, 3, max(1, inner_h), inner_w, theme)

        if self.error:
            th.safe_addstr(win, height - 3, 2, th.trunc(f"! {self.error}", width - 4), theme.err)
        elif self.info:
            th.safe_addstr(win, height - 3, 2, th.trunc(f"✓ {self.info}", width - 4), theme.ok)
        footer = [("←/b", "back"), ("→/⏎", "next"), ("S", "skip"), ("q", "quit"), ("?", "help")]
        if self.step.text_edit() is not None:
            # while a field is focused the arrows move the cursor, not the
            # wizard, so say so instead of promising navigation
            footer = [("⏎", "next"), ("←/→", "cursor"), ("esc", "leave"),
                      ("?", "help")]
        if extra_footer:
            footer = extra_footer + footer
        theme.keybar(win, footer)

    def confirm_text(self) -> str:
        return f"Leave {self.title}? progress on this step will be lost."
