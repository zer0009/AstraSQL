# Changelog

All notable changes to AstraSQL will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-16

### Added

- Apache-2.0 license and public-release documentation (`README`, `SECURITY`, `CONTRIBUTING`)
- Startup fail-fast when `DEBUG=false` and `ENCRYPTION_KEY` is still the placeholder default
- GitHub Actions CI (Ruff, pytest, frontend build)
- Smoke tests for health endpoint, SQL DML guard, and available database types
- GitHub issue templates for bugs and feature requests

### Changed

- Version set to `0.1.0` for the initial public release
- Public settings / Connections UI surface **PostgreSQL** only (MySQL/MSSQL remain unimplemented stubs)
- UI branding updated to general AstraSQL (removed “Enterprise NL2SQL” labels)
- README accuracy: PostgreSQL-only support, security warnings, roadmap

### Security

- Documented no-auth deployment model for v0.1
- Reject insecure default encryption key outside debug mode
