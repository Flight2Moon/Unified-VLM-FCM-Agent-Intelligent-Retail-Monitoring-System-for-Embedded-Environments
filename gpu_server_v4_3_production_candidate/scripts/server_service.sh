#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
PROFILE="${2:-${EAGER_RUNTIME_PROFILE:-low_vram}}"
PID_FILE="storage/eager_server.pid"
LOG_DIR="storage/logs"
LOG_FILE="$LOG_DIR/server_stdout.log"
mkdir -p "$LOG_DIR" storage/events storage/cache storage/datasets storage/model_registry

start() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Already running pid=$(cat "$PID_FILE")"
    exit 0
  fi
  echo "Starting EAGER GPU Server profile=$PROFILE"
  nohup ./run_server.sh "$PROFILE" >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  echo "Started pid=$(cat "$PID_FILE") log=$LOG_FILE"
}
stop() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Stopping pid=$(cat "$PID_FILE")"
    kill "$(cat "$PID_FILE")" || true
    sleep 1
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then kill -9 "$(cat "$PID_FILE")" || true; fi
  fi
  rm -f "$PID_FILE"
}
status() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then echo "RUNNING pid=$(cat "$PID_FILE")"; else echo "STOPPED"; fi
}
logs() { touch "$LOG_FILE"; tail -n 200 -f "$LOG_FILE"; }
health() { curl -s http://127.0.0.1:8008/health | python3 -m json.tool; }
case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  logs) logs ;;
  health) health ;;
  *) echo "Usage: $0 {start|stop|restart|status|logs|health} [cpu|cuda|metal|low_vram]"; exit 1 ;;
esac
