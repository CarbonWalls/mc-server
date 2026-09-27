import curses
import time

from ..core import console as console_core
from ..core import logs as logs_core
from ..core import paths, procs
from ..ui import theme as th
from ..ui import widgets as w
from ..ui.widgets import is_enter
from ._base import Screen


class console(Screen):
    """Live server console: the running server's output plus a command line.

    The output pane tails the same log file the log viewer uses, so what you
    type and what the server echoes back appear in one place. Commands travel
    through the console relay (see mctui/core/console.py), which keeps the
    server's stdin open even after the TUI exits.
    """

    def enter(self):
        self.instance = self.ctx.instance_id
        self.tail = None
        self.scroll = w.ScrollView(maxlen=2000)
        self.edit = w.TextEdit("", label="")
        self.editing = True
        self.history = console_core.read_history(self.instance)
        self.hist_index = None
        self.last_result = ""
        self.last_ok = True
        self.result_until = 0.0
        self._load()
        self._client = console_core.ConsoleClient(self.instance)

    def leave(self):
        try:
            self._client.close()
        except Exception:
            pass

    def _load(self):
        path = paths.log_paths(self.instance)["server_log"]
        self.tail = logs_core.LiveTail(path, maxlen=2000)
        self.tail.load(keep=400)
        self.scroll.follow = True
        self.scroll.scroll = 0

    def _say(self, text, ok=True, ttl=5.0):
        self.last_result = text
        self.last_ok = ok
        self.result_until = time.time() + ttl
        self.ctx.notify(text, "ok" if ok else "err", ttl)

    def _status_line(self) -> str:
        running = procs.server_status(self.instance).get("state") == "running"
        relay = console_core.relay_alive(self.instance)
        if running and relay:
            return "console: live (type a command and press enter)"
        if running and not relay:
            return "console: server is running but the relay is gone - " \
                   "restart the server to send commands"
        return "console: server is not running - start it first (commands " \
               "will not reach anything)"

    def tick(self):
        if self.tail is not None:
            self.tail.refresh()

    def render(self, win):
        height, width = self.size(win)
        self.header(win, "console", f"instance: {self.instance}   "
                                    f"{self._status_line()}")
        cmd_h = 3
        out_h = max(4, height - 4 - cmd_h)
        lines = self._output_lines()
        self.scroll.render(win, 3, 1, out_h, width - 2, self.theme,
                           "server output", lines=lines)
        cmd_top = 3 + out_h + 1
        th.safe_addstr(win, cmd_top, 1, "send a command:", self.theme.dim)
        self.edit.render(win, cmd_top + 1, 1, width - 2, self.theme,
                         show_label=False)
        if time.time() < self.result_until:
            attr = self.theme.ok if self.last_ok else self.theme.err
            th.safe_addstr(win, height - 2, 2, th.trunc(self.last_result,
                                                        width - 4), attr)
        self.footer(win, [
            ("enter", "send"), ("↑↓", "history"), ("pgup/pgdn", "scroll"),
            ("esc", "clear line"), ("?", "help"), ("q", "back"),
        ])

    def _output_lines(self) -> list:
        if self.tail is None:
            return ["(no log file yet - start the server)"]
        lines = self.tail.apply_filter("")
        if self.tail.missing:
            return [f"(file missing: {self.tail.path}) - start the server"]
        return lines or ["(waiting for the server to write its first line...)"]

    # --- input --------------------------------------------------------
    def handle_key(self, key):
        # quit only from an empty prompt; escape clears the line instead
        if key in (ord("q"), 27):
            if key == 27 and self.edit.value != "":
                self.edit.value = ""
                self.edit.cursor = 0
                self.hist_index = None
                return None
            if key == 27:
                return None
            return "back"
        if is_enter(key):
            return self._submit()
        if key == curses.KEY_UP:
            return self._history_older()
        if key == curses.KEY_DOWN:
            return self._history_newer()
        if key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
            page = max(4, self.size(self.ctx.stdscr)[0] - 10)
            self.scroll.handle_key(key, page=page)
            return None
        # every printable key types into the command line, so no letter can be
        # a shortcut here: pgup/pgdn scroll (and re-enable follow at the
        # bottom), arrows recall history.
        result = self.edit.handle_key(key)
        if result == "edit":
            self.hist_index = None
        return None

    def _submit(self):
        command = self.edit.value.strip()
        if not command:
            return None
        outcome = self._client.send(command)
        if outcome.get("ok"):
            self.history = console_core.read_history(self.instance)
            self._say(f"sent: {command}", ok=True, ttl=3.0)
            self.edit = w.TextEdit("", label="")
            self.hist_index = None
        else:
            self._say(outcome.get("error", "send failed"), ok=False, ttl=6.0)
        return None

    def _history_older(self):
        if not self.history:
            return None
        if self.hist_index is None:
            self.hist_index = len(self.history) - 1
        else:
            self.hist_index = max(0, self.hist_index - 1)
        self.edit.value = self._history_command(self.hist_index)
        self.edit.cursor = len(self.edit.value)
        return None

    def _history_newer(self):
        if self.hist_index is None:
            return None
        if self.hist_index >= len(self.history) - 1:
            self.hist_index = None
            self.edit.value = ""
        else:
            self.hist_index += 1
            self.edit.value = self._history_command(self.hist_index)
        self.edit.cursor = len(self.edit.value)
        return None

    def _history_command(self, index: int) -> str:
        line = self.history[index]
        if "] " in line:
            line = line.split("] ", 1)[1]
        return line
