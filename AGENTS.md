# Guidance for code-writing agents

Read `docs/MASTER_PLAN.md` and `docs/SECURITY_MODEL.md` before implementing MioAgent changes. Respect locked scope and use new ADRs for major architectural changes. Prefer cohesive complete-file changes over fragmented patches. Keep phase claims accurate and test changes before proposing GitHub publication. Never commit `.env` files, credentials, private memory or datasets. Do not add unrestricted host shell, browser control, unsandboxed code execution, or stealthy background behavior. All external actions require scoped permissions.
