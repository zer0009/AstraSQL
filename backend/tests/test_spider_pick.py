from src.eval.spider_data import default_pilot_db, infer_hardness, pick_stratified


def test_infer_hardness():
    assert infer_hardness("SELECT name FROM singer") == "easy"
    assert infer_hardness("SELECT COUNT(*) FROM singer") == "medium"
    assert (
        infer_hardness(
            "SELECT s.name FROM singer s JOIN album a ON s.id = a.singer_id"
        )
        == "medium"
    )
    assert (
        infer_hardness(
            "SELECT name FROM singer WHERE id IN (SELECT singer_id FROM album)"
        )
        == "hard"
    )


def test_pick_stratified_deterministic():
    items = []
    for i, hard_sql in enumerate(
        [
            ("SELECT a FROM t", "easy"),
            ("SELECT COUNT(*) FROM t", "medium"),
            ("SELECT * FROM t JOIN u ON t.id = u.id JOIN v ON u.id = v.id", "hard"),
            (
                "SELECT * FROM t WHERE id IN (SELECT id FROM u JOIN v ON u.id=v.id GROUP BY u.id)",
                "extra",
            ),
            ("SELECT AVG(x) FROM t", "medium"),
        ]
    ):
        items.append(
            {
                "db_id": "concert_singer",
                "question": f"Q{i}",
                "query": hard_sql[0],
            }
        )
    a = pick_stratified(items, db_id="concert_singer", n=5, seed=42)
    b = pick_stratified(items, db_id="concert_singer", n=5, seed=42)
    assert [x["question"] for x in a] == [x["question"] for x in b]
    assert len(a) == 5
    hardnesses = {x["_hardness"] for x in a}
    assert "easy" in hardnesses
    assert default_pilot_db(items) == "concert_singer"
