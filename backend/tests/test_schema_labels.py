from src.context.schema_labels import (
    fk_label_hint,
    humanize_dimension_expr,
    reading_label_for_group_keys,
    unreadable_fk_dimension_issues,
)


def test_humanize_strips_id_suffix():
    assert humanize_dimension_expr("rp.country_id") == "country"
    assert humanize_dimension_expr('rcs.name->>\'en_US\'') == "name"


def test_reading_label_nudge_for_fk_ids():
    label = reading_label_for_group_keys(["rp.country_id", "rp.state_id"])
    assert "country" in label.lower()
    assert "state" in label.lower()
    assert "names" in label.lower()
    assert "country_id" not in label


def test_fk_label_hint_includes_prefer_join():
    hint = fk_label_hint(
        {"table": "res_country", "column": "id"},
        target_columns=[
            {"name": "id", "primary_key": True},
            {"name": "name", "type": "jsonb"},
            {"name": "code", "type": "varchar"},
        ],
    )
    assert "FK to res_country.id" in hint
    assert "prefer JOIN res_country" in hint
    assert "name" in hint


def test_unreadable_fk_dimension_issues_flags_raw_ids():
    schema = """
-- TABLE: sale_order
CREATE TABLE sale_order (
    id  integer PRIMARY KEY,
    partner_id  integer,  -- FK to res_partner.id; prefer JOIN res_partner and SELECT name
    FOREIGN KEY (partner_id) REFERENCES res_partner(id)
);
-- TABLE: res_partner
CREATE TABLE res_partner (
    id  integer PRIMARY KEY,
    name  varchar,
    country_id  integer,
    FOREIGN KEY (country_id) REFERENCES res_country(id)
);
-- TABLE: res_country
CREATE TABLE res_country (
    id  integer PRIMARY KEY,
    name  varchar,
    code  varchar
);
"""
    sql = (
        "SELECT rp.country_id, SUM(1) AS n "
        "FROM sale_order so "
        "JOIN res_partner rp ON rp.id = so.partner_id "
        "GROUP BY rp.country_id"
    )
    issues = unreadable_fk_dimension_issues(
        sql, dialect="postgres", enriched_schema=schema
    )
    assert issues
    assert any("country_id" in i and "res_country" in i for i in issues)


def test_unreadable_fk_ok_when_label_projected():
    schema = """
-- TABLE: sale_order
CREATE TABLE sale_order (
    id  integer PRIMARY KEY,
    partner_id  integer,
    FOREIGN KEY (partner_id) REFERENCES res_partner(id)
);
-- TABLE: res_partner
CREATE TABLE res_partner (
    id  integer PRIMARY KEY,
    name  varchar,
    country_id  integer,
    FOREIGN KEY (country_id) REFERENCES res_country(id)
);
-- TABLE: res_country
CREATE TABLE res_country (
    id  integer PRIMARY KEY,
    name  varchar
);
"""
    sql = (
        "SELECT rc.name, SUM(1) AS n "
        "FROM sale_order so "
        "JOIN res_partner rp ON rp.id = so.partner_id "
        "JOIN res_country rc ON rc.id = rp.country_id "
        "GROUP BY rc.name"
    )
    assert (
        unreadable_fk_dimension_issues(
            sql, dialect="postgres", enriched_schema=schema
        )
        == []
    )
