from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GoldItem(BaseModel):
    id: str
    question: str
    gold_sql: str | None = None
    expect: Literal["answer", "clarify"]
    tags: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    id: str
    question: str
    expect: Literal["answer", "clarify"]
    intent: str | None = None
    trust_level: str | None = None
    generated_sql: str | None = None
    error: str | None = None
    sql_match: bool | None = None
    result_match: bool | None = None
    clarified: bool = False
    silent_wrong: bool = False
    used_golden: bool = False


class EvalReport(BaseModel):
    n: int
    model: str
    gold_path: str
    connection_id: str
    execution_match: float | None = None
    sql_match_rate: float | None = None
    clarify_hit: float | None = None
    silent_wrong: float | None = None
    taught_repeat: float | None = None
    cases: list[CaseResult] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
