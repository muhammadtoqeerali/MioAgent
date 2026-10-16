"""Read-only diagnostics for the Linux workstation and Phase-1 repository."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def fs_type(path: Path) -> str:
    existing = path
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    result = subprocess.run(
        ["findmnt", "-no", "FSTYPE", "-T", str(existing)],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    home = Path.home()
    secrets = home / ".config/mioagent/.env"
    print("=== MIOAGENT PHASE 1 DOCTOR (READ ONLY) ===")
    for label, path in (("project", root), ("home", home), ("credentials", secrets)):
        filesystem = fs_type(path) if shutil.which("findmnt") else "unknown"
        print(f"{label}: {path} [filesystem: {filesystem}]")
        if filesystem.lower() in {"fuseblk", "ntfs", "ntfs3", "vfat", "exfat"}:
            print("  WARNING: Unix permissions may not protect files as expected.")
    if secrets.exists():
        mode = secrets.stat().st_mode & 0o777
        print(f"credentials: PRESENT (reported permission mode: {mode:03o})")
    else:
        print("credentials: MISSING (run scripts/init_env.py before Docker start)")
    for cmd in ("python3", "node", "npm", "git", "docker"):
        print(f"{cmd}: {shutil.which(cmd) or 'not in PATH'}")
    print("No secrets were read or printed. No filesystem changes were made.")


if __name__ == "__main__":
    main()
