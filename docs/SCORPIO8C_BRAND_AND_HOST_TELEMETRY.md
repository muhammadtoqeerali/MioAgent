# SCORPIO8C — premium scorpion mark and measured API-host resources

## Scope

This release replaces the public Scorpio mark with a scalable, vector-drawn, transparent 128×128 SVG comprising multiple articulated armor segments, claws, legs and a curled tail. It enhances the existing sidebar logo without changing any chat, project, Work or approval behavior.

It adds a **read-only authenticated** `GET /api/system/telemetry` endpoint. The existing dashboard proxy supplies the API bearer token server-side. It reports Linux CPU percentage sampled from `/proc/stat`, Linux `MemAvailable` and `MemTotal`, disk usage of the **configured MioAgent workspace** and **native Work storage**, plus one or more **locally visible NVIDIA GPUs** using a bounded, no-shell `nvidia-smi` query. All figures identify the host on which the API process is running. A remote GPU is never implied to be locally measured. Missing sensors produce explicit `unavailable`, not a fabricated zero. There are no user-supplied filesystem paths, command strings, service controls or grants. The API endpoint requires the existing token; the public `/health` endpoint remains unchanged.

The Scorpio global frame shows a resource panel under the Control Room and System Health pages, populated every 12 seconds by `mioApi("system/telemetry")`. All existing Chat / Project / Work pages remain in the persistent Scorpio shell. Before the API deploys, the panel must show the endpoint is unavailable instead of displaying fake readings. The runtime model host, image ComfyUI GPU and separate workers **may be on other machines** and are not included unless their own authenticated, explicitly scoped collectors are later implemented.

## Lifecycle and limitations

A guarded **source-only install and regression** precedes selective Git publication. API and dashboard deployment require separate approvals with process identity verification, existing resource database preservation, backup and rollback. Do not use old 8B deployment controller after this commit: its source checks pin the old release. This first telemetry release does not implement remote resource monitoring, GPU vendor support beyond NVIDIA, per-process CPU attribution, runtime tool permission grants, task checkpointing, or autonomous terminal access. The following supervisor milestone must implement durable owner requests, task-scoped grants, immutable audit events, bounded sandbox execution and restart-safe resume before exposing any controls.

## Manual test after explicitly approved deployment

1. Open `/control-room` and `/system-health`; verify the improved scorpion mark scales crisply.
2. Confirm both pages show the **API host name** and CPU, RAM, volumes and available local NVIDIA GPUs; unavailable GPU reporting must say so plainly.
3. Compare CPU/RAM/storage against commands run **on that API host**, not an arbitrary browser machine.
4. Verify `/api/proxy/system/telemetry` responds through authenticated local Next.js proxy; unauthorized direct API requests return 401.
5. Confirm the API, worker, dashboard and ComfyUI PIDs after selective service deployment, Git status, data integrity and original 11 unrelated source digests.
