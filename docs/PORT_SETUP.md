# Port setup — making your server reachable

This guide explains, in plain language, which ports this project uses, how to
make them reachable from the public internet **without port forwarding or a
public IP**, and how to let Bedrock players in.

If you just want it working: run `./setup.sh && ./start.sh` and skip to
[Connecting](#connecting). Read this when something does not connect, or when
you want Bedrock players to join.

---

## The 30-second version

| Edition | Local port | Protocol | Who connects on it |
|---------|-----------|----------|--------------------|
| Java Edition | `25565` | TCP | PC/Mac/Linux players |
| Bedrock Edition | `19132` | UDP | phone/console/Windows 10 players |

Two different **protocols** — that single detail causes most of the confusion
below. TCP is what Java Edition speaks; UDP is what Bedrock Edition speaks.
A tunnel that only carries TCP can never reach Bedrock players.

Nothing on this machine is exposed directly to the internet. Both ports are
reached through an outbound **tunnel** instead, so it works behind NAT,
carrier-grade NAT, mobile data, hotel Wi-Fi and anywhere else you cannot open
a router port.

---

## How "reachable from anywhere" works

Most home and mobile networks sit behind NAT: your machine has a private
address, so no one on the internet can dial it directly. Opening a router port
is often impossible (CGNAT, a locked-down router, a phone hotspot).

This project flips the direction. Your server **calls out** to a public relay,
and players connect through that relay. There is no inbound connection to
configure, which is exactly why it works on a phone in a Debian container.

Two relays are bundled:

| Relay | Account | Address | Protocols | Notes |
|-------|---------|---------|-----------|-------|
| `bore.pub` | none | `bore.pub:<port>` | TCP only | **Default.** Zero config. Port changes each start. |
| `playit.gg` | free | persistent host:port | TCP **and UDP** | Needed for Bedrock; one-time browser claim. |

Use `bore.pub` for a quick Java-only session with friends. Use `playit.gg`
when you want a stable address, or when **Bedrock** players need to join —
Bedrock needs UDP and `bore` cannot carry it.

---

## Java Edition players (the easy case)

Java Edition speaks TCP, so the default `bore.pub` tunnel is enough.

```bash
./start.sh
```

The last lines print something like:

```
 PUBLIC ADDRESS (share with friends - works from anywhere):
   bore.pub:43217
```

Share that `host:port`. Players use *Multiplayer → Direct Connect →*
`bore.pub:43217` and appear in your world.

**Caveat:** the `bore.pub` port is ephemeral — it changes every time you
restart the server. For an address that survives a reboot, use playit.gg.

### What if a Java player is on your LAN?

They can skip the tunnel entirely and connect to this machine's local IP on
`25565`. Find it with:

```bash
hostname -I          # Linux: first address is usually the right one
ipconfig             # Windows (WSL: use the host's IP)
```

---

## Bedrock players (needs UDP — use playit.gg)

Bedrock Edition speaks UDP. `bore.pub` only tunnels TCP, so Bedrock players
cannot use it. You need `playit.gg`, which tunnels both.

### Step 1 — start with the playit tunnel

```bash
TUNNEL=playit ./start.sh
```

On the very first run it prints a one-time claim URL:

```
 ONE-TIME SETUP: open this URL in any browser and follow the
 prompts to claim this agent (free, no payment):

   https://playit.gg/claim/abc123def456
```

Open it on any device, log in, confirm the agent, add it. This happens exactly
once and cannot be automated by design — it ties the agent to your account.

Then re-run `TUNNEL=playit ./start.sh`. Playit assigns you a persistent
address, for example `<your-tunnel>.tun.ply.gg`.

> **This project never prints your real tunnel address**, because the files are
> public. Read it from the playit dashboard (or the claim page) instead.

### Step 2 — create the tunnels in the playit dashboard

The free tier cannot combine TCP and UDP on one tunnel, so create **two**:

1. Log in at <https://playit.gg>, open **Agents**, choose your agent, then
   **Tunnels → Add Tunnel**.
2. **Tunnel 1 — Java (TCP)**
   - Type: `Minecraft Java`
   - Local destination: `127.0.0.1` port `25565`
3. **Tunnel 2 — Bedrock (UDP)**
   - Type: `Minecraft Bedrock`
   - Local destination: `127.0.0.1` port `19132`
   - **Proxy Protocol: `proxy-protocol-v2`** ← required, see below
4. Note the **public port** each tunnel is assigned.

The local destination port must match what the server actually listens on.
This project uses the Minecraft defaults — `25565` for Java and `19132` for
Bedrock — so leave them alone unless you changed something.

### Step 3 — give players the address

- **Java players:** `<your-tunnel>.tun.ply.gg` + the Java tunnel's public port,
  via *Multiplayer → Direct Connect*.
- **Bedrock players:** *Servers → Add Server* → the playit host + the **Bedrock
  tunnel's public port**.

Bedrock players on your **LAN** instead use this machine's local IP with port
`19132` — no tunnel needed.

---

## The Geyser settings, and why they are what they are

Geyser is the bridge that lets Bedrock players join a Java world. Its config
lives at `server/plugins/Geyser-Spigot/config.yml` (for the main install) or
`instances/<name>/plugins/Geyser-Spigot/config.yml` (for a TUI-created
instance). Four settings matter:

```yaml
bedrock:
  port: 19132                    # the local UDP port Geyser listens on
  clone-remote-port: false       # must stay false
advanced:
  bedrock:
    broadcast-port: 19132        # the public port playit assigned
    use-haproxy-protocol: true   # must be true with playit
```

What each one does:

- **`bedrock.port: 19132`** — where Geyser listens for Bedrock connections.
  This is the port the playit Bedrock tunnel forwards to, so the two must
  match. Keep the default unless you run a second Geyser on the same machine.

- **`clone-remote-port: false`** — when this is `true`, Geyser copies the Java
  port onto the Bedrock port on every start. That would silently move Bedrock
  to `25565` and break the setup, so leave it `false`.

- **`broadcast-port: 19132`** — the port Geyser advertises to Bedrock clients
  in its MOTD. This is the **public** port playit assigned the Bedrock tunnel,
  *not* the local one, because clients connect from the internet. Set it to
  the tunnel's public port. A value of `0` advertises `bedrock.port`, which is
  right only when the two are the same.

- **`use-haproxy-protocol: true`** — playit forwards traffic with
  proxy-protocol v2. With this enabled, Geyser sees each player's **real**
  address instead of the relay's, so bans, whitelist logs and
  `/seen` all work correctly. It must match the **Proxy Protocol** setting on
  the Bedrock tunnel in the playit dashboard: both on, or both off.

The `mctui` doctor checks all four for you:

```bash
python3 mc_tui.py --doctor
```

If you moved a port, the doctor says exactly which value is wrong; the config
editor screen (`python3 mc_tui.py --screen config`) edits the same file with a
`.bak` kept next to it.

---

## Changing the ports

Do not change ports unless one is already in use on this machine. If you must:

1. Pick new values, say `25570` (Java) and `19140` (Bedrock).
2. **Java:** set `server-port` in `server/server.properties`, and export
   `SERVER_PORT=25570` (or change it in the TUI *settings* screen) so the
   tunnel targets the new port.
3. **Bedrock:** set `bedrock.port` in the Geyser config to `19140`, then update
   the playit Bedrock tunnel's local destination to `127.0.0.1:19140`, and set
   `broadcast-port` to the tunnel's public port.
4. Update the ports in `mctui` settings so the TUI's diagnostics ping the
   right place: `python3 mc_tui.py --screen settings`.
5. Restart the server and re-run `--doctor`.

The two editions use separate ports and separate tunnels, so changing one
never affects the other.

---

## It does not connect — checklist

Work through it in order; the cause is almost always one of these.

**Server-side first**

- *Is the server actually up?* `python3 mc_tui.py --screen dashboard` shows the
  status, or `tail -f logs/server.log` — look for a line ending in `Done (`.

- *Is the tunnel up?* Check `logs/tunnel.log`. Bore prints `listening at`;
  playit prints the tunnel address. Restart with `./start.sh` if it died.

- *Are you on the same network as a player?* Test from a phone on mobile data,
  not from the same Wi-Fi as the server.

- *Did you claim playit?* If `data/playit.toml` is missing, `TUNNEL=playit
  ./start.sh` prints the claim URL again. You only need to do it once.

**Bedrock-specific**

- *Using `bore` for Bedrock?* It cannot work — bore is TCP-only and Bedrock is
  UDP. Switch to `TUNNEL=playit`.

- *`clone-remote-port` still true?* Geyser would have moved Bedrock onto the
  Java port. Set it to `false` and restart.

- *Wrong `broadcast-port`?* Bedrock shows in the server list but fails to
  connect. It must be the **tunnel's public port**, not `19132`-the-local-one.

- *Proxy protocol mismatch?* If the playit tunnel has proxy-protocol v2 on but
  Geyser has `use-haproxy-protocol: false` (or the reverse), Bedrock players
  get stuck on *locating server*. Make both the same.

- *Bedrock version too new?* Geyser supports a specific Bedrock version range;
  check `notify-on-new-bedrock-update` in the console and the version on
  <https://geysermc.org>.

**Still stuck**

Run the diagnostics and read what they say:

```bash
python3 mc_tui.py --doctor
python3 mc_tui.py --screen diag     # probes: java ping, raknet ping, status APIs
```

The *raknet ping* probe is the authoritative Bedrock test: if it answers
locally, Geyser is listening, and the problem is the tunnel or the
`broadcast-port`.

---

## Quick reference

```bash
./setup.sh                        # one time: paper, java 25, tunnels
./start.sh                        # server + bore.pub (Java only)
TUNNEL=playit ./start.sh          # server + playit (Java AND Bedrock)
TUNNEL=none ./start.sh            # LAN only, no tunnel
./stop.sh                         # clean shutdown, saves the world

python3 mc_tui.py --doctor        # read-only health check incl. geyser config
python3 mc_tui.py --bootstrap     # from-zero install, resumable
python3 mc_tui.py                 # the dashboard
```

| File | Holds |
|------|-------|
| `server/server.properties` | the Java port (`server-port`) |
| `server/plugins/Geyser-Spigot/config.yml` | the Bedrock port and the four settings above |
| `data/tui_settings.json` | the ports the TUI remembers and probes |
| `data/playit.toml` | the playit agent secret — **never share, never commit** |

The playit secret is git-ignored on purpose. If it leaks, revoke the agent in
the playit dashboard and re-claim a new one.
