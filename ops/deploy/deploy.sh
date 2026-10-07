#!/usr/bin/env bash
# ops/deploy/deploy.sh — install/restart the 2D car game server. Idempotent.
#
# Usage:  sudo ops/deploy/deploy.sh
#
# What it does:
#   1. sanity-check the artifact exists and is non-empty
#   2. install ops/deploy/2d-car-game.service -> /etc/systemd/system/
#   3. systemctl daemon-reload; enable --now the unit (or restart if running)
#   4. run ops/deploy/healthcheck.sh and report the outcome
#
# Safe to re-run: it never touches index.html; it only (re)installs the server.
set -euo pipefail

DOC_ROOT="/home/serverbot/aidev"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="${HERE}/2d-car-game.service"
UNIT_DST="/etc/systemd/system/2d-car-game.service"
UNIT="2d-car-game.service"

if [ ! -s "${DOC_ROOT}/index.html" ]; then
  echo "ERROR: ${DOC_ROOT}/index.html missing or empty — nothing to serve" >&2
  exit 1
fi
echo "Artifact present: ${DOC_ROOT}/index.html ($(wc -c < "${DOC_ROOT}/index.html") bytes)"

echo "Installing unit -> ${UNIT_DST}"
install -m 0644 "$UNIT_SRC" "$UNIT_DST"

systemctl daemon-reload
systemctl enable "$UNIT" >/dev/null 2>&1 || true
if systemctl is-active --quiet "$UNIT"; then
  echo "Restarting ${UNIT}"
  systemctl restart "$UNIT"
else
  echo "Starting ${UNIT}"
  systemctl start "$UNIT"
fi

# Give the socket a moment to bind before health-checking.
for _ in 1 2 3 4 5; do
  systemctl is-active --quiet "$UNIT" && break
  sleep 0.5
done

echo "-----------------------"
"${HERE}/healthcheck.sh"
