from src.eval.spider_data import (
    infer_hardness,
    pick_multi_db,
    pick_stratified,
    question_stable_id,
)


def _fake_items() -> list[dict]:
    items = []
    # concert_singer: mix of hardness
    for _i, (q, sql, hard) in enumerate(
        [
            ("q_easy_1", "SELECT name FROM singer", "easy"),
            ("q_med_1", "SELECT country, count(*) FROM singer GROUP BY country", "medium"),
            ("q_hard_1", "SELECT name FROM singer WHERE id IN (SELECT id FROM stadium)", "hard"),
            ("q_extra_1", "SELECT a.name FROM singer a JOIN concert b ON a.id=b.id JOIN stadium c ON b.sid=c.id GROUP BY a.name", "extra"),
            ("q_easy_2", "SELECT age FROM singer", "easy"),
            ("q_med_2", "SELECT * FROM singer JOIN concert ON singer.id = concert.sid", "medium"),
        ]
    ):
        items.append(
            {
                "db_id": "concert_singer",
                "question": q,
                "query": sql,
                "hardness": hard,
            }
        )
    for i in range(6):
        items.append(
            {
                "db_id": "pets_1",
                "question": f"pets_q_{i}",
                "query": "SELECT name FROM Pets" if i < 3 else "SELECT name FROM Pets JOIN Student ON 1=1",
                "hardness": "easy" if i < 3 else "medium",
            }
        )
    return items


def test_pick_stratified_uses_hardness_labels():
    items = _fake_items()
    picked = pick_stratified(items, db_id="concert_singer", n=4, seed=7)
    assert len(picked) == 4
    hardnesses = {p["_hardness"] for p in picked}
    assert "easy" in hardnesses
    assert "medium" in hardnesses


def test_pick_multi_db_respects_db_ids():
    items = _fake_items()
    picked = pick_multi_db(
        items,
        db_ids=["concert_singer", "pets_1"],
        per_db=3,
        seed=1,
    )
    assert len(picked) == 6
    dbs = {p["db_id"] for p in picked}
    assert dbs == {"concert_singer", "pets_1"}


def test_question_stable_id_stable():
    item = {"db_id": "x", "question": "how many?"}
    assert question_stable_id(item) == question_stable_id(item)


def test_infer_hardness_fallback():
    assert infer_hardness("SELECT name FROM t") == "easy"
    assert infer_hardness("SELECT count(*) FROM t GROUP BY a") == "medium"
