from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class GoldItem(BaseModel):
    id: str
    question: str
    gold_sql: Optional[str] = None
    expect: Literal["answer", "clarify"]
    tags: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    id: str
    question: str
    expect: Literal["answer", "clarify"]
    intent: Optional[str] = None
    trust_level: Optional[str] = None
    generated_sql: Optional[str] = None
    error: Optional[str] = None
    sql_match: Optional[bool] = None
    result_match: Optional[bool] = None
    clarified: bool = False
    silent_wrong: bool = False
    used_golden: bool = False


class EvalReport(BaseModel):
    n: int
    model: str
    gold_path: str
    connection_id: str
    execution_match: Optional[float] = None
    sql_match_rate: Optional[float] = None
    clarify_hit: Optional[float] = None
    silent_wrong: Optional[float] = None
    taught_repeat: Optional[float] = None
    cases: list[CaseResult] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
