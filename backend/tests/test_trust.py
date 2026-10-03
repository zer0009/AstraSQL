from src.agent.trust import compute_trust_level, normalize_sql


def test_normalize_sql_ignores_formatting():
    a = "SELECT  amount FROM orders WHERE id = 1"
    b = "select amount from orders where id=1"
    assert normalize_sql(a, "postgres") == normalize_sql(b, "postgres")


def test_certified_when_sql_matches_golden():
    level = compute_trust_level(
        intent="SQL_QUERY",
        error=None,
        generated_sql="SELECT amount FROM orders",
        golden_sqls=["select  amount  from orders"],
        used_golden=True,
        dialect="postgres",
    )
    assert level == "certified"


def test_taught_when_golden_used_but_sql_differs():
    level = compute_trust_level(
        intent="SQL_QUERY",
        error=None,
        generated_sql="SELECT SUM(amount) FROM orders",
        golden_sqls=["SELECT amount FROM orders"],
        used_golden=True,
        dialect="postgres",
    )
    assert level == "taught"


def test_guessed_when_no_golden():
    level = compute_trust_level(
        intent="SQL_QUERY",
        error=None,
        generated_sql="SELECT amount FROM orders",
        golden_sqls=[],
        used_golden=False,
        dialect="postgres",
    )
    assert level == "guessed"


def test_clarifying_when_no_sql_and_clarify_intent():
    level = compute_trust_level(
        intent="CLARIFICATION_NEEDED",
        error=None,
        generated_sql="",
        golden_sqls=[],
        used_golden=False,
        dialect="postgres",
    )
    assert level == "clarifying"


def test_failed_when_error_and_no_sql():
    level = compute_trust_level(
        intent="SQL_QUERY",
        error="relation does not exist",
        generated_sql="",
        golden_sqls=[],
        used_golden=False,
        dialect="postgres",
    )
    assert level == "failed"
