#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV="$HOME/.cache/mioagent/phase1-venv"
cd "$PROJECT"
GIT=(git -c "safe.directory=$PROJECT")

printf '=== PHASE 2 FINAL VALIDATION (REQUIRES REAL LOCAL MODEL) ===\n'
"$VENV/bin/python" -m pytest -q
"$VENV/bin/python" -m ruff check mio tests scripts
npm --prefix apps/dashboard run typecheck
npm --prefix apps/dashboard run build
python3 scripts/native_runtime.py smoke
python3 scripts/phase2_smoke.py

printf '\n=== REVIEW PUBLISH TARGET ===\n'
REMOTE="$("${GIT[@]}" remote get-url origin)"
test "$REMOTE" = 'https://github.com/muhammadtoqeerali/MioAgent.git'
"${GIT[@]}" config --local core.filemode false
"${GIT[@]}" add \
  mio/api.py mio/config.py mio/database.py mio/workers.py \
  mio/llm.py mio/memory.py mio/supervisor.py \
  scripts/native_runtime.py scripts/install_phase2.sh scripts/publish_phase2.sh \
  scripts/configure_model.py scripts/setup_ollama_rootless.sh scripts/phase2_smoke.py \
  scripts/dashboard_doctor.py scripts/ollama_native.py scripts/repair_phase2_activation.sh \
  scripts/upgrade_ollama_user.sh tests/test_ollama_upgrade.py docs/PHASE_2_OLLAMA_UPDATE.md \
  tests/test_intelligence.py tests/test_model_http.py tests/test_native_runtime.py \
  tests/test_phase2_activation.py tests/test_port_preflight.py docs/PHASE_2_ACTIVATION_REPAIR.md \
  docs/PHASE_2_PORT_RECOVERY.md \
  apps/dashboard/app/page.tsx apps/dashboard/app/assistant/page.tsx \
  'apps/dashboard/app/api/proxy/[...path]/route.ts' \
  apps/dashboard/app/globals.css \
  pyproject.toml README.md \
  docs/PHASE_2_IMPLEMENTATION.md docs/DASHBOARD_ACCESS_TROUBLESHOOTING.md \
  docs/decisions/0002-phase2-text-intelligence.md
"${GIT[@]}" diff --cached --check
STAGED="$("${GIT[@]}" diff --cached --name-only)"
if printf '%s\n' "$STAGED" | grep -Ei '(^|/)(\.env($|\.)|id_rsa|id_ed25519|credentials\.json|.*\.pem$|.*\.key$)' | grep -vE '(^|/)\.env\.example$'; then
    echo 'Refusing to publish sensitive-looking file paths.' >&2
    exit 1
fi
"${GIT[@]}" diff --cached --stat
printf '\n=== REVIEW UNCOMMITTED FILES ===\n'
"${GIT[@]}" status --short
printf '\nPress Enter to publish this reviewed milestone, or Ctrl+C to abort.\n'
read -r _reply
if ! "${GIT[@]}" diff --cached --quiet; then
    "${GIT[@]}" commit -m 'feat: integrate Phase 2 text supervisor, model router and durable memory'
fi
GIT_TERMINAL_PROMPT=0 "${GIT[@]}" push -u origin main
printf '\nPublished to %s\n' "$REMOTE"
