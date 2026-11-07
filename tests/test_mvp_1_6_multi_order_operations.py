from datetime import datetime, timedelta, timezone

from services.identity import Principal
from services.conversation_orchestrator import ConversationOrchestrator

NOW = datetime.now(timezone.utc)

def principal():
    return Principal(
        principal_id="DEMO-PRINCIPAL-CUST-001",
        customer_id="CUST-001",
        auth_method="demo_pin",
        authenticated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=20)).isoformat(),
    )

def start_cancel(agent, context, history):
    first = agent.handle_booking_query("我要取消订单", principal=principal(), history=history, context=context)
    assert first["status"] == "needs_clarification"
    selected = agent.handle_booking_query("第一笔", principal=principal(), history=history, context=context)
    assert selected["status"] == "awaiting_confirmation"
    return selected["data"]["booking"]["booking_id"]

def test_two_cancellations_in_one_conversation_use_distinct_orders():
    agent, context = ConversationOrchestrator(), {}
    history = [{"intent": "transaction_request"}]
    first_id = start_cancel(agent, context, history)
    confirmed_a = agent.handle_booking_query("确认", principal=principal(), history=history, context=context)
    assert confirmed_a["status"] == "ticket_created"
    assert context["current_operation"] is None
    assert context["booking_operations"][0]["booking_id"] == first_id
    assert context["booking_operations"][0]["user_confirmed"] is True

    second = agent.handle_booking_query("另外一笔也要退款", principal=principal(), history=history, context=context)
    assert second["status"] == "needs_clarification"
    selected_b = agent.handle_booking_query("第二笔", principal=principal(), history=history, context=context)
    second_id = selected_b["data"]["booking"]["booking_id"]
    assert second_id != first_id
    confirmed_b = agent.handle_booking_query("确认", principal=principal(), history=history, context=context)
    assert confirmed_b["status"] == "ticket_created"
    assert [x["booking_id"] for x in context["booking_operations"]] == [first_id, second_id]

def test_cancel_then_report_issue_on_another_order():
    agent, context = ConversationOrchestrator(), {}
    history = [{"intent": "transaction_request"}]
    first_id = start_cancel(agent, context, history)
    agent.handle_booking_query("确认", principal=principal(), history=history, context=context)

    issue = agent.handle_booking_query("另外一笔订单订错了", principal=principal(),
                                       history=[{"intent": "booking_issue"}], context=context)
    assert issue["status"] == "needs_clarification"
    selected = agent.handle_booking_query("第二笔", principal=principal(),
                                          history=[{"intent": "booking_list_query"}], context=context)
    second_id = selected["data"]["booking"]["booking_id"]
    assert second_id != first_id
    assert selected["status"] == "awaiting_ticket_confirmation"
    agent.handle_booking_query("房型订错了", principal=principal(), context=context)
    final = agent.handle_booking_query("确认", principal=principal(), context=context)
    assert final["status"] == "ticket_created"
    assert final["data"]["ticket"]["booking_id"] == second_id

def test_rejecting_current_operation_does_not_erase_completed_operation():
    agent, context = ConversationOrchestrator(), {}
    history = [{"intent": "transaction_request"}]
    first_id = start_cancel(agent, context, history)
    agent.handle_booking_query("确认", principal=principal(), history=history, context=context)
    agent.handle_booking_query("另外一笔也要退款", principal=principal(), history=history, context=context)
    agent.handle_booking_query("第二笔", principal=principal(), history=history, context=context)
    rejected = agent.handle_booking_query("算了", principal=principal(), history=history, context=context)
    assert rejected["status"] == "cancelled_by_user"
    assert len(context["booking_operations"]) == 2
    assert context["booking_operations"][0]["booking_id"] == first_id
    assert context["booking_operations"][1]["status"] == "cancelled_by_user"
