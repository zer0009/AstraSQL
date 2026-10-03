"""CLI: run gold questions through the existing agent and write a report.

uv run python -m src.eval.run --gold eval/datasets/project_shop/gold.json \\
  --connection-id <id> --model gpt-4o --out eval/results/<stamp>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config.settings import clear_settings_cache, get_settings, override_settings_env
from src.eval.compare import results_equal, sql_equal
from src.eval.models import CaseResult, EvalReport, GoldItem
from src.storage.database import get_session_factory
from src.storage.models import Connection

_BACKEND = Path(__file__).resolve().parents[2]


def _load_gold(path: Path) -> list[GoldItem]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["items"] if isinstance(raw, dict) and "items" in raw else raw
    return [GoldItem.model_validate(item) for item in items]


def _generated_sql(state: dict[str, Any]) -> str:
    return str(state.get("corrected_sql") or state.get("sql") or "").strip()


def _is_clarified(state: dict[str, Any]) -> bool:
    intent = str(state.get("intent") or "").upper()
    trust = str(state.get("trust_level") or "").lower()
    sql = _generated_sql(state)
    if trust == "clarifying":
        return True
    if intent == "CLARIFICATION_NEEDED" and not sql:
        return True
    return False


async def _score_case(
    session,
    connection: Connection,
    item: GoldItem,
    provider: Any,
) -> CaseResult:
    from src.agent.runner import run_query

    state = await run_query(session, connection, item.question)
    sql = _generated_sql(state)
    clarified = _is_clarified(state)
    silent_wrong = item.expect == "clarify" and bool(sql) and not clarified

    sql_match: bool | None = None
    result_match: bool | None = None
    if item.expect == "answer" and item.gold_sql:
        dialect = (
            provider.sqlglot_dialect()
            if provider is not None and hasattr(provider, "sqlglot_dialect")
            else "sqlite"
        )
        sql_match = sql_equal(sql, item.gold_sql, dialect=dialect)
        if sql and provider is not None:
            try:
                generated_rows = await provider.execute_readonly(sql, max_rows=500)
                gold_rows = await provider.execute_readonly(item.gold_sql, max_rows=500)
                result_match = results_equal(generated_rows, gold_rows)
            except (ValueError, RuntimeError, OSError):
                generated = state.get("results") or {}
                try:
                    gold_rows = await provider.execute_readonly(item.gold_sql, max_rows=500)
                    result_match = results_equal(generated, gold_rows)
                except (ValueError, RuntimeError, OSError):
                    result_match = False

    return CaseResult(
        id=item.id,
        question=item.question,
        expect=item.expect,
        intent=state.get("intent"),
        trust_level=state.get("trust_level"),
        generated_sql=sql or None,
        error=state.get("error"),
        sql_match=sql_match,
        result_match=result_match,
        clarified=clarified,
        silent_wrong=silent_wrong,
        used_golden=bool(state.get("used_golden")),
    )


def _rate(values: list[bool]) -> float | None:
    if not values:
        return None
    return round(sum(1 for v in values if v) / len(values), 4)


def build_report(
    cases: list[CaseResult],
    *,
    model: str,
    gold_path: str,
    connection_id: str,
    extra: dict[str, Any] | None = None,
) -> EvalReport:
    answer_ex = [c.result_match for c in cases if c.expect == "answer" and c.result_match is not None]
    answer_sql = [c.sql_match for c in cases if c.expect == "answer" and c.sql_match is not None]
    clarify = [c.clarified for c in cases if c.expect == "clarify"]
    silent = [c.silent_wrong for c in cases if c.expect == "clarify"]
    return EvalReport(
        n=len(cases),
        model=model,
        gold_path=gold_path,
        connection_id=connection_id,
        execution_match=_rate([bool(v) for v in answer_ex]),
        sql_match_rate=_rate([bool(v) for v in answer_sql]),
        clarify_hit=_rate(clarify),
        silent_wrong=_rate(silent),
        cases=cases,
        extra=extra or {},
    )


async def _run(args: argparse.Namespace) -> EvalReport:
    gold_path = Path(args.gold)
    if not gold_path.is_absolute():
        gold_path = (_BACKEND / gold_path).resolve()
    items = _load_gold(gold_path)

    if args.model:
        override_settings_env(LLM_MODEL=args.model, OPENAI_MODEL=args.model)
        clear_settings_cache()

    settings = get_settings()
    model = args.model or settings.llm_model

    factory = get_session_factory()
    async with factory() as session:
        connection = await session.get(Connection, args.connection_id)
        if connection is None:
            raise SystemExit(f"Connection not found: {args.connection_id}")

        from src.providers.database.registry import provider_from_connection

        provider = provider_from_connection(connection)
        try:
            if args.pack:
                from src.context.pack import import_pack

                pack_path = Path(args.pack)
                if not pack_path.is_absolute():
                    pack_path = (_BACKEND / pack_path).resolve()
                pack = json.loads(pack_path.read_text(encoding="utf-8"))
                await import_pack(session, args.connection_id, pack)
                await session.commit()

            cases: list[CaseResult] = []
            for item in items:
                cases.append(await _score_case(session, connection, item, provider))
        finally:
            await provider.close()

    extra = {"taught_pass": bool(args.pack)} if args.pack else {}
    report = build_report(
        cases,
        model=model,
        gold_path=str(gold_path),
        connection_id=args.connection_id,
        extra=extra,
    )
    if args.pack:
        answer_after = [
            c.result_match
            for c in cases
            if c.expect == "answer" and c.result_match is not None
        ]
        report.taught_repeat = _rate([bool(v) for v in answer_after])
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AstraSQL gold-file eval runner")
    parser.add_argument("--gold", required=True, help="Path to gold.json")
    parser.add_argument("--connection-id", required=True, help="Existing AstraSQL connection id")
    parser.add_argument("--model", default="", help="Override OPENAI_MODEL for this process")
    parser.add_argument(
        "--out",
        default="",
        help="Output JSON path (default eval/results/<stamp>-<model>.json)",
    )
    parser.add_argument(
        "--pack",
        default="",
        help="Optional astra-pack.json to import before scoring (taught pass)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = asyncio.run(_run(args))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    model_slug = (args.model or report.model or "model").replace("/", "-")
    out = Path(args.out) if args.out else _BACKEND / "eval" / "results" / f"{stamp}-{model_slug}.json"
    if not out.is_absolute():
        out = (_BACKEND / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(out)
    print(
        json.dumps(
            {
                "n": report.n,
                "execution_match": report.execution_match,
                "sql_match_rate": report.sql_match_rate,
                "clarify_hit": report.clarify_hit,
                "silent_wrong": report.silent_wrong,
                "taught_repeat": report.taught_repeat,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
