import json
from pathlib import Path

import pytest

from src.eval.ambiguity_eval import (
    load_bird_interact_items,
    load_must_clarify,
    score_ask_precision_recall,
    state_was_clarified,
)


def test_load_must_clarify_default():
    items = load_must_clarify()
    assert len(items) >= 10
    assert all(i["expect"] in ("clarify", "answer") for i in items)
    assert all(i["question"] for i in items)


def test_score_ask_precision_recall_basic():
    cases = [
        {"expect": "clarify", "clarified": True},   # TP
        {"expect": "clarify", "clarified": False},  # FN
        {"expect": "answer", "clarified": False},   # TN
        {"expect": "answer", "clarified": True},    # FP
    ]
    scores = score_ask_precision_recall(cases)
    assert scores["tp"] == 1
    assert scores["fn"] == 1
    assert scores["tn"] == 1
    assert scores["fp"] == 1
    assert scores["precision"] == pytest.approx(0.5)
    assert scores["recall"] == pytest.approx(0.5)
    assert scores["f1"] == pytest.approx(0.5)


def test_score_perfect_clarify_set():
    cases = [{"expect": "clarify", "clarified": True} for _ in range(5)]
    scores = score_ask_precision_recall(cases)
    assert scores["precision"] == 1.0
    assert scores["recall"] == 1.0
    assert scores["fp"] == 0


def test_state_was_clarified_helpers():
    assert state_was_clarified({"ambiguity": {"should_clarify": True}})
    assert state_was_clarified({"intent": "CLARIFICATION_NEEDED"})
    assert not state_was_clarified({"ambiguity": {"should_clarify": False}, "sql": "SELECT 1"})
    assert not state_was_clarified(None)


def test_load_bird_interact_items(tmp_path: Path):
    path = tmp_path / "bird.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "a1",
                    "amb_user_query": "What is revenue?",
                    "user_query_ambiguity": True,
                },
                {
                    "id": "a2",
                    "query": "How many orders?",
                    "user_query_ambiguity": False,
                },
            ]
        ),
        encoding="utf-8",
    )
    items = load_bird_interact_items(path)
    assert len(items) == 2
    assert items[0]["expect"] == "clarify"
    assert items[1]["expect"] == "answer"
