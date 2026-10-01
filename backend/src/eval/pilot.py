"""Spider accuracy pilot: tokens, time, cost, values-only score, failure labels.

Examples:
  uv run python -m src.eval.pilot --n 5 --model gpt-5.6-luna
  uv run python -m src.eval.pilot --dbs 5 --per-db 5 --model gpt-5.6-luna
  uv run python -m src.eval.pilot rescore eval/results/pilot-….json
  uv run python -m src.eval.pilot --from-report eval/results/run25-….json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from src.config.settings import get_settings
from src.eval.compare import results_equal, results_equal_values, sql_equal
from src.eval.failure_labels import extract_tables, label_failure
from src.eval.models import CaseResult, GoldItem
from src.eval.spider_data import (
    db_sqlite_path,
    default_pilot_db,
    ensure_spider_data,
    load_dev,
    pick_multi_db,
    pick_stratified,
    question_stable_id,
)
from src.eval.usage import (
    RateCard,
    UsageTracker,
    extrapolate,
    track_usage,
    usage_case,
    usage_stage,
)
from src.storage.crypto import encrypt_password
from src.storage.database import get_session_factory
from src.storage.models import Connection, SchemaCache

_BACKEND = Path(__file__).resolve().parents[2]
_RESULT_PREVIEW_ROWS = 8


def _pin_models(model: str, reasoning_effort: str) -> dict[str, str]:
    os.environ["OPENAI_MODEL"] = model
    os.environ["ENRICHMENT_MODEL"] = model
    os.environ["INTERPRETATION_MODEL"] = model
    if reasoning_effort:
        os.environ["LLM_REASONING_EFFORT"] = reasoning_effort
    get_settings.cache_clear()
    settings = get_settings()
    return {
        "openai_model": settings.openai_model,
        "enrichment_model": settings.enrichment_model,
        "interpretation_model": settings.interpretation_model or settings.enrichment_model,
        "llm_reasoning_effort": settings.llm_reasoning_effort,
        "embedding_model": settings.openai_embedding_model,
    }


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = (_BACKEND / p).resolve()
    return p


def _preview_result(payload: Optional[dict], *, max_rows: int = _RESULT_PREVIEW_ROWS) -> Optional[dict]:
    if not payload:
        return None
    rows = list(payload.get("rows") or [])
    return {
        "columns": list(payload.get("columns") or []),
        "row_count": int(payload.get("row_count") or len(rows)),
        "rows": rows[:max_rows],
        "truncated": len(rows) > max_rows,
    }


async def _get_or_create_sqlite_connection(
    session,
    *,
    db_id: str,
    sqlite_path: Path,
) -> Connection:
    name = f"spider-{db_id}"
    result = await session.execute(
        select(Connection).where(Connection.name == name)
    )
    conn = result.scalar_one_or_none()
    if conn is not None:
        conn.database = str(sqlite_path)
        conn.db_type = "sqlite"
        conn.host = "local"
        conn.port = 0
        await session.commit()
        return conn

    conn = Connection(
        id=str(uuid.uuid4()),
        name=name,
        db_type="sqlite",
        host="local",
        port=0,
        database=str(sqlite_path),
        username="",
        encrypted_password=encrypt_password(""),
        ssl_enabled=False,
    )
    session.add(conn)
    await session.commit()
    await session.refresh(conn)
    return conn


async def _ensure_scanned(session, connection: Connection, tracker: UsageTracker) -> dict[str, Any]:
    from src.context.auto_enricher import SchemaAutoEnricher
    from src.context.retriever import scan_connection_schema
    from src.context.schema_linker import SchemaLinker
    from src.providers.database.registry import provider_from_connection

    started = time.perf_counter()
    enriched = 0
    with usage_stage("setup_scan"), usage_case("setup"):
        result = await session.execute(
            select(SchemaCache).where(SchemaCache.connection_id == connection.id)
        )
        caches = list(result.scalars().all())
        provider = provider_from_connection(connection)
        try:
            if not caches:
                caches = await scan_connection_schema(
                    session, connection, provider, rebuild_table_index=True
                )
                await session.commit()
            try:
                enriched = await SchemaAutoEnricher().enrich_connection(
                    session, connection.id, caches
                )
                if enriched > 0:
                    await SchemaLinker().build_table_index(session, connection.id)
            except Exception as exc:
                print(f"Warning: enrichment failed ({exc}); continuing without it")
        finally:
            await provider.close()

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    setup_summary = tracker.summary_for_case("setup")
    return {
        "tables": len(caches),
        "enriched": enriched,
        "elapsed_ms": elapsed_ms,
        "cost_usd": setup_summary.get("cost_usd", 0.0),
        "usage": setup_summary,
    }


def _schema_linking_recall(
    selected_tables: list[str],
    gold_sql: Optional[str],
) -> dict[str, Any]:
    gold = extract_tables(gold_sql, dialect="sqlite")
    selected = {str(t).lower() for t in (selected_tables or [])}
    if not gold:
        return {
            "gold_tables": [],
            "selected_tables": sorted(selected),
            "hit": None,
            "recall": None,
        }
    hit = gold <= selected
    recall = (len(gold & selected) / len(gold)) if gold else None
    return {
        "gold_tables": sorted(gold),
        "selected_tables": sorted(selected),
        "hit": hit,
        "recall": recall,
    }


async def _execute_pair(
    provider: Any,
    *,
    generated_sql: Optional[str],
    gold_sql: Optional[str],
) -> tuple[Optional[dict], Optional[dict], Optional[str]]:
    gold_rows: Optional[dict] = None
    gen_rows: Optional[dict] = None
    err: Optional[str] = None
    if gold_sql:
        try:
            gold_rows = await provider.execute_readonly(gold_sql, max_rows=500)
        except Exception as exc:
            err = f"gold_exec: {exc}"
    if generated_sql:
        try:
            gen_rows = await provider.execute_readonly(generated_sql, max_rows=500)
        except Exception as exc:
            err = (err + "; " if err else "") + f"gen_exec: {exc}"
    return gold_rows, gen_rows, err


async def _score_one(
    session,
    connection: Connection,
    item: GoldItem,
    provider: Any,
    tracker: UsageTracker,
    *,
    hardness: str,
    db_id: str,
) -> tuple[CaseResult, dict[str, Any], int, dict[str, Any]]:
    from src.agent.runner import run_query
    from src.eval.run import _generated_sql, _is_clarified

    started = time.perf_counter()
    with usage_case(item.id):
        state = await run_query(session, connection, item.question)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    sql = _generated_sql(state)
    clarified = _is_clarified(state)
    silent_wrong = item.expect == "clarify" and bool(sql) and not clarified
    ctx = state.get("context") or {}
    selected_tables = list(ctx.get("selected_tables") or [])
    linking = _schema_linking_recall(selected_tables, item.gold_sql)

    sql_match: Optional[bool] = None
    result_match: Optional[bool] = None
    result_match_values: Optional[bool] = None
    gold_result: Optional[dict] = None
    gen_result: Optional[dict] = None
    exec_error: Optional[str] = None

    if item.expect == "answer" and item.gold_sql:
        sql_match = sql_equal(sql, item.gold_sql, dialect="sqlite")
        if provider is not None:
            gold_result, gen_result, exec_error = await _execute_pair(
                provider, generated_sql=sql, gold_sql=item.gold_sql
            )
            if gen_result is None and state.get("results"):
                gen_result = state.get("results")
            if gold_result is not None and gen_result is not None:
                result_match = results_equal(gold_result, gen_result)
                result_match_values = results_equal_values(
                    gold_result, gen_result, gold_sql=item.gold_sql
                )
            elif sql and gold_result is not None:
                result_match = False
                result_match_values = False

    error = state.get("error") or exec_error
    failure_label: Optional[str] = None
    if result_match_values is True and result_match is False:
        failure_label = "scorer_only"
    elif result_match_values is not True:
        failure_label = label_failure(
            question=item.question,
            gold_sql=item.gold_sql,
            generated_sql=sql,
            gold_result=gold_result,
            generated_result=gen_result,
            clarified=clarified,
            error=error,
            dialect="sqlite",
        )

    case = CaseResult(
        id=item.id,
        question=item.question,
        expect=item.expect,
        intent=state.get("intent"),
        trust_level=state.get("trust_level"),
        generated_sql=sql or None,
        error=error,
        sql_match=sql_match,
        result_match=result_match,
        clarified=clarified,
        silent_wrong=silent_wrong,
        used_golden=bool(state.get("used_golden")),
    )
    usage = tracker.summary_for_case(item.id)
    detail = {
        "db_id": db_id,
        "hardness": hardness,
        "result_match_values": result_match_values,
        "failure_label": failure_label,
        "gold_result": _preview_result(gold_result),
        "generated_result": _preview_result(gen_result),
        "schema_linking": linking,
        "retries": int(state.get("retries") or 0),
        "selected_tables": selected_tables,
    }
    return case, usage, elapsed_ms, detail


def _accuracy_breakdown(question_rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _rate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
        n = len(rows)
        strict = sum(1 for r in rows if r.get("result_match") is True)
        values = sum(1 for r in rows if r.get("result_match_values") is True)
        return {
            "n": n,
            "strict_correct": strict,
            "values_correct": values,
            "strict_accuracy": round(strict / n, 4) if n else 0.0,
            "values_accuracy": round(values / n, 4) if n else 0.0,
        }

    by_hardness: dict[str, Any] = {}
    by_db: dict[str, Any] = {}
    for key_name, bucket in (("hardness", by_hardness), ("db_id", by_db)):
        groups: dict[str, list] = defaultdict(list)
        for row in question_rows:
            groups[str(row.get(key_name) or "unknown")].append(row)
        for k, rows in sorted(groups.items()):
            bucket[k] = _rate(rows, key_name)

    labels = Counter(
        r.get("failure_label") or "pass"
        for r in question_rows
        if r.get("result_match_values") is not True
    )
    linking_hits = [
        r["schema_linking"]["hit"]
        for r in question_rows
        if isinstance(r.get("schema_linking"), dict)
        and r["schema_linking"].get("hit") is not None
    ]
    return {
        "overall": _rate(question_rows, "overall"),
        "by_hardness": by_hardness,
        "by_database": by_db,
        "failure_labels": dict(labels),
        "schema_linking_recall": {
            "n": len(linking_hits),
            "full_hit": sum(1 for h in linking_hits if h),
            "rate": round(sum(1 for h in linking_hits if h) / len(linking_hits), 4)
            if linking_hits
            else None,
        },
    }


def _print_report(report: dict[str, Any]) -> None:
    print("\n======== PILOT REPORT ========")
    models = report.get("models") or {}
    print(f"Model: {models.get('openai_model')}")
    print(
        f"Enrichment / interpretation: "
        f"{models.get('enrichment_model')} / {models.get('interpretation_model')}"
    )
    print(f"Reasoning effort: {models.get('llm_reasoning_effort') or '(default)'}")
    dbs = report.get("db_ids") or [report.get("db_id")]
    print(f"Databases: {dbs}  questions: {report.get('n')}")

    setup = report.get("setup") or {}
    if isinstance(setup, dict) and "by_db" in setup:
        total_cost = sum(float(v.get("cost_usd") or 0) for v in setup["by_db"].values())
        print(f"Setup (all DBs): cost=${total_cost:.6f}")
        for db, info in setup["by_db"].items():
            print(
                f"  {db}: tables={info.get('tables')} "
                f"cost=${info.get('cost_usd', 0):.6f} time={info.get('elapsed_ms')}ms"
            )
    else:
        print(
            f"Setup: tables={setup.get('tables')} cost=${setup.get('cost_usd', 0):.6f} "
            f"time={setup.get('elapsed_ms')}ms"
        )

    acc = report.get("accuracy") or {}
    overall = acc.get("overall") or {}
    print(
        f"\nAccuracy: values-only "
        f"{overall.get('values_correct', 0)}/{overall.get('n', 0)} "
        f"({100 * float(overall.get('values_accuracy') or 0):.1f}%)  |  "
        f"strict {overall.get('strict_correct', 0)}/{overall.get('n', 0)} "
        f"({100 * float(overall.get('strict_accuracy') or 0):.1f}%)"
    )
    if acc.get("by_hardness"):
        print("By hardness (values-only):")
        for hard, stats in acc["by_hardness"].items():
            print(
                f"  {hard}: {stats['values_correct']}/{stats['n']} "
                f"({100 * stats['values_accuracy']:.1f}%)"
            )
    if acc.get("by_database"):
        print("By database (values-only):")
        for db, stats in acc["by_database"].items():
            print(
                f"  {db}: {stats['values_correct']}/{stats['n']} "
                f"({100 * stats['values_accuracy']:.1f}%)"
            )
    if acc.get("failure_labels"):
        print("Failure labels:")
        for lab, n in sorted(acc["failure_labels"].items(), key=lambda x: -x[1]):
            print(f"  {lab}: {n}")
    sl = acc.get("schema_linking_recall") or {}
    if sl.get("rate") is not None:
        print(
            f"Schema-linking full recall: {sl.get('full_hit')}/{sl.get('n')} "
            f"({100 * float(sl['rate']):.1f}%)"
        )

    print("\nPer question:")
    for row in report.get("questions") or []:
        vok = row.get("result_match_values")
        sok = row.get("result_match")
        ok_s = "PASS" if vok is True else ("FAIL" if vok is False else "n/a")
        strict_s = "strict-ok" if sok is True else ("strict-fail" if sok is False else "")
        label = row.get("failure_label") or ""
        print(
            f"  [{ok_s}] {row['id']}  db={row.get('db_id')}  "
            f"hardness={row.get('hardness')}  {strict_s}  "
            f"label={label}  cost=${row['cost_usd']:.6f}  "
            f"time={row['elapsed_ms']}ms  "
            f"tokens_in={row['input_tokens']} out={row['output_tokens']} "
            f"reason={row['reasoning_tokens']}  calls={row['calls']}"
        )
        print(f"         Q: {row['question'][:120]}")
        if row.get("error"):
            print(f"         error: {row['error']}")
        if vok is not True:
            print(f"         gold SQL: {(row.get('gold_sql') or '')[:160]}")
            print(f"         gen  SQL: {(row.get('generated_sql') or '')[:160]}")

    totals = report.get("totals") or {}
    print("\nTotals (questions only):")
    print(
        f"  cost=${totals.get('cost_usd', 0):.6f}  "
        f"time={totals.get('elapsed_ms')}ms  "
        f"input={totals.get('input_tokens')}  "
        f"output={totals.get('output_tokens')}  "
        f"reasoning={totals.get('reasoning_tokens')}  "
        f"calls={totals.get('calls')}"
    )
    print("\nBy pipeline stage:")
    for stage, bucket in (report.get("by_stage") or {}).items():
        print(
            f"  {stage}: calls={bucket['calls']}  "
            f"in={bucket['input_tokens']} out={bucket['output_tokens']} "
            f"reason={bucket['reasoning_tokens']}  "
            f"cost=${bucket['cost_usd']:.6f}  time={bucket['latency_ms']}ms"
        )

    if report.get("extrapolation"):
        print("\nExtrapolation (from measured averages):")
        for name, ext in (report.get("extrapolation") or {}).items():
            print(
                f"  {name}: n={ext['n_questions']}  "
                f"est_cost=${ext['total_cost_usd']:.4f}  "
                f"est_time_h={ext['estimated_total_latency_ms'] / 3_600_000:.2f}"
            )
    print(f"\nWrote {report.get('out_path')}")
    print("==============================\n")


def _print_side_by_side(report: dict[str, Any]) -> None:
    print("\n======== GOLD vs GENERATED (failures + scorer_only) ========")
    for row in report.get("questions") or []:
        vok = row.get("result_match_values")
        sok = row.get("result_match")
        if vok is True and sok is True:
            continue
        print(f"\n--- {row.get('id')} [{row.get('failure_label')}] ---")
        print(f"Q: {row.get('question')}")
        print(f"Gold SQL:\n  {row.get('gold_sql')}")
        print(f"Gen  SQL:\n  {row.get('generated_sql')}")
        print(f"Gold result: {json.dumps(row.get('gold_result'), default=str)[:400]}")
        print(f"Gen  result: {json.dumps(row.get('generated_result'), default=str)[:400]}")
    print("============================================================\n")


async def _rescore_report(path: Path) -> dict[str, Any]:
    """Re-execute gold/generated SQL from a saved report. No LLM calls."""
    data = json.loads(path.read_text(encoding="utf-8"))
    root = ensure_spider_data()
    questions = list(data.get("questions") or [])
    from src.providers.database.sqlite import SQLiteProvider

    rescored: list[dict[str, Any]] = []
    for row in questions:
        db_id = str(row.get("db_id") or data.get("db_id") or "")
        if not db_id:
            # Infer from id prefix like concert_singer-0
            rid = str(row.get("id") or "")
            db_id = rid.rsplit("-", 1)[0] if "-" in rid else ""
        sqlite_path = db_sqlite_path(db_id, root)
        provider = SQLiteProvider(database=str(sqlite_path))
        try:
            gold_sql = row.get("gold_sql")
            gen_sql = row.get("generated_sql")
            gold_result, gen_result, exec_error = await _execute_pair(
                provider, generated_sql=gen_sql, gold_sql=gold_sql
            )
            strict = (
                results_equal(gold_result, gen_result)
                if gold_result is not None and gen_result is not None
                else False
            )
            values = (
                results_equal_values(gold_result, gen_result, gold_sql=gold_sql)
                if gold_result is not None and gen_result is not None
                else False
            )
            label = None
            if values and not strict:
                label = "scorer_only"
            elif not values:
                label = label_failure(
                    question=str(row.get("question") or ""),
                    gold_sql=gold_sql,
                    generated_sql=gen_sql,
                    gold_result=gold_result,
                    generated_result=gen_result,
                    clarified=bool(row.get("clarified")),
                    error=row.get("error") or exec_error,
                    dialect="sqlite",
                )
            updated = dict(row)
            updated["db_id"] = db_id
            updated["result_match"] = strict
            updated["result_match_values"] = values
            updated["failure_label"] = label
            updated["gold_result"] = _preview_result(gold_result)
            updated["generated_result"] = _preview_result(gen_result)
            if exec_error and not updated.get("error"):
                updated["error"] = exec_error
            rescored.append(updated)
        finally:
            await provider.close()

    accuracy = _accuracy_breakdown(rescored)
    out = {
        "kind": "spider-rescore",
        "source": str(path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n": len(rescored),
        "questions": rescored,
        "accuracy": accuracy,
        "original_totals": data.get("totals"),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = path.parent / f"rescore-{stamp}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    out["out_path"] = str(out_path)

    ov = accuracy["overall"]
    print("\n======== RESCORE (no LLM) ========")
    print(f"Source: {path}")
    print(
        f"Values-only: {ov['values_correct']}/{ov['n']} "
        f"({100 * ov['values_accuracy']:.1f}%)"
    )
    print(
        f"Strict:      {ov['strict_correct']}/{ov['n']} "
        f"({100 * ov['strict_accuracy']:.1f}%)"
    )
    print("Failure labels:", accuracy.get("failure_labels"))
    for row in rescored:
        vok = row.get("result_match_values")
        mark = "PASS" if vok else "FAIL"
        print(
            f"  [{mark}] {row.get('id')} strict={row.get('result_match')} "
            f"label={row.get('failure_label')}"
        )
        print(f"         Q: {(row.get('question') or '')[:100]}")
    print(f"Wrote {out_path}")
    print("==================================\n")
    _print_side_by_side(out)
    return out


def _load_questions_from_report(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for row in data.get("questions") or []:
        out.append(
            {
                "db_id": row.get("db_id") or data.get("db_id"),
                "question": row.get("question"),
                "query": row.get("gold_sql"),
                "_hardness": row.get("hardness") or "unknown",
                "_stable_id": row.get("id"),
            }
        )
    return out


def _select_questions(args: argparse.Namespace, items: list[dict], root: Path) -> list[dict]:
    if args.from_report:
        return _load_questions_from_report(_resolve_path(args.from_report))

    if args.db_ids:
        db_ids = [x.strip() for x in args.db_ids.split(",") if x.strip()]
        return pick_multi_db(
            items, db_ids=db_ids, per_db=args.per_db, seed=args.seed, root=root
        )

    if args.dbs and args.dbs > 0:
        return pick_multi_db(
            items, n_dbs=args.dbs, per_db=args.per_db, seed=args.seed, root=root
        )

    db_id = args.db or default_pilot_db(items)
    return pick_stratified(items, db_id=db_id, n=args.n, seed=args.seed)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.download_only:
        root = ensure_spider_data(force=args.force_download)
        print(root)
        return {"root": str(root)}

    model_info = _pin_models(args.model, args.reasoning_effort)
    settings = get_settings()
    if not (settings.openai_api_key or "").strip():
        raise SystemExit("OPENAI_API_KEY is not set")

    root = ensure_spider_data(force=args.force_download)
    items = load_dev(root)
    picked = _select_questions(args, items, root)
    if not picked:
        raise SystemExit("No questions selected")

    rate_card = RateCard.default()
    tracker = UsageTracker(rate_card=rate_card)
    factory = get_session_factory()
    question_rows: list[dict[str, Any]] = []
    cases: list[CaseResult] = []
    setup_by_db: dict[str, dict[str, Any]] = {}
    connections: dict[str, Connection] = {}

    # Group by db for scan-once
    by_db: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for i, raw in enumerate(picked):
        by_db[str(raw.get("db_id") or "")].append((i, raw))

    with track_usage(tracker):
        async with factory() as session:
            from src.providers.database.registry import provider_from_connection

            running_cost = 0.0
            # Scan each DB once
            for db_id in by_db:
                sqlite_path = db_sqlite_path(db_id, root)
                conn = await _get_or_create_sqlite_connection(
                    session, db_id=db_id, sqlite_path=sqlite_path
                )
                connections[db_id] = conn
                setup_info = await _ensure_scanned(session, conn, tracker)
                setup_by_db[db_id] = setup_info
                running_cost += float(setup_info.get("cost_usd") or 0.0)

            # Score in original pick order
            for raw in picked:
                db_id = str(raw.get("db_id") or "")
                if running_cost >= args.max_cost:
                    print(
                        f"Stopping: running cost ${running_cost:.4f} "
                        f">= max-cost ${args.max_cost}"
                    )
                    break
                stable = str(raw.get("_stable_id") or question_stable_id(raw))
                hardness = str(raw.get("_hardness") or "unknown")
                gold = GoldItem(
                    id=stable,
                    question=str(raw.get("question") or ""),
                    gold_sql=str(raw.get("query") or ""),
                    expect="answer",
                    tags=[hardness, db_id],
                )
                connection = connections[db_id]
                provider = provider_from_connection(connection)
                try:
                    case, usage, elapsed_ms, detail = await _score_one(
                        session,
                        connection,
                        gold,
                        provider,
                        tracker,
                        hardness=hardness,
                        db_id=db_id,
                    )
                finally:
                    await provider.close()

                cases.append(case)
                cost = float(usage.get("cost_usd") or 0.0)
                running_cost += cost
                question_rows.append(
                    {
                        "id": gold.id,
                        "db_id": db_id,
                        "question": gold.question,
                        "hardness": hardness,
                        "gold_sql": gold.gold_sql,
                        "generated_sql": case.generated_sql,
                        "result_match": case.result_match,
                        "result_match_values": detail["result_match_values"],
                        "failure_label": detail["failure_label"],
                        "sql_match": case.sql_match,
                        "clarified": case.clarified,
                        "error": case.error,
                        "intent": case.intent,
                        "trust_level": case.trust_level,
                        "retries": detail["retries"],
                        "schema_linking": detail["schema_linking"],
                        "selected_tables": detail["selected_tables"],
                        "gold_result": detail["gold_result"],
                        "generated_result": detail["generated_result"],
                        "elapsed_ms": elapsed_ms,
                        "cost_usd": cost,
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "reasoning_tokens": usage.get("reasoning_tokens", 0),
                        "cached_input_tokens": usage.get("cached_input_tokens", 0),
                        "calls": usage.get("calls", 0),
                        "estimated_calls": usage.get("estimated_calls", 0),
                        "by_stage": usage.get("by_stage") or {},
                    }
                )

    q_costs = [r["cost_usd"] for r in question_rows]
    q_times = [r["elapsed_ms"] for r in question_rows]
    avg_cost = sum(q_costs) / len(q_costs) if q_costs else 0.0
    avg_time = sum(q_times) / len(q_times) if q_times else 0.0
    setup_cost = sum(float(v.get("cost_usd") or 0) for v in setup_by_db.values())
    setup_time = sum(int(v.get("elapsed_ms") or 0) for v in setup_by_db.values())

    question_ids = {r["id"] for r in question_rows}
    q_records = [r for r in tracker.records if r.case_id in question_ids]
    by_stage: dict[str, dict[str, Any]] = {}
    for rec in q_records:
        key = rec.stage or "(unset)"
        bucket = by_stage.setdefault(
            key,
            {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "latency_ms": 0,
                "cost_usd": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += rec.input_tokens
        bucket["output_tokens"] += rec.output_tokens
        bucket["reasoning_tokens"] += rec.reasoning_tokens
        bucket["latency_ms"] += rec.latency_ms
        bucket["cost_usd"] = round(bucket["cost_usd"] + rec.cost_usd, 8)

    accuracy = _accuracy_breakdown(question_rows)
    ov = accuracy["overall"]
    totals = {
        "cost_usd": round(sum(q_costs), 6),
        "elapsed_ms": sum(q_times),
        "input_tokens": sum(r["input_tokens"] for r in question_rows),
        "output_tokens": sum(r["output_tokens"] for r in question_rows),
        "reasoning_tokens": sum(r["reasoning_tokens"] for r in question_rows),
        "calls": sum(r["calls"] for r in question_rows),
        "estimated_calls": sum(r["estimated_calls"] for r in question_rows),
        "correct_strict": ov["strict_correct"],
        "correct_values": ov["values_correct"],
        "n": len(question_rows),
    }

    db_ids = sorted({r["db_id"] for r in question_rows})
    report: dict[str, Any] = {
        "kind": "spider-pilot",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "models": model_info,
        "rate_card": {
            "gpt-5.6-luna": {"input": 0.20, "output": 1.20, "cached_input": 0.02},
            "embedding": 0.02,
        },
        "db_id": db_ids[0] if len(db_ids) == 1 else None,
        "db_ids": db_ids,
        "question_ids": [r["id"] for r in question_rows],
        "n": len(question_rows),
        "seed": args.seed,
        "setup": {"by_db": setup_by_db, "cost_usd": setup_cost, "elapsed_ms": setup_time},
        "questions": question_rows,
        "accuracy": accuracy,
        "totals": totals,
        "by_stage": by_stage,
        "extrapolation": {
            "spider_dev_1034": extrapolate(
                avg_cost_usd=avg_cost,
                avg_latency_ms=avg_time,
                n_questions=1034,
                setup_cost_usd=setup_cost,
                setup_latency_ms=setup_time,
            ),
            "bird_mini_dev_500": extrapolate(
                avg_cost_usd=avg_cost,
                avg_latency_ms=avg_time,
                n_questions=500,
                setup_cost_usd=setup_cost,
                setup_latency_ms=setup_time,
            ),
        },
        "usage": tracker.to_dict(),
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    default_name = (
        f"run{len(question_rows)}-{stamp}.json"
        if len(db_ids) > 1
        else f"pilot-{stamp}.json"
    )
    out = Path(args.out) if args.out else _BACKEND / "eval" / "results" / default_name
    if not out.is_absolute():
        out = (_BACKEND / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["out_path"] = str(out)
    _print_report(report)
    _print_side_by_side(report)
    return report


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    argv = list(argv) if argv is not None else sys.argv[1:]

    # Subcommand: rescore <path>
    if argv and argv[0] == "rescore":
        p = argparse.ArgumentParser(description="Re-score a saved pilot JSON (no LLM)")
        p.add_argument("rescore_path", help="Path to pilot JSON")
        ns = p.parse_args(argv[1:])
        ns.command = "rescore"
        return ns

    p = argparse.ArgumentParser(description="AstraSQL Spider accuracy pilot")
    p.add_argument("--n", type=int, default=5, help="Questions when using single --db")
    p.add_argument("--db", default="", help="Single Spider db_id")
    p.add_argument(
        "--dbs",
        type=int,
        default=0,
        help="Number of small databases to sample (multi-db mode)",
    )
    p.add_argument(
        "--per-db",
        type=int,
        default=5,
        help="Questions per database in multi-db mode",
    )
    p.add_argument(
        "--db-ids",
        default="",
        help="Comma-separated Spider db_ids (overrides --dbs selection)",
    )
    p.add_argument(
        "--from-report",
        default="",
        help="Re-run the exact questions from a prior report JSON",
    )
    p.add_argument("--model", default="gpt-5.6-luna", help="Chat model for all LLM steps")
    p.add_argument(
        "--reasoning-effort",
        default="low",
        help="Reasoning effort for gpt-5 family (none|low|medium|high)",
    )
    p.add_argument("--seed", type=int, default=42, help="Question selection seed")
    p.add_argument("--max-cost", type=float, default=1.0, help="Stop if cost exceeds this USD")
    p.add_argument("--out", default="", help="Output JSON path")
    p.add_argument("--download-only", action="store_true", help="Only download Spider data")
    p.add_argument("--force-download", action="store_true", help="Re-download Spider zip")
    ns = p.parse_args(argv)
    ns.command = "run"
    return ns


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if getattr(args, "command", "run") == "rescore":
        asyncio.run(_rescore_report(_resolve_path(args.rescore_path)))
        return 0
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
