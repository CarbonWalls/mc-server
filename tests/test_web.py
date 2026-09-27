"""Phase 8 tests: the web backend for webui/index.html.

Every endpoint the frozen UI fetches is exercised against an isolated tree,
including the three the UI's header documents as TODOs: bans in
GET /api/players, POST /api/instances/settings and GET /api/plugins/catalogue.

A fake java stands in for the real one so start/console/stop run end to end
through the relay. The server binds to port 0 (any free port) and the accept
loop runs in a background thread of the test process.
"""
import json
import shutil
import socket
import socketserver
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


def _fake_agent(sock_path, tunnels):
    """A stand-in playitd speaking the project's IPC line protocol.

    Replies to get_status / subscribe with a claimed agent that owns the given
    tunnels, so the tunnels endpoint can be exercised without a real agent
    (playitd 1.0.10 is not runnable in CI).
    """
    import os
    if os.path.exists(sock_path):
        try:
            os.unlink(sock_path)
        except OSError:
            pass

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.sendall(
                (json.dumps({"data": {"agent_id": "fake"}}) + "\n").encode())
            buf = b""
            while True:
                try:
                    chunk = self.request.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        msg = json.loads(line.decode())
                    except ValueError:
                        continue
                    rtype = (msg.get("request") or {}).get("type")
                    if rtype == "get_status":
                        data = {"pid": os.getpid(), "version": "fake",
                                "has_secret": True}
                    elif rtype == "subscribe":
                        data = {"snapshot": {"lifecycle": {
                            "state": "Claimed",
                            "data": {"tunnels": tunnels,
                                     "account_status": "claimed",
                                     "login_link": None},
                        }, "stats": {}}}
                    else:
                        data = {}
                    reply = {"message_kind": "response",
                             "data": {"request_id": msg.get("request_id"),
                                      "response": {"type": rtype,
                                                    "data": data}}}
                    try:
                        self.request.sendall((json.dumps(reply) + "\n").encode())
                    except OSError:
                        return

    server = socketserver.ThreadingUnixStreamServer(str(sock_path), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever,
                     kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server


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
          "Minecraft Server Manager" in page and 'src="app.js"' in page)

    # the page is split into index.html + styles.css + app.js; the two linked
    # assets must be served from the same origin, still with no build step
    with urllib.request.urlopen(BASE + "/styles.css", timeout=20) as r:
        css = r.read().decode()
    check("styles.css is served", ":root" in css and "--accent" in css)
    with urllib.request.urlopen(BASE + "/app.js", timeout=20) as r:
        appjs = r.read().decode()
    check("app.js is served and unchanged",
          "EventSource" in appjs and "SCREENS" in appjs)
    check("linked assets are not inlined into index.html",
          "<style" not in page and "EventSource" not in page)
    # webui/ is the only folder served: a traversal attempt must not leak files
    try:
        with urllib.request.urlopen(BASE + "/../../README.md", timeout=20) as r:
            leaked = r.status == 200
    except urllib.error.HTTPError:
        leaked = False
    check("paths outside webui/ are not served", not leaked)

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

    # bedrock_port also rewrites Geyser's broadcast-port (what the README
    # promises for this endpoint) and rejects garbage instead of 500ing
    bad = post("/api/instances/settings",
               {"instance": INSTANCE, "bedrock_port": "not-a-port"})
    check("a non-numeric bedrock_port is rejected", not bad.get("ok"), str(bad))
    ranged = post("/api/instances/settings",
                  {"instance": INSTANCE, "bedrock_port": 99999})
    check("an out-of-range bedrock_port is rejected", not ranged.get("ok"),
          str(ranged))
    applied = post("/api/instances/settings",
                   {"instance": INSTANCE, "bedrock_port": 7777})
    check("bedrock_port accepted", applied.get("ok"), str(applied))
    check("bedrock_port stored on the instance",
          instances.get_instance(INSTANCE).get("bedrock_port") == 7777)
    geyser = (paths.instance_path(INSTANCE) / "plugins" / "Geyser-Spigot"
              / "config.yml")
    check("settings also wrote broadcast-port",
          "broadcast-port: 7777" in geyser.read_text())


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


def test_servers_and_connect():
    """The Servers screen rows and the guided playit flow."""
    listing = get("/api/instances")
    row = next(i for i in listing["instances"] if i["id"] == INSTANCE)
    for key in ("id", "name", "path", "exists", "paper_version", "build",
                "tunnel", "bedrock_port", "state", "created", "note",
                "xms", "xmx", "java_override", "server_port"):
        check(f"instance row has {key}", key in row, str(row)[:200])
    # the raw classification, so Servers can tell 'stale' from 'missing'
    check("instance state is the raw process state",
          row["state"] in ("running", "stopped", "stale", "missing"), str(row))

    tunnels = get("/api/tunnels")
    check("tunnels reports the claimed flag", "has_secret" in tunnels, str(tunnels))
    check("tunnels reports a claim link", "claim_url" in tunnels)

    applied = post("/api/instances/tunnel-port",
                   {"instance": INSTANCE, "port": 6695})
    check("tunnel port applied", applied.get("ok"), str(applied))
    geyser = paths.instance_path(INSTANCE) / "plugins" / "Geyser-Spigot" / "config.yml"
    text = geyser.read_text()
    check("broadcast-port was written to the Geyser config",
          "broadcast-port: 6695" in text, text[-200:])
    bad = post("/api/instances/tunnel-port", {"instance": INSTANCE, "port": 0})
    check("an invalid port is refused", not bad.get("ok"), str(bad))

    # the paper listing degrades to an error rather than raising when the
    # papermc API is unreachable
    versions = get("/api/paper/versions")
    check("paper versions shape", "versions" in versions, str(versions)[:160])

    # a missing instance must fail in the job instead of downloading anything
    check("paper-version accepts the job",
          post("/api/instances/paper-version",
               {"instance": "no-such-instance", "version": "1.21.4"}).get("ok"))
    deadline = time.time() + 25.0
    failed = False
    while time.time() < deadline:
        jobs = get("/api/jobs")["jobs"]
        mine = [j for j in jobs if str(j.get("name", "")).startswith("paper ")]
        if mine and all(j.get("done") for j in mine):
            failed = all(not j.get("ok") for j in mine)
            break
        time.sleep(0.4)
    check("paper-version on a missing instance fails cleanly", failed)

    # the daemon stub exits immediately; starting and stopping must be safe
    check("playit start is accepted",
          post("/api/playit/start", {"first_run": True}).get("ok"))
    check("playit stop is accepted",
          post("/api/playit/stop", {}).get("ok"))


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


def test_two_tunnels_both_editions():
    """The post-setup state is TWO tunnels: TCP for Java, UDP for Bedrock.

    The dashboard used to read tunnels.tunnels[0] and call it "the" address,
    which hid whichever edition sorted second. This stands up a fake agent
    speaking the real IPC protocol, reporting both, and checks the endpoint
    hands both back with the right protocol labels - the UI layer above it
    then renders one address per edition.
    """
    sock_path = paths.playit_socket()
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    server = None
    try:
        server = _fake_agent(sock_path, [
            {"display_address": "java.example.tun.ply.gg:25565",
             "destination": "127.0.0.1:25565", "is_disabled": False,
             "disabled_reason": None},
            {"display_address": "bedrock.example.tun.ply.gg:19132",
             "destination": "127.0.0.1:19132", "is_disabled": False,
             "disabled_reason": None},
        ])
        deadline = time.time() + 5.0
        while not sock_path.exists() and time.time() < deadline:
            time.sleep(0.05)
        tunnels = get("/api/tunnels")
        rows = tunnels.get("tunnels") or []
        check("two tunnels came back from the agent", len(rows) == 2, str(rows))
        protos = sorted(r.get("proto") for r in rows)
        check("one TCP and one UDP tunnel",
              protos == ["TCP", "UDP"], str(protos))
        # the UI picks the Java row for the primary address and the UDP row for
        # the Bedrock one; both have to survive the round trip
        java = next((r for r in rows if r.get("proto") != "UDP"), None)
        udp = next((r for r in rows if r.get("proto") == "UDP"), None)
        check("the java tunnel address is intact",
              java and java.get("host") and java.get("port"), str(java))
        check("the bedrock tunnel address is intact",
              udp and udp.get("host") and udp.get("port"), str(udp))
        # 19132 is what marks a tunnel as Bedrock (see _looks_udp)
        check("the UDP tunnel is the one pointing at 19132",
              udp and str(udp.get("destination", "")).endswith(":19132"), str(udp))
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        try:
            sock_path.unlink()
        except OSError:
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
                   test_settings, test_instance_lifecycle, test_servers_and_connect,
                   test_claim_link, test_two_tunnels_both_editions,
                   test_backups, test_sse):
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


def test_claim_link():
    """The claim link the Connect screen shows, against the real binaries.

    playitd 1.0.10 never prints a claim URL: it waits for a secret to be
    provisioned over IPC. The link has to come from the bundled `playit` CLI
    (claim generate + claim url), which is offline. Skipped when the binaries
    are absent, so the suite still runs on a tree without them.
    """
    playit = paths.bin_dir() / "playit"
    # seed() writes an exit-0 stub in place of the real agent binaries; put the
    # real CLI there so this is exercised wherever playit is installed,
    # otherwise it is skipped
    real = mctui_test_env.PROJECT / "bin" / "playit"
    if not real.is_file():
        print("   (skipped: bin/playit not present)")
        return
    paths.bin_dir().mkdir(parents=True, exist_ok=True)
    shutil.copy(real, playit)

    # the claim code is what the CLI generates, and the URL is deterministic
    # from it, so the two have to agree
    link = web._claim_link_from_cli()
    check("the CLI produced a claim url", bool(link), link)
    if not link:
        return
    code = link.rsplit("/claim/", 1)[1]
    import subprocess
    import re
    check("the claim url matches playit's format",
          bool(re.fullmatch(r"https://playit\.gg/claim/[A-Za-z0-9]{6,}", link)), link)
    again = web._claim_link_from_cli()
    check("the link is cached between polls (the code is random per call)",
          again == link, f"{link} vs {again}")

    # and the same URL the CLI would print for that code
    try:
        printed = subprocess.run([str(playit), "claim", "url", code],
                                 capture_output=True, text=True,
                                 timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        check("playit claim url ran", False, str(exc))
        return
    check("the url matches `playit claim url <code>`", printed == link,
          f"{printed!r} vs {link!r}")

    # the log scrape is the fallback: it must find a URL a daemon actually
    # printed, and stay quiet when there is nothing to find
    log = paths.log_paths("main")["playitd_verbose_log"]
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "2026-01-01T00:00:00Z INFO playitd::daemon: Starting playitd\n"
        "2026-01-01T00:00:00Z INFO playitd::daemon: Waiting for frontend "
        "secret provisioning over IPC\n"
        "2026-01-01T00:00:01Z INFO https://playit.gg/claim/legacycode123\n"
        "2026-01-01T00:00:02Z INFO tunnel up\n",
        encoding="utf-8")
    check("the log scrape finds the last claim url a daemon printed",
          web._claim_url_from_log() == "https://playit.gg/claim/legacycode123",
          web._claim_url_from_log())
    log.unlink()
    check("the log scrape is quiet when there is no log",
          web._claim_url_from_log() == "", web._claim_url_from_log())


if __name__ == "__main__":
    raise SystemExit(main())
