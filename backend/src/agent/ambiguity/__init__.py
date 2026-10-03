"""Conservative, deterministic ambiguity gate. No LLM, no IO.

Pre-SQL: only conflicting *project* rules. Identity slots are checked
after SQL is written — see ``src.agent.provenance``.

Schema-grounded interpretation policy (ask vs proceed) lives here too:
the LLM may propose candidates; this module decides.
"""

from src.agent.ambiguity.candidates import (
    _candidates_materially_different,
    candidate_is_grounded,
    parse_interpretation_payload,
    prior_turn_was_clarification,
    validate_candidates,
)
from src.agent.ambiguity.policy import apply_interpretation_policy, decide_ambiguity
from src.agent.ambiguity.schema_digest import build_schema_digest, build_schema_index
from src.agent.ambiguity.types import (
    AmbiguityDecision,
    InterpretationCandidate,
    InterpretationProposal,
    PolicyDecision,
)

__all__ = [
    "AmbiguityDecision",
    "InterpretationCandidate",
    "InterpretationProposal",
    "PolicyDecision",
    "apply_interpretation_policy",
    "build_schema_digest",
    "build_schema_index",
    "candidate_is_grounded",
    "decide_ambiguity",
    "parse_interpretation_payload",
    "prior_turn_was_clarification",
    "validate_candidates",
    "_candidates_materially_different",
]
