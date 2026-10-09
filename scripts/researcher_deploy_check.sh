#!/usr/bin/env bash
# Cek sehat agent "researcher" (read-only; tidak mengubah apa pun).
#
# Dijalankan DI ROOT INSTALASI BABD (default: direktori kerja saat ini), mis.:
#     cd /home/serverbot/aidev && scripts/researcher_deploy_check.sh
#
# Override: BABD_INSTALL_ROOT=/path BABD_DASHBOARD_URL=http://host:8800
#
# Exit 0 hanya bila SEMUA check wajib lolos. Kegagalan provider (exit 2) dilaporkan
# sebagai BELUM OPERASIONAL, bukan sebagai sehat — dan bukan sebagai crash.

set -uo pipefail

ROOT="${BABD_INSTALL_ROOT:-$(pwd)}"
DASH="${BABD_DASHBOARD_URL:-http://127.0.0.1:8800}"
PY="${ROOT}/.venv/bin/python"
RESEARCH_BIN="${ROOT}/.babd/researcher/bin/research"

pass=0; fail=0; warnn=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=$((fail+1)); }
soft() { printf '  \033[33m⚠\033[0m %s\n' "$1"; warnn=$((warnn+1)); }

printf '\nCek sehat researcher di %s\n\n' "$ROOT"

# H0 — lingkungan dasar
printf 'H0 · prasyarat\n'
[[ -x "$PY" ]] && ok "python venv ada: $PY" || bad "python venv tidak ada: $PY"
[[ -f "${ROOT}/agents.json" ]] && ok "agents.json ada" || bad "agents.json tidak ada"

# H1 — konfigurasi roster + harness menemukan perintah (path absolut)
printf '\nH1 · konfigurasi & resolusi command\n'
if [[ -x "$PY" ]]; then
  out=$("$PY" - <<'PYEOF' 2>&1
import sys
sys.path.insert(0, ".")
try:
    from babd.config import load_config
    from babd.harness import create_harness
except Exception as e:
    print("IMPORT_ERROR:", e); raise SystemExit(3)
agents = load_config()["agents"]
r = [a for a in agents if a.get("id") == "researcher"]
if not r:
    print("NO_RESEARCHER_IN_ROSTER"); raise SystemExit(2)
a = r[0]
h = create_harness(a)
p = h.command_path()
print("COMMAND_PATH:", p)
if not p.startswith("/"):
    print("NOT_ABSOLUTE"); raise SystemExit(4)
if a.get("permissions") != "workspace":
    print("PERMISSIONS:", a.get("permissions"))
if "researcher" not in [x["id"] for x in agents[1:]]:
    print("AFTER_LEAD_OK")
raise SystemExit(0)
PYEOF
)
  rc=$?
  case $rc in
    0)  ok "researcher ada di roster; command teresolusi absolut"; printf '      %s\n' "$out" ;;
    2)  bad "researcher TIDAK ada di agents.json" ;;
    3)  bad "import gagal: $out" ;;
    4)  bad "command researcher bukan path absolut — perlu resolusi ROOT di Process.command_path(): $out" ;;
    *)  bad "H1 gagal (exit $rc): $out" ;;
  esac
else
  bad "lewati H1: python venv tidak ada"
fi

# H2 — adapter hidup sebagai program (kontrak stdin -> stdout)
printf '\nH2 · adapter black box (stdin -> stdout)\n'
if [[ -x "$RESEARCH_BIN" ]]; then
  set +e
  out=$(printf 'You are the RESEARCHER.\n\n---\n\nBerapa versi terbaru httpx?\n' \
        | "$RESEARCH_BIN" --json 2>&1); rc=$?
  set -e
  case $rc in
    0)
      if printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.loads(sys.stdin.read()); assert isinstance(d.get("answer"),str) and isinstance(d.get("sources"),list)' 2>/dev/null; then
        ok "adapter exit 0 dan JSON berskema (answer + sources)"
      else
        bad "adapter exit 0 tapi output bukan JSON berskema (answer + sources)"
      fi
      ;;
    2)
      soft "adapter exit 2 (tidak ada search provider) — BELUM OPERASIONAL, tapi jujur (bukan crash)"
      printf '      %s\n' "$(printf '%s' "$out" | head -n1)"
      ;;
    *)  bad "adapter exit $rc (rusak?): $(printf '%s' "$out" | head -2 | tr '\n' ' ')" ;;
  esac
else
  bad "adapter tidak ada / tidak executable: $RESEARCH_BIN"
fi

# H3 — kolaborasi: researcher di specialist_roles & PEER_WHO
printf '\nH3 · kolaborasi (roster & peer)\n'
if [[ -x "$PY" ]]; then
  out=$("$PY" - <<'PYEOF' 2>&1
import sys
sys.path.insert(0, ".")
from babd import flow
from babd.config import load_config
from babd.team import Team
t = Team(load_config(), log=lambda m: None)
print("SPECIALISTS:", flow.specialist_roles(t))
print("PEER_WHO:", (flow.PEER_WHO.get("researcher") or "<kosong>"))
assert "researcher" in flow.specialist_roles(t), "researcher bukan specialist"
assert (flow.PEER_WHO.get("researcher") or "").strip(), "PEER_WHO researcher kosong"
PYEOF
)
  [[ $? -eq 0 ]] && ok "researcher jalan sendiri & bisa dipanggil-peer" || bad "H3 gagal: $out"
  printf '      %s\n' "$(printf '%s' "$out" | tr '\n' ' ')"
else
  bad "lewati H3: python venv tidak ada"
fi

# H4 — dashboard menampilkan researcher
printf '\nH4 · dashboard\n'
if command -v curl >/dev/null 2>&1; then
  body=$(curl -fsS --max-time 8 "${DASH}/api/board" 2>/dev/null || true)
  if [[ -n "$body" ]]; then
    if printf '%s' "$body" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); ids=[a["id"] for a in d.get("agents",[])]; sys.exit(0 if "researcher" in ids else 1)' 2>/dev/null; then
      ok "researcher tampil di /api/board"
    else
      soft "dashboard hidup tapi researcher belum tampil (auth? token? belum restart?)"
    fi
  else
    soft "dashboard tidak menjawab di $DASH (token auth? service mati?)"
  fi
else
  soft "curl tidak ada; lewati H4"
fi

printf '\nRingkasan: %d lulus, %d gagal, %d peringatan\n' "$pass" "$fail" "$warnn"
if [[ $fail -gt 0 ]]; then
  printf '\033[31mVERDICT: FAIL\033[0m — jangan deploy sebelum diperbaiki.\n\n'
  exit 1
fi
if [[ $warnn -gt 0 ]]; then
  printf '\033[33mVERDICT: PASS DENGAN CATATAN\033[0m — cek peringatan di atas (mis. provider belum diset).\n\n'
  exit 0
fi
printf '\033[32mVERDICT: PASS\033[0m\n\n'
