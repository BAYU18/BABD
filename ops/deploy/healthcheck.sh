#!/usr/bin/env bash
# ops/deploy/healthcheck.sh — verify the 2D car game is actually being served.
#
# Exits 0 only if EVERY check passes. Prints one PASS/FAIL line per check so a
# human or a monitor can see exactly which assertion failed.
#
# Checks (all against the real listening socket, not a mock):
#   1. systemd unit is active (if systemd-managed)
#   2. port 8080 is LISTENing on 192.168.0.222
#   3. HTTP 200 on /            (local loopback)
#   4. HTTP 200 on /index.html  (the exact URL the CEO opens)
#   5. body contains a <canvas> (i.e. the game, not a directory listing)
#   6. body byte-size matches the committed index.html (no stale/partial file)
#   7. reachable over the LAN IP (192.168.0.222:8080)
#
# Usage:  ops/deploy/healthcheck.sh
set -uo pipefail

HOST_LAN="192.168.0.222"
PORT="8080"
DOC_ROOT="/home/serverbot/aidev"
UNIT="2d-car-game.service"
fail=0

pass() { printf 'PASS  %s\n' "$1"; }
bad()  { printf 'FAIL  %s\n' "$1"; fail=1; }

# 1. systemd unit active
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q "^${UNIT}"; then
  if systemctl is-active --quiet "$UNIT"; then pass "unit ${UNIT} active"; else bad "unit ${UNIT} not active"; fi
else
  echo "SKIP  unit ${UNIT} not installed via systemd (manual run?)"
fi

# 2. port listening, bound to the LAN address
if ss -tln 2>/dev/null | grep -qE "LISTEN.*${HOST_LAN}:${PORT}\b"; then
  pass "port ${PORT} LISTENing on ${HOST_LAN}"
elif ss -tln 2>/dev/null | grep -qE "LISTEN.*:${PORT}\b"; then
  bad "port ${PORT} listening but NOT bound to ${HOST_LAN} (check --bind)"
else
  bad "port ${PORT} not listening"
fi

# 3-4. HTTP status via loopback and via the LAN address
code_loop=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${PORT}/" || echo "000")
[ "$code_loop" = "200" ] && pass "HTTP 200 on http://127.0.0.1:${PORT}/" || bad "HTTP ${code_loop} on http://127.0.0.1:${PORT}/"

code_file=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${PORT}/index.html" || echo "000")
[ "$code_file" = "200" ] && pass "HTTP 200 on http://127.0.0.1:${PORT}/index.html" || bad "HTTP ${code_file} on http://127.0.0.1:${PORT}/index.html"

code_lan=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://${HOST_LAN}:${PORT}/" || echo "000")
[ "$code_lan" = "200" ] && pass "HTTP 200 on http://${HOST_LAN}:${PORT}/" || bad "HTTP ${code_lan} on http://${HOST_LAN}:${PORT}/"

# 5. body contains the game canvas (not a dir listing / Placeholder)
canvas=$(curl -s --max-time 5 "http://127.0.0.1:${PORT}/index.html" | grep -c '<canvas' || true)
[ "${canvas:-0}" -ge 1 ] && pass "served body contains <canvas> (count=${canvas})" || bad "served body has no <canvas> (count=${canvas:-0})"

# 6. served bytes == on-disk bytes (byte-for-byte freshness)
disk_len=$(wc -c < "${DOC_ROOT}/index.html" 2>/dev/null || echo 0)
served_len=$(curl -s --max-time 5 "http://127.0.0.1:${PORT}/index.html" | wc -c)
[ "$disk_len" = "$served_len" ] && pass "served size == on-disk size (${served_len} bytes)" \
  || bad "size mismatch: disk=${disk_len} served=${served_len} (stale/partial file?)"

echo "-----"
if [ "$fail" -eq 0 ]; then echo "HEALTHCHECK: OK"; exit 0; else echo "HEALTHCHECK: FAILED"; exit 1; fi
