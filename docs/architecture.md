# AstraSQL Backend Architecture

This document describes the intended layering after the clean-architecture refactor.
It is a contract for maintainers: keep dependencies flowing in one direction.

## Layers

```text
api  →  services  →  storage
 │         │
 │         └→ providers (database / llm)
 ├→ agent → context → providers
 │            └→ storage
 └→ config (read-only settings)
```

| Layer | Path | Responsibility |
|-------|------|----------------|
| API | `backend/src/api/` | HTTP/SSE adapters, Pydantic schemas, thin routers |
| Services | `backend/src/services/` | Use-cases that span stores (golden promotion, scan jobs) |
| Agent | `backend/src/agent/` | LangGraph graph, nodes, SQL pipeline, trust/ambiguity |
| Context | `backend/src/context/` | Schema scan, retrieval, semantic layer, goldens/rules |
| Providers | `backend/src/providers/` | Dialect DB adapters and LLM adapters (registries) |
| Storage | `backend/src/storage/` | ORM models, migrations, crypto, small repositories |
| Config | `backend/src/config/` | Process settings (`llm_*` with `OPENAI_*` env aliases) |
| Eval | `backend/src/eval/` | Offline benchmarks only — not imported by API runtime |

## Allowed import directions

- `api` may import `services`, `agent` (runner / public helpers), `storage`, `providers`, `config`
- `api` must **not** import `agent.nodes` (node internals)
- `agent` may import `context`, `providers`, `storage` (via repositories when available), `config`
- `agent` must **not** import `api`
- `context` may import `providers`, `storage`, `config`
- `providers` may import `config` (and shared agent SQL guards when needed for execute safety)
- `services` may import `storage`, `providers`, `context`, `config`
- `eval` may import `agent` / `providers` for offline runs; runtime must not import `eval`

Enforced by `backend/tests/test_import_boundaries.py`.

## Provider seams

### Database

- Contract: `BaseDatabaseProvider` (`dialect_name`, `sqlglot_dialect`, `execute_readonly`, …)
- Registry: `get_database_provider` / `normalize_db_type` / `provider_from_connection`
- Capabilities: `supports_explain`, `supports_execute_gate`, `needs_deterministic_repair`
- Implemented: PostgreSQL (public), SQLite/MySQL/MSSQL registered (some `available=False`)

Agent SQL helpers take an explicit `dialect` from `db_provider.sqlglot_dialect()` — no silent Postgres default.

### LLM

- Contract: `BaseLLMProvider` (`get_chat_model`, `get_embedding_model`, `default_model`)
- Registry: `get_llm_provider` / `register_llm_provider`
- Settings: `llm_api_key`, `llm_model`, `embedding_model` (env aliases `OPENAI_*` still work)
- Implemented today: OpenAI only — add providers by registering a new class, not by branching in nodes

### Business / domain

Connection-scoped, not hard-coded in the engine:

- Semantic layer JSON on `Connection`
- Golden records, business rules, schema enrichments in metadata DB
- Learning loop appends reviewed Q→SQL into the semantic layer

## Agent graph (runtime)

```text
START → context_retriever
      → [interpretation_resolver] → query_generator
      → ambiguity_gate → query_validator → query_executor → response_formatter → END
      ↘ direct_response → END
```

Configured in `agent/graph.py` via `build_graph()` / `get_graph()`.

## Working rules

1. Prefer moving code behind existing interfaces over adding features in routers.
2. Keep routers thin; put multi-step domain logic in `services/`.
3. Thread dialect and provider capabilities — never hard-code `"postgres"` / `"mysql"` outside provider modules.
4. Behavior-preserving refactors: re-export from old module paths until all callers are updated.
