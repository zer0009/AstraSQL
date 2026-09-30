# Clarification baseline (pre-fix)

Recorded from user report + code path analysis (2026-03-29).

## Failing turn

- Question: "how we can calculate to get best employee"
- Observed intent: `CLARIFICATION_NEEDED` at `intent_classified` (no schema yet)
- Next node: `direct_response` (skipped `context_retriever`)
- Answer invented generic metrics: leave balance, performance, sales, attendance
- "Did you mean?" options sometimes mentioned leave (unrelated to a grounded schema check)

## Root cause

Intent classifier and direct_response both ran without the retrieved schema.
Clarification was an LLM reflex, not a policy over schema-grounded candidates.

## Baseline metrics

Full live eval against `project_shop` requires a configured connection id + LLM
credits. Unit/policy baseline is covered by:

- `tests/test_clarification_baseline.py`
- `tests/test_ambiguity.py` (policy / validation)
- `tests/test_graph_routing.py`

Acceptance after the fix (compare with `python -m src.eval.run` when connected):

| Metric | Target |
| --- | --- |
| option-validity (schema refs) | 100% (enforced in code) |
| false-ask on clear count questions | not higher than prior |
| silent_wrong on expect=clarify | not higher than prior |
| clear-still-answers | expect=answer must still answer |

Gold additions: `vague-best-customer`, `vague-top-product`,
`unanswerable-churn-score`, `clear-still-answers`.
