"""Opt in to an ALREADY installed, local ComfyUI checkpoint; no downloads."""
from __future__ import annotations

import argparse
import asyncio
import json
import os

from mio.studio_api import RUNTIME
from mio.studio_files import StudioError, private_root
from mio.studio_tools import available_checkpoints, comfy_settings
from scripts.native_runtime import setup_runtime


async def run(checkpoint: str | None) -> None:
    setup_runtime()
    root = private_root(RUNTIME / "studio")
    options = await available_checkpoints()
    if not checkpoint:
        print(json.dumps({"available_local_checkpoints": options, "configured": comfy_settings(RUNTIME)}, indent=2))
        return
    if checkpoint not in options:
        raise StudioError("Checkpoint is not advertised by local ComfyUI on 127.0.0.1:8188")
    target = root / "image-backend.json"
    if target.exists() or target.is_symlink():
        raise StudioError("Image backend already configured; refusing silent replacement")
    from mio.studio_files import StudioError as Invalid
    from mio.studio_tools import comfy_settings as check
    # Validate before writing a permanent operator choice.
    temp = root / "image-backend.tmp"
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"checkpoint": checkpoint}, stream)
    try:
        if check(root) is not None:
            raise Invalid("Unexpected existing configuration")
        os.replace(temp, target)
        comfy_settings(root)
    finally:
        temp.unlink(missing_ok=True)
    print("SUCCESS: enabled local ComfyUI raster generation (no models were downloaded)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", help="Exact installed ComfyUI checkpoint name")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.checkpoint))
    except (StudioError, OSError, ValueError) as exc:
        parser.exit(1, f"STOP: {exc}\n")


if __name__ == "__main__":
    main()
