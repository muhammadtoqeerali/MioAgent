"""Create/reuse private project secrets on the user's home filesystem.

The project source may be stored on a permissive HDD mount, so secrets are intentionally
stored OUTSIDE the source tree at ~/.config/mioagent/.env (mode 0600).
"""
import os
from pathlib import Path
from secrets import token_hex, token_urlsafe

folder = Path.home() / ".config" / "mioagent"
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
folder.chmod(0o700)
target = folder / ".env"
if target.exists():
    print(f"Existing private secrets preserved at {target}")
else:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(f"MIO_API_TOKEN={token_urlsafe(48)}\nMIO_DB_PASSWORD={token_hex(24)}\n")
    print(f"New private secrets created at {target}")
target.chmod(0o600)
print("Use: docker compose --env-file ~/.config/mioagent/.env up -d --build")
