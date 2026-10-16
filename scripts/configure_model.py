"""Configure local-only Phase 2 model name in protected runtime storage.

Usage: python3 scripts/configure_model.py gpt-oss:20b
Will NOT download a model or send requests to a cloud service.
"""

from __future__ import annotations

import argparse
import os

from native_runtime import RUNTIME, setup_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="An Ollama model already pulled on this workstation")
    args = parser.parse_args()
    if not args.model.strip() or any(c in args.model for c in "\n\r=\x00"):
        parser.error("Invalid model name")
    setup_runtime()
    config = RUNTIME / "model.env"
    if config.is_symlink():
        raise SystemExit("Refusing symlink for model config")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(config, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(f"MIO_LOCAL_MODEL={args.model.strip()}\n")
            file.write("MIO_LOCAL_BASE_URL=http://127.0.0.1:11434/v1\n")
            file.write("MIO_MODEL_ROUTE=local\n")
            file.write("MIO_ALLOW_CLOUD=false\n")
    except BaseException:
        os.close(fd)
        raise
    print("Configured local model name in private model.env; cloud disabled.")
    print("Restart MioAgent to load this configuration.")


if __name__ == "__main__":
    main()
