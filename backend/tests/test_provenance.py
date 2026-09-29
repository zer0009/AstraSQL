from src.agent.catalog import identity_keys_from_tables, serialize_keys
from src.agent.graph import route_after_validate
from src.agent.provenance import (
    clarify_or_none,
    clarify_unbound,
    ungrounded_key_filters,
)

LEAVE_TABLES = [
    {
        "table_name": "employees",
        "columns": [
            {"name": "id", "primary_key": True},
            {"name": "name"},
        ],
    },
    {
        "table_name": "leave_balances",
        "columns": [
            {"name": "id", "primary_key": True},
            {
                "name": "employee_id",
                "foreign_key": {"table": "employees", "column": "id"},
            },
            {"name": "year"},
        ],
    },
    {
        "table_name": "users",
        "columns": [
            {"name": "id", "primary_key": True},
            {
                "name": "employee_id",
                "foreign_key": {"table": "employees", "column": "id"},
            },
        ],
    },
]

KEYS = identity_keys_from_tables(LEAVE_TABLES)

LIVE_BIND_SQL = (
    "SELECT e.name AS employee_name, lb.year, lt.code AS leave_type_code, "
    "lt.name AS leave_type_name, lbe.days AS available_days "
    "FROM employees AS e "
    "JOIN leave_balances AS lb ON e.id = lb.employee_id "
    "JOIN leave_balance_entries AS lbe ON lb.id = lbe.balance_id "
    "JOIN leave_types AS lt ON lbe.leave_type_id = lt.id "
    "WHERE e.id = $1 AND lb.year = EXTRACT(YEAR FROM CURRENT_DATE)::integer "
    "ORDER BY lt.name LIMIT 500"
)

SESSION_SQL = (
    "SELECT e.name AS employee_name, lb.year, lt.code AS leave_type_code, "
    "lt.name AS leave_type_name, SUM(lbe.days) AS available_days "
    "FROM users AS u JOIN employees AS e ON e.id = u.employee_id "
    "JOIN leave_balances AS lb ON lb.employee_id = e.id "
    "JOIN leave_balance_entries AS lbe ON lbe.balance_id = lb.id "
    "JOIN leave_types AS lt ON lt.id = lbe.leave_type_id "
    "WHERE u.id = current_setting('app.user_id', true) "
    "AND lb.year = EXTRACT(YEAR FROM CURRENT_DATE)::integer "
    "GROUP BY e.name, lb.year, lt.code, lt.name ORDER BY lt.name LIMIT 500"
)


def _slots(sql: str, question: str, extra: str = ""):
    return ungrounded_key_filters(
        sql,
        question=question,
        extra_text=extra,
        identity_keys=KEYS,
    )


def test_ungrounded_employee_id_literal():
    slots = _slots(
        "SELECT lb.available_days FROM leave_balances lb "
        "JOIN employees e ON e.id = lb.employee_id WHERE e.id = 1",
        "I need to know my available balance",
    )
    assert slots
    assert slots[0].table == "employees"
    assert slots[0].column == "id"
    assert slots[0].used_value == "1"


def test_arabic_question_same_ungrounded_id():
    slots = _slots(
        "SELECT lb.available_days FROM leave_balances lb WHERE lb.employee_id = 1",
        "اريد معرفة رصيد اجازتي",
    )
    assert slots
    assert slots[0].used_value == "1"


LIVE_USERS_BIND_SQL = (
    "SELECT e.name AS employee_name, lt.code AS leave_type_code, "
    "lt.name AS leave_type_name, SUM(lbe.days) AS available_days "
    "FROM users AS u JOIN employees AS e ON e.id = u.employee_id "
    "JOIN leave_balances AS lb ON lb.employee_id = e.id "
    "JOIN leave_balance_entries AS lbe ON lbe.balance_id = lb.id "
    "JOIN leave_types AS lt ON lt.id = lbe.leave_type_id "
    "WHERE u.id = $1 AND lb.year = EXTRACT(YEAR FROM CURRENT_DATE)::integer "
    "GROUP BY e.name, lt.code, lt.name ORDER BY lt.name"
)


def test_placeholder_on_users_id_is_ungrounded():
    slots = _slots(LIVE_USERS_BIND_SQL, "اريد معرفة رصيد اجازتي")
    assert slots
    assert any(s.used_value == "$1" for s in slots)


def test_placeholder_on_key_is_ungrounded():
    slots = _slots(LIVE_BIND_SQL, "my available balance")
    assert slots
    assert any(s.used_value == "$1" for s in slots)


def test_bind_without_catalog_still_blocked():
    slots = ungrounded_key_filters(
        LIVE_BIND_SQL,
        question="اريد معرفة رصيد اجازتي",
        identity_keys=set(),
    )
    assert slots
    assert slots[0].used_value == "$1"


def test_id_in_the_question_is_grounded():
    assert (
        _slots(
            "SELECT available_days FROM leave_balances WHERE employee_id = 42",
            "Show leave balance for employee 42",
        )
        == []
    )


def test_history_can_ground_an_id():
    assert (
        _slots(
            "SELECT available_days FROM leave_balances WHERE employee_id = 42",
            "and the sick leave?",
            extra="Show leave for employee 42\nWHERE employee_id = 42",
        )
        == []
    )


def test_rule_can_ground_a_literal():
    assert (
        _slots(
            "SELECT * FROM leave_balances WHERE employee_id = 7",
            "my balance",
            extra="demo employee is always employee_id = 7",
        )
        == []
    )


def test_status_filter_is_not_a_key():
    shop = identity_keys_from_tables(
        [
            {
                "table_name": "orders",
                "columns": [
                    {"name": "id", "primary_key": True},
                    {"name": "status"},
                ],
            }
        ]
    )
    slots = ungrounded_key_filters(
        "SELECT COUNT(*) FROM orders WHERE status = 'completed'",
        question="how many orders",
        identity_keys=shop,
    )
    assert slots == []


def test_no_key_filter_means_no_slot():
    assert (
        _slots(
            "SELECT e.name, lb.available_days FROM leave_balances lb "
            "JOIN employees e ON e.id = lb.employee_id",
            "I need to know my available balance",
        )
        == []
    )


def test_current_setting_on_users_id_is_ungrounded():
    slots = _slots(SESSION_SQL, "I need to know my available balance")
    assert slots
    assert any("current_setting" in (s.used_value or "").lower() for s in slots)
    assert any(s.column == "id" and s.table == "users" for s in slots)


def test_extract_year_is_not_a_key_filter():
    assert (
        _slots(
            "SELECT SUM(lbe.days) FROM leave_balances lb "
            "JOIN leave_balance_entries lbe ON lbe.balance_id = lb.id "
            "WHERE lb.year = EXTRACT(YEAR FROM CURRENT_DATE)",
            "available leave this year",
        )
        == []
    )


def test_join_keys_are_not_filters():
    assert (
        _slots(
            "SELECT e.name FROM users u JOIN employees e ON e.id = u.employee_id",
            "list employees",
        )
        == []
    )


def test_clarify_or_none_uses_context_keys():
    state = {
        "question": "I need to know my available balance",
        "context": {"identity_keys": serialize_keys(KEYS)},
        "steps": [],
    }
    update = clarify_or_none(state, SESSION_SQL, "postgres")
    assert update is not None
    assert update["intent"] == "CLARIFICATION_NEEDED"
    assert update["ambiguity"]["should_clarify"] is True
    assert update["error"] is None


def test_route_after_validate_clarifies_before_execute():
    assert (
        route_after_validate(
            {"ambiguity": {"should_clarify": True}, "error": None}
        )
        == "clarify"
    )
    assert route_after_validate({"error": None}) == "execute"


LIVE_LB_BIND_SQL = (
    "SELECT e.name AS employee_name, lb.year, lt.code AS leave_type_code, "
    "lt.name AS leave_type_name, lbe.days AS available_days "
    "FROM leave_balances AS lb "
    "JOIN employees AS e ON lb.employee_id = e.id "
    "JOIN leave_balance_entries AS lbe ON lbe.balance_id = lb.id "
    "JOIN leave_types AS lt ON lbe.leave_type_id = lt.id "
    "WHERE lb.employee_id = $1 "
    "AND lb.year = EXTRACT(YEAR FROM CURRENT_DATE)::integer "
    "ORDER BY lt.name LIMIT 500"
)


def test_placeholder_on_leave_balances_employee_id():
    slots = _slots(LIVE_LB_BIND_SQL, "I need to know my available balance")
    assert slots
    assert any(
        s.table == "leave_balances" and s.column == "employee_id"
        for s in slots
    )


LOWER_OR_BIND_SQL = (
    "SELECT e.name AS employee_name, lt.name AS leave_type, "
    "lt.code AS leave_type_code, lbe.days AS available_days, lb.year "
    "FROM users AS u JOIN employees AS e ON e.id = u.employee_id "
    "JOIN leave_balances AS lb ON lb.employee_id = e.id "
    "JOIN leave_balance_entries AS lbe ON lbe.balance_id = lb.id "
    "JOIN leave_types AS lt ON lt.id = lbe.leave_type_id "
    "WHERE lower(u.username) = lower($1) OR lower(u.email) = lower($1) "
    "AND lb.year = EXTRACT(YEAR FROM CURRENT_DATE)::integer "
    "ORDER BY lt.name LIMIT 500"
)


def test_bind_inside_lower_function_is_still_caught():
    # $1 is wrapped in lower(...) on both sides of an OR — neither side is a
    # bare Column, so the AST-level key match cannot see it. The plain-text
    # bind scan must still flag it: any $n/:name/? is always invented.
    slots = _slots(LOWER_OR_BIND_SQL, "I need to know my available balance")
    assert slots
    assert any(s.used_value == "$1" for s in slots)


def test_clarify_unbound_always_asks():
    state = {"question": "my balance", "context": {}, "steps": []}
    update = clarify_unbound(state, LIVE_LB_BIND_SQL, "postgres")
    assert update["intent"] == "CLARIFICATION_NEEDED"
    assert update["ambiguity"]["should_clarify"] is True
    assert update["error"] is None


async def test_executor_never_explains_bind_sql():
    from unittest.mock import AsyncMock, MagicMock

    from src.agent.nodes.query_executor import query_executor

    db = MagicMock()
    db.sqlglot_dialect.return_value = "postgres"
    db.explain_query = AsyncMock(
        side_effect=AssertionError("EXPLAIN must not run")
    )
    state = {
        "question": "I need to know my available balance",
        "sql": LIVE_LB_BIND_SQL,
        "corrected_sql": LIVE_LB_BIND_SQL,
        "context": {"identity_keys": serialize_keys(KEYS)},
        "steps": [],
        "retries": 0,
    }
    update = await query_executor(
        state, {"configurable": {"db_provider": db}}
    )
    assert update["intent"] == "CLARIFICATION_NEEDED"
    assert update["ambiguity"]["should_clarify"] is True
    db.explain_query.assert_not_called()
