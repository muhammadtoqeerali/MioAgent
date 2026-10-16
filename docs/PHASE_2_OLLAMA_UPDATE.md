# Phase 2 Ollama model manifest compatibility

Ollama returned HTTP 412 when pulling `gpt-oss:20b`, indicating that the installed `/usr/local/bin/ollama` is too old.

A user-owned binary upgrade is provided in `scripts/upgrade_ollama_user.sh`. It installs an official pinned v0.34.1 AMD64 archive (SHA256 verification against the [upstream release](https://github.com/ollama/ollama/releases/tag/v0.34.1)) in `/var/tmp/mioagent-ollama-binaries-<uid>`, without sudo or altering system packages. It does not install an updater daemon.

The script stops only the MioAgent-owned Ollama service, refuses unrelated port listeners, verifies the download checksum, checks filesystem ownership and free space, extracts on native Linux storage, and restarts the service using the user-owned executable. The existing model directory stays untouched. A large archive download (~1.33 GB) is required; `gpt-oss:20b` weights require a separate download.

Run:

```bash
bash scripts/upgrade_ollama_user.sh
python3 scripts/ollama_native.py pull gpt-oss:20b
python3 scripts/phase2_smoke.py
```

The scripts deliberately preserve the current SQLite database and existing dashboard. Neither AI task completion nor GPU acceleration is accepted until a genuine model smoke test finishes. The user-owned binary under `/var/tmp` is not a durable deployment across system cleanup. Future phases should move binaries, model data, and tokens to a protected persistent native Linux partition.

The user-owned Ollama binary is selected consistently for managed process detection, startup, and downloads. Use `python3 scripts/ollama_native.py status`, `... start`, `... stop` and `... pull` instead of invoking the potentially older `/usr/local/bin/ollama` directly.
