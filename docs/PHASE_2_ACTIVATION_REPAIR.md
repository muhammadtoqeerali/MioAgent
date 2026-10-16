# Phase 2 local model activation repair

## Why the original deployment failed

- `configure_model.py` generated owner-private `/var/tmp/mioagent-native-<uid>/model.env` correctly, but native API startup did not load that file; `MIO_LOCAL_MODEL` stayed blank.
- `ollama` being installed does not imply its HTTP service is running on loopback port 11434.
- The earlier port 3000 collision blocked one installer run; a later explicit native startup succeeded. Never kill an unidentified process on port 3000 just to make installation pass.

## Repair scope

`native_runtime.py` now reads and validates protected `model.env`, injecting allowed `MIO_` settings into the API child process. Remote/cloud routing is explicitly disabled for this workstation profile. The separate `ollama_native.py` can start, query, download models through, and stop a user-owned Ollama service on `127.0.0.1:11434`. It never kills a non-owned service, changes Docker configuration, or requires `sudo`.

## Run

1. Unpack repair ZIP into the existing project directory.
2. `bash scripts/repair_phase2_activation.sh`
3. `python3 scripts/ollama_native.py pull gpt-oss:20b` (explicit large download; use the model configured in your `model.env`)
4. `python3 scripts/phase2_smoke.py` (real inference test)
5. Open laptop Chrome at `http://127.0.0.1:13000/assistant` using the existing SSH tunnel.

Model weights for a newly managed service are located at `$HOME/MioAgentModels` by default, **outside Git**. If your home is on NTFS, these model weights are potentially writable by other workstation users; use trusted model sources and migrate to a suitably protected store before sensitive tasks. API credentials and SQLite continue in private `/var/tmp/mioagent-native-<uid>/`. The directory may be removed by maintenance and is not suitable for permanent production secrets.

Running the API smoke test only confirms API, queue, storage, and proxy. Real inference acceptance requires that a model has been downloaded and `phase2_smoke.py` completes with a nonempty answer and plan. This repair does not implement voice, autonomous shell/browser access, or unrestricted self-modification.

The old generated `model.env` is not changed. Git commits must not include secrets, DB files, or model weights. Do not publish Phase 2 until actual model inference and frontend access are verified.
