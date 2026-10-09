#!/bin/bash
# Wrapper to start the BABD dashboard with a fixed token and the full .env
# loaded into the process environment, so Hermes child processes inherit a
# valid OPENAI_API_KEY / KEY1 (the root cause of the intermittent
# "HTTP 401: API key required for remote API access" during team runs).
set -a
# shellcheck disable=SC1091
source /home/serverbot/aidev/.env
set +a

export PATH="/home/serverbot/aidev/.babd/tools/hermes/bin:/home/serverbot/aidev/.babd/tools/bun/bin:$PATH"

exec /home/serverbot/aidev/.venv/bin/python -c '
import sys
sys.path.insert(0, "/home/serverbot/aidev")
from babd.dashboard.server import serve
serve(host="0.0.0.0", port=8800, open_browser=False, token="aidev-babd-2024")
'
