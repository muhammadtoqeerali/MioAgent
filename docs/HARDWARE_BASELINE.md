# Workstation hardware baseline — 2026-10-15

Derived from supplied command output; not independently read from the workstation.

| Component | Observed value |
|---|---|
| Host | iot4care-workstation |
| OS | Ubuntu 22.04.5 LTS / Linux 6.8.0-138-generic |
| CPU | AMD Ryzen 9 7950X, 16 physical cores, 32 hardware threads |
| RAM | 187 GiB total, approximately 175 GiB available at measurement time |
| Swap | 2.0 GiB total, approximately 1.5 GiB used (at measurement time) |
| GPU 0 | NVIDIA RTX 4090, 24,564 MiB VRAM |
| GPU 1 | NVIDIA RTX 4090, 24,564 MiB VRAM |
| NVIDIA driver | 580.178.04; nvidia-smi reports CUDA compatibility 13.0 |
| Filesystem | /dev/sda2 mounted at /mnt/hdd16T; 17 TB total, ~12 TB available |
| Python | 3.13.12 |
| Node.js | 22.22.3 |
| Docker | 28.4.0 |
| Git | 2.34.1 |
| Root project | /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent/ |
| Initial state | Empty directory, not a Git repository, root-owned mode 0777 as printed |

**Cautions:** GPU device memory is separate (do not treat as automatically pooled). NVIDIA drivers do not prove NVIDIA Container Toolkit is installed. CUDA toolkit runtime inside container is not required for the Phase 1 stack. Filesystem ownership/mount options should be checked with `findmnt -T <project>` and `stat` before making any permission change; do not recursively chown a 17 TB mount. Low reported 'free' RAM is not a problem by itself when Linux has a large reclaimable cache; observe 'available' RAM. Swap utilization deserves monitoring but is not a blocker.

## Next audit commands

```bash
findmnt -T /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent -o TARGET,SOURCE,FSTYPE,OPTIONS
stat -c '%U:%G %a %n' /mnt/hdd16T/ToqeerHomeBackup/toqeer/MioAgent
docker compose version
docker info --format '{{.ServerVersion}}'
command -v nvidia-ctk || true
nvidia-smi -L
```

Keep any machine-specific secrets or output that contains credential paths out of the public repository.
