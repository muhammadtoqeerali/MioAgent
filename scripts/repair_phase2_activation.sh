#!/usr/bin/env bash
# Phase 2 recovery with real TCP LISTEN checks (not bind/TIME_WAIT guesses).
set -Eeuo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV="$HOME/.cache/mioagent/phase1-venv"
cd "$PROJECT"

echo '=== MIOAGENT PHASE 2 SAFE RESTART ==='
echo '[1/9] Verify model configuration, runtime, and dependencies'
test -x "$VENV/bin/python"
test -f apps/dashboard/package-lock.json
command -v ollama
command -v ss
"$VENV/bin/python" - <<'PY_CHECK'
from scripts.native_runtime import load_model_config
config = load_model_config()
if not config.get('MIO_LOCAL_MODEL'):
    raise SystemExit('Model not configured. Run python3 scripts/configure_model.py gpt-oss:20b')
print('Selected local model:', config['MIO_LOCAL_MODEL'])
print('Cloud inference: disabled')
PY_CHECK

echo '[2/9] Stop only services that MioAgent can positively identify'
python3 scripts/native_runtime.py stop

echo '[3/9] Verify Python checks'
"$VENV/bin/python" -m compileall -q mio tests scripts
"$VENV/bin/python" -m pytest -q
"$VENV/bin/python" -m ruff check mio tests scripts

echo '[4/9] Build the Next.js dashboard'
npm --prefix apps/dashboard run typecheck
npm --prefix apps/dashboard run build

echo '[5/9] Inspect actual TCP listeners (TIME_WAIT is NOT a conflict)'
for PORT in 8000 3000; do
    LISTENER="$(ss -H -ltnp "sport = :${PORT}")"
    if [[ -n "$LISTENER" ]]; then
        echo "STOP: TCP port $PORT still has an active listener:" >&2
        printf '%s\n' "$LISTENER" >&2
        echo 'Do not kill it blindly. Check its PID, UID and working directory.' >&2
        echo 'Run: ss -ltnp | grep -E ":(3000|8000) "' >&2
        exit 1
    fi
    echo "Port $PORT: no active listener"
done

echo '[6/9] Start MioAgent and verify real background task processing'
python3 scripts/native_runtime.py start
python3 scripts/native_runtime.py smoke

echo '[7/9] Start local Ollama service'
python3 scripts/ollama_native.py start
python3 scripts/ollama_native.py status

echo '[8/9] Verify model configuration reached the API'
"$VENV/bin/python" - <<'PY_STATUS'
from scripts.native_runtime import API_URL, get_token, load_json, load_model_config
selected = load_model_config()['MIO_LOCAL_MODEL']
state = load_json(f'{API_URL}/api/assistant/status', get_token())
print('Model status:', state)
if not state.get('configured') or state.get('local_model') != selected:
    raise SystemExit('The API did not load the selected local model')
if not state.get('local_reachable'):
    raise SystemExit('Ollama is not reachable through the MioAgent model gateway')
print('PASS: configured model and local Ollama connection')
PY_STATUS

echo '[9/9] Final process and HTTP status'
python3 scripts/native_runtime.py status

echo '=== SERVICES READY; MODEL DOWNLOAD MAY STILL BE NEEDED ==='
echo 'Next: python3 scripts/ollama_native.py pull gpt-oss:20b'
echo 'Then: python3 scripts/phase2_smoke.py'
echo 'Laptop dashboard (existing SSH tunnel): http://127.0.0.1:13000/assistant'
