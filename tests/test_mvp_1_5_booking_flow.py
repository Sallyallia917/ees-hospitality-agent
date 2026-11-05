from datetime import datetime, timedelta, timezone

from services.identity import Principal
from services.semantic_classifier import classify_by_rules
from services.intent_router import route_question
from services.conversation_orchestrator import ConversationOrchestrator

NOW = datetime.now(timezone.utc)

def principal(customer_id="CUST-001"):
    return Principal(
        principal_id=f"DEMO-PRINCIPAL-{customer_id}",
        customer_id=customer_id,
        auth_method="demo_pin",
        authenticated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=20)).isoformat(),
    )

def test_cancellation_policy_is_distinct_from_cancel_execution():
    assert classify_by_rules("我的高级双床房能取消吗")["intent"] == "cancellation_policy_inquiry"
    assert classify_by_rules("订单的取消政策")["intent"] == "cancellation_policy_inquiry"
    assert classify_by_rules("我要取消我预定的房源")["intent"] == "transaction_request"
    assert route_question("取消退款")["action"] == "transaction_handoff"

def test_policy_query_returns_policy_not_unrelated_booking_fields():
    context = {}
    agent = ConversationOrchestrator()
    result = agent.handle_booking_query(
        "订单的取消政策", principal=principal(), context=context
    )
    assert result["handled"] is True
    assert result["action"] == "select_booking_for_policy"
    selected = agent.handle_booking_query(
        "高级双床房", principal=principal(),
        history=[{"intent": "cancellation_policy_inquiry"}], context=context
    )
    assert selected["action"] == "booking_policy_lookup"
    assert "取消政策" in selected["answer"] or "取消" in selected["answer"]
    assert "超过72小时" in selected["answer"]

def test_cancel_request_requires_order_selection_and_explicit_confirmation():
    context = {}
    agent = ConversationOrchestrator()
    first = agent.handle_booking_query("我要取消我预定的房源", principal=principal(), context=context)
    assert first["status"] == "needs_clarification"
    assert context["pending_action"] == "select_transaction"
    selected = agent.handle_booking_query(
        "高级双床房", principal=principal(),
        history=[{"intent": "transaction_request"}], context=context
    )
    assert selected["status"] == "awaiting_confirmation"
    assert context["pending_action"] == "confirm_transaction"
    confirmed = agent.handle_booking_query(
        "确认", principal=principal(),
        history=[{"intent": "transaction_request"}], context=context
    )
    assert confirmed["status"] == "human_handoff"
    assert confirmed["needs_human"] is True
    assert "不会直接执行" in confirmed["answer"] or "不会执行" in confirmed["answer"]

def test_booking_issue_asks_order_then_issue_details():
    context = {}
    agent = ConversationOrchestrator()
    first = agent.handle_booking_query("订单订错了", principal=principal(), context=context)
    assert first["status"] == "needs_clarification"
    selected = agent.handle_booking_query(
        "高级双床房", principal=principal(),
        history=[{"intent": "booking_issue"}], context=context
    )
    assert selected["status"] == "awaiting_issue_details"
    final = agent.handle_booking_query(
        "入住日期写错了", principal=principal(),
        history=[{"intent": "booking_issue"}], context=context
    )
    assert final["status"] == "human_handoff"
    assert final["needs_human"] is True

def test_candidate_selection_rejects_ambiguous_property_match():
    context = {}
    agent = ConversationOrchestrator()
    agent.handle_booking_query("我有几笔订单", principal=principal(), context=context)
    result = agent.handle_booking_query(
        "双床房", principal=principal(),
        history=[{"intent": "booking_list_query"}], context=context
    )
    assert result["status"] == "needs_clarification"
