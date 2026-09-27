# Cross-Platform Minecraft Server (Free, Self-Hosted)

A fully self-contained Minecraft server that anyone on the internet can join —
no port forwarding, no router access, no public IP, and no paid hosting. It runs
entirely from this folder: **nothing is installed globally**.

Runs on Linux (x86_64, arm64/armv7), macOS, and Windows (WSL / Git Bash).
Tested on a phone running a Debian container (aarch64) behind carrier-grade NAT.

## What you get

- **Paper 26.2** server (Minecraft Java Edition, latest stable)
- **Public reachability** via a tunnel — friends connect from anywhere, not just LAN
- **Cross-platform**: Java Edition *and* Bedrock Edition players (phones, consoles,
  Windows 10/11) can all join the same world, via Geyser + Floodgate

## Quick start

```bash
./setup.sh     # downloads Paper, Java 25, and the tunnel clients (one time)
./start.sh     # starts the server + a public tunnel
```

`start.sh` prints a public address like `bore.pub:12345`. Share `host:port` with
your friends — they connect via *Multiplayer → Direct Connect*. That's it.

Stop it with `./stop.sh` (saves the world cleanly).

Prefer a mouse? After `setup.sh`, the same controls run in a browser:

```bash
python3 mc_tui.py --web     # serves http://127.0.0.1:8080 (start/stop/console/players)
```

It only listens on this machine, and closing it does not stop the server.

### From a completely raw machine

If the folder is a fresh checkout with nothing downloaded yet, `mctui` can take
it from zero to a running server on its own — the same logic `setup.sh` uses,
but driven from Python so it reports progress and is resumable:

```bash
python3 mc_tui.py --doctor      # what's present, what's missing (changes nothing)
python3 mc_tui.py --bootstrap   # download + configure everything into this folder
python3 mc_tui.py --check       # is this tree ready to host a server? exits non-zero if not
```

`--bootstrap` is idempotent: every artifact it finds on disk is reused, and the
large downloads retry and resume from where the connection dropped, so a flaky
link just makes it slower rather than restarting a 140 MB JDK from scratch. It
only writes inside this folder — no `pip`, no root, no system-wide installs. It
also writes the Geyser config for the playit tunnel (Bedrock on 19132,
proxy-protocol v2, `broadcast-port` = the tunnel's public port); see
[`docs/PORT_SETUP.md`](docs/PORT_SETUP.md).

`--check` reports each requirement individually (Python + curses, a writable
root, a Java runtime, the instance index, an active instance, the Paper jar,
tunnel binaries, the playit secret) and says what to do about any that are
missing. It never prints "all good" unless hosting would actually work — an
empty checkout imports fine but cannot run anything, so importing is not the
test.

## How "reachable from anywhere" works

Most home/mobile networks sit behind NAT or carrier-grade NAT, so you can't just
open a port. This project uses an **outbound tunnel** instead — the server reaches
out to a public relay, and players connect through it. No inbound port, no router
config, works on mobile data.

Two tunnels are bundled:

| Tunnel    | Account | Address            | Protocols      | Notes                          |
|-----------|---------|--------------------|----------------|--------------------------------|
| bore.pub  | none    | `bore.pub:<port>`  | TCP            | **Default.** Zero config. Port changes each start. |
| playit.gg | free    | persistent host:port | TCP **and UDP** | Better for Bedrock; one-time browser claim. |

**Live addresses on this host (playit.gg, verified):** hostnames redacted — this
repo is public; see `docs/PORT_SETUP.md` for how to get your own.

| Edition  | Address                          | Protocol | Status        |
|----------|----------------------------------|----------|---------------|
| Java     | `<your-tunnel>.tun.ply.gg:25565` | TCP      | ✅ verified — full Minecraft handshake from the public internet |
| Bedrock  | `<your-tunnel>.tun.ply.gg:19132` | UDP      | ✅ verified — mcstatus.io online + raw RakNet pong from the public internet |

Two separate tunnels are required on playit's free tier (a combined TCP+UDP
tunnel is a paid feature): one TCP tunnel for Java → `127.0.0.1:25565`, and one
UDP tunnel for Bedrock → `127.0.0.1:19132`. In the playit dashboard create the
Bedrock tunnel as type **Minecraft Bedrock**, destination `127.0.0.1:19132`,
with **proxy-protocol-v2** enabled. Geyser then listens on the default Bedrock
port **19132** and `broadcast-port` is set to the public port playit assigned,
so Bedrock clients are sent to the tunnel and not to the local port. See
[`docs/PORT_SETUP.md`](docs/PORT_SETUP.md) for the full walkthrough.

- **Java Edition** works over either tunnel (TCP).
- **Bedrock Edition** needs UDP, so use playit.gg for Bedrock players:
  ```bash
  TUNNEL=playit ./start.sh
  ```
  On first run it prints a one-time claim URL (e.g. `https://playit.gg/claim/xxxxx`).
  Open it in any browser, follow the prompts, then re-run the command. Playit then
  gives you a stable address that supports both Java and Bedrock.

## Connecting

- **Java Edition** (PC/Mac/Linux): Multiplayer → Direct Connect → the printed `host:port`
- **Bedrock Edition** (phone/console/Win10): the server speaks Bedrock via Geyser on
  UDP **19132**. Over the internet, add the playit host + the tunnel's public port
  in *Servers → Add Server*. On LAN, use this machine's local IP with port 19132.

## Bedrock players over the internet (one-time setup)

Java traffic is TCP, so the default `bore.pub` tunnel covers it. Bedrock is UDP, and
`bore` is TCP-only — so for Bedrock players use playit.gg, which tunnels both:

```bash
TUNNEL=playit ./start.sh
```

The agent connects and playit assigns you a persistent public host. Give Bedrock
players the playit host with the Bedrock port (the tunnel's public port, 19132 on
this host). Java players use the same host on the Java port.

This step can't be automated — the claim is intentionally an interactive browser
login that ties the agent to your account. It happens exactly once.

### Verified status of the two tunnels

- **Java** (`<your-tunnel>.tun.ply.gg:25565`, TCP): **verified working.** A full
  Minecraft handshake completes from the public internet and the server returns
  its MOTD and player slots.
- **Bedrock** (`<your-tunnel>.tun.ply.gg:19132`, UDP): **verified working.**
  mcstatus.io reports `online: true` (version 26.51 / MCPE), and a correctly
  formed RakNet Unconnected Ping from the open internet gets a 161-byte pong.
  Geyser listens on the default **UDP 19132**, which is where the playit
  Minecraft-Bedrock tunnel forwards; `broadcast-port` is set to the tunnel's
  public port so Bedrock clients are pointed at it. When playit assigns you a
  public Bedrock port, tell the manager once (diagnostics screen, `o`, or
  `POST /api/instances/settings` on the web API) and it rewrites
  `broadcast-port` for you. If you move Geyser to
  another port, set the tunnel destination to match and update `bedrock.port`
  + `broadcast-port` in `plugins/Geyser-Spigot/config.yml`. LAN Bedrock players
  use this machine's local IP on port **19132**.

The RakNet ping wire format (for re-testing) is:
`0x01` + 8-byte big-endian time + 16-byte MAGIC `00FFFF00FEFEFEFEFDFDFDFD12345678`
+ 8-byte GUID. Field order matters — magic does *not* come first.

## Files & folders

```
mc-server/
├── setup.sh         # downloads everything (idempotent)
├── start.sh         # starts server + tunnel (env: TUNNEL, XMS, XMX, SERVER_PORT)
├── stop.sh          # clean shutdown
├── webui/           # the frozen browser UI (served by mc_tui.py --web)
├── bin/             # bore + playit binaries (local, not on PATH)
├── jdk/current/     # Temurin JDK 25 (bundled, not system-wide)
├── server/          # Paper jar, world data, plugins (Geyser + Floodgate)
├── instances/       # extra servers, each self-identifying via .mctui-instance.json
├── data/            # tui_settings.json, roots.json, playit secret, console sockets
└── logs/            # server.log, tunnel.log, startup logs
```

## Environment variables (start.sh)

| Var          | Default | Purpose                                   |
|--------------|---------|-------------------------------------------|
| `TUNNEL`     | `bore`  | `bore` / `playit` / `none`                |
| `XMS`        | `512M`  | initial Java heap                          |
| `XMX`        | `768M`  | max Java heap (raise if you have RAM)      |
| `SERVER_PORT`| `25565` | local Java port                            |

## Keeping a public server safe

The tunnel address is public — anyone who has it can join. To restrict access:

1. **Enable the whitelist** (in `server/server.properties`): `white-list=true`,
   then add players from the server console: `whitelist add <username>` (the
   `console` screen or the browser console, or `/api/console` on the web API)
2. Set `online-mode=false` **only** if you understand the impersonation risk; with
   it `true`, players must authenticate with a real Minecraft account.
3. `enable-query=false` and `enable-rcon=false` are already set.

When you edit `server.properties` through the config editor, keys that vanilla
Paper only reads at startup (the port, `online-mode`, `level-type`, …) are
labelled *needs restart* before you commit, and the save message says so again
if the server is running at the time.

## Notes & caveats

- **Paper 26.2 requires Java 25** — that's why a JDK 25 is bundled rather than
  relying on a system Java.
- **RAM**: default heap is 512–768 MB, sized for small hosts. Raise `XMX` on a
  real PC. Player view/simulation distances are already reduced in
  `server/server.properties` and Paper's config.
- **bore.pub ports are ephemeral**: the port changes every time you restart. For a
  stable address, use playit.gg (`TUNNEL=playit`).
- Tunnel relays are operated by third parties (bore / playit). For a private world
  with only trusted friends, also consider a VPN mesh (Tailscale, ZeroTier).

## Cost

$0. All components are free: Paper, Temurin JDK, bore.pub, and playit.gg's free tier.

## TUI — `mc_tui.py`

A curses front-end for everything above, written with **Python stdlib only**
(no pip, no root, works in Termux/Debian proot).

```
python3 mc_tui.py                 # dashboard
python3 mc_tui.py --screen logs    # start on a specific screen
python3 mc_tui.py --check          # can this tree host a server? (no terminal needed)
python3 mc_tui.py --doctor         # check this machine, change nothing
python3 mc_tui.py --bootstrap      # install everything from zero, resumable
python3 mc_tui.py --web            # browser UI + API instead of the terminal UI
```

| Screen        | What it does |
|---------------|--------------|
| `dashboard`   | live status (server/playitd/tunnel/disk), menu, quick ping |
| `control`     | start / stop / force-kill / clear stale pid, playitd + tunnel toggles, heap, recent log |
| `console`     | the live server console: type commands (`say`, `whitelist add …`), they go straight to the server's stdin |
| `create`      | 9-step wizard: id → display name → install location → Paper build → memory preset → gameplay → network → plugins → review |
| `instances`   | list / activate / clone / rename / delete, change Paper version |
| `players`     | online list, whitelist, ops, bans (add/remove, toggle whitelist) |
| `logs`        | every log file, live tail, filter, snapshot, clear |
| `backup`      | create / restore / delete / purge, free-space + >50 % confirm |
| `diag`        | host + java + process report, tunnel-port sync, optional network probes (status API, RakNet, playit IPC) |
| `config`      | edit `server.properties`, Geyser `config.yml`, view `eula.txt` |
| `settings`    | `data/tui_settings.json` (heap, ports, tunnel, active instance, java override) |

Keys: `↑↓/jk` move · `⏎` open/select · `←→` back/next (wizard) · `1-9` jump ·
`/` filter (logs) · `t` follow (logs) · `q` back · `?` help · `Ctrl-C` quit.

**What it changes.** Only these paths: `data/tui_settings.json` (+`.bak`),
`data/roots.json` (the list of folders searched for instances),
`data/console-<instance>.{sock,pid,history}`, `instances/*`, `backups/*`,
`logs/*`, `plugins/*` of the active instance, and `instances/active`. Every
config write goes through `mctui/core/config.py`, which keeps a `.bak` next to
the original.

**What it does not touch.** `start.sh`, `stop.sh`, `watch-tunnel.sh`,
`setup.sh`, the bundled JDK layout, or the playit secret.

**Launching the server.** From *server control* the TUI spawns Java itself with
the same Aikar flags as `start.sh` and writes `logs/server.pid` /
`logs/<instance>.log`. `start.sh` keeps working unchanged — both paths write
the same pid file, so `stop.sh` and `watch-tunnel.sh` still behave.
`settings/active_instance` (+ the `instances/active` symlink) tells *you* which
instance is current; `start.sh` continues to launch `server/` unless you export
`TUNNEL`/`XMS` yourself.

**Quitting never stops the server.** The server runs in its own process group,
so closing the TUI (or the browser UI, or the SSH session it was started from)
leaves it running and your players connected. Only an explicit *stop*
(the TUI's stop action, `./stop.sh`, or a `SIGTERM` to the pid in
`logs/server.pid`) saves the world and shuts it down. The console keeps working
after you quit too: the server's stdin is held by a small detached relay
(`data/console-<instance>.sock` + `.pid`), so a later TUI or browser session
reconnects and keeps typing. When the server exits, the relay notices and
removes the socket itself — nothing is left behind.

**Tests.** `python3 tests/test_*.py` — foundation/config, processes, network +
probes, versions/downloads, a flaky-link download test (retry + HTTP-range
resume against a local stdlib server), logs/backups/instances/players, the
console relay (commands reach a fake server end to end and the socket is
cleaned up on stop), the web backend (every endpoint the browser UI uses,
including the SSE stream, against an isolated tree), and a pty-driven smoke
test that walks every screen plus the create wizard (metadata only, it stops
before any jar download). Every test runs against a throwaway tree via
`tests/mctui_test_env.py` (`MCTUI_ROOT`), never the live checkout.

## Browser UI — `--web`

A second front-end for the same manager, served from this folder with the
Python standard library only (`http.server`, no framework, no build step):

```bash
python3 mc_tui.py --web                    # http://127.0.0.1:8080
python3 mc_tui.py --web --web-port 9000    # pick a port
```

It serves the frozen single-file page in `webui/index.html` and the JSON API it
talks to: status, instances, start/stop/kill, the console, players and bans,
backups, tunnels, jobs, and an SSE stream (`/api/events`) that pushes status,
log lines, player changes and job progress to the browser. Open it with
`?mock=1` to click through the whole UI against a built-in dataset, with no
server and no network — it is the fastest way to see what the UI does.

The server binds to **127.0.0.1 only** on purpose: the page can send console
commands to your server, so it must not be public. `--web-host 0.0.0.0` is
refused unless you set `MCTUI_WEB_ALLOW_PUBLIC=1`, and even then it warns.

### Assumptions & limitations

- Offline-mode accounts are assumed for player lists (the bundled Geyser setup
  uses `java.auth-type: offline`); whitelist/ops/ban edits are written while the
  server may be running — restart it (or `reload`) to apply.
- Changing `server_port` / `bedrock_port` in settings only affects future
  launches and the tunnel's local target; `server.properties` is rewritten to
  match at every start, so the properties file and the tunnel can never drift
  apart and forward to a port nothing is listening on.
- The create wizard needs network for Paper metadata + plugin resolution; a
  build fails without it (no offline mirror cache yet).
- Backups are `tar.gz` of the whole instance folder; restoring while the server
  is running is refused.
- Force-kill (`k`) is SIGKILL: the world keeps the last autosave only.
- Screen sizes below ~40×16 are not usable; the layout is built for a terminal
  of at least 80×24. The browser UI has no such constraint.
- The web UI is not authenticated. It binds to 127.0.0.1 for that reason; do
  not expose it to a network you do not trust.
