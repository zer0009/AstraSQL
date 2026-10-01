"""Execution-evidence ambiguity gate.

Sample candidate SQLs, execute them, cluster by denotation, and ask only when
clusters split. Clarification options come from sqlglot AST clause diffs —
no English word lists or regex measure heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import sqlglot
from sqlglot import exp

from src.eval.compare import results_equal_values


@dataclass(frozen=True)
class ResultCluster:
    """One denotation cluster of executed candidate SQLs."""

    member_indices: tuple[int, ...]
    representative_sql: str
    results: dict[str, Any]


@dataclass
class GateDecision:
    should_clarify: bool
    status: str  # clear | assumed | ambiguous | unanswerable | failed_open
    reason: str
    assumption: str
    options: list[str] = field(default_factory=list)
    decision_why: str = ""
    selected_sql: Optional[str] = None
    clusters: list[dict[str, Any]] = field(default_factory=list)
    gate: str = "execution_evidence"


def cluster_by_results(
    candidates: list[dict[str, Any]],
) -> list[ResultCluster]:
    """Cluster executed candidates by values-only denotation equality.

    Each item: ``{"sql": str, "results": dict | None}``. Failed executes
    (results is None) are dropped.
    """
    ok: list[tuple[int, str, dict[str, Any]]] = []
    for i, item in enumerate(candidates):
        sql = str(item.get("sql") or "").strip()
        results = item.get("results")
        if not sql or not isinstance(results, dict):
            continue
        ok.append((i, sql, results))

    clusters: list[ResultCluster] = []
    for idx, sql, res in ok:
        placed = False
        for cluster in clusters:
            if results_equal_values(res, cluster.results):
                members = cluster.member_indices + (idx,)
                # Prefer earliest SQL as representative.
                clusters[clusters.index(cluster)] = ResultCluster(
                    member_indices=members,
                    representative_sql=cluster.representative_sql,
                    results=cluster.results,
                )
                placed = True
                break
        if not placed:
            clusters.append(
                ResultCluster(
                    member_indices=(idx,),
                    representative_sql=sql,
                    results=res,
                )
            )
    return clusters


def _parse_select(sql: str, dialect: str | None = None) -> Optional[exp.Expression]:
    try:
        trees = sqlglot.parse(sql, read=dialect or None)
    except Exception:
        return None
    if not trees:
        return None
    return trees[0]


def _join_kinds(tree: exp.Expression) -> list[str]:
    kinds: list[str] = []
    for join in tree.find_all(exp.Join):
        kind = (join.args.get("kind") or join.side or "INNER")
        kinds.append(str(kind).upper())
    return kinds


def _agg_fns(tree: exp.Expression) -> list[str]:
    return sorted(
        {
            (node.sql_name() or type(node).__name__).upper()
            for node in tree.find_all(exp.AggFunc)
        }
    )


def _where_sql(tree: exp.Expression) -> str:
    where = tree.find(exp.Where)
    if where is None:
        return ""
    try:
        return where.this.sql(pretty=False)
    except Exception:
        return str(where)


def _group_keys(tree: exp.Expression) -> list[str]:
    group = tree.find(exp.Group)
    if group is None:
        return []
    try:
        return [e.sql(pretty=False) for e in group.expressions]
    except Exception:
        return []


def _select_cols(tree: exp.Expression) -> list[str]:
    try:
        return [e.sql(pretty=False) for e in tree.selects]
    except Exception:
        return []


def clause_diffs(
    sql_a: str,
    sql_b: str,
    *,
    dialect: str | None = None,
) -> list[str]:
    """Return human-readable clause-level differences between two SQLs."""
    a = _parse_select(sql_a, dialect)
    b = _parse_select(sql_b, dialect)
    if a is None or b is None:
        return ["Different SQL implementations"]

    diffs: list[str] = []
    ja, jb = _join_kinds(a), _join_kinds(b)
    if ja != jb:
        diffs.append(f"Join type: {'/'.join(ja) or 'none'} vs {'/'.join(jb) or 'none'}")

    wa, wb = _where_sql(a), _where_sql(b)
    if wa != wb:
        diffs.append("Filter / WHERE clause differs")

    aa, ab = _agg_fns(a), _agg_fns(b)
    if aa != ab:
        diffs.append(
            f"Aggregation: {', '.join(aa) or 'none'} vs {', '.join(ab) or 'none'}"
        )

    ga, gb = _group_keys(a), _group_keys(b)
    if ga != gb:
        diffs.append("GROUP BY keys differ")

    sa, sb = _select_cols(a), _select_cols(b)
    if sa != sb:
        diffs.append("Selected columns differ")

    if not diffs:
        diffs.append("Result sets differ (same surface SQL shape)")
    return diffs


def options_from_clusters(
    clusters: list[ResultCluster],
    *,
    dialect: str | None = None,
    max_options: int = 4,
) -> list[str]:
    """Build clarification options from pairwise clause diffs across clusters."""
    if len(clusters) < 2:
        return []
    options: list[str] = []
    base = clusters[0]
    for other in clusters[1:]:
        for diff in clause_diffs(
            base.representative_sql, other.representative_sql, dialect=dialect
        ):
            # Phrase as a clickable rewrite-style option.
            option = f"Use reading where: {diff}"
            if option not in options:
                options.append(option)
            if len(options) >= max_options:
                return options
    # Always leave an escape hatch.
    if "Other (describe what you mean)" not in options:
        options.append("Other (describe what you mean)")
    return options[:max_options]


def decide_from_clusters(
    clusters: list[ResultCluster],
    *,
    dominance_threshold: float = 0.67,
    dialect: str | None = None,
    intent_flagged: bool = False,
    assumption_hint: str = "",
) -> GateDecision:
    """Ask only when result clusters split and no cluster dominates."""
    if not clusters:
        return GateDecision(
            should_clarify=False,
            status="failed_open",
            reason="No executable candidates; proceeding without clarification",
            assumption=assumption_hint,
            decision_why="execution_gate;no_ok_executes",
            selected_sql=None,
            clusters=[],
        )

    total = sum(len(c.member_indices) for c in clusters)
    ranked = sorted(clusters, key=lambda c: (-len(c.member_indices), c.representative_sql))
    top = ranked[0]
    mass = len(top.member_indices) / total if total else 0.0

    cluster_payload = [
        {
            "size": len(c.member_indices),
            "sql": c.representative_sql[:500],
            "row_count": (c.results or {}).get("row_count"),
        }
        for c in ranked
    ]

    if len(ranked) == 1:
        return GateDecision(
            should_clarify=False,
            status="clear",
            reason="All executable candidates agree on results",
            assumption=assumption_hint,
            options=[],
            decision_why=f"execution_gate;single_cluster;n={total}",
            selected_sql=top.representative_sql,
            clusters=cluster_payload,
        )

    if mass >= dominance_threshold and not intent_flagged:
        options = options_from_clusters(ranked, dialect=dialect)
        # Drop the "Other" from assumed path follow-ups noise if only 1 real option.
        alts = [o for o in options if not o.startswith("Other")]
        return GateDecision(
            should_clarify=False,
            status="assumed",
            reason=(
                f"Dominant result cluster ({len(top.member_indices)}/{total}); "
                "answering with assumption"
            ),
            assumption=assumption_hint
            or f"Assumed the majority reading ({len(top.member_indices)} of {total} candidates)",
            options=alts[:3],
            decision_why=(
                f"execution_gate;dominant;mass={mass:.2f};"
                f"threshold={dominance_threshold:.2f};clusters={len(ranked)}"
            ),
            selected_sql=top.representative_sql,
            clusters=cluster_payload,
        )

    # Split (or intent-flagged with multiple clusters) → ask.
    options = options_from_clusters(ranked, dialect=dialect)
    return GateDecision(
        should_clarify=True,
        status="ambiguous",
        reason=(
            "Candidates produce materially different results; "
            "please choose the intended reading"
        ),
        assumption="",
        options=options,
        decision_why=(
            f"execution_gate;split;mass={mass:.2f};"
            f"threshold={dominance_threshold:.2f};clusters={len(ranked)}"
            + (";intent_flagged" if intent_flagged else "")
        ),
        selected_sql=None,
        clusters=cluster_payload,
    )


def effective_dominance_threshold(
    *,
    base: float,
    policy: str,
    connection_override: float | None = None,
) -> float:
    """Resolve per-connection dominance threshold.

    ``strict`` asks more (lower threshold); ``casual`` answers more (higher).
    """
    if connection_override is not None:
        return max(0.5, min(1.0, float(connection_override)))
    pol = (policy or "balanced").strip().lower()
    if pol == "strict":
        return max(0.5, min(1.0, base - 0.1))
    if pol == "casual":
        return max(0.5, min(1.0, base + 0.15))
    return max(0.5, min(1.0, base))


def filter_candidates_by_option(
    candidates: list[dict[str, Any]],
    *,
    chosen_option: str,
    dialect: str | None = None,
) -> list[dict[str, Any]]:
    """Keep candidates whose clause profile matches the chosen option text.

    Best-effort: if we cannot match, return the original list unchanged.
    """
    chosen = (chosen_option or "").strip().lower()
    if not chosen or chosen.startswith("other"):
        return candidates
    kept: list[dict[str, Any]] = []
    for item in candidates:
        sql = str(item.get("sql") or "")
        # Match option keywords against this SQL's own shape vs a peer.
        # Without a peer, accept any candidate whose AST mentions the clause word.
        tree = _parse_select(sql, dialect)
        if tree is None:
            continue
        blob = " ".join(
            [
                " ".join(_join_kinds(tree)),
                _where_sql(tree),
                " ".join(_agg_fns(tree)),
                " ".join(_group_keys(tree)),
                " ".join(_select_cols(tree)),
            ]
        ).lower()
        # Option text like "Use reading where: Join type: LEFT vs INNER"
        tokens = [t for t in chosen.replace(":", " ").split() if len(t) > 2]
        hit = any(t in blob for t in tokens if t not in {"use", "reading", "where", "type", "vs"})
        if hit:
            kept.append(item)
    return kept or candidates
