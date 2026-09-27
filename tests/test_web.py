"""Phase 8 tests: the web backend for webui/index.html.

Every endpoint the frozen UI fetches is exercised against an isolated tree,
including the three the UI's header documents as TODOs: bans in
GET /api/players, POST /api/instances/settings and GET /api/plugins/catalogue.

A fake java stands in for the real one so start/console/stop run end to end
through the relay. The server binds to port 0 (any free port) and the accept
loop runs in a background thread of the test process.
"""
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import mctui_test_env

ROOT = mctui_test_env.activate()
mctui_test_env.seed(ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctui import web  # noqa: E402
from mctui.core import console as console_core  # noqa: E402
from mctui.core import instances, paths, procs  # noqa: E402

INSTANCE = "main"
FAKE = ROOT / "fakejava_web"
SERVER = None
BASE = ""
ERRORS = []


def make_fake_java():
    FAKE.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, threading, time\n"
        # procs.java_version runs this with -version; answer instantly so the\n"
        # status endpoint never blocks on a sleep\n"
        "if '-version' in sys.argv or '--version' in sys.argv:\n"
        "    sys.stderr.write('openjdk version \"21.0.2\" 2024-01-16\\n')\n"
        "    sys.exit(0)\n"
        # the server gets stdin as a pipe so the console relay can write to\n"
        # it; a read error on that pipe must not take the process down\n"
        "def _drain():\n"
        "    try:\n"
        "        for line in sys.stdin:\n"
        "            print('CMD: ' + line.strip(), flush=True)\n"
        "    except Exception:\n"
        "        pass\n"
        "threading.Thread(target=_drain, daemon=True).start()\n"
        "time.sleep(300)\n")
    FAKE.chmod(0o755)
    procs._resolve_jdk = lambda override="": FAKE


def check(label, condition, extra=""):
    if condition:
        print(f"ok   {label}")
        return
    print(f"FAIL {label}  {extra}")
    ERRORS.append(label)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode())


def post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode() or "{}")


def wait_for_server(seconds=15.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if procs.server_status(INSTANCE).get("state") == "running":
            return True
        time.sleep(0.3)
    return False


def test_ui_and_gets():
    with urllib.request.urlopen(BASE + "/", timeout=20) as r:
        page = r.read().decode()
    check("serves the frozen index.html",
          "Minecraft Server Manager" in page and "EventSource" in page)

    status = get("/api/status")
    check("status shape",
          status["server"]["state"] in ("running", "stopped", "stale", "missing"),
          str(status)[:200])
    check("status reports the instance", status["instance"] == INSTANCE)

    listing = get("/api/instances")
    check("instances lists main",
          any(i["id"] == INSTANCE for i in listing["instances"]))
    check("instances reports the active one",
          listing["active"] == instances.active_id())

    check("logs shape", isinstance(get(
        "/api/logs?instance=main&lines=5")["lines"], list))

    players = get("/api/players?instance=main")
    for key in ("online", "recent", "whitelist", "ops", "bans", "max_players"):
        check(f"players payload has {key}", key in players, str(players)[:160])
    check("players bans are name/reason/created entries",
          all(set(b) >= {"name", "reason", "created"} for b in players["bans"])
          or players["bans"] == [])

    check("backups shape", isinstance(get("/api/backups?instance=main")["backups"], list))
    check("tunnels shape",
          "tunnels" in get("/api/tunnels") and "account" in get("/api/tunnels"))
    check("jobs shape", isinstance(get("/api/jobs")["jobs"], list))

    # TODO #3 from the UI's contract: a real plugin catalogue
    catalogue = get("/api/plugins/catalogue")
    check("plugins catalogue is non-empty",
          len(catalogue.get("plugins", [])) >= 5, str(catalogue)[:120])
    check("catalogue includes geyser",
          any(p.get("id") == "geyser" for p in catalogue.get("plugins", [])))


def test_player_lists():
    check("whitelist add",
          post("/api/players/whitelist/add",
               {"instance": INSTANCE, "name": "Steve"}).get("ok"))
    check("duplicate whitelist add refused",
          not post("/api/players/whitelist/add",
                   {"instance": INSTANCE, "name": "Steve"}).get("ok"))
    check("op add",
          post("/api/players/op/add",
               {"instance": INSTANCE, "name": "Alex"}).get("ok"))
    ban = post("/api/players/ban", {"instance": INSTANCE, "name": "Griefer",
                                    "reason": "griefing"})
    check("ban", ban.get("ok"), str(ban))
    bans = get(f"/api/players?instance={INSTANCE}")["bans"]
    check("ban is visible with its reason",
          any(b.get("name") == "Griefer" and b.get("reason") == "griefing"
              for b in bans), str(bans))
    check("op remove",
          post("/api/players/op/remove",
               {"instance": INSTANCE, "name": "Alex"}).get("ok"))
    check("whitelist remove",
          post("/api/players/whitelist/remove",
               {"instance": INSTANCE, "name": "Steve"}).get("ok"))


def test_server_and_console():
    check("server start accepted",
          post("/api/server/start", {"instance": INSTANCE}).get("ok"))
    check("server reaches running state", wait_for_server())
    if not wait_for_server():
        return
    time.sleep(1.0)
    check("console relay is up", console_core.relay_alive(INSTANCE))

    sent = post("/api/console", {"instance": INSTANCE, "command": "say hello"})
    check("console command delivered", sent.get("ok"), str(sent))
    time.sleep(0.7)
    log_text = paths.log_paths(INSTANCE)["server_log"].read_text()
    check("typed command reached the server", "CMD: say hello" in log_text,
          log_text[-200:])

    # a kick is a console command: it is delivered even for an offline player
    # (the server says so itself), so delivery is the contract
    kick = post("/api/players/kick", {"instance": INSTANCE, "name": "Nobody"})
    check("kick command delivered", kick.get("ok"), str(kick))
    history = console_core.read_history(INSTANCE)
    check("console history records commands",
          any("say hello" in line for line in history), str(history[-3:]))

    check("server stop accepted",
          post("/api/server/stop", {"instance": INSTANCE}).get("ok"))
    deadline = time.time() + 15.0
    while console_core.relay_alive(INSTANCE) and time.time() < deadline:
        time.sleep(0.3)
    check("relay exits and removes its socket when the server stops",
          not console_core.relay_alive(INSTANCE)
          and not console_core.relay_socket_path(INSTANCE).exists())


def test_settings():
    """TODO #2: persisting runtime settings (memory / ports / tunnel / java)."""
    outcome = post("/api/instances/settings", {"instance": INSTANCE,
                                               "memory": "2G", "tunnel": "playit"})
    check("settings accepted", outcome.get("ok"), str(outcome))
    entry = instances.get_instance(INSTANCE)
    check("memory stored on the instance",
          entry.get("xms") == "2G" and entry.get("xmx") == "2G",
          f"xms={entry.get('xms')} xmx={entry.get('xmx')}")
    check("tunnel stored", entry.get("tunnel") == "playit")
    again = post("/api/instances/settings", {"instance": INSTANCE,
                                             "memory": "2G", "tunnel": "playit"})
    check("identical settings are a no-op", again.get("ok") and again.get("unchanged"),
          str(again))


def test_instance_lifecycle():
    """Validation paths that don't need a download."""
    check("create rejects a duplicate id",
          not post("/api/instances/create", {"id": INSTANCE, "name": "dup"}).get("ok"))
    check("create rejects an empty id",
          not post("/api/instances/create", {"id": "", "name": "x"}).get("ok"))
    check("clone accepted",
          post("/api/instances/clone",
               {"instance": INSTANCE, "new_id": "webclone"}).get("ok"))
    time.sleep(1.0)
    check("rename accepted",
          post("/api/instances/rename",
               {"instance": "webclone", "new_id": "webrenamed"}).get("ok"))
    check("delete accepted",
          post("/api/instances/delete", {"instance": "webrenamed"}).get("ok"))


def test_backups():
    check("backup create accepted",
          post("/api/backups/create", {"instance": INSTANCE}).get("ok"))
    deadline = time.time() + 20.0
    listing = []
    while time.time() < deadline:
        listing = get(f"/api/backups?instance={INSTANCE}")["backups"]
        if listing:
            break
        time.sleep(0.5)
    check("backup appears in the listing", len(listing) >= 1,
          f"{len(listing)} backups")
    if listing:
        check("backup delete",
              post("/api/backups/delete",
                   {"name": listing[0]["name"], "instance": INSTANCE}).get("ok"))


def test_sse():
    """The event stream must deliver at least one named event."""
    port = SERVER.server_address[1]
    sock = socket.create_connection(("127.0.0.1", port), timeout=20)
    sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    sock.settimeout(20.0)
    buffer = b""
    got = None
    try:
        end = time.time() + 20
        while time.time() < end:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            for kind in (b"event: status", b"event: players",
                         b"event: log", b"event: job"):
                if kind in buffer:
                    got = kind.decode()
                    break
            if got:
                break
    except socket.timeout:
        pass
    sock.close()
    check("sse delivers a named event", got is not None, repr(buffer[:160]))


def cleanup():
    try:
        procs.stop_server(INSTANCE, timeout=5)
    except Exception:
        pass
    for path in (console_core.relay_socket_path(INSTANCE),
                 console_core.relay_pid_path(INSTANCE)):
        try:
            path.unlink()
        except OSError:
            pass
    for stray in ("webclone", "webrenamed"):
        try:
            instances.delete(stray, make_backup=False)
        except Exception:
            pass


def main():
    global SERVER, BASE
    make_fake_java()
    (paths.server_dir() / "paper.jar").write_bytes(b"fakejar")
    SERVER = web.serve("127.0.0.1", 0)
    BASE = f"http://127.0.0.1:{SERVER.server_address[1]}"
    # the accept loop has to be running before any request is handled
    threading.Thread(target=SERVER.serve_forever,
                     kwargs={"poll_interval": 0.2}, daemon=True).start()
    time.sleep(0.4)
    try:
        for fn in (test_ui_and_gets, test_player_lists, test_server_and_console,
                   test_settings, test_instance_lifecycle, test_backups,
                   test_sse):
            print(f"-- {fn.__name__}")
            try:
                fn()
            except Exception as exc:  # a helper failing is a failure
                check(fn.__name__, False, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            SERVER.shutdown()
            SERVER.server_close()
        except Exception:
            pass
        cleanup()
    print()
    if ERRORS:
        print(f"FAILED ({len(ERRORS)}): {ERRORS}")
        return 1
    print("PASS web")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
