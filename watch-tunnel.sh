#!/usr/bin/env bash
# Keep the public tunnel alive. Restarts it if it dies.
# Usage: ./watch-tunnel.sh [interval_seconds]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
BIN_DIR="$SCRIPT_DIR/bin"
SERVER_PORT="${SERVER_PORT:-25565}"
BEDROCK_PORT="${BEDROCK_PORT:-19132}"
INTERVAL="${1:-20}"

echo "Watching tunnel (checking every ${INTERVAL}s). Ctrl-C to stop."

while true; do
  if [ -f "$LOG_DIR/tunnel.pid" ]; then
    PID="$(cat "$LOG_DIR/tunnel.pid" 2>/dev/null || true)"
    if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
      # tunnel alive; also make sure the server is alive
      if [ -f "$LOG_DIR/server.pid" ]; then
        SPID="$(cat "$LOG_DIR/server.pid" 2>/dev/null || true)"
        if [ -n "${SPID:-}" ] && ! kill -0 "$SPID" 2>/dev/null; then
          echo "$(date +%H:%M:%S) server died - restarting everything"
          "$SCRIPT_DIR/start.sh" || true
        fi
      fi
      sleep "$INTERVAL"
      continue
    fi
  fi
  echo "$(date +%H:%M:%S) tunnel down - restarting bore.pub"
  if [ -x "$BIN_DIR/bore-bin" ]; then
    "$BIN_DIR/bore-bin" local "$SERVER_PORT" --to bore.pub > "$LOG_DIR/tunnel.log" 2>&1 &
    echo $! > "$LOG_DIR/tunnel.pid"
    sleep 3
    grep -oE "listening at [^ ]+" "$LOG_DIR/tunnel.log" 2>/dev/null | tail -n1 || true
  fi
  sleep "$INTERVAL"
done
