"""Explicitly opt in/out of local source-draft Project Mode (no code execution)."""

from __future__ import annotations

import argparse
import os
import stat

from scripts.native_runtime import RUNTIME, setup_runtime

MARKER = RUNTIME / "project-mode-enabled"


def enabled() -> bool:
    if MARKER.is_symlink():
        raise RuntimeError("Unsafe Project Mode marker")
    if not MARKER.exists():
        return False
    info = MARKER.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise RuntimeError("Project Mode marker must be an owner-private file")
    return MARKER.read_text(encoding="utf-8") == "enabled\n"


def set_enabled(value: bool) -> None:
    setup_runtime()
    if enabled() == value:
        return
    if value:
        fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write("enabled\n")
    else:
        MARKER.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["enable", "disable", "status"])
    args = parser.parse_args()
    try:
        if args.action in {"enable", "disable"}:
            set_enabled(args.action == "enable")
        print("Project Mode:", "enabled for next native-runtime start" if enabled() else "disabled")
        print("This never grants command execution, browser access, or GitHub push permissions.")
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc


if __name__ == "__main__":
    main()
