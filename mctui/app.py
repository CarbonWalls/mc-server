import curses
import json
import os
import time
from pathlib import Path

from . import screens
from .core import instances, paths, procs
from .core.jobs import JobRunner
from .ui import theme as th
from .ui.panels import spinner_char

SCREENS = {
    "dashboard": ("Dashboard", "dashboard"),
    "control": ("Server control", "server_control"),
    "create": ("Create server", "create_server"),
    "instances": ("Instances", "instances"),
    "players": ("Players", "players"),
    "logs": ("Logs", "logs"),
    "backup": ("Backups", "backups"),
    "diag": ("Diagnostics", "diagnostics"),
    "config": ("Config editor", "config_editor"),
    "settings": ("Settings", "settings"),
}

TICK_MS = 100


class AppContext:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.theme = th.Theme(stdscr)
        self.jobs = JobRunner()
        self.settings = paths.load_settings()
        self.tick = 0
        self.stack = []
        self.overlay = None
        self.running = True
        self.toasts = []
        self._callbacks = {}
        self._status_cache = {"at": 0.0, "data": {}}
        self.state_file = os.environ.get("MCTUI_STATE_FILE", "")
        paths.ensure_dirs()

    def write_state(self, screen) -> None:
        if not self.state_file:
            return
        state = {"screen": getattr(screen, "name", ""), "tick": self.tick}
        wiz = getattr(screen, "wiz", None)
        if wiz is not None:
            state["step"] = wiz.index + 1
            state["steps"] = len(wiz.steps)
            state["finished"] = bool(wiz.finished)
        phase = getattr(screen, "phase", None)
        if phase is not None:
            state["phase"] = phase
        try:
            Path(self.state_file).write_text(json.dumps(state) + "\n")
        except OSError:
            pass

    # --- navigation -------------------------------------------------
    @staticmethod
    def title_of(name: str) -> str:
        return SCREENS.get(name, (name, name))[0]

    def push(self, name: str, **kwargs):
        cls = getattr(screens, SCREENS[name][1])
        screen = cls(self, **kwargs)
        screen.name = name
        if hasattr(screen, "enter"):
            screen.enter()
        self.stack.append(screen)
        return screen

    def replace(self, name: str, **kwargs):
        old = self.stack.pop()
        if hasattr(old, "leave"):
            old.leave()
        return self.push(name, **kwargs)

    def pop(self):
        if len(self.stack) > 1:
            old = self.stack.pop()
            if hasattr(old, "leave"):
                old.leave()
            return True
        return False

    @property
    def current(self):
        return self.stack[-1] if self.stack else None

    @property
    def instance_id(self) -> str:
        return instances.active_id()

    def reload_settings(self) -> None:
        self.settings = paths.load_settings()

    # --- jobs / toasts ---------------------------------------------
    def notify(self, text, level: str = "info", ttl: float = 5.0) -> None:
        self.toasts.append((str(text), level, time.time() + ttl))
        self.toasts = self.toasts[-4:]

    def run_job(self, name: str, fn, *args, on_done=None, **kwargs):
        job = self.jobs.run(name, fn, *args, **kwargs)
        if on_done is not None:
            self._callbacks[job.id] = on_done
        return job

    def drain_jobs(self) -> None:
        for job in self.jobs.poll():
            cb = self._callbacks.pop(job.id, None)
            if job.ok:
                self.notify(f"{job.name}: done", "ok", 4.0)
            else:
                self.notify(f"{job.name}: {job.error}", "err", 8.0)
            if cb is not None:
                try:
                    cb(job)
                except Exception as exc:  # callback must never kill the loop
                    self.notify(f"{job.name} callback: {exc}", "err", 6.0)

    def active_jobs(self):
        return self.jobs.active()

    # --- drawing helpers -------------------------------------------
    def status_data(self) -> dict:
        now = time.time()
        cache = self._status_cache
        if now - cache["at"] < 2.0 and cache["data"]:
            return cache["data"]
        instance = self.instance_id
        data = {
            "instance": instance,
            "server": procs.server_status(instance),
            "playitd": procs.playitd_status(),
            "tunnel": procs.tunnel_status(),
            "free": paths.free_bytes(),
        }
        self._status_cache = {"at": now, "data": data}
        return data

    def draw_toast(self, win) -> None:
        now = time.time()
        self.toasts = [t for t in self.toasts if t[2] > now]
        if not self.toasts:
            return
        text, level, _ = self.toasts[-1]
        attr = {"ok": self.theme.ok, "err": self.theme.err,
                "warn": self.theme.warn}.get(level, self.theme.accent)
        try:
            height, width = win.getmaxyx()
        except curses.error:
            return
        th.safe_addstr(win, height - 2, 1, th.trunc(f" {text}", width - 2), attr)

    def draw_footer(self, win, items) -> None:
        self.theme.keybar(win, items)

    def busy_line(self) -> str:
        jobs = self.active_jobs()
        if not jobs:
            return ""
        job = jobs[0]
        pct = int(job.progress * 100)
        return f"{spinner_char(self.tick)} {job.name} {pct}% {job.message}"


class App:
    def __init__(self, start_screen: str = "dashboard", theme_fix: bool = True):
        self.start_screen = start_screen
        self.theme_fix = theme_fix

    def run(self) -> None:
        curses.wrapper(self._main)

    def _main(self, stdscr) -> None:
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.timeout(TICK_MS)
        ctx = AppContext(stdscr)
        start = self.start_screen if self.start_screen in SCREENS else "dashboard"
        ctx.push("dashboard")
        if start != "dashboard":
            ctx.push(start)

        while ctx.running:
            ctx.tick += 1
            ctx.drain_jobs()
            screen = ctx.current
            if screen is None:
                ctx.running = False
                break
            if hasattr(screen, "tick"):
                try:
                    screen.tick()
                except Exception as exc:
                    ctx.notify(f"tick error: {exc}", "err", 6.0)
            ctx.write_state(screen)
            stdscr.erase()
            try:
                screen.render(stdscr)
            except curses.error as exc:
                th.safe_addstr(stdscr, 0, 1, f"render error: {exc}", ctx.theme.err)
            ctx.draw_toast(stdscr)
            if ctx.overlay == "help":
                th.draw_help(stdscr, ctx.theme)
            stdscr.refresh()
            key = stdscr.getch()
            if key == -1:
                continue
            if self._global_key(ctx, key):
                continue
            if ctx.overlay == "help":
                if key in (ord("?"), 27, ord("q"), 10):
                    ctx.overlay = None
                continue
            try:
                result = screen.handle_key(key)
            except curses.error as exc:
                ctx.notify(f"key error: {exc}", "err", 6.0)
                result = None
            if result == "back":
                if not ctx.pop():
                    ctx.running = False
            elif result == "quit":
                ctx.running = False
            elif isinstance(result, str) and result in SCREENS:
                ctx.push(result)

    def _global_key(self, ctx: AppContext, key: int) -> bool:
        if key == ord("?"):
            ctx.overlay = None if ctx.overlay == "help" else "help"
            return True
        if key == 3:  # ctrl-c
            ctx.running = False
            return True
        if key == curses.KEY_RESIZE:
            return False
        return False
