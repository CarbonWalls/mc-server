#!/usr/bin/env bash
# Stop the Minecraft server and the playit tunnel cleanly.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

stopped_any=0

# --- Stop the tunnel first -------------------------------------------------
if [ -f "$LOG_DIR/playit.pid" ]; then
  PID="$(cat "$LOG_DIR/playit.pid" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    echo "Stopping playit tunnel (PID $PID)..."
    kill "$PID" 2>/dev/null || true
    stopped_any=1
  fi
  rm -f "$LOG_DIR/playit.pid"
fi

# --- Gracefully stop the server via RCON-less shutdown ---------------------
# Paper/Bukkit have no built-in remote console on vanilla, so we send the
# JVM a SIGTERM. Paper installs a shutdown hook that saves the world.
if [ -f "$LOG_DIR/server.pid" ]; then
  PID="$(cat "$LOG_DIR/server.pid" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    echo "Stopping Minecraft server (PID $PID)..."
    kill -TERM "$PID" 2>/dev/null || true
    stopped_any=1
    # Wait up to 60s for a clean save
    for i in $(seq 1 60); do
      kill -0 "$PID" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$PID" 2>/dev/null; then
      echo "Server did not exit in time, forcing..."
      kill -KILL "$PID" 2>/dev/null || true
    fi
  fi
  rm -f "$LOG_DIR/server.pid"
fi

if [ "$stopped_any" -eq 1 ]; then
  echo "Stopped."
else
  echo "No running server or tunnel found."
fi
