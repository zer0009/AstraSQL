from __future__ import annotations

from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.agent.prompts.generator import render_generator_prompt
from src.agent.state import AgentState
from src.agent.utils import append_step, extract_json, get_configurable, message_text
from src.config.settings import get_settings
from src.providers.llm import get_llm_provider


async def query_generator(
    state: AgentState, config: RunnableConfig
) -> dict[str, Any]:
    """Generate dialect-aware SQL from the user question and retrieved context."""
    cfg = get_configurable(config)
    db_provider = cfg.get("db_provider")
    settings = get_settings()

    if db_provider is None:
        return {
            "error": "Missing db_provider in configurable",
            "steps": append_step(state, "generate_error", "db_provider missing"),
        }

    context = state.get("context") or {}
    question = state.get("question") or ""
    retry_context = state.get("retry_context") or ""
    retries = int(state.get("retries") or 0)

    # Fatal upstream failure (e.g. context) — do not invent SQL.
    if state.get("error") and not context.get("enriched_schema"):
        return {
            "sql": "",
            "corrected_sql": "",
            "error": state.get("error"),
            "steps": append_step(
                state,
                "generate_skipped",
                state.get("error") or "Missing context; skipped SQL generation",
            ),
        }

    updates: dict[str, Any] = {}
    # Entering a retry path: bump attempt counter once per regeneration.
    if retry_context.strip():
        retries = retries + 1
        updates["retries"] = retries

    try:
        system = render_generator_prompt(
            dialect_name=db_provider.dialect_name(),
            enriched_schema=context.get("enriched_schema") or "",
            business_rules=context.get("business_rules") or "",
            golden_records=context.get("golden_records_text") or "",
            dialect_prompt_rules=db_provider.dialect_prompt_rules(),
            max_rows=settings.max_result_rows,
            retry_context=retry_context,
            user_question=question,
            current_date=date.today().isoformat(),
        )
        llm = get_llm_provider().get_chat_model(
            temperature=0.0,
            max_tokens=settings.llm_max_tokens,
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=question or "Generate the SQL query."),
            ],
            config=config,
        )
        parsed = extract_json(message_text(response))
        sql = str(parsed.get("sql") or "").strip()
        if not sql:
            raise ValueError("Generator returned empty SQL")

        gen_steps = {
            k: parsed.get(k)
            for k in (
                "step1_metric",
                "step2_tables",
                "step3_joins",
                "step4_filters",
                "step5_aggregation",
                "step6_ordering",
            )
            if k in parsed
        }
    except Exception as exc:
        updates.update(
            {
                "sql": "",
                "corrected_sql": "",
                "error": f"SQL generation failed: {exc}",
                "steps": append_step(
                    state,
                    "generate_error",
                    str(exc),
                    retries=retries,
                ),
            }
        )
        return updates

    updates.update(
        {
            "sql": sql,
            "corrected_sql": sql,
            "error": None,
            "steps": append_step(
                state,
                "sql_generated",
                f"Generated SQL (attempt retries={retries})",
                sql=sql,
                generation=gen_steps,
                retries=retries,
            ),
        }
    )
    return updates
