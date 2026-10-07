#!/usr/bin/env bash
# One-command install for BABD (Linux / macOS; on Windows use WSL).
#   ./install.sh
# Creates .venv, installs BABD and its Python dependencies, then installs and configures the
# harness of every agent in agents.json (Hermes Agent, Claude Code + Node.js when needed).
# Re-running it is safe. BABD_SKIP_HARNESS=1 skips the harness step.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "BABD needs Python 3.10 or newer: https://www.python.org/downloads/" >&2
  exit 1
fi
say "Python: $("$PY" --version)"

if [ ! -x .venv/bin/python ]; then
  say "Creating the virtual environment (.venv)"
  if ! "$PY" -m venv .venv; then
    echo "Could not create a virtualenv. On Debian/Ubuntu: sudo apt install python3-venv" >&2
    exit 1
  fi
fi

say "Installing BABD and its Python dependencies"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  say "Created .env (API keys go here, or set them from the dashboard)"
fi
mkdir -p workspace

if [ "${BABD_SKIP_HARNESS:-0}" != "1" ]; then
  say "Installing and configuring every agent's harness"
  if ! .venv/bin/babd setup; then
    echo "Some harnesses could not be set up (see above). Fix the cause and run: .venv/bin/babd setup" >&2
  fi
fi

say "Done"
cat <<'MSG'
Start the dashboard:      .venv/bin/babd dashboard
Add API keys there (Configure -> LLM), or put them in .env.
Command line:             .venv/bin/babd --help
MSG
