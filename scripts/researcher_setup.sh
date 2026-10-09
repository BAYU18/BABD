#!/usr/bin/env bash
# Setup adapter researcher: vendor gpt-researcher lokal + venv terpisah.
#
# Idempoten: aman dijalankan berulang kali. Dipanggil otomatis oleh harness `process`
# (agents.json -> harness.install) sekali per perintah install, atau manual.
#
# Tidak ada port baru dan tidak ada service yang harus dijaga hidup: gpt-researcher
# dipakai sebagai library Python dari venv ini.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${RESEARCHER_HOME:-$ROOT/.babd/researcher}"
VENDOR="$DIR/gpt-researcher"
VENV="$DIR/venv"
BIN="$DIR/bin"
REPO="${RESEARCHER_REPO:-https://github.com/assafelovic/gpt-researcher}"
REF="${RESEARCHER_REF:-master}"

mkdir -p "$DIR" "$BIN"

if [ ! -d "$VENDOR/.git" ]; then
  echo "researcher-setup: cloning $REPO ($REF) -> $VENDOR"
  if ! git clone --depth 1 --branch "$REF" "$REPO" "$VENDOR"; then
    echo "researcher-setup: WARNING clone gagal (jaringan?). Adapter tetap jalan dalam mode jujur:"
    echo "researcher-setup: tanpa gpt-researcher ia exit 2 'no search provider', tidak mengarang sumber."
    exit 0
  fi
else
  echo "researcher-setup: vendor sudah ada di $VENDOR (skip clone)"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "researcher-setup: membuat venv $VENV"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
if ! "$VENV/bin/pip" install --quiet -e "$VENDOR"; then
  echo "researcher-setup: WARNING install gpt-researcher gagal. Jalankan ulang saat jaringan tersedia."
  exit 0
fi

# Symlink agar agents.json bisa memakai path relatif yang stabil.
ln -sf "$ROOT/scripts/researcher_adapter.py" "$BIN/research"
ln -sf "$ROOT/scripts/researcher_setup.sh" "$BIN/setup"
chmod +x "$ROOT/scripts/researcher_adapter.py" "$ROOT/scripts/researcher_setup.sh"

echo "researcher-setup: selesai. Uji cepat:"
echo "  printf 'RESEARCHER\\n\\n---\\n\\ntest\\n' | RESEARCHER_SEARXNG_URL=http://127.0.0.1:8888 $BIN/research --json"
