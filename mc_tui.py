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
                        help="report whether this tree can host a server, and exit")
    parser.add_argument("--doctor", action="store_true",
                        help="check this machine for a from-zero bootstrap (no curses)")
    parser.add_argument("--bootstrap", action="store_true",
                        help="install everything this project needs, from zero")
    parser.add_argument("--paper-version", default="",
                        help="paper line to bootstrap (default: newest stable)")
    parser.add_argument("--yes", action="store_true",
                        help="accept the Mojang EULA without prompting")
    parser.add_argument("--web", action="store_true",
                        help="serve the browser UI and API instead of the TUI")
    parser.add_argument("--web-host", default=os.environ.get("MCTUI_WEB_HOST", "127.0.0.1"),
                        help="address to bind the web UI to (default 127.0.0.1)")
    parser.add_argument("--web-port", type=int,
                        default=int(os.environ.get("MCTUI_WEB_PORT", "8080")),
                        help="port to bind the web UI to (default 8080)")
    return parser.parse_args(argv)


def self_check() -> int:
    """Honest readiness report: exit 0 only if this tree can host a server.

    Never claims success just because the modules import; an empty checkout
    imports fine but cannot run anything.
    """
    from mctui.core import check
    return check.run()


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
    from mctui.core import bootstrap, paths

    if not bootstrap.host_arch():
        print(f"bootstrap: unsupported architecture {bootstrap._machine()!r}; "
              f"supported: x86_64, aarch64/arm64, armv7l", file=sys.stderr)
        return 1
    for step in bootstrap.plan({"paper_version": args.paper_version}):
        mark = "will install" if step["needed"] else "already present"
        print(f"  {step['label']:<22} {mark}")
    print()
    # the Mojang EULA gates the server: never accept it on the user's behalf
    spec = {"paper_version": args.paper_version}
    if not paths.server_dir().joinpath("eula.txt").is_file():
        print("Minecraft is not free software. Before the server can start you")
        print("must accept the Mojang EULA: https://aka.ms/MinecraftEULA")
        print()
        if os.environ.get("MCTUI_YES"):
            print("accepted via MCTUI_YES (non-interactive)", file=sys.stderr)
            consent = True
        elif args.yes:
            consent = True
        elif sys.stdin.isatty():
            answer = input("Accept the EULA? [y/N] ").strip().lower()
            consent = answer in ("y", "yes")
        else:
            print("not a terminal and MCTUI_YES unset - skipping the EULA; "
                  "the download will finish but the server will not start",
                  file=sys.stderr)
            consent = False
        if not consent:
            print("EULA declined; nothing written to server/eula.txt.",
                  file=sys.stderr)
        else:
            spec["eula_consent"] = True
        print()
    print("downloading into this folder only (no root, no system installs) ...")

    class Job:
        def update(self, progress=None, message=""):
            if message:
                pct = int((progress or 0) * 100)
                print(f"  [{pct:3d}%] {message}")

    result = bootstrap.bootstrap(Job(), spec)
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


def run_web(args) -> int:
    """Serve the browser UI and its JSON API (does not touch running servers)."""
    from mctui import web
    from mctui.core import paths
    try:
        server = web.serve(args.web_host, args.web_port)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"web: cannot bind {args.web_host}:{args.web_port}: {exc}",
              file=sys.stderr)
        return 1
    ui = paths.relative(web.WEBUI_FILE) if web.WEBUI_FILE.exists() else "webui/index.html"
    # report the port actually bound: --web-port 0 lets the OS choose one
    real_host, real_port = server.server_address[:2]
    print(f"mc_tui web UI: http://{real_host}:{real_port}", flush=True)
    print(f"  serving {ui}", flush=True)
    print("  ctrl-c to stop (running servers are not affected)", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nstopping the web UI (your server keeps running)")
    finally:
        server.shutdown()
        server.server_close()
    return 0


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
    if args.web:
        return run_web(args)
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
