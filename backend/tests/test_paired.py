from src.eval.paired import bootstrap_accuracy_diff, compare_reports, mcnemar_exact


def test_mcnemar_identical():
    a = {"q1": True, "q2": False, "q3": True}
    b = dict(a)
    r = mcnemar_exact(a, b)
    assert r["discordant"] == 0
    assert r["p_value"] == 1.0


def test_mcnemar_detects_flip():
    a = {f"q{i}": False for i in range(10)}
    b = {f"q{i}": (i < 8) for i in range(10)}
    r = mcnemar_exact(a, b)
    assert r["b_only"] == 8
    assert r["a_only"] == 0
    assert r["significant_0_05"] is True


def test_bootstrap_ci():
    a = {f"q{i}": False for i in range(20)}
    b = {f"q{i}": True for i in range(20)}
    r = bootstrap_accuracy_diff(a, b, n_boot=500, seed=1)
    assert r["mean_diff"] > 0.9
    assert r["ci_excludes_zero"] is True


def test_compare_reports():
    a = {
        "questions": [
            {"id": "1", "result_match_values": True},
            {"id": "2", "result_match_values": False},
        ]
    }
    b = {
        "questions": [
            {"id": "1", "result_match_values": True},
            {"id": "2", "result_match_values": True},
        ]
    }
    r = compare_reports(a, b)
    assert r["a_accuracy"] == 0.5
    assert r["b_accuracy"] == 1.0
    assert len(r["flips"]) == 1
