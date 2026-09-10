# AstraSQL V2

Enterprise natural-language-to-SQL: ask questions in plain English, get dialect-aware SQL, results, and a feedback loop that improves future answers.

## Architecture

| Layer | Role |
| --- | --- |
| **Frontend** | React + Vite UI (Chat, Connections, Context, History, Settings) |
| **API** | FastAPI (`/api/*`), SSE streaming for query runs |
| **Agent** | LangGraph pipeline: intent → schema link → SQL generate → validate → execute → format |
| **Context Layer** | Schema enrichments, business rules, golden Q→SQL records, FAISS retrieval |
| **Providers** | Pluggable **LLM** (OpenAI) and **database** drivers (PostgreSQL, MySQL, MSSQL) |
| **Storage** | SQLite metadata (connections, history, context) + encrypted credentials |

```
Question → LangGraph agent → Context retrieval → Dialect SQL → Readonly execute → Answer + confidence
                                    ↑
                         enrichments / rules / golden records / ratings
```

## Quick start (Docker)

```bash
cp .env.example .env
# set OPENAI_API_KEY (and optionally ENCRYPTION_KEY)

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
uv sync
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
2. Create a connection (type, host, port, database, user, password, SSL).
3. **Test** connectivity, then **Scan** to ingest table metadata for the context layer.
4. Use **Chat** with that connection selected.

Supported types out of the box: `postgresql`, `mysql`, `mssql`.

## Context enrichment, golden records, and feedback

- **Enrichments** — human descriptions, aliases, and example values for tables/columns so the agent links schema more accurately.
- **Business rules** — free-text constraints (e.g. “active customers means status = 'A'”) injected into generation.
- **Golden records** — curated question → SQL pairs; indexed with FAISS and retrieved as few-shot examples.
- **Feedback loop** — thumbs-up on History promotes that Q/SQL into golden records and rebuilds the index; thumbs-down records a negative rating for filtering and review.

Manage context under **Context**; review past runs under **History**.

## Adding a new database provider

Three steps:

1. **Implement** a class extending `BaseDatabaseProvider` in `backend/src/providers/database/` (dialect prompts, sqlglot dialect, async engine, schema introspection, readonly execute, EXPLAIN, test).
2. **Register** it in `backend/src/providers/database/registry.py` (`_REGISTRY` and optional aliases).
3. **Export** from `backend/src/providers/database/__init__.py` if you want a public import path.

The new type appears in `GET /api/settings/public` → `database_types` and in the Connections UI once the frontend lists those types.

## Environment variables

| Variable | Description | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI API key | _(empty)_ |
| `OPENAI_MODEL` | Chat model | `gpt-4o` |
| `LLM_PROVIDER` | LLM provider key | `openai` |
| `ENCRYPTION_KEY` | Secret used to derive Fernet key for DB passwords | `change-me-to-a-32-byte-secret!!` |
| `SQLITE_URL` | Async SQLAlchemy URL for app metadata | `sqlite+aiosqlite:///./data/astrasql.db` |
| `DATA_DIR` | Data directory (SQLite path relative, FAISS indexes) | `./data` |
| `CORS_ORIGINS` | Comma-separated browser origins | `http://localhost:5173,http://localhost:3000` |
| `MAX_RESULT_ROWS` | Cap on query result rows | `500` |
| `DEBUG` | SQL echo / debug mode | `false` |

Copy `.env.example` to `.env` before `docker compose up`. Never commit real API keys.

## Project layout

```
AstraSQL_V2/
├── backend/          # FastAPI + LangGraph + providers
├── frontend/         # React SPA (nginx in Docker)
├── docker-compose.yml
├── .env.example
└── README.md
```

## License

Proprietary — internal use unless otherwise specified.
