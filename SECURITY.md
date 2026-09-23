# Security Policy

## Supported versions

Security fixes are applied on the latest `main` branch and the most recent `v0.x` release tag.

## Deployment warnings

AstraSQL uses a **single local admin** with an HttpOnly session cookie.

- Change the default password (`admin` / `AstraSQL-change-me`) on first login. The API rejects all other routes until you do.
- Override `DEFAULT_ADMIN_PASSWORD` in `.env` if you do not want the documented default on a fresh volume.
- Prefer TLS at a reverse proxy. When `DEBUG=false`, the session cookie is marked `Secure`.
- Do **not** expose the UI or API on a public network without HTTPS.
- Always set a strong unique `ENCRYPTION_KEY`. When `DEBUG=false`, the process refuses to start if the placeholder default key is still configured.
- Keep `OPENAI_API_KEY` and database credentials out of git; use `.env` locally and a secret store in production.
- This release is still single-tenant: every signed-in admin can see all connections and history.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security reports.

Email or message the repository maintainers privately (GitHub Security Advisories preferred when available on this repository), and include:

1. Description of the issue
2. Steps to reproduce
3. Impact assessment (if known)
4. Suggested fix (optional)

We aim to acknowledge reports within a few business days.
