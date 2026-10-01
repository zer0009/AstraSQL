from src.eval.spider_fewshot import question_skeleton


def test_question_skeleton_masks_quotes_and_numbers():
    q = 'How many singers in "USA" are older than 30?'
    sk = question_skeleton(q)
    assert '"USA"' not in sk
    assert "USA" not in sk
    assert "30" not in sk
    assert "<STR>" in sk
    assert "<NUM>" in sk
    assert "how many singers" in sk


def test_question_skeleton_collapses_whitespace():
    sk = question_skeleton("  Count   5   rows  ")
    assert "  " not in sk
    assert "<NUM>" in sk


def test_question_skeleton_single_quotes():
    sk = question_skeleton("Find name = 'Alice'")
    assert "Alice" not in sk
    assert "<STR>" in sk
