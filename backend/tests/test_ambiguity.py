from src.agent.ambiguity import (
    InterpretationCandidate,
    InterpretationProposal,
    apply_interpretation_policy,
    build_schema_index,
    candidate_is_grounded,
    decide_ambiguity,
    parse_interpretation_payload,
    prior_turn_was_clarification,
    validate_candidates,
)


def test_conflicting_revenue_rules_clarify():
    decision = decide_ambiguity(
        "what is revenue",
        rules=[
            "revenue means SUM(order_items.qty * order_items.unit_price) as gross",
            "revenue means gross minus refunds in payments as net",
        ],
        golden_questions=[],
    )
    assert decision.should_clarify is True
    assert "revenue" in decision.reason.lower()
    assert len(decision.options) >= 2


def test_close_golden_does_not_clarify():
    decision = decide_ambiguity(
        "how many customers in texas",
        rules=[],
        golden_questions=["How many customers are in Texas?"],
    )
    assert decision.should_clarify is False


def test_undefined_metric_does_not_use_english_word_lists():
    """No hardcoded metric lexicon — a lone word is not a product rule."""
    decision = decide_ambiguity(
        "what is revenue",
        rules=[],
        golden_questions=[],
    )
    assert decision.should_clarify is False


def test_defined_active_with_entity_answers():
    decision = decide_ambiguity(
        "How many active customers?",
        rules=["active customers means status = 'A'"],
        golden_questions=[],
    )
    assert decision.should_clarify is False


def test_first_person_is_not_an_english_pre_sql_gate():
    decision = decide_ambiguity(
        "I need to know my available balance",
        rules=[],
        golden_questions=[],
    )
    assert decision.should_clarify is False


def test_arabic_question_is_not_an_english_pre_sql_gate():
    decision = decide_ambiguity(
        "اريد معرفة رصيد اجازتي",
        rules=[],
        golden_questions=[],
    )
    assert decision.should_clarify is False


def test_gross_revenue_picks_one_rule():
    decision = decide_ambiguity(
        "What is total gross revenue from order line items?",
        rules=[
            "gross revenue means SUM(order_items.qty * order_items.unit_price)",
            "net revenue means gross revenue minus refunds",
        ],
        golden_questions=[],
    )
    assert decision.should_clarify is False


def test_specific_question_without_conflict_answers():
    decision = decide_ambiguity(
        "how many orders did customers in texas place in 2024",
        rules=["active customers means status = 'A'"],
        golden_questions=[],
    )
    assert decision.should_clarify is False


def test_arabic_conflicting_rules_clarify():
    decision = decide_ambiguity(
        "ما هو الايراد",
        rules=[
            "الايراد يعني مجموع المبيعات الاجمالي",
            "الايراد يعني الصافي بعد المرتجعات",
        ],
        golden_questions=[],
    )
    assert decision.should_clarify is True


def _shop_schema():
    return build_schema_index(
        ["customers", "orders", "order_items"],
        [
            {"table": "customers", "column": "id"},
            {"table": "customers", "column": "name"},
            {"table": "customers", "column": "status"},
            {"table": "orders", "column": "id"},
            {"table": "orders", "column": "customer_id"},
            {"table": "order_items", "column": "qty"},
            {"table": "order_items", "column": "unit_price"},
        ],
    )


def test_candidate_validation_drops_invented_tables():
    tables, pairs, bare = _shop_schema()
    valid = validate_candidates(
        [
            InterpretationCandidate(
                label="most orders",
                question="Which customer placed the most orders?",
                tables=("customers", "orders"),
                columns=("customers.name", "orders.id"),
            ),
            InterpretationCandidate(
                label="sales performance",
                question="Which employee has the highest sales?",
                tables=("employees", "sales"),
                columns=("employees.name", "sales.amount"),
            ),
        ],
        tables=tables,
        column_pairs=pairs,
        bare_columns=bare,
    )
    assert len(valid) == 1
    assert "orders" in valid[0].question.lower()


def test_candidate_is_grounded_requires_schema_refs():
    tables, pairs, bare = _shop_schema()
    ok = InterpretationCandidate(
        label="x",
        question="List customer names",
        tables=("customers",),
        columns=("customers.name",),
    )
    bad = InterpretationCandidate(
        label="y",
        question="Top salesperson",
        tables=("sales",),
        columns=("sales.amount",),
    )
    assert candidate_is_grounded(
        ok, tables=tables, column_pairs=pairs, bare_columns=bare
    )
    assert not candidate_is_grounded(
        bad, tables=tables, column_pairs=pairs, bare_columns=bare
    )


def test_policy_asks_when_two_valid_candidates():
    tables, pairs, bare = _shop_schema()
    proposal = InterpretationProposal(
        status="ambiguous",
        assumption="",
        reason="best is vague",
        candidates=(
            InterpretationCandidate(
                label="most orders",
                question="Which customer placed the most orders?",
                tables=("customers", "orders"),
                columns=("customers.name", "orders.id"),
            ),
            InterpretationCandidate(
                label="highest spend",
                question="Which customer has the highest order-item spend?",
                tables=("customers", "order_items"),
                columns=("customers.name", "order_items.unit_price"),
            ),
        ),
    )
    decision = apply_interpretation_policy(
        proposal,
        question="who is the best customer",
        tables=tables,
        column_pairs=pairs,
        bare_columns=bare,
        rules=[],
        golden_questions=[],
    )
    assert decision.should_clarify is True
    assert decision.status == "ambiguous"
    assert len(decision.options) >= 2
    assert any("Other" in o for o in decision.options)


def test_policy_assumes_single_valid_candidate():
    tables, pairs, bare = _shop_schema()
    proposal = InterpretationProposal(
        status="ambiguous",
        assumption="",
        reason="one reading",
        candidates=(
            InterpretationCandidate(
                label="most orders",
                question="Which customer placed the most orders?",
                tables=("customers", "orders"),
                columns=("customers.name", "orders.id"),
            ),
            InterpretationCandidate(
                label="fake sales",
                question="Highest sales employee",
                tables=("employees",),
                columns=("employees.sales",),
            ),
        ),
    )
    decision = apply_interpretation_policy(
        proposal,
        question="best customer",
        tables=tables,
        column_pairs=pairs,
        bare_columns=bare,
        rules=[],
        golden_questions=[],
    )
    assert decision.should_clarify is False
    assert decision.status == "assumed"
    assert decision.selected is not None
    assert "orders" in decision.selected.question.lower()


def test_policy_budget_spent_proceeds_with_top():
    tables, pairs, bare = _shop_schema()
    proposal = InterpretationProposal(
        status="ambiguous",
        assumption="",
        reason="still vague",
        candidates=(
            InterpretationCandidate(
                label="most orders",
                question="Which customer placed the most orders?",
                tables=("customers", "orders"),
                columns=("customers.name", "orders.id"),
            ),
            InterpretationCandidate(
                label="highest spend",
                question="Which customer has the highest order-item spend?",
                tables=("customers", "order_items"),
                columns=("customers.name", "order_items.unit_price"),
            ),
        ),
    )
    decision = apply_interpretation_policy(
        proposal,
        question="the first one",
        tables=tables,
        column_pairs=pairs,
        bare_columns=bare,
        rules=[],
        golden_questions=[],
        conversation_history=[
            {
                "question": "best customer",
                "sql": "",
                "answer": "Which metric?",
                "trust_level": "clarifying",
            }
        ],
    )
    assert decision.should_clarify is False
    assert decision.status == "assumed"
    assert "budget" in decision.decision_why


def test_prior_turn_was_clarification():
    assert prior_turn_was_clarification(
        [
            {
                "question": "q",
                "sql": "",
                "answer": "need more",
                "trust_level": "clarifying",
            }
        ]
    )
    assert prior_turn_was_clarification(
        [{"question": "q", "sql": None, "answer": "Which metric?"}]
    )
    assert not prior_turn_was_clarification(
        [{"question": "q", "sql": "SELECT 1", "answer": "1"}]
    )


def test_policy_unanswerable_when_no_valid():
    tables, pairs, bare = _shop_schema()
    proposal = InterpretationProposal(
        status="unanswerable",
        assumption="",
        reason="no performance table",
        candidates=(
            InterpretationCandidate(
                label="performance",
                question="Highest performance score",
                tables=("performance_reviews",),
                columns=("performance_reviews.score",),
            ),
        ),
    )
    decision = apply_interpretation_policy(
        proposal,
        question="best employee by performance",
        tables=tables,
        column_pairs=pairs,
        bare_columns=bare,
        rules=[],
        golden_questions=[],
    )
    assert decision.should_clarify is True
    assert decision.status == "unanswerable"


def test_policy_failed_open_when_empty_ambiguous():
    tables, pairs, bare = _shop_schema()
    proposal = InterpretationProposal(
        status="ambiguous",
        assumption="",
        reason="model returned junk",
        candidates=(),
    )
    decision = apply_interpretation_policy(
        proposal,
        question="best customer",
        tables=tables,
        column_pairs=pairs,
        bare_columns=bare,
        rules=[],
        golden_questions=[],
    )
    assert decision.should_clarify is False
    assert decision.status == "failed_open"


def test_parse_interpretation_payload():
    proposal = parse_interpretation_payload(
        {
            "status": "AMBIGUOUS",
            "assumption": "",
            "reason": "vague",
            "candidates": [
                {
                    "label": "a",
                    "question": "Q1?",
                    "tables": ["customers"],
                    "columns": ["customers.name"],
                }
            ],
        }
    )
    assert proposal.status == "ambiguous"
    assert len(proposal.candidates) == 1
