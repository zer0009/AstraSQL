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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from src.config.settings import get_settings
from src.eval.compare import (
    results_equal,
    results_equal_lenient,
    results_equal_values,
    sql_equal,
)
from src.eval.failure_labels import extract_tables, label_failure
from src.eval.models import CaseResult, GoldItem
from src.eval.paired import compare_reports
from src.eval.spider_data import (
    db_sqlite_path,
    default_pilot_db,
    ensure_spider_data,
    load_dev,
    pick_held_out,
    pick_multi_db,
    pick_stratified,
    pick_tuning_split,
    question_stable_id,
)
from src.eval.usage import (
    RateCard,
    UsageTracker,
    extrapolate,
    latency_percentiles,
    track_usage,
    usage_case,
    usage_stage,
)
from src.storage.crypto import encrypt_password
from src.storage.database import get_session_factory
from src.storage.models import Connection, SchemaCache

_BACKEND = Path(__file__).resolve().parents[2]
_RESULT_PREVIEW_ROWS = 8


def _pin_models(
    model: str,
    reasoning_effort: str,
    *,
    interpretation_mode: str = "",
    validator_mode: str = "",
    schema_link_mode: str = "",
    format_response: bool | None = None,
    sql_candidate_count: int | None = None,
    execution_evidence_gate: bool | None = None,
    merge_interpret_generate: bool | None = None,
) -> dict[str, Any]:
    from src.config.settings import clear_settings_cache, override_settings_env

    override_settings_env(
        LLM_MODEL=model,
        OPENAI_MODEL=model,
        ENRICHMENT_MODEL=model,
        INTERPRETATION_MODEL=model,
    )
    if reasoning_effort:
        os.environ["LLM_REASONING_EFFORT"] = reasoning_effort
    if interpretation_mode:
        os.environ["INTERPRETATION_MODE"] = interpretation_mode
    if validator_mode:
        os.environ["VALIDATOR_MODE"] = validator_mode
    if schema_link_mode:
        os.environ["SCHEMA_LINK_MODE"] = schema_link_mode
    if format_response is not None:
        os.environ["FORMAT_RESPONSE"] = "true" if format_response else "false"
    if sql_candidate_count is not None:
        os.environ["SQL_CANDIDATE_COUNT"] = str(sql_candidate_count)
    if execution_evidence_gate is not None:
        os.environ["EXECUTION_EVIDENCE_GATE"] = (
            "true" if execution_evidence_gate else "false"
        )
    if merge_interpret_generate is not None:
        os.environ["MERGE_INTERPRET_GENERATE"] = (
            "true" if merge_interpret_generate else "false"
        )
    # Eval runs skip NL formatter by default for speed unless overridden.
    if format_response is None and "FORMAT_RESPONSE" not in os.environ:
        os.environ["FORMAT_RESPONSE"] = "false"
    clear_settings_cache()
    settings = get_settings()
    return {
        "openai_model": settings.llm_model,
        "enrichment_model": settings.enrichment_model,
        "interpretation_model": settings.interpretation_model or settings.enrichment_model,
        "llm_reasoning_effort": settings.llm_reasoning_effort,
        "embedding_model": settings.embedding_model,
        "interpretation_mode": settings.interpretation_mode,
        "validator_mode": settings.validator_mode,
        "schema_link_mode": settings.schema_link_mode,
        "format_response": settings.format_response,
        "sql_candidate_count": settings.sql_candidate_count,
        "execution_evidence_gate": settings.execution_evidence_gate,
        "merge_interpret_generate": settings.merge_interpret_generate,
    }


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = (_BACKEND / p).resolve()
    return p


def _preview_result(payload: dict | None, *, max_rows: int = _RESULT_PREVIEW_ROWS) -> dict | None:
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
    name_prefix: str = "spider",
) -> Connection:
    name = f"{name_prefix}-{db_id}"
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
    gold_sql: str | None,
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
    generated_sql: str | None,
    gold_sql: str | None,
) -> tuple[dict | None, dict | None, str | None]:
    gold_rows: dict | None = None
    gen_rows: dict | None = None
    err: str | None = None
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
    evidence: str = "",
    dialect: str = "sqlite",
) -> tuple[CaseResult, dict[str, Any], int, dict[str, Any]]:
    from src.agent.runner import run_query
    from src.eval.run import _generated_sql, _is_clarified

    started = time.perf_counter()
    with usage_case(item.id):
        state = await run_query(
            session, connection, item.question, evidence=evidence
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    sql = _generated_sql(state)
    clarified = _is_clarified(state)
    silent_wrong = item.expect == "clarify" and bool(sql) and not clarified
    ctx = state.get("context") or {}
    selected_tables = list(ctx.get("selected_tables") or [])
    linking = _schema_linking_recall(selected_tables, item.gold_sql)

    sql_match: bool | None = None
    result_match: bool | None = None
    result_match_values: bool | None = None
    result_match_lenient: bool | None = None
    gold_result: dict | None = None
    gen_result: dict | None = None
    exec_error: str | None = None

    if item.expect == "answer" and item.gold_sql:
        sql_match = sql_equal(sql, item.gold_sql, dialect=dialect)
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
                result_match_lenient = results_equal_lenient(
                    gold_result, gen_result, gold_sql=item.gold_sql
                )
            elif sql and gold_result is not None:
                result_match = False
                result_match_values = False
                result_match_lenient = False

    error = state.get("error") or exec_error
    failure_label: str | None = None
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
            dialect=dialect,
        )

    ambiguity = state.get("ambiguity") if isinstance(state.get("ambiguity"), dict) else {}
    ambiguity_diag = {
        "status": ambiguity.get("status"),
        "decision_why": ambiguity.get("decision_why"),
        "reason": ambiguity.get("reason"),
        "assumption": ambiguity.get("assumption") or state.get("assumption"),
        "should_clarify": ambiguity.get("should_clarify"),
        "proposal_status": ambiguity.get("proposal_status"),
        "options": list(ambiguity.get("options") or [])[:6],
        "candidates": list(ambiguity.get("candidates") or [])[:6],
        "selected": ambiguity.get("selected"),
        "clusters": ambiguity.get("clusters"),
        "gate": ambiguity.get("gate"),
    }

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
        "result_match_lenient": result_match_lenient,
        "failure_label": failure_label,
        "gold_result": _preview_result(gold_result),
        "generated_result": _preview_result(gen_result),
        "schema_linking": linking,
        "retries": int(state.get("retries") or 0),
        "selected_tables": selected_tables,
        "ambiguity": ambiguity_diag,
        "assumption": state.get("assumption") or ambiguity.get("assumption"),
    }
    return case, usage, elapsed_ms, detail


def _accuracy_breakdown(question_rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _rate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
        n = len(rows)
        strict = sum(1 for r in rows if r.get("result_match") is True)
        values = sum(1 for r in rows if r.get("result_match_values") is True)
        lenient = sum(1 for r in rows if r.get("result_match_lenient") is True)
        return {
            "n": n,
            "strict_correct": strict,
            "values_correct": values,
            "lenient_correct": lenient,
            "strict_accuracy": round(strict / n, 4) if n else 0.0,
            "values_accuracy": round(values / n, 4) if n else 0.0,
            "lenient_accuracy": round(lenient / n, 4) if n else 0.0,
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
        f"lenient {overall.get('lenient_correct', 0)}/{overall.get('n', 0)} "
        f"({100 * float(overall.get('lenient_accuracy') or 0):.1f}%)  |  "
        f"strict {overall.get('strict_correct', 0)}/{overall.get('n', 0)} "
        f"({100 * float(overall.get('strict_accuracy') or 0):.1f}%)"
    )
    conv = acc.get("convention_adjusted") or {}
    if conv:
        print(
            f"Convention-adjusted: {conv.get('convention_adjusted_correct', 0)}/"
            f"{conv.get('n', 0)} "
            f"({100 * float(conv.get('convention_adjusted_accuracy') or 0):.1f}%)"
        )
    totals = report.get("totals") or {}
    if totals.get("latency_p50_ms") is not None:
        print(
            f"Latency p50/p95: {totals.get('latency_p50_ms')}ms / "
            f"{totals.get('latency_p95_ms')}ms  |  "
            f"avg cost ${float(totals.get('avg_cost_usd') or 0):.6f}"
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
            lenient = (
                results_equal_lenient(gold_result, gen_result, gold_sql=gold_sql)
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
            updated["result_match_lenient"] = lenient
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
        "created_at": datetime.now(UTC).isoformat(),
        "n": len(rescored),
        "questions": rescored,
        "accuracy": accuracy,
        "original_totals": data.get("totals"),
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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

    dataset = str(getattr(args, "dataset", "spider") or "spider").strip().lower()
    if dataset == "bird":
        from src.eval.bird_data import pick_bird_stratified

        n = int(args.n or 150)
        if getattr(args, "dbs", 0) and args.per_db:
            n = int(args.dbs) * int(args.per_db)
        db_ids = None
        if getattr(args, "db_ids", ""):
            db_ids = [x.strip() for x in str(args.db_ids).split(",") if x.strip()]
        return pick_bird_stratified(
            items, n=n, seed=args.seed, db_ids=db_ids
        )

    split = str(getattr(args, "split", "") or "").strip().lower()
    if split == "held_out":
        return pick_held_out(
            items,
            n_dbs=int(getattr(args, "dbs", 0) or 5),
            per_db=int(args.per_db or 12),
            seed=int(getattr(args, "seed", 99) or 99),
            root=root,
        )
    if split == "tune":
        return pick_tuning_split(
            items,
            n_dbs=int(getattr(args, "dbs", 0) or 10),
            per_db=int(args.per_db or 6),
            seed=int(getattr(args, "seed", 42) or 42),
            root=root,
        )

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


def _convention_adjusted(question_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Values accuracy treating join-type / direction convention misses as OK.

    These are product-correct under a connection convention; Spider gold may
    disagree. Reported separately so they are not hidden as silent wins.
    """
    convention_labels = {
        "join_type",
        "left_vs_inner",
        "min_vs_max",
        "direction",
        "convention",
    }
    n = len(question_rows)
    values_ok = 0
    convention_ok = 0
    for r in question_rows:
        if r.get("result_match_values") is True:
            values_ok += 1
            convention_ok += 1
            continue
        label = str(r.get("failure_label") or "").lower()
        why = str((r.get("ambiguity") or {}).get("decision_why") or "").lower()
        assumption = str(r.get("assumption") or "").lower()
        if any(x in label for x in convention_labels) or any(
            x in why or x in assumption
            for x in ("join type", "left join", "inner join", "min vs", "max vs")
        ):
            convention_ok += 1
    return {
        "n": n,
        "values_correct": values_ok,
        "values_accuracy": round(values_ok / n, 4) if n else 0.0,
        "convention_adjusted_correct": convention_ok,
        "convention_adjusted_accuracy": round(convention_ok / n, 4) if n else 0.0,
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    dataset = str(getattr(args, "dataset", "spider") or "spider").strip().lower()
    if args.download_only:
        if dataset == "bird":
            import importlib.util

            fetch_path = _BACKEND / "scripts" / "fetch_benchmarks.py"
            spec = importlib.util.spec_from_file_location(
                "fetch_benchmarks", fetch_path
            )
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(mod)
            mod.fetch_bird(force=args.force_download)
            return {"root": str(_BACKEND / "eval" / "benchmarks" / "data" / "bird")}
        root = ensure_spider_data(force=args.force_download)
        print(root)
        return {"root": str(root)}

    model_info = _pin_models(
        args.model,
        args.reasoning_effort,
        interpretation_mode=getattr(args, "interpretation_mode", "") or "",
        validator_mode=getattr(args, "validator_mode", "") or "",
        schema_link_mode=getattr(args, "schema_link_mode", "") or "",
        format_response=getattr(args, "format_response", None),
        sql_candidate_count=getattr(args, "sql_candidate_count", None),
        execution_evidence_gate=getattr(args, "execution_evidence_gate", None),
        merge_interpret_generate=getattr(args, "merge_interpret_generate", None),
    )
    settings = get_settings()
    if not (settings.llm_api_key or "").strip():
        raise SystemExit("LLM_API_KEY / OPENAI_API_KEY is not set")

    include_evidence = True
    if str(getattr(args, "evidence", "true") or "true").lower() in {
        "false",
        "0",
        "no",
    }:
        include_evidence = False

    if dataset == "bird":
        from src.eval.bird_data import bird_db_path, bird_root, load_bird_mini_dev

        root = bird_root()
        items = load_bird_mini_dev(root)
        conn_prefix = "bird"
    else:
        root = ensure_spider_data(force=args.force_download)
        items = load_dev(root)
        conn_prefix = "spider"

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
    db_paths: dict[str, Path] = {}

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
                if dataset == "bird":
                    sqlite_path = bird_db_path(db_id, root)
                else:
                    sqlite_path = db_sqlite_path(db_id, root)
                db_paths[db_id] = sqlite_path
                conn = await _get_or_create_sqlite_connection(
                    session,
                    db_id=db_id,
                    sqlite_path=sqlite_path,
                    name_prefix=conn_prefix,
                )
                connections[db_id] = conn
                setup_info = await _ensure_scanned(session, conn, tracker)
                if dataset == "bird" and bool(
                    getattr(args, "import_dictionary", True)
                ):
                    try:
                        from src.context.dictionary_import import (
                            import_bird_descriptions_for_db,
                        )

                        n_desc = await import_bird_descriptions_for_db(
                            session, conn.id, db_id, root=root
                        )
                        setup_info["dictionary_rows"] = n_desc
                    except Exception as exc:
                        setup_info["dictionary_error"] = str(exc)
                setup_by_db[db_id] = setup_info
                running_cost += float(setup_info.get("cost_usd") or 0.0)

            concurrency = max(1, int(getattr(args, "concurrency", 1) or 1))
            sem = asyncio.Semaphore(concurrency)
            cost_lock = asyncio.Lock()
            stop_flag = {"stop": False}

            async def _score_raw(raw: dict[str, Any]) -> dict[str, Any] | None:
                nonlocal running_cost
                async with cost_lock:
                    if stop_flag["stop"] or running_cost >= args.max_cost:
                        stop_flag["stop"] = True
                        return None
                db_id = str(raw.get("db_id") or "")
                stable = str(raw.get("_stable_id") or question_stable_id(raw))
                hardness = str(raw.get("_hardness") or "unknown")
                gold_sql = str(
                    raw.get("query")
                    or raw.get("SQL")
                    or raw.get("gold_sql")
                    or raw.get("sol_sql")
                    or ""
                )
                gold = GoldItem(
                    id=stable,
                    question=str(raw.get("question") or ""),
                    gold_sql=gold_sql,
                    expect="answer",
                    tags=[hardness, db_id],
                )
                evidence = ""
                if include_evidence:
                    evidence = str(
                        raw.get("_evidence") or raw.get("evidence") or ""
                    )
                connection = connections[db_id]
                provider = provider_from_connection(connection)
                async with sem:
                    async with cost_lock:
                        if stop_flag["stop"] or running_cost >= args.max_cost:
                            stop_flag["stop"] = True
                            await provider.close()
                            return None
                    # Fresh session per task — shared AsyncSession is not concurrent-safe.
                    async with factory() as task_session:
                        task_conn = await task_session.merge(connection)
                        try:
                            case, usage, elapsed_ms, detail = await _score_one(
                                task_session,
                                task_conn,
                                gold,
                                provider,
                                tracker,
                                hardness=hardness,
                                db_id=db_id,
                                evidence=evidence,
                            )
                        finally:
                            await provider.close()

                cost = float(usage.get("cost_usd") or 0.0)
                async with cost_lock:
                    running_cost += cost
                    if running_cost >= args.max_cost:
                        stop_flag["stop"] = True
                        print(
                            f"Stopping: running cost ${running_cost:.4f} "
                            f">= max-cost ${args.max_cost}"
                        )
                return {
                    "case": case,
                    "row": {
                        "id": gold.id,
                        "db_id": db_id,
                        "question": gold.question,
                        "hardness": hardness,
                        "split": raw.get("_split") or getattr(args, "split", "") or "",
                        "dataset": dataset,
                        "evidence": evidence,
                        "gold_sql": gold.gold_sql,
                        "generated_sql": case.generated_sql,
                        "result_match": case.result_match,
                        "result_match_values": detail["result_match_values"],
                        "result_match_lenient": detail.get("result_match_lenient"),
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
                        "ambiguity": detail.get("ambiguity"),
                        "assumption": detail.get("assumption"),
                        "elapsed_ms": elapsed_ms,
                        "cost_usd": cost,
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "reasoning_tokens": usage.get("reasoning_tokens", 0),
                        "cached_input_tokens": usage.get("cached_input_tokens", 0),
                        "calls": usage.get("calls", 0),
                        "estimated_calls": usage.get("estimated_calls", 0),
                        "by_stage": usage.get("by_stage") or {},
                    },
                }

            if concurrency <= 1:
                results = []
                for raw in picked:
                    item = await _score_raw(raw)
                    results.append(item)
                    if stop_flag["stop"]:
                        break
            else:
                results = await asyncio.gather(*[_score_raw(raw) for raw in picked])
            for item in results:
                if item is None:
                    continue
                cases.append(item["case"])
                question_rows.append(item["row"])

    q_costs = [r["cost_usd"] for r in question_rows]
    q_times = [r["elapsed_ms"] for r in question_rows]
    avg_cost = sum(q_costs) / len(q_costs) if q_costs else 0.0
    avg_time = sum(q_times) / len(q_times) if q_times else 0.0
    setup_cost = sum(float(v.get("cost_usd") or 0) for v in setup_by_db.values())
    setup_time = sum(int(v.get("elapsed_ms") or 0) for v in setup_by_db.values())

    question_ids = {r["id"] for r in question_rows}
    q_records = [r for r in tracker.records if r.case_id in question_ids]
    by_stage: dict[str, dict[str, Any]] = {}
    stage_lats: dict[str, list[int]] = {}
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
        stage_lats.setdefault(key, []).append(int(rec.latency_ms))
    for key, bucket in by_stage.items():
        stats = latency_percentiles(stage_lats.get(key) or [])
        bucket["latency_p50_ms"] = stats["p50"]
        bucket["latency_p95_ms"] = stats["p95"]
        bucket["latency_mean_ms"] = stats["mean"]

    q_lat_stats = latency_percentiles(q_times)
    accuracy = _accuracy_breakdown(question_rows)
    accuracy["convention_adjusted"] = _convention_adjusted(question_rows)
    ov = accuracy["overall"]
    totals = {
        "cost_usd": round(sum(q_costs), 6),
        "elapsed_ms": sum(q_times),
        "latency_p50_ms": q_lat_stats["p50"],
        "latency_p95_ms": q_lat_stats["p95"],
        "latency_mean_ms": q_lat_stats["mean"],
        "avg_cost_usd": round(avg_cost, 6),
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
        "kind": f"{dataset}-pilot",
        "dataset": dataset,
        "include_evidence": include_evidence if dataset == "bird" else None,
        "created_at": datetime.now(UTC).isoformat(),
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
        "split": str(getattr(args, "split", "") or ""),
        "concurrency": int(getattr(args, "concurrency", 1) or 1),
        "max_cost": float(args.max_cost),
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

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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


def _compare_reports_cli(path_a: Path, path_b: Path) -> dict[str, Any]:
    a = json.loads(path_a.read_text(encoding="utf-8"))
    b = json.loads(path_b.read_text(encoding="utf-8"))
    result = compare_reports(a, b)
    print("\n======== PAIRED COMPARISON ========")
    print(f"A: {path_a}")
    print(f"B: {path_b}")
    print(f"A accuracy (values): {100 * result['a_accuracy']:.1f}%")
    print(f"B accuracy (values): {100 * result['b_accuracy']:.1f}%")
    m = result["mcnemar"]
    print(
        f"McNemar: n={m['n_paired']} a_only={m['a_only']} b_only={m['b_only']} "
        f"p={m['p_value']} significant@0.05={m['significant_0_05']}"
    )
    boot = result["bootstrap"]
    print(
        f"Bootstrap diff(B-A): mean={boot['mean_diff']} "
        f"CI95={boot['ci95']} excludes_zero={boot['ci_excludes_zero']}"
    )
    if result["flips"]:
        print(f"Flips ({len(result['flips'])}):")
        for f in result["flips"][:20]:
            print(f"  {f['id']}: A={f['a']} -> B={f['b']}")
    print("===================================\n")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = path_b.parent / f"compare-{stamp}.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out}")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(argv) if argv is not None else sys.argv[1:]

    # Subcommand: rescore <path>
    if argv and argv[0] == "rescore":
        p = argparse.ArgumentParser(description="Re-score a saved pilot JSON (no LLM)")
        p.add_argument("rescore_path", help="Path to pilot JSON")
        ns = p.parse_args(argv[1:])
        ns.command = "rescore"
        return ns

    # Subcommand: compare <a.json> <b.json>
    if argv and argv[0] == "compare":
        p = argparse.ArgumentParser(description="Paired significance between two reports")
        p.add_argument("report_a", help="Baseline report JSON")
        p.add_argument("report_b", help="Candidate report JSON")
        ns = p.parse_args(argv[1:])
        ns.command = "compare"
        return ns

    p = argparse.ArgumentParser(description="AstraSQL accuracy pilot (Spider / BIRD)")
    p.add_argument(
        "--dataset",
        choices=["spider", "bird"],
        default="spider",
        help="Benchmark dataset (default spider)",
    )
    p.add_argument(
        "--evidence",
        choices=["true", "false", ""],
        default="true",
        help="BIRD: inject evidence into business rules (default true)",
    )
    p.add_argument(
        "--import-dictionary",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="BIRD: import database_description CSVs when present",
    )
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
    p.add_argument(
        "--interpretation-mode",
        default="",
        help="Ablation: on|off|assume_only (env INTERPRETATION_MODE)",
    )
    p.add_argument(
        "--validator-mode",
        default="",
        help="Ablation: full|deterministic|off",
    )
    p.add_argument(
        "--schema-link-mode",
        default="",
        help="Ablation: auto|full|faiss",
    )
    p.add_argument(
        "--format-response",
        choices=["true", "false", ""],
        default="",
        help="Ablation: run NL formatter (default false for eval)",
    )
    p.add_argument(
        "--sql-candidate-count",
        type=int,
        default=None,
        help="Ablation: multi-candidate generation count",
    )
    p.add_argument(
        "--execution-evidence-gate",
        choices=["true", "false", ""],
        default="",
        help="Ablation: execution-evidence clarify gate (default: settings)",
    )
    p.add_argument(
        "--merge-interpret-generate",
        choices=["true", "false", ""],
        default="",
        help="Ablation: merge interpretation into generator",
    )
    p.add_argument("--seed", type=int, default=42, help="Question selection seed")
    p.add_argument(
        "--split",
        choices=["", "tune", "held_out"],
        default="",
        help="tune=historical small DBs; held_out=disjoint DBs/seed for reporting",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Score up to N questions in parallel (latency stats use concurrency=1)",
    )
    p.add_argument("--max-cost", type=float, default=1.0, help="Stop if cost exceeds this USD")
    p.add_argument("--out", default="", help="Output JSON path")
    p.add_argument("--download-only", action="store_true", help="Only download Spider data")
    p.add_argument("--force-download", action="store_true", help="Re-download Spider zip")
    ns = p.parse_args(argv)
    if ns.format_response == "true":
        ns.format_response = True
    elif ns.format_response == "false":
        ns.format_response = False
    else:
        ns.format_response = None
    if getattr(ns, "execution_evidence_gate", "") == "true":
        ns.execution_evidence_gate = True
    elif getattr(ns, "execution_evidence_gate", "") == "false":
        ns.execution_evidence_gate = False
    else:
        ns.execution_evidence_gate = None
    if getattr(ns, "merge_interpret_generate", "") == "true":
        ns.merge_interpret_generate = True
    elif getattr(ns, "merge_interpret_generate", "") == "false":
        ns.merge_interpret_generate = False
    else:
        ns.merge_interpret_generate = None
    ns.command = "run"
    return ns


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cmd = getattr(args, "command", "run")
    if cmd == "rescore":
        asyncio.run(_rescore_report(_resolve_path(args.rescore_path)))
        return 0
    if cmd == "compare":
        _compare_reports_cli(
            _resolve_path(args.report_a),
            _resolve_path(args.report_b),
        )
        return 0
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
