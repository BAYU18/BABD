#!/usr/bin/env bash
# ops/deploy/monitor.sh — lightweight uptime monitor for the 2D car game server.
#
# Runs the healthcheck on an interval, appends a timestamped line to a log, and
# rings the bell (non-zero exit + loud line) after N consecutive failures.
#
# Designed to be run either:
#   * in the foreground for a quick soak:   ops/deploy/monitor.sh
#   * as a systemd timer/service:           see ops/deploy/monitor.md
#   * from cron:                            */2 * * * * ops/deploy/monitor.sh --once
#
# Options:
#   --once            run one check and exit (0 healthy, 1 unhealthy)
#   --interval N      seconds between checks (default 30)
#   --fail-threshold N  consecutive failures before declaring DOWN (default 3)
#   --log FILE        log file (default /home/serverbot/aidev/logs/monitor.log)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTERVAL=30
THRESHOLD=3
LOG="/home/serverbot/aidev/logs/monitor.log"
ONCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --once) ONCE=1; shift ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --fail-threshold) THRESHOLD="$2"; shift 2 ;;
    --log) LOG="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$(dirname "$LOG")"

run_check() {
  # Capture the healthcheck's full output so the log shows WHICH check failed.
  local out code
  out="$("${HERE}/healthcheck.sh" 2>&1)"; code=$?
  local status="UP"
  [ "$code" -ne 0 ] && status="DOWN"
  printf '%s  %-4s  %s\n' "$(date -Is)" "$status" "$(echo "$out" | tail -1)" >> "$LOG"
  if [ "$code" -ne 0 ]; then
    # Dump the per-check detail only when failing, keeps the log small.
    printf '%s  detail:\n%s\n' "$(date -Is)" "$out" >> "$LOG"
  fi
  return $code
}

if [ "$ONCE" -eq 1 ]; then
  run_check
  exit $?
fi

consecutive=0
echo "monitor started: interval=${INTERVAL}s threshold=${THRESHOLD} log=${LOG}"
while true; do
  if run_check; then
    if [ "$consecutive" -ge "$THRESHOLD" ]; then
      printf '%s  RECOVERED after %d failed checks\n' "$(date -Is)" "$consecutive" >> "$LOG"
      echo "$(date -Is) RECOVERED"
    fi
    consecutive=0
  else
    consecutive=$((consecutive + 1))
    echo "$(date -Is) FAILED (${consecutive}/${THRESHOLD})"
    if [ "$consecutive" -eq "$THRESHOLD" ]; then
      printf '%s  ALERT: server DOWN for %d consecutive checks (threshold %d) — 192.168.0.222:8080\n' \
        "$(date -Is)" "$consecutive" "$THRESHOLD" >> "$LOG"
      echo "$(date -Is) *** ALERT: 2D car game server DOWN (192.168.0.222:8080) ***"
    fi
  fi
  sleep "$INTERVAL"
done
