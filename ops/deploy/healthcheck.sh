#!/usr/bin/env bash
# ops/deploy/healthcheck.sh — verify the 2D car game is actually being served.
#
# Exits 0 only if EVERY check passes. Prints one PASS/FAIL line per check so a
# human or a monitor can see exactly which assertion failed.
#
# IMPORTANT: the server binds ONLY to 192.168.0.222 (per the unit's --bind), so
# every HTTP check must target 192.168.0.222:8080 — NOT 127.0.0.1, which the
# server correctly refuses. (An earlier draft checked loopback and reported
# false failures.)
#
# Checks (all against the real listening socket, not a mock):
#   1. systemd unit is active
#   2. port 8080 is LISTENing on 192.168.0.222
#   3. HTTP 200 on /            (the exact URL the CEO opens)
#   4. HTTP 200 on /index.html
#   5. body contains a <canvas> (i.e. the game, not a directory listing)
#   6. served byte-size matches the committed index.html (no stale/partial file)
#
# Usage:  ops/deploy/healthcheck.sh
set -uo pipefail

HOST_LAN="192.168.0.222"
PORT="8080"
DOC_ROOT="/home/serverbot/aidev"
UNIT="2d-car-game.service"
BASE="http://${HOST_LAN}:${PORT}"
fail=0

pass() { printf 'PASS  %s\n' "$1"; }
bad()  { printf 'FAIL  %s\n' "$1"; fail=1; }

# http_code URL -> prints the 3-digit status, or 000 on connection failure.
# NOTE: curl prints "000" itself on connection failure AND exits non-zero, so a
# `curl ... || printf 000` fallback would emit "000000" (observed in prod logs).
# Capture the output and only substitute when curl produced nothing usable.
http_code() {
  local c
  c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$1" 2>/dev/null)
  case "$c" in
    [0-9][0-9][0-9]) printf '%s' "$c" ;;
    *) printf '000' ;;
  esac
}

# 1. systemd unit active
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet "$UNIT"; then
    pass "unit ${UNIT} active"
  else
    bad "unit ${UNIT} not active (systemctl is-active)"
  fi
else
  echo "SKIP  systemd not available (manual run?)"
fi

# 2. port listening, bound to the LAN address
if ss -tln 2>/dev/null | grep -qE "LISTEN[[:space:]].*${HOST_LAN}:${PORT}[[:space:]]"; then
  pass "port ${PORT} LISTENing on ${HOST_LAN}"
elif ss -tln 2>/dev/null | grep -qE "LISTEN[[:space:]].*:${PORT}[[:space:]]"; then
  bad "port ${PORT} listening but NOT bound to ${HOST_LAN} (check --bind)"
else
  bad "port ${PORT} not listening"
fi

# 3. HTTP 200 on the root URL the CEO opens
code_root=$(http_code "${BASE}/")
[ "$code_root" = "200" ] && pass "HTTP 200 on ${BASE}/" || bad "HTTP ${code_root} on ${BASE}/"

# 4. HTTP 200 on /index.html
code_file=$(http_code "${BASE}/index.html")
[ "$code_file" = "200" ] && pass "HTTP 200 on ${BASE}/index.html" || bad "HTTP ${code_file} on ${BASE}/index.html"

# 5. body contains the game canvas (not a dir listing / placeholder)
canvas=$(curl -s --max-time 5 "${BASE}/index.html" | grep -c '<canvas' || true)
[ "${canvas:-0}" -ge 1 ] && pass "served body contains <canvas> (count=${canvas})" || bad "served body has no <canvas> (count=${canvas:-0})"

# 6. served bytes == on-disk bytes (byte-for-byte freshness)
disk_len=$(wc -c < "${DOC_ROOT}/index.html" 2>/dev/null || echo 0)
served_len=$(curl -s --max-time 5 "${BASE}/index.html" | wc -c)
[ "$disk_len" = "$served_len" ] && pass "served size == on-disk size (${served_len} bytes)" \
  || bad "size mismatch: disk=${disk_len} served=${served_len} (stale/partial file?)"

echo "-----"
if [ "$fail" -eq 0 ]; then echo "HEALTHCHECK: OK"; exit 0; else echo "HEALTHCHECK: FAILED"; exit 1; fi
