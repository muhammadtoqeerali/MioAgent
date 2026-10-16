"""Owner-controlled enable/disable/probe for Bubblewrap test execution."""

from __future__ import annotations

import argparse
import os
import stat

from mio.sandbox_verify import preflight
from scripts.native_runtime import RUNTIME, setup_runtime

MARKER = RUNTIME / "sandbox-verify-enabled"


def enabled() -> bool:
    if MARKER.is_symlink():
        raise RuntimeError("Refusing sandbox control symlink")
    if not MARKER.exists():
        return False
    info = MARKER.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise RuntimeError("Sandbox control flag must be an owner-private file")
    if MARKER.read_text(encoding="utf-8") != "enabled\n":
        raise RuntimeError("Sandbox control flag has unexpected contents")
    return True


def set_enabled(value: bool) -> None:
    setup_runtime()
    if value:
        preflight(RUNTIME / "projects")  # FAIL CLOSED if actual Bubblewrap is blocked.
        if not enabled():
            fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("enabled\n")
    elif enabled():
        MARKER.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["probe", "enable", "disable", "status"])
    args = parser.parse_args()
    if args.action == "probe":
        setup_runtime()
        print(preflight(RUNTIME / "projects"))
    elif args.action in {"enable", "disable"}:
        set_enabled(args.action == "enable")
    print("Sandbox unittest verification:", "enabled" if enabled() else "disabled")
    print("No arbitrary model-generated shell commands, package installs or network access")


if __name__ == "__main__":
    main()
