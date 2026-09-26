#!/usr/bin/env python3
"""mc_tui.py - curses TUI for the self-hosted Minecraft server in this folder.

Run:  python3 mc_tui.py            (dashboard)
      python3 mc_tui.py --screen logs
"""
import argparse
import os
import sys

BANNER = "mc_tui - Minecraft server manager (TUI)"


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="mc_tui.py", description=BANNER)
    parser.add_argument("--screen", default=os.environ.get("MCTUI_SCREEN", "dashboard"),
                        help="start on a screen: dashboard, control, create, instances, "
                             "players, logs, backup, diag, config, settings")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument("--check", action="store_true",
                        help="import every module and exit (no curses needed)")
    return parser.parse_args(argv)


def self_check() -> int:
    import mctui.app
    import mctui.core.backup
    import mctui.core.config
    import mctui.core.download
    import mctui.core.instances
    import mctui.core.jobs
    import mctui.core.logs
    import mctui.core.paths
    import mctui.core.players
    import mctui.core.playit_ipc
    import mctui.core.probes
    import mctui.core.procs
    import mctui.core.version
    import mctui.screens
    import mctui.ui.theme
    import mctui.ui.widgets
    import mctui.ui.wizard
    print("ok: all modules import")
    return 0


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        print(BANNER)
        return 0
    if args.check:
        return self_check()
    from mctui.app import App, SCREENS
    if args.screen not in SCREENS:
        print(f"unknown screen {args.screen!r}; choose from: "
              + ", ".join(sorted(SCREENS)), file=sys.stderr)
        return 2
    try:
        import curses
    except ImportError as exc:
        print(f"curses unavailable: {exc}", file=sys.stderr)
        return 1
    if not os.isatty(sys.stdout.fileno()) and not os.environ.get("MCTUI_FORCE_TTY"):
        print("stdin/stdout must be a terminal (use a real tty, e.g. tmux or ssh)",
              file=sys.stderr)
        return 1
    App(start_screen=args.screen).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
