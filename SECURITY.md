# Security Policy

## Supported versions

Security fixes are applied on the latest `main` branch and the most recent `v0.x` release tag.

## Deployment warnings (v0.1)

AstraSQL currently has **no built-in authentication or authorization**.

- Do **not** expose the UI or API on a public network without your own access control (reverse proxy auth, VPN, firewall, etc.).
- Anyone who can reach the API can create database connections, run read-only queries, and read query history.
- Always set a strong unique `ENCRYPTION_KEY`. When `DEBUG=false`, the process refuses to start if the placeholder default key is still configured.
- Keep `OPENAI_API_KEY` and database credentials out of git; use `.env` locally and a secret store in production.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security reports.

Email or message the repository maintainers privately (GitHub Security Advisories preferred when available on this repository), and include:

1. Description of the issue
2. Steps to reproduce
3. Impact assessment (if known)
4. Suggested fix (optional)

We aim to acknowledge reports within a few business days.
