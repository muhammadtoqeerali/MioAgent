# MioAgent v0.3G — encrypted export and Windows VPN relay

## Verified network facts / deployment boundaries

- MioAgent workstation currently resolves neither `kiosgpusim3.ucy.ac.cy` nor its internal KIOS DNS; do not assume direct SSH.
- Windows laptop with university VPN can SSH to `mali0004@kiosgpusim3.ucy.ac.cy`.
- KIOS user `mali0004` has an XFS home on a **91%-used shared root filesystem** and a writable CIFS personal file server. Neither can safely host MioAgent's *live* SQLite. The 3.1 TB reported free is a **shared filesystem value**, not user quota.
- University server IT instructions warn users to minimize root-disk usage and ask permission before large allocations. Confirm that storing a **small encrypted personal project backup** is permitted under your account before first transfer.

## What this stage does

- Existing authenticated running local API/dashboard are required. Refuse if SQLite has queued/running tasks.
- Prompt for a unique passphrase twice (never put it in terminal commands or GitHub). Requires at least 16 characters; a random multiword passphrase is recommended. **Losing the passphrase makes recovery impossible.** Keep it in an independent secure password manager.
- Automatically stop native services. Verify current owner-private runtime on native Linux ext4, SQLite integrity, artifact ownership and no symlinks. SQLite `backup()` creates a short-lived 0600 working copy on native `/var/tmp`.
- Stream a gzip tar of the backed-up SQLite plus `projects/` files and SHA-256 manifest directly into `gpg --symmetric --cipher-algo AES256` using a passphrase fed via an anonymous pipe. GPG uses a short-lived 0700 home under `/var/tmp`, not the NTFS user home. No passphrase command-line arguments or environment variables. **No plaintext tar archive** and no credential/model configuration files.
- Produce a ciphertext `.gpg` file at a fresh, nonexisting filename (may be on the user's NTFS Downloads mount because only encrypted bytes are saved there). Decrypt-verify streaming into an ephemeral private staging directory; check per-file SHA-256 and full SQLite `PRAGMA integrity_check`.
- Always attempt to restart the existing API/dashboard and smoke-test it, even if export fails. A crash/power loss can still strand the service or leave an ephemeral DB copy; manual recovery uses `python scripts/native_runtime.py start` and `status`. Temporary SQLite copies aren't securely erasable from SSD in the forensic sense.
- Output has SHA-256 digest for independent transport integrity checks. The digest doesn't replace encrypted archive authentication and internal manifest verification.

### Preflight and example on MioAgent workstation

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
VENV="$HOME/.cache/mioagent/phase1-venv"
BACKUP="$HOME/Downloads/mioagent-private-$(date -u +%Y%m%dT%H%M%SZ).tar.gz.gpg"
"$VENV/bin/python" -m scripts.encrypted_backup create --output "$BACKUP" --max-mib 64
"$VENV/bin/python" scripts/native_runtime.py status
sha256sum -- "$BACKUP"
```

Run only after completing your current projects and when none is queued. The passphrase prompt happens **before** the services stop. Use a new filename for each backup. The encrypted output path can be copied to the Windows VPN laptop without exposing its contents.

### Relay from Windows to KIOS (only after KIOS storage permission is confirmed)

Run in Windows PowerShell while VPN connected, replacing `BACKUP_NAME` with the exact generated ciphertext filename:

```powershell
$File = 'BACKUP_NAME.tar.gz.gpg'
scp "toqeer@157.27.31.126:/mnt/hdd16T/ToqeerHomeBackup/Downloads/$File" "$env:USERPROFILE\Downloads\$File"
# From here, use your *approved user-owned KIOS destination*, not the shared root by default:
scp "$env:USERPROFILE\Downloads\$File" 'mali0004@kiosgpusim3.ucy.ac.cy:/home/mali0004/fileserver_data/APPROVED_PRIVATE_BACKUP_DIRECTORY/'
```

Create the approved destination yourself only if policy and filesystem permissions allow. `fileserver_data` directory permissions as previously reported are `drwxr-xr-x`, **not private**; do not treat it as confidential storage simply because it is writable. Use an approved owner-private folder if the CIFS server actually honors its permissions. Encrypt locally regardless.

Run `sha256sum <ciphertext-name>` at the source and on KIOS and ensure digests match. The SSH connection uses your existing VPN and SSH authentication, not a new tunnel or access workaround. **No direct workstation-to-KIOS connection is required.**

### Restore limitations and boundaries

`verify` rechecks a local encrypted archive using the passphrase, but does not alter the live runtime:

```bash
"$VENV/bin/python" -m scripts.encrypted_backup verify --input "$BACKUP" --max-mib 64
```

A passing backup verification is **not proof of full runtime restoration**: `projects.workspace_path` in SQLite includes absolute legacy `/var/tmp/...` paths and must be migrated safely. Automated application restoration and persistent active runtime are separate future milestones. Existing Vercel, Ollama, GPUs and academic servers are not modified by this release. The package never connects to KIOS or installs third-party skills/models.
