# MioAgent v0.4F — Live intelligence & repository evidence dashboard

The v0.4E release shipped Python CLI capabilities but no React UI changes, so `127.0.0.1:13000` still showed the old dashboard. v0.4F adds a linked `Intelligence & Engineering` page at `/intelligence`.

The Ubuntu dashboard is bound to **127.0.0.1:3000**. The Windows address **127.0.0.1:13000** is usable only when an SSH tunnel explicitly forwards the port, e.g. `ssh -N -L 13000:127.0.0.1:3000 toqeer@157.27.31.126` from Windows while that user's VPN/connection is available. The dashboard must be the Ubuntu managed process, not a separate old local development server.

The page displays live installed Ollama model names, active model priorities for seven roles, recent existing-repository engineering run outcomes, an authenticated verified patch preview, goal-engineering report summaries, and honest availability of capabilities. It makes only read-only calls to `/api/intelligence/overview` and `/api/intelligence/repository/<64-char-digest>/patch`, through the existing local server-side bearer-token proxy. It never applies patches or creates tasks. Existing `v0.4E` CLI approval remains the only way to apply existing-repository changes.

The FastAPI endpoint checks its bearer token, checks private directory/file ownership and permissions, only enumerates fixed private native runtime subdirectories, limits file sizes and entry count, and refuses symlinked records. It does not accept arbitrary filesystem paths. Vercel proxy remains disabled.

A successful installation must rebuild Next.js, test API auth and frontend build, restart both managed processes, and smoke `http://127.0.0.1:3000/intelligence` and `http://127.0.0.1:8000/api/intelligence/overview` with the native bearer token before any Git commit/push.

The API `/health` legacy service version is not an accurate frontend version indicator. The new UI visibly labels itself `v0.4F DASHBOARD` and `UI release v0.4F`.

Limitations: UI is a read-only evidence viewer and is not yet a browser IDE, arbitrary filesystem editor, or general agent launcher. It intentionally does not expose operator credentials or automatically approve changes.
