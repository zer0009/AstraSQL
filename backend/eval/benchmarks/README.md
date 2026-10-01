# Benchmark ladder (AstraSQL eval)

Downloaded datasets live under `data/` (git-ignored). Point env vars at local
copies after accepting each dataset’s license.

## Tier ladder

| Tier | Focus | Module(s) | Path / env |
|------|--------|-----------|------------|
| **A** | Clean Spider accuracy | `src.eval.pilot`, `src.eval.spider_data` | `eval/benchmarks/data/spider/` |
| **B** | Robustness: Dr.Spider / Spider-Realistic + schema perturbation | `src.eval.drspider_data`, `src.eval.perturb` | `DRSPIDER_ROOT` or `data/drspider/`; perturb copies any Spider/BIRD sqlite |
| **C** | LiveSQLBench + HKB semantic layer | `src.eval.livesqlbench_data` | `LIVESQLBENCH_ROOT` or `data/livesqlbench/` |
| **D** | Domain / unanswerable: EHRSQL, Olist, Odoo | `src.eval.ehrsql_data`, `src/eval/olist_gold.json`, `src/eval/odoo_gold.json` | `EHRSQL_ROOT`; Olist/Odoo gold are fixtures — set `OLIST_DB_PATH` / `ODOO_DB_PATH` on the connection |
| **E** | Latency: TPC-H style probes | `src.eval.tpc_bench` | `TPC_DB_PATH` (preloaded warehouse DB; no data generator) |

Also: **BIRD Mini-Dev** (`src.eval.bird_data`, `data/bird/`) and **Spider 2.0-lite** (`src.eval.spider2_data`, `data/spider2/`) as relative enterprise-stress metrics.

## Ambiguity / must-clarify (prefer `ambiguity_eval`)

Product ask-precision uses **`src.eval.ambiguity_eval`**, not the Spider pilot:

- Fixture: [`must_clarify.json`](./must_clarify.json) in this folder
- Optional BIRD-Interact-Lite local JSON via `--bird-interact` / `load_bird_interact_items`
- Scoring: ask **precision/recall** (clear → do not clarify; amb → clarify)
- Runner: `run_ambiguity_suite(...)` (injectable `run_query_fn` for tests)

```bash
# Load + preview items (no LLM)
uv run python -m src.eval.ambiguity_eval

# Score a precomputed cases file: [{expect, clarified}, ...]
uv run python -m src.eval.ambiguity_eval --score-only path/to/cases.json
```

Wire a live `Connection` in a script or notebook:

```python
from src.eval.ambiguity_eval import load_must_clarify, run_ambiguity_suite
report = await run_ambiguity_suite(load_must_clarify(), connection=conn, session=session)
print(report["scores"])  # precision / recall / f1
```

## Tier A — Spider 1.0 (dev)

- License: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
- Citation: Yu et al., EMNLP 2018
- Source package: Hugging Face `HAL-9001/spider-databases` (`spider_data.zip`)

```bash
uv run python -m src.eval.pilot --download-only
uv run python -m src.eval.pilot --dbs 5 --per-db 5 --model gpt-5.6-luna --out eval/results/run25.json
uv run python -m src.eval.pilot --dbs 10 --per-db 10 --model gpt-5.6-luna --out eval/results/run100.json
uv run python -m src.eval.pilot compare eval/results/run25.json eval/results/run25-variance.json
uv run python scripts/eval_gate.py --baseline eval/results/run25.json --candidate eval/results/run25-variance.json
```

## Tier B — Dr.Spider + perturbation

```text
DRSPIDER_ROOT=/path/to/drspider   # or place JSON under data/drspider/
```

```python
from src.eval.perturb import perturb_sqlite
meta = perturb_sqlite("path/to/db.sqlite", "path/to/db_perturbed.sqlite", seed=0)
# meta["column_renames"], meta["value_maps"], meta["notes"]
```

Flags: `cryptic_names`, `coded_values`, `drop_fks`, `soft_delete` (each optional).

## Tier C — LiveSQLBench

```text
LIVESQLBENCH_ROOT=/path/to/livesqlbench
# expected: tasks.json (+ optional kb.jsonl)
```

Use `hkb_to_semantic_layer_dict` / `hkb_to_semantic_layer_text` to inject HKB into
`connection.semantic_layer_json` before running tasks.

## Tier D — EHRSQL / Olist / Odoo

```text
EHRSQL_ROOT=/path/to/ehrsql
OLIST_DB_PATH=/path/to/olist.sqlite   # connection target for olist_gold.json
ODOO_DB_PATH=/path/to/odoo.db         # connection target for odoo_gold.json
```

Gold fixtures (GoldItem-compatible `items`):

- `backend/src/eval/olist_gold.json`
- `backend/src/eval/odoo_gold.json`

## Tier E — TPC latency probes

```text
TPC_DB_PATH=/path/to/tpch.sqlite
```

```python
from src.eval.tpc_bench import run_tpc_latency_probes
report = await run_tpc_latency_probes(db_provider)
# report["summary"]["elapsed_ms_mean"], report["probes"]
```

Does **not** generate TPC data — only executes fixed aggregate SQLs.

## BIRD Mini-Dev

Treat as a **relative** metric — annotation error rates are high in published studies.
Place files under `data/bird/mini_dev_sqlite/` (see `src/eval/bird_data.py`). No auto-download.

## Spider 2.0-lite

Wide-schema / enterprise-style stress. Place files under `data/spider2/lite/` (see `src/eval/spider2_data.py`).
