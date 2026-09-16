# Contributing to AstraSQL

Thanks for your interest in contributing.

## Development setup

1. Fork and clone the repository.
2. Copy `.env.example` to `.env` and set `OPENAI_API_KEY` plus a non-default `ENCRYPTION_KEY`.
3. Backend:

   ```bash
   cd backend
   uv sync --extra dev
   uv run uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
   ```

4. Frontend:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

Or use `docker compose up --build` from the repo root.

## Guidelines

- Keep changes focused; prefer small pull requests.
- Match existing code style (Python: Ruff; frontend: TypeScript + Tailwind patterns already in the tree).
- Add or update tests when you change backend behavior that is easy to unit-test (validators, API health, provider registry).
- Do not commit `.env`, API keys, or real database credentials.
- Be accurate in docs: only claim database types / features that are actually available.

## Pull requests

1. Create a branch from `main`.
2. Make your change with a clear commit message.
3. Ensure CI passes (lint, backend tests, frontend build).
4. Open a PR describing **why** the change is needed and how you verified it.

## Code of conduct

Be respectful in issues and PRs. Harassment or abusive behavior is not welcome.
