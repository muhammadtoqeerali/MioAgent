#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# Optional and explicit: no sudo, no system modifications.
STORE="/var/tmp/mioagent-ollama-$(id -u)"
MODEL_DIR="${MIO_OLLAMA_MODELS_DIR:-$HOME/MioAgentModels}"

for tool in curl tar zstd findmnt; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Cannot perform manual Ollama install without sudo."; exit 1; }
done

FS="$(findmnt -n -o FSTYPE -T /var/tmp)"
case "$FS" in ext4|xfs|btrfs|zfs|f2fs) ;; *) echo "Cannot install binary on $FS"; exit 1;; esac
if [ -e "$STORE" ] || [ -L "$STORE" ]; then
  test ! -L "$STORE"
  test "$(stat -c '%u' "$STORE")" = "$(id -u)"
fi
mkdir -p -m 700 "$STORE"
chmod 700 "$STORE"

TMP="$(mktemp -d /var/tmp/mio-ollama.XXXXXXXX)"
trap 'rm -rf -- "$TMP"' EXIT
ARCHIVE="$TMP/ollama.tar.zst"

printf 'Downloading the official Ollama Linux AMD64 distribution. This may be large.\n'
curl --fail --location --retry 3 \
  'https://ollama.com/download/ollama-linux-amd64.tar.zst' -o "$ARCHIVE"
sha256sum "$ARCHIVE" | tee "$STORE/distribution.sha256"
# This is a transport-integrity checksum, not a verified publisher checksum.
# Do not run downloads with administrator privileges.
echo 'Examining archive paths before extraction...'
tar --zstd -tf "$ARCHIVE" > "$TMP/names"
if grep -E '(^/|(^|/)\.\.(\/|$))' "$TMP/names"; then
  echo 'Unsafe archive path detected'; exit 1
fi
# Preflight symlink/hardlink destinations and archives before using in security-sensitive settings.
mkdir -p -m 700 "$STORE/ollama"
tar --zstd -xf "$ARCHIVE" -C "$STORE/ollama" --no-same-owner --no-same-permissions
CLI="$STORE/ollama/bin/ollama"
test -x "$CLI"
"$CLI" --version || true
printf '\nRootless binary: %s\n' "$CLI"
printf 'Model weights directory (set OLLAMA_MODELS): %s\n' "$MODEL_DIR"
printf '\nRun in a workstation terminal:\n'
printf '  OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS="%s" "%s" serve\n' "$MODEL_DIR" "$CLI"
printf '\nIn a second workstation terminal:\n'
printf '  "%s" pull gpt-oss:20b\n' "$CLI"
