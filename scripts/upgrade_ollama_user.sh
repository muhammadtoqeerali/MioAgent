#!/usr/bin/env bash
# Install official Ollama v0.34.1 for MioAgent (no sudo, no system changes).
# Download source: https://github.com/ollama/ollama/releases/tag/v0.34.1
set -Eeuo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$PROJECT"
VERSION="v0.34.1"
ARCHIVE="${OLLAMA_ARCHIVE:-$HOME/Downloads/ollama-linux-amd64-v0.34.1.tar.zst}"
EXPECTED="f361dc3992ec07e4ad429f4bb2d10d4663ba2c295f9a9a688c7d52f4ba650034"
URL="https://github.com/ollama/ollama/releases/download/${VERSION}/ollama-linux-amd64.tar.zst"
ROOT="/var/tmp/mioagent-ollama-binaries-$(id -u)"
RELEASE="$ROOT/$VERSION"

printf '=== MIOAGENT OFFICIAL OLLAMA USER UPGRADE ===\n'
command -v curl >/dev/null
command -v zstd >/dev/null
command -v tar >/dev/null
command -v sha256sum >/dev/null
command -v findmnt >/dev/null
[[ "$(uname -m)" == "x86_64" ]] || { echo 'STOP: x86_64 Linux required' >&2; exit 1; }
case "$(findmnt -n -o FSTYPE -T /var/tmp)" in
    ext4|xfs|btrfs|zfs|f2fs) ;;
    *) echo 'STOP: /var/tmp needs owner-enforcing native Linux filesystem' >&2; exit 1 ;;
esac

printf '\n[1/6] Verify the fixed official release download\n'
if [[ ! -f "$ARCHIVE" ]]; then
  mkdir -p "$(dirname "$ARCHIVE")"
  echo 'The official archive is approximately 1.33 GB; downloading with resume support.'
  curl -fL --retry 4 --retry-delay 3 -C - --output "$ARCHIVE" "$URL"
fi
printf '%s  %s\n' "$EXPECTED" "$ARCHIVE" | sha256sum -c - || {
  echo 'STOP: Release archive checksum mismatch. Do not extract it.' >&2
  echo 'Delete the corrupted archive before retrying the download.' >&2
  exit 1
}

printf '\n[2/6] Verify private installation directory and disk space\n'
if [[ -L "$ROOT" ]]; then echo 'STOP: Installation root is a symlink.' >&2; exit 1; fi
mkdir -m 700 -p "$ROOT"
OWNER="$(stat -c '%u' "$ROOT")"
MODE="$(stat -c '%a' "$ROOT")"
if [[ "$OWNER" != "$(id -u)" || "$MODE" != "700" ]]; then
  echo 'STOP: Invalid owner or permissions on private Ollama root.' >&2
  exit 1
fi
if (( $(df -Pk "$ROOT" | awk 'END {print $4}') < 5242880 )); then
  echo 'STOP: At least 5 GiB free native-Linux storage is required for extraction.' >&2
  exit 1
fi

printf '\n[3/6] Extract to an unprivileged native-Linux directory\n'
if [[ ! -x "$RELEASE/bin/ollama" ]]; then
  [[ ! -e "$RELEASE" ]] || { echo 'STOP: Partial installation exists; inspect it.' >&2; exit 1; }
  STAGING="$(mktemp -d "$ROOT/staging.XXXXXX")"
  trap 'if [[ -n "${STAGING:-}" && -d "$STAGING" ]]; then rm -rf -- "$STAGING"; fi' EXIT
  tar --use-compress-program=zstd -xf "$ARCHIVE" -C "$STAGING"
  [[ -f "$STAGING/bin/ollama" && ! -L "$STAGING/bin/ollama" ]] || {
    echo 'STOP: Official archive has unexpected binary layout.' >&2; exit 1;
  }
  chmod u+x "$STAGING/bin/ollama"
  "$STAGING/bin/ollama" --version || true
  mv -- "$STAGING" "$RELEASE"
  STAGING=""
fi

printf '\n[4/6] Stop previous MioAgent-managed Ollama safely\n'
python3 scripts/ollama_native.py stop
if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo 'STOP: An Ollama service still responds; do not replace a non-owned process.' >&2
  exit 1
fi
if [[ -n "$(ss -H -ltnp 'sport = :11434')" ]]; then
  echo 'STOP: Port 11434 has a listener. Inspect it before proceeding.' >&2
  ss -H -ltnp 'sport = :11434' >&2
  exit 1
fi

printf '\n[5/6] Switch the project to the new binary\n'
[[ ! -e "$ROOT/current" || -L "$ROOT/current" ]] || {
  echo 'STOP: current is not a symlink.' >&2; exit 1;
}
rm -f -- "$ROOT/current.new"
ln -s "$VERSION" "$ROOT/current.new"
mv -Tf "$ROOT/current.new" "$ROOT/current"
python3 - <<'PY_CHECK'
from scripts.ollama_native import binary
import subprocess
selected = binary()
print('MioAgent Ollama binary:', selected)
assert '/var/tmp/mioagent-ollama-binaries-' in selected
print(subprocess.run([selected, '--version'], check=True, capture_output=True, text=True).stdout.strip())
PY_CHECK

printf '\n[6/6] Start updated Ollama, preserve model directory\n'
python3 scripts/ollama_native.py start
python3 scripts/ollama_native.py status
printf '\nSUCCESS: Pinned user-owned Ollama release active.\n'
printf 'Next: python3 scripts/ollama_native.py pull gpt-oss:20b\n'
