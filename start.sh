#!/usr/bin/env bash
# Start the Minecraft server and expose it on the public internet.
#
# Tunnels (no router port forwarding needed, works behind CGNAT/carrier NAT):
#   * bore.pub  - default, zero config, no account. Gives bore.pub:<RANDOM PORT>
#   * playit.gg - optional, needs a one-time browser claim; gives a persistent
#                 address AND supports UDP (needed for Bedrock players).
#
# Usage:
#   ./start.sh                 # server + bore.pub tunnel
#   TUNNEL=playit ./start.sh   # server + playit.gg tunnel
#   TUNNEL=none ./start.sh     # server only (LAN play)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SERVER_DIR="$SCRIPT_DIR/server"
JDK_DIR="$SCRIPT_DIR/jdk/current"
BIN_DIR="$SCRIPT_DIR/bin"
LOG_DIR="$SCRIPT_DIR/logs"
DATA_DIR="$SCRIPT_DIR/data"

# JVM heap. Tune for your machine.
XMS="${XMS:-512M}"
XMX="${XMX:-768M}"
SERVER_PORT="${SERVER_PORT:-25565}"
TUNNEL="${TUNNEL:-bore}"

mkdir -p "$LOG_DIR" "$DATA_DIR"

# --- Java ---------------------------------------------------------------
if [ ! -x "$JDK_DIR/bin/java" ]; then
  echo "ERROR: bundled JDK not found at $JDK_DIR - run ./setup.sh first"
  exit 1
fi
JAVA="$JDK_DIR/bin/java"
echo "Using Java: $($JAVA -version 2>&1 | head -1)"

# --- EULA ---------------------------------------------------------------
mkdir -p "$SERVER_DIR"
if [ ! -f "$SERVER_DIR/eula.txt" ]; then
  echo "Accepting Mojang EULA (https://aka.ms/MinecraftEULA) ..."
  printf 'eula=true\n' > "$SERVER_DIR/eula.txt"
fi

# --- stop anything already running --------------------------------------
if [ -x "$SCRIPT_DIR/stop.sh" ]; then "$SCRIPT_DIR/stop.sh" || true; fi

# --- start server -------------------------------------------------------
echo "Starting Paper server on port $SERVER_PORT (heap ${XMS}-${XMX}) ..."
cd "$SERVER_DIR"
"$JAVA" -Xms"$XMS" -Xmx"$XMX" \
  -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 \
  -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC \
  -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 \
  -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 \
  -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 \
  -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 \
  -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1 \
  -Dusing.aikars.flags=https://mcflags.emc.gs -Daikars.new.flags=true \
  -jar "$SERVER_DIR/paper.jar" nogui \
  > "$LOG_DIR/server.log" 2>&1 &

SERVER_PID=$!
echo "$SERVER_PID" > "$LOG_DIR/server.pid"
echo "Server PID: $SERVER_PID"

echo "Waiting for world load (can take ~1 min on first start) ..."
for _ in $(seq 1 240); do
  if grep -q "Done (" "$LOG_DIR/server.log" 2>/dev/null; then echo "Server ready."; break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "ERROR: server exited early. Last 30 log lines:"; tail -n 30 "$LOG_DIR/server.log" || true; exit 1
  fi
  sleep 2
done

# --- start tunnel -------------------------------------------------------
start_bore() {
  if [ ! -x "$BIN_DIR/bore-bin" ]; then echo "bore binary missing - skipping tunnel"; return 1; fi
  echo "Starting bore.pub tunnel (no account needed) ..." >&2
  "$BIN_DIR/bore-bin" local "$SERVER_PORT" --to bore.pub > "$LOG_DIR/tunnel.log" 2>&1 &
  local pid=$!; echo "$pid" > "$LOG_DIR/tunnel.pid"
  # wait for the "listening at" line
  for _ in $(seq 1 30); do
    grep -q "listening at" "$LOG_DIR/tunnel.log" 2>/dev/null && break
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  grep -oE "listening at [^ ]+" "$LOG_DIR/tunnel.log" 2>/dev/null | tail -n1 | sed 's/listening at //'
}

start_playit() {
  local SOCK="$DATA_DIR/playit.sock" SECRET="$DATA_DIR/playit.toml"
  if [ ! -x "$BIN_DIR/playitd" ] || [ ! -x "$BIN_DIR/playit" ]; then
    echo "playit binaries missing - falling back to bore"; start_bore; return
  fi
  if [ ! -f "$SECRET" ]; then
    echo "playit not claimed yet. Starting daemon and generating a claim URL ..."
    "$BIN_DIR/playitd" --socket-path "$SOCK" --secret-path "$SECRET" > "$LOG_DIR/playitd.log" 2>&1 &
    echo $! > "$LOG_DIR/playitd.pid"
    sleep 3
    local code
    code="$("$BIN_DIR/playit" --socket-path "$SOCK" claim generate 2>/dev/null || true)"
    echo
    echo "*****************************************************************"
    echo " ONE-TIME SETUP: open this URL in any browser and follow the"
    echo " prompts to claim this agent (free, no payment):"
    echo
    echo "   https://playit.gg/claim/$code"
    echo
    echo " Then rerun: TUNNEL=playit ./start.sh"
    echo "*****************************************************************"
    echo "(bore.pub fallback not started - server is LAN-only until claimed)"
    return 0
  fi
  echo "Starting playit.gg tunnel (already claimed) ..."
  "$BIN_DIR/playitd" --socket-path "$SOCK" --secret-path "$SECRET" > "$LOG_DIR/playitd.log" 2>&1 &
  echo $! > "$LOG_DIR/playitd.pid"
  "$BIN_DIR/playit" --socket-path "$SOCK" --stdout attach > "$LOG_DIR/tunnel.log" 2>&1 &
  echo $! > "$LOG_DIR/tunnel.pid"
  sleep 5
  tail -n 20 "$LOG_DIR/tunnel.log" 2>/dev/null || true
}

case "$TUNNEL" in
  bore|"" ) PUB="$(start_bore)" ;;
  playit ) start_playit ;;
  none ) PUB="" ;;
  *) echo "Unknown TUNNEL=$TUNNEL (use bore|playit|none)"; PUB="" ;;
esac

echo
echo "======================================================================"
echo " Minecraft server is running."
echo
if [ -n "${PUB:-}" ]; then
  echo " PUBLIC ADDRESS (share with friends - works from anywhere):"
  echo "   ${PUB#listening at }"
  echo
  echo " Java Edition: Multiplayer -> Direct Connect -> enter that host:port"
else
  echo " Tunnel: see tunnel.log / claim instructions above."
fi
echo
echo " LAN players can also connect to this machine's local IP:$SERVER_PORT"
echo " Stop: ./stop.sh    Logs: logs/server.log"
echo "======================================================================"
