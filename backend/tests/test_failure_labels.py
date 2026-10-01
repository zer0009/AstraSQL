from src.eval.failure_labels import label_failure


def test_scorer_only_label():
    gold_sql = "SELECT country, count(*) FROM singer GROUP BY country"
    gen_sql = (
        "SELECT country, COUNT(*) AS singer_count FROM singer "
        "GROUP BY country ORDER BY country"
    )
    gold = {
        "columns": ["country", "count(*)"],
        "rows": [{"country": "France", "count(*)": 2}],
    }
    gen = {
        "columns": ["country", "singer_count"],
        "rows": [{"country": "France", "singer_count": 2}],
    }
    assert (
        label_failure(
            gold_sql=gold_sql,
            generated_sql=gen_sql,
            gold_result=gold,
            generated_result=gen,
        )
        == "scorer_only"
    )


def test_wrong_table_label():
    assert (
        label_failure(
            gold_sql="SELECT name FROM singer",
            generated_sql="SELECT name FROM stadium",
            gold_result={"columns": ["name"], "rows": [{"name": "Alice"}]},
            generated_result={"columns": ["name"], "rows": [{"name": "Big Arena"}]},
        )
        == "wrong_table"
    )


def test_join_type_label():
    gold = {
        "columns": ["name", "c"],
        "rows": [{"name": "A", "c": 1}],
        "row_count": 1,
    }
    gen = {
        "columns": ["name", "c"],
        "rows": [{"name": "A", "c": 1}, {"name": "B", "c": 0}],
        "row_count": 2,
    }
    assert (
        label_failure(
            gold_sql=(
                "SELECT s.Name, COUNT(st.concert_ID) FROM singer AS s "
                "JOIN singer_in_concert AS st ON s.Singer_ID = st.Singer_ID "
                "GROUP BY s.Name"
            ),
            generated_sql=(
                "SELECT s.Name, COUNT(st.concert_ID) FROM singer AS s "
                "LEFT JOIN singer_in_concert AS st ON s.Singer_ID = st.Singer_ID "
                "GROUP BY s.Name"
            ),
            gold_result=gold,
            generated_result=gen,
        )
        == "join_type"
    )


def test_clarified_label():
    assert (
        label_failure(
            gold_sql="SELECT 1",
            generated_sql=None,
            clarified=True,
        )
        == "clarified_instead_of_answering"
    )


def test_sql_error_label():
    assert (
        label_failure(
            gold_sql="SELECT 1",
            generated_sql="SELECT bad",
            error="no such column",
        )
        == "sql_error"
    )


def test_tie_or_limit_label():
    gold = {"columns": ["n"], "rows": [{"n": 1}], "row_count": 1}
    gen = {"columns": ["n"], "rows": [{"n": 2}], "row_count": 1}
    assert (
        label_failure(
            gold_sql=(
                "SELECT count(*) FROM concert WHERE stadium_id = "
                "(SELECT stadium_id FROM stadium ORDER BY capacity DESC LIMIT 1)"
            ),
            generated_sql=(
                "SELECT count(*) FROM concert WHERE Capacity = "
                "(SELECT MAX(Capacity) FROM stadium)"
            ),
            gold_result=gold,
            generated_result=gen,
        )
        == "tie_or_limit"
    )
