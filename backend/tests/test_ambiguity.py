from src.agent.ambiguity import decide_ambiguity


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
