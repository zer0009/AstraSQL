# AstraSQL

Self-hosted natural-language-to-SQL: ask questions in plain English, get dialect-aware SQL, results, and a feedback loop that improves future answers.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](backend/pyproject.toml)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](docker-compose.yml)

> **Security:** AstraSQL v0.1 has **no built-in authentication**. Run it on localhost, or behind your own reverse proxy / VPN / auth gateway. Do not expose the API or UI directly to the public internet.

## What it does

- **Chat** — natural-language questions with SSE streaming, SQL preview, results table/charts
- **Connections** — connect to PostgreSQL, test, and scan schema metadata
- **Context** — enrichments, business rules, and golden Q→SQL records (FAISS retrieval)
- **Feedback** — thumbs up/down promotes useful answers into golden records
- **History** — review past queries, re-run, export CSV/JSON/XLSX

## Requirements

- Docker (recommended) **or** Python 3.11+ and Node.js 20+
- An [OpenAI API key](https://platform.openai.com/)
- A **PostgreSQL** database you can connect to (MySQL / MSSQL are on the roadmap)

## Quick start (Docker)

```bash
cp .env.example .env
# set OPENAI_API_KEY and a strong ENCRYPTION_KEY (required when DEBUG=false)

docker compose up --build
```

- UI: [http://localhost:3000](http://localhost:3000)
- API: [http://localhost:8000](http://localhost:8000)
- Health: [http://localhost:8000/health](http://localhost:8000/health)

Persistent data (SQLite + FAISS indexes) lives in the `astrasql_data` volume at `/app/data`.

## Local development

### Backend

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
cd backend
uv sync --extra dev
cp ../.env.example ../.env   # or place .env in backend/
uv run uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to the backend in development. Open the printed local URL (typically `http://localhost:5173`).

## Adding a database connection

1. Open **Connections** in the UI.
2. Create a PostgreSQL connection (host, port, database, user, password, SSL).
3. **Test** connectivity, then **Scan** to ingest table metadata for the context layer.
4. Use **Chat** with that connection selected.

**Supported today:** PostgreSQL only. MySQL and Microsoft SQL Server providers are stubs on the roadmap.

## Context enrichment, golden records, and feedback

- **Enrichments** — human descriptions, aliases, and example values for tables/columns so the agent links schema more accurately.
- **Business rules** — free-text constraints (e.g. “active customers means status = 'A'”) injected into generation.
- **Golden records** — curated question → SQL pairs; indexed with FAISS and retrieved as few-shot examples.
- **Feedback loop** — thumbs-up on History promotes that Q/SQL into golden records and rebuilds the index; thumbs-down records a negative rating for filtering and review.

Manage context under **Context**; review past runs under **History**.

## Architecture

| Layer | Role |
| --- | --- |
| **Frontend** | React + Vite UI (Chat, Connections, Context, History, Settings) |
| **API** | FastAPI (`/api/*`), SSE streaming for query runs |
| **Agent** | LangGraph pipeline: intent → schema link → SQL generate → validate → execute → format |
| **Context Layer** | Schema enrichments, business rules, golden Q→SQL records, FAISS retrieval |
| **Providers** | Pluggable **LLM** (OpenAI) and **database** drivers (PostgreSQL today) |
| **Storage** | SQLite metadata (connections, history, context) + encrypted credentials |

```
Question → LangGraph agent → Context retrieval → Dialect SQL → Readonly execute → Answer + confidence
                                    ↑
                         enrichments / rules / golden records / ratings
```

## Security

- **No authentication** in v0.1 — anyone who can reach the API can manage connections and run read-only SQL against configured databases.
- Set a unique `ENCRYPTION_KEY` before production-like use. The app **refuses to start** when `DEBUG=false` and the default placeholder key is still set.
- Prefer TLS termination at a reverse proxy if you leave localhost.
- See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## Environment variables

| Variable | Description | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI API key | _(empty)_ |
| `OPENAI_MODEL` | Chat model | `gpt-5.6-luna` |
| `LLM_PROVIDER` | LLM provider key | `openai` |
| `ENCRYPTION_KEY` | Secret used to derive Fernet key for DB passwords | _(must set when DEBUG=false)_ |
| `SQLITE_URL` | Async SQLAlchemy URL for app metadata | `sqlite+aiosqlite:///./data/astrasql.db` |
| `DATA_DIR` | Data directory (SQLite path relative, FAISS indexes) | `./data` |
| `CORS_ORIGINS` | Comma-separated browser origins | `http://localhost:5173,http://localhost:3000` |
| `MAX_RESULT_ROWS` | Cap on query result rows | `500` |
| `DEBUG` | SQL echo / allow default encryption key | `false` |

Copy `.env.example` to `.env` before `docker compose up`. Never commit real API keys.

## Adding a new database provider

Three steps:

1. **Implement** a class extending `BaseDatabaseProvider` in `backend/src/providers/database/` (set `available = True`, dialect prompts, sqlglot dialect, async engine, schema introspection, readonly execute, EXPLAIN, test).
2. **Register** it in `backend/src/providers/database/registry.py` (`_REGISTRY` and optional aliases).
3. **Export** from `backend/src/providers/database/__init__.py` if you want a public import path.

The new type appears in `GET /api/settings/public` → `database_types` and in the Connections UI once it is marked available.

## Roadmap

- Auth / multi-user access control
- MySQL and Microsoft SQL Server connectors
- Additional LLM providers (Azure OpenAI, Anthropic, local models)
- Stronger governance (audit log, row/column policies)
- Evaluation tooling around golden records

## Project layout

```
AstraSQL/
├── backend/          # FastAPI + LangGraph + providers
├── frontend/         # React SPA (nginx in Docker)
├── docker-compose.yml
├── .env.example
├── LICENSE
└── README.md
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and pull requests are welcome.

## License

Copyright 2026 AstraSQL contributors.

Licensed under the [Apache License, Version 2.0](LICENSE).
