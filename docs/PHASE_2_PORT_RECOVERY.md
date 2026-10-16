# Phase 2 — Port and startup recovery (2026-10-16)

## Root cause under investigation

The original preflight checked TCP port availability by `socket.bind()` immediately
following a controlled service shutdown. Such checks can report a busy port
while old TCP connections remain in `TIME_WAIT`, even when no service is
actively listening. Logs showed the services had stopped before that preflight
failed. This is a plausible explanation, but must be verified on the workstation.

The new preflight asks `ss -H -ltnp` for **active TCP LISTEN sockets** rather
than assuming any bind failure means an active server. `ss` is already available
on the workstation. The native runtime makes the same distinction.

If an actual listener owns port 3000 or 8000, the script prints its owner and
exits. **It never kills unidentified processes.** SSH-tunneled access is still
used; do not expose the local API or Ollama ports to the LAN.

## Install and test

```bash
cd /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
bash scripts/repair_phase2_activation.sh
python3 scripts/ollama_native.py pull gpt-oss:20b
python3 scripts/phase2_smoke.py
```

The first model download may be large and is user-initiated. No cloud fallback
is enabled. Once the model actually responds, use `bash scripts/publish_phase2.sh`
for a reviewed GitHub commit, adding this port-recovery fix to the staged set.

## Check a real port conflict

```bash
ss -H -ltnp 'sport = :3000'
ss -H -ltnp 'sport = :8000'
ss -H -tan state time-wait 'sport = :3000'
python3 scripts/native_runtime.py status
python3 scripts/native_runtime.py logs
```

Do not execute generic `pkill node`, `kill -9`, `fuser -k`, change Docker socket
permissions, or bind MioAgent to `0.0.0.0`. Identify any live listener first.

## Zsh paste behavior

Interactive `zsh` may interpret pasted `#` comment lines as commands and
unescaped parentheses as glob patterns. Run prepared commands inside a Bash
heredoc or use scripts from `bash` as shown above.

## Known constraints

- Native Phase 2 still requires a working local Ollama installation and model.
- A successful Python/Next.js test build does not imply real model inference.
- Native services do not automatically restart after reboot.
- The local SQLite database and private model configuration are preserved.
