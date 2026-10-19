#!/usr/bin/env bash
# Explicitly opt-in image backend installer. Never run as part of MioAgent publish.
set -Eeuo pipefail

ROOT="$HOME/.cache/mioagent/comfyui"
APP="$ROOT/ComfyUI"
VENV="$ROOT/venv"
MODEL="$APP/models/checkpoints/v1-5-pruned-emaonly-fp16.safetensors"
SOURCE='https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/82ddc01b8d77adc5b4a7c6b5e8f2ddf1a6fe0c08/v1-5-pruned-emaonly-fp16.safetensors'
SHA='e9476a13728cd75d8279f6ec8bad753a66a1957ca375a1464dc63b37db6e3916'

case "${1:-}" in
  --install)
    echo 'Image backend install: ComfyUI + PyTorch dependencies + 2.13 GB SD1.5 FP16 checkpoint.'
    echo 'This requires several GB additional downloads, internet access, disk and GPU memory.'
    echo 'No sudo or Docker. Python packages are from public upstream repositories.'
    test "${2:-}" = '--i-approve-downloads' || { echo 'STOP: add --i-approve-downloads after reviewing this script'; exit 2; }
    command -v git >/dev/null
    command -v curl >/dev/null
    command -v sha256sum >/dev/null
    command -v python3 >/dev/null
    mkdir -p "$ROOT"
    if [ ! -e "$APP" ]; then
      git clone --depth 1 https://github.com/Comfy-Org/ComfyUI.git "$APP"
    elif [ ! -d "$APP/.git" ]; then
      echo 'STOP: existing ComfyUI folder is unrecognized'; exit 2
    fi
    if [ ! -f "$VENV/bin/python" ]; then python3 -m venv "$VENV"; fi
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
    "$VENV/bin/python" -m pip install -r "$APP/requirements.txt"
    mkdir -p "$(dirname "$MODEL")"
    if [ ! -f "$MODEL" ]; then
      echo 'Downloading pinned Comfy-Org checkpoint (2.13 GB) with full SHA-256 verification...'
      curl --proto '=https' --proto-redir '=https' -fL --retry 3 --connect-timeout 15 \
        --output "$MODEL.part" "$SOURCE"
      printf '%s  %s\n' "$SHA" "$MODEL.part" | sha256sum -c -
      mv "$MODEL.part" "$MODEL"
    fi
    printf '%s  %s\n' "$SHA" "$MODEL" | sha256sum -c -
    echo 'READY TO START: run this script with --start in a separate terminal.'
    ;;
  --start)
    test -f "$VENV/bin/python" || { echo 'STOP: run --install first'; exit 2; }
    printf '%s  %s\n' "$SHA" "$MODEL" | sha256sum -c -
    if ss -ltn "sport = :8188" | grep -q '127.0.0.1:8188'; then
      echo 'STOP: ComfyUI port already in use; inspect the existing service'; exit 2
    fi
    cd "$APP"
    # Use second GPU by default; move workloads if that GPU is already occupied.
    CUDA_VISIBLE_DEVICES=1 "$VENV/bin/python" main.py --listen 127.0.0.1 --port 8188
    ;;
  *)
    echo 'Usage:'
    echo '  bash scripts/bootstrap_studio_image.sh --install --i-approve-downloads'
    echo '  bash scripts/bootstrap_studio_image.sh --start'
    exit 2
    ;;
esac
