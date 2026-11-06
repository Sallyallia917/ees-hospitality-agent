"""Stateful orchestration for authenticated, read-only booking queries and safe handoff."""
import re
import uuid
from services.identity import principal_is_valid
from services.booking_service import BookingService
from services.ticket_service import TicketService
from services.intent_router import route_question
from services.response_generator import generate_booking_answer, _policy_answer
from services.context_manager import (
    remember_intent, remember_candidates, remember_active_booking,
    begin_operation, complete_operation
)

BOOKING_ID_RE = re.compile(r"\bDEMO-BOOKING-\d{4,}\b", re.IGNORECASE)
ORDINALS = {"一": 1, "二": 2, "三": 3, "1": 1, "2": 2, "3": 3}

class ConversationOrchestrator:
    def __init__(self, booking_service=None, ticket_service=None):
        self.booking_service = booking_service or BookingService()
        self.ticket_service = ticket_service or TicketService(':memory:')

    def handle_booking_query(self, message, principal=None, history=None, context=None):
        history = history or []
        context = context if isinstance(context, dict) else {}
        route = route_question(message, context, history)
        remember_intent(context, route.get("intent"), route.get("sub_intent"))
        action, intent = route.get("action"), route.get("intent")

        handled_actions = {"booking_lookup", "booking_list", "booking_selection",
                           "booking_policy_lookup", "transaction_confirmation", "transaction_handoff", "booking_issue"}
        if action not in handled_actions:
            return {"handled": False, "route": route}
        if not principal_is_valid(principal):
            return self._simple(route, "unauthenticated",
                "查询个人订单前，请先在左侧完成演示身份登录。", "login_required")

        if action == "booking_selection":
            return self._select_candidate(message, principal, context, route)
        if action == "booking_list":
            return self._list_bookings(principal, context, route)
        if action == "booking_policy_lookup":
            return self._resolve_booking(message, principal, context, route, "policy")
        if action == "transaction_confirmation":
            return self._transaction(message, principal, context, route)
        if action == "transaction_handoff":
            if intent == "booking_issue":
                return self._booking_issue(message, principal, context, route)
            return self._transaction(message, principal, context, route)
        if action == "booking_issue":
            return self._booking_issue(message, principal, context, route)
        return self._resolve_booking(message, principal, context, route, "detail")

    def _simple(self, route, status, answer, action, needs_human=False, clarification=False, data=None, audit_id=None):
        return {"handled": True, "status": status, "intent": route["intent"], "action": action,
                "answer": answer, "data": data, "needs_clarification": clarification,
                "needs_human": needs_human, "audit_id": audit_id, "route": route}

    def _list_bookings(self, principal, context, route):
        result = self.booking_service.search_my_bookings(principal, limit=3)
        if result.get("status") != "ok":
            return self._failure(result, route)
        rows = result.get("matched_bookings") or []
        if not rows:
            return self._simple(route, "not_found", "没有找到您名下的订单。", "booking_lookup",
                                audit_id=result.get("audit_id"))
        remember_candidates(context, rows)
        return self._candidate_prompt(rows, route, result.get("audit_id"), count_only=True)

    def _candidate_prompt(self, rows, route, audit_id, purpose="select_booking", count_only=False):
        heading = f"查询到您名下最近 {len(rows)} 笔订单：" if count_only else "找到多笔符合条件的订单，请选择一笔："
        lines = [heading]
        for i, row in enumerate(rows, 1):
            prop = row.get("property_name") or row.get("property_id") or "房源未记录"
            lines.append(f'{i}. {prop}｜{row.get("room_type") or "房型未记录"}｜入住 {str(row.get("check_in") or "日期未记录")[:10]}｜状态 {row.get("booking_status") or "未记录"}')
        lines.append("可回复序号、房型、房源名称或入住日期。若有多个匹配项，我会继续请您确认。")
        return self._simple(route, "needs_clarification", "\n".join(lines), purpose,
                            clarification=True, data={"matched_bookings": rows}, audit_id=audit_id)

    def _resolve_booking(self, message, principal, context, route, purpose):
        booking_id = None
        match = BOOKING_ID_RE.search(message or "")
        if match:
            booking_id = match.group(0).upper()
        if not booking_id and context.get("active_booking_id"):
            booking_id = context["active_booking_id"]
        if booking_id:
            return self._fetch_detail(message, principal, context, route, booking_id, purpose)

        result = self.booking_service.search_my_bookings(principal, limit=3)
        if result.get("status") != "ok":
            return self._failure(result, route)
        rows = result.get("matched_bookings") or []
        if len(rows) == 0:
            return self._simple(route, "not_found", "没有找到您名下的订单，无法查询个人订单政策或详情。", "booking_lookup",
                                audit_id=result.get("audit_id"))
        if len(rows) == 1:
            return self._fetch_detail(message, principal, context, route, rows[0]["booking_id"], purpose)
        remember_candidates(context, rows, pending_action="select_policy" if purpose == "policy" else "select_booking")
        return self._candidate_prompt(rows, route, result.get("audit_id"),
                                      purpose="select_booking_for_policy" if purpose == "policy" else "select_booking")

    def _fetch_detail(self, message, principal, context, route, booking_id, purpose):
        result = self.booking_service.get_my_booking(principal, booking_id)
        if result.get("status") not in ("ok", "data_incomplete"):
            return self._failure(result, route)
        remember_active_booking(context, booking_id)
        if purpose == "policy":
            return self._simple(route, result["status"],
                _policy_answer(result.get("cancellation_policy")), "booking_policy_lookup",
                data={"booking": result.get("booking"), "cancellation_policy": result.get("cancellation_policy"),
                      "missing_fields": result.get("missing_fields", [])}, audit_id=result.get("audit_id"))
        return self._simple(route, result["status"], generate_booking_answer(message, result),
            "booking_lookup", data={"booking": result.get("booking"), "property": result.get("property"),
            "cancellation_policy": result.get("cancellation_policy"), "missing_fields": result.get("missing_fields", [])},
            audit_id=result.get("audit_id"))

    def _select_candidate(self, message, principal, context, route):
        ids = context.get("candidate_booking_ids") or []
        if not ids:
            return self._simple(route, "needs_clarification",
                "当前没有待选择的订单。请先查询您的订单列表。", "select_booking", clarification=True)
        booking_id = route.get("entities", {}).get("booking_id")
        if not booking_id:
            match = re.search(r"(?:第)?([一二三123])", message or "")
            if match:
                index = ORDINALS[match.group(1)] - 1
                if 0 <= index < len(ids):
                    booking_id = ids[index]
        if not booking_id:
            query = "".join(str(message or "").lower().split())
            matched = []
            for candidate_id in ids:
                detail = self.booking_service.get_my_booking(principal, candidate_id)
                if detail.get("status") not in ("ok", "data_incomplete"):
                    continue
                booking = detail.get("booking") or {}
                prop = detail.get("property") or {}
                values = [booking.get("room_type"), prop.get("property_name"), str(booking.get("check_in") or "")[:10], str(booking.get("check_out") or "")[:10]]
                if any(v and len(str(v)) >= 2 and (str(v).lower() in query or query in str(v).lower()) for v in values):
                    matched.append(candidate_id)
            if len(matched) == 1:
                booking_id = matched[0]
            else:
                return self._simple(route, "needs_clarification", "没有唯一匹配到订单。请提供序号、完整房型、房源名称或入住日期。", "select_booking", clarification=True)
        if booking_id not in ids:
            return self._simple(route, "needs_clarification",
                "该信息不属于刚才展示的候选订单，请重新选择。", "select_booking", clarification=True)
        purpose = context.get("pending_action") or "select_booking"
        result = self.booking_service.get_my_booking(principal, booking_id)
        if result.get("status") not in ("ok", "data_incomplete"):
            return self._failure(result, route)
        remember_active_booking(context, booking_id)
        if purpose == "select_policy":
            return self._simple(route, result["status"], _policy_answer(result.get("cancellation_policy")),
                "booking_policy_lookup", data={"booking": result.get("booking"),
                "cancellation_policy": result.get("cancellation_policy")}, audit_id=result.get("audit_id"))
        if purpose == "select_transaction":
            begin_operation(context, booking_id, "cancel_or_refund")
            return self._transaction_prompt(result, route)
        if purpose == "select_issue":
            begin_operation(context, booking_id, "booking_issue")
            return self._issue_prompt(result, route)
        return self._simple(route, result["status"], generate_booking_answer(message, result),
            "booking_lookup", data={"booking": result.get("booking"), "cancellation_policy": result.get("cancellation_policy")},
            audit_id=result.get("audit_id"))

    def _transaction(self, message, principal, context, route):
        sub = route.get("sub_intent")
        current = context.get("current_operation") or {}
        if sub == "reject_transaction" and current.get("operation_type") == "cancel_or_refund" and current.get("stage") == "awaiting_confirmation":
            completed = complete_operation(context, "cancelled_by_user", user_confirmed=False)
            return self._simple(route, "cancelled_by_user", "好的，已停止本次取消/退款申请，没有执行任何订单操作。您仍可继续处理其他订单。",
                                "transaction_aborted", data={"operation": completed})
        if sub == "confirm_transaction" and current.get("operation_type") == "cancel_or_refund" and current.get("stage") == "awaiting_confirmation":
            booking_id = current.get("booking_id")
            detail = self.booking_service.get_my_booking(principal, booking_id)
            if detail.get("status") not in ("ok", "data_incomplete"):
                return self._simple(route, "ticket_creation_blocked",
                    "暂时无法重新核验这笔订单，因此没有创建退款工单。请稍后重试或联系工作人员。",
                    "ticket_creation_blocked", needs_human=True, data={"booking_id": booking_id})
            booking = detail.get("booking") or {}
            policy = detail.get("cancellation_policy") or {}
            operation_id = current.get("operation_id") or str(uuid.uuid4())
            ticket_result = self.ticket_service.create_ticket(
                guest_id=principal.customer_id,
                booking_id=booking_id,
                category="REFUND_REQUEST",
                priority="HIGH",
                description=f"住客已在 AI 对话中确认申请取消/退款。原始诉求：{current.get('request_text') or message}",
                idempotency_key=f"{principal.customer_id}:{operation_id}:refund",
                operation_id=operation_id,
                metadata={
                    "source": "ai_conversation",
                    "intent": "cancel_or_refund",
                    "user_confirmed": True,
                    "booking_snapshot": booking,
                    "cancellation_policy_snapshot": policy,
                    "conversation_history": history[-8:],
                    "operation_id": operation_id,
                    "requires_human_review": True,
                    "execution_boundary": "ticket_only_no_refund_execution",
                },
            )
            if not ticket_result.get("ok"):
                return self._simple(route, "ticket_creation_failed",
                    "已收到您的确认，但服务工单暂时创建失败；系统没有执行退款。请稍后重试，或联系工作人员。",
                    "ticket_creation_failed", needs_human=True,
                    data={"booking_id": booking_id, "error": ticket_result.get("error")})
            completed = complete_operation(
                context, "ticket_created", user_confirmed=True,
                ticket_id=ticket_result["ticket"]["ticket_id"]
            )
            return self._simple(route, "ticket_created",
                f"已为订单 {booking_id} 自动创建退款申请工单，工单编号 {ticket_result['ticket']['ticket_id']}。工作人员将核验订单渠道、取消政策及退款资格；当前仅提交申请，尚未执行取消或退款。",
                "automatic_ticket_created", needs_human=True,
                data={"booking_id": booking_id, "ticket": ticket_result["ticket"],
                      "operation": completed})
        # New transaction requests must not inherit a previous operation's booking.
        result = self.booking_service.search_my_bookings(principal, limit=3)
        if result.get("status") != "ok":
            return self._failure(result, route)
        rows = result.get("matched_bookings") or []
        if not rows:
            return self._simple(route, "not_found", "没有找到您名下的订单，无法确认取消/退款对象。", "booking_lookup",
                                audit_id=result.get("audit_id"))
        if len(rows) > 1:
            remember_candidates(context, rows, pending_action="select_transaction")
            return self._candidate_prompt(rows, route, result.get("audit_id"), purpose="select_booking_for_transaction")
        detail = self.booking_service.get_my_booking(principal, rows[0]["booking_id"])
        if detail.get("status") not in ("ok", "data_incomplete"):
            return self._failure(detail, route)
        remember_active_booking(context, rows[0]["booking_id"])
        begin_operation(context, rows[0]["booking_id"], "cancel_or_refund")
        return self._transaction_prompt(detail, route)

    def _transaction_prompt(self, detail, route):
        b = detail.get("booking") or {}
        return self._simple(route, "awaiting_confirmation",
            f"请确认是否针对以下订单申请取消/退款：{b.get('room_type') or '房型未记录'}，入住 {str(b.get('check_in') or '日期未记录')[:10]}，订单号 {b.get('booking_id')}。请回复“确认”或“不是/算了”。确认后我会转人工，不会直接执行取消或退款。",
            "confirm_transaction", clarification=True, data={"booking": b}, audit_id=detail.get("audit_id"))

    def _booking_issue(self, message, principal, context, route):
        current = context.get("current_operation") or {}
        if route.get("sub_intent") == "issue_details" and current.get("operation_type") == "booking_issue" and current.get("stage") == "awaiting_issue_details":
            booking_id = current.get("booking_id")
            completed = complete_operation(context, "handed_off", user_confirmed=True, issue=message)
            return self._simple(route, "human_handoff",
                f"已记录您反馈的订单问题：{message}。关联订单 {booking_id}。当前演示版本不会自动修改订单，也未创建真实服务单，请联系工作人员核对处理。您可以继续处理其他订单。",
                "transaction_handoff", needs_human=True, data={"booking_id": booking_id, "issue": message, "operation": completed})
        # New issue reports must not inherit a previous operation's booking.
        result = self.booking_service.search_my_bookings(principal, limit=3)
        if result.get("status") != "ok":
            return self._failure(result, route)
        rows = result.get("matched_bookings") or []
        if not rows:
            return self._simple(route, "not_found", "没有找到您名下的订单。请提供订单信息或联系工作人员。", "booking_lookup")
        if len(rows) > 1:
            remember_candidates(context, rows, pending_action="select_issue")
            return self._candidate_prompt(rows, route, result.get("audit_id"), purpose="select_booking_for_issue")
        detail = self.booking_service.get_my_booking(principal, rows[0]["booking_id"])
        if detail.get("status") not in ("ok", "data_incomplete"):
            return self._failure(detail, route)
        remember_active_booking(context, rows[0]["booking_id"])
        begin_operation(context, rows[0]["booking_id"], "booking_issue")
        return self._issue_prompt(detail, route)

    def _issue_prompt(self, detail, route):
        b = detail.get("booking") or {}
        context_message = f"请确认这笔订单是否有误：{b.get('room_type')}，入住 {str(b.get('check_in') or '')[:10]}。请描述具体错误内容。"
        return self._simple(route, "awaiting_issue_details", context_message, "describe_booking_issue",
                            clarification=True, data={"booking": b}, audit_id=detail.get("audit_id"))

    def _failure(self, result, route):
        status = result.get("status", "tool_error")
        if status == "unauthenticated": answer = "登录状态已失效，请重新登录后再查询订单。"
        elif status == "not_found": answer = "没有找到您有权查看的这笔订单。请核对订单编号。"
        else: answer = "订单查询暂时不可用，系统没有返回订单信息。请稍后重试或联系工作人员。"
        return self._simple(route, status, answer, "booking_lookup",
                            needs_human=status == "tool_error", audit_id=result.get("audit_id"))
