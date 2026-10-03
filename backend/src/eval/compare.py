"""Result-set equality and SQL normalize for eval.

Implementation lives in ``src.agent.result_compare`` so the runtime agent pack
does not depend on ``src.eval``. This module re-exports the public API.
"""

from __future__ import annotations

from src.agent.result_compare import (  # noqa: F401
    gold_has_order_by,
    results_equal,
    results_equal_lenient,
    results_equal_values,
    sql_equal,
)

__all__ = [
    "gold_has_order_by",
    "results_equal",
    "results_equal_lenient",
    "results_equal_values",
    "sql_equal",
]
