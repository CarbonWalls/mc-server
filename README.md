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
UDP tunnel for Bedrock → `127.0.0.1:44041`. Geyser's `bedrock.port` is set to
**44041** to match that tunnel's local destination port.

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
  UDP **44041** (matching the playit tunnel destination). Over the internet, add the
  playit host + port 44041 in *Servers → Add Server*. On LAN, use this machine's
  local IP with port 44041.

## Bedrock players over the internet (one-time setup)

Java traffic is TCP, so the default `bore.pub` tunnel covers it. Bedrock is UDP, and
`bore` is TCP-only — so for Bedrock players use playit.gg, which tunnels both:

```bash
TUNNEL=playit ./start.sh
```

The agent connects and playit assigns you a persistent public host. Give Bedrock
players the playit host with the Bedrock port (44041 on this host, matching the
UDP tunnel's local destination). Java players use the same host on the Java port.

This step can't be automated — the claim is intentionally an interactive browser
login that ties the agent to your account. It happens exactly once.

### Verified status of the two tunnels

- **Java** (`<your-tunnel>.tun.ply.gg:25565`, TCP): **verified working.** A full
  Minecraft handshake completes from the public internet and the server returns
  its MOTD and player slots.
- **Bedrock** (`<your-tunnel>.tun.ply.gg:19132`, UDP): **verified working.**
  mcstatus.io reports `online: true` (version 26.51 / MCPE), and a correctly
  formed RakNet Unconnected Ping from the open internet gets a 161-byte pong.
  Geyser listens on **UDP 44041** (not 19132) so it matches the playit tunnel's
  local destination port — if you change the tunnel, change `bedrock.port` in
  `plugins/Geyser-Spigot/config.yml` to match. LAN Bedrock players must use
  port **44041** (not the default 19132).

The RakNet ping wire format (for re-testing) is:
`0x01` + 8-byte big-endian time + 16-byte MAGIC `00FFFF00FEFEFEFEFDFDFDFD12345678`
+ 8-byte GUID. Field order matters — magic does *not* come first.

## Files & folders

```
mc-server/
├── setup.sh         # downloads everything (idempotent)
├── start.sh         # starts server + tunnel (env: TUNNEL, XMS, XMX, SERVER_PORT)
├── stop.sh          # clean shutdown
├── bin/             # bore + playit binaries (local, not on PATH)
├── jdk/current/     # Temurin JDK 25 (bundled, not system-wide)
├── server/          # Paper jar, world data, plugins (Geyser + Floodgate)
├── data/            # tunnel state (playit secret, mock listener)
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
   then add players from the server console: `whitelist add <username>`
2. Set `online-mode=false` **only** if you understand the impersonation risk; with
   it `true`, players must authenticate with a real Minecraft account.
3. `enable-query=false` and `enable-rcon=false` are already set.

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
python3 mc_tui.py --check          # import every module (no terminal needed)
```

| Screen        | What it does |
|---------------|--------------|
| `dashboard`   | live status (server/playitd/tunnel/disk), menu, quick ping |
| `control`     | start / stop / force-kill / clear stale pid, playitd + tunnel toggles, heap, recent log |
| `create`      | 8-step wizard: id → Paper version → build → memory preset → gameplay → network → plugins → review → build |
| `instances`   | list / activate / clone / rename / delete, change Paper version |
| `players`     | online list, whitelist, ops, bans (add/remove, toggle whitelist) |
| `logs`        | every log file, live tail, filter, snapshot, clear |
| `backup`      | create / restore / delete / purge, free-space + >50 % confirm |
| `diag`        | host + java + process report, optional network probes (status API, RakNet, playit IPC) |
| `config`      | edit `server.properties`, Geyser `config.yml`, view `eula.txt` |
| `settings`    | `data/tui_settings.json` (heap, ports, tunnel, active instance, java override) |

Keys: `↑↓/jk` move · `⏎` open/select · `←→` back/next (wizard) · `1-9` jump ·
`/` filter (logs) · `t` follow (logs) · `q` back · `?` help · `Ctrl-C` quit.

**What it changes.** Only these paths: `data/tui_settings.json` (+`.bak`),
`instances/*`, `backups/*`, `logs/*`, `plugins/*` of the active instance, and
`instances/active`. Every file write goes through `mctui/core/config.py`,
which keeps a `.bak` next to the original.

**What it does not touch.** `start.sh`, `stop.sh`, `watch-tunnel.sh`,
`setup.sh`, the bundled JDK layout, or the playit secret.

**Launching the server.** From *server control* the TUI spawns Java itself with
the same Aikar flags as `start.sh` and writes `logs/server.pid` /
`logs/<instance>.log`. `start.sh` keeps working unchanged — both paths write
the same pid file, so `stop.sh` and `watch-tunnel.sh` still behave.
`settings/active_instance` (+ the `instances/active` symlink) tells *you* which
instance is current; `start.sh` continues to launch `server/` unless you export
`TUNNEL`/`XMS` yourself.

**Tests.** `python3 tests/test_*.py` — foundation/config, processes, network +
probes, versions/downloads, logs/backups/instances/players, and a pty-driven
smoke test that walks every screen plus the create wizard (metadata only, it
stops before any jar download).

### Assumptions & limitations

- Offline-mode accounts are assumed for player lists (the bundled Geyser setup
  uses `java.auth-type: offline`); whitelist/ops/ban edits are written while the
  server may be running — restart it (or `reload`) to apply.
- Changing `server_port` / `bedrock_port` in settings only affects future
  launches and the tunnel's local target; `server/server.properties` must match.
- The create wizard needs network for Paper metadata + plugin resolution; a
  build fails without it (no offline mirror cache yet).
- Backups are `tar.gz` of the whole instance folder; restoring while the server
  is running is refused.
- Force-kill (`k`) is SIGKILL: the world keeps the last autosave only.
- Screen sizes below ~40×16 are not usable; the layout is built for a terminal
  of at least 80×24.
