#!/usr/bin/env bash
# Execute AFTER extracting the Phase 2 overlay ZIP into MioAgent root.
set -Eeuo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV="$HOME/.cache/mioagent/phase1-venv"
cd "$PROJECT"

fail(){ echo "Phase 2 install stopped. Inspect the error above; no Git changes were pushed." >&2; }
trap fail ERR

printf '\n========== MIOAGENT PHASE 2 INSTALLATION ==========\n'
echo '[1/7] Verify project and previous runtime'
test -f docs/MASTER_PLAN.md
test -x "$VENV/bin/python"
test -f apps/dashboard/package-lock.json

echo '[2/7] Stop MioAgent-owned processes (preserves data and Git history)'
python3 scripts/native_runtime.py stop

echo '[3/7] Install Python package and run Python regression suite'
"$VENV/bin/python" -m pip install -e '.[dev]'
"$VENV/bin/python" -m ruff check --fix mio tests scripts
"$VENV/bin/python" -m compileall -q mio scripts tests
"$VENV/bin/python" -m pytest -q
"$VENV/bin/python" -m ruff check mio tests scripts

echo '[4/7] Validate TypeScript and build production dashboard'
npm --prefix apps/dashboard ci --no-audit --no-fund
npm --prefix apps/dashboard run typecheck
npm --prefix apps/dashboard run build

echo '[5/7] Start updated localhost runtime'
python3 scripts/native_runtime.py start

echo '[6/7] Run native integration smoke test'
python3 scripts/native_runtime.py smoke
python3 scripts/native_runtime.py status

echo '[7/7] Check model status (model installation is a separate explicit step)'
"$VENV/bin/python" - <<'PY'
from scripts.native_runtime import API_URL, get_token, load_json
print(load_json(f'{API_URL}/api/assistant/status', get_token()))
PY
printf '\n========== PHASE 2 INFRASTRUCTURE READY ==========\n'
printf 'Laptop (SSH tunnel): http://127.0.0.1:13000/assistant\n'
printf 'The AI workspace is only fully active after Ollama is installed, a model\n'
printf 'is pulled/configured, and scripts/phase2_smoke.py passes.\n'
printf 'Do not publish untested changes yet.\n'
