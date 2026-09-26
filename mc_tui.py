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
    parser.add_argument("--doctor", action="store_true",
                        help="check this machine for a from-zero bootstrap (no curses)")
    parser.add_argument("--bootstrap", action="store_true",
                        help="install everything this project needs, from zero")
    parser.add_argument("--paper-version", default="",
                        help="paper line to bootstrap (default: newest stable)")
    return parser.parse_args(argv)


def self_check() -> int:
    import mctui.app
    import mctui.core.backup
    import mctui.core.bootstrap
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


_LABEL = {"ok": "ok  ", "warn": "WARN", "err": "FAIL", "todo": "todo"}


def run_doctor() -> int:
    from mctui.core import bootstrap
    findings = bootstrap.doctor()
    for status, message in findings:
        print(f"[{_LABEL.get(status, status)}] {message}")
    bad = [m for s, m in findings if s == "err"]
    missing = [m for s, m in findings if s == "todo"]
    print()
    if bad:
        print(f"doctor: {len(bad)} blocking problem(s), {len(missing)} missing piece(s)")
        return 1
    print(f"doctor: {len(missing)} step(s) left to bootstrap; "
          f"run: python3 mc_tui.py --bootstrap")
    return 0


def run_bootstrap(args) -> int:
    from mctui.core import bootstrap
    if not bootstrap.host_arch():
        print(f"bootstrap: unsupported architecture {bootstrap._machine()!r}; "
              f"supported: x86_64, aarch64/arm64, armv7l", file=sys.stderr)
        return 1
    for step in bootstrap.plan({"paper_version": args.paper_version}):
        mark = "will install" if step["needed"] else "already present"
        print(f"  {step['label']:<22} {mark}")
    print()
    print("downloading into this folder only (no root, no system installs) ...")

    class Job:
        def update(self, progress=None, message=""):
            if message:
                pct = int((progress or 0) * 100)
                print(f"  [{pct:3d}%] {message}")

    result = bootstrap.bootstrap(Job(), {"paper_version": args.paper_version})
    print()
    for step in result.get("steps", []):
        if step.get("ok"):
            print(f"  ok    {step.get('step')}")
        else:
            print(f"  FAIL  {step.get('step')}: {step.get('error')}")
    for item in result.get("todo", []):
        print(f"  next  {item}")
    if result.get("ok"):
        print("\nbootstrap complete. Start the server with: ./start.sh")
        return 0
    print(f"\nbootstrap incomplete: {result.get('error')}", file=sys.stderr)
    print("re-run to retry from where it stopped (already-downloaded pieces are kept)",
          file=sys.stderr)
    return 1


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.version:
        print(BANNER)
        return 0
    if args.check:
        return self_check()
    if args.doctor:
        return run_doctor()
    if args.bootstrap:
        return run_bootstrap(args)
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
