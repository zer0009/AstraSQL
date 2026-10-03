from src.agent.catalog import (
    deserialize_keys,
    identity_keys,
    identity_keys_from_tables,
    serialize_keys,
)

LEAVE_TABLES = [
    {
        "table_name": "employees",
        "columns": [
            {"name": "id", "primary_key": True},
            {"name": "name"},
            {"name": "email"},
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


def test_identity_keys_are_only_pk_and_fk():
    keys = identity_keys_from_tables(LEAVE_TABLES)
    assert ("employees", "id") in keys
    assert ("leave_balances", "employee_id") in keys
    assert ("users", "id") in keys
    assert ("employees", "name") not in keys
    assert ("leave_balances", "year") not in keys


def test_identity_keys_accept_column_name_alias():
    keys = identity_keys(
        {
            "orders": [
                {"column_name": "id", "primary_key": True},
                {
                    "column_name": "customer_id",
                    "foreign_key": {"foreign_table_name": "customers"},
                },
            ]
        }
    )
    assert keys == {("orders", "id"), ("orders", "customer_id")}


def test_serialize_roundtrip():
    keys = identity_keys_from_tables(LEAVE_TABLES)
    assert deserialize_keys(serialize_keys(keys)) == keys


def test_arabic_table_names():
    keys = identity_keys_from_tables(
        [
            {
                "table_name": "الموظفين",
                "columns": [
                    {"name": "id", "primary_key": True},
                    {"name": "الاسم"},
                ],
            },
            {
                "table_name": "الارصدة",
                "columns": [
                    {"name": "id", "primary_key": True},
                    {
                        "name": "employee_id",
                        "foreign_key": {"table": "الموظفين", "column": "id"},
                    },
                ],
            },
        ]
    )
    assert ("الموظفين", "id") in keys
    assert ("الارصدة", "employee_id") in keys
    assert ("الموظفين", "الاسم") not in keys
