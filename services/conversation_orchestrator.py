"""Stateful conversation orchestration for authorized, read-only booking queries."""
import re
from services.identity import principal_is_valid
from services.booking_service import BookingService
from services.intent_router import route_question
from services.response_generator import generate_booking_answer
from services.context_manager import (
    remember_intent, remember_candidates, remember_active_booking
)

BOOKING_ID_RE = re.compile(r"\bDEMO-BOOKING-\d{4,}\b", re.IGNORECASE)
ORDINALS = {"一": 1, "二": 2, "三": 3, "1": 1, "2": 2, "3": 3}

class ConversationOrchestrator:
    def __init__(self, booking_service=None):
        self.booking_service = booking_service or BookingService()

    def handle_booking_query(self, message, principal=None, history=None, context=None):
        history = history or []
        context = context if isinstance(context, dict) else {}
        route = route_question(message, context, history)
        remember_intent(context, route.get("intent"), route.get("sub_intent"))
        action = route.get("action")
        if action not in {"booking_lookup", "booking_list", "booking_selection"}:
            return {"handled": False, "route": route}

        if not principal_is_valid(principal):
            return {
                "handled": True, "status": "unauthenticated", "intent": route["intent"],
                "action": "login_required", "answer": "查询个人订单前，请先在左侧完成演示身份登录。",
                "data": None, "needs_clarification": False, "needs_human": False,
                "audit_id": None, "route": route
            }

        if action == "booking_selection":
            return self._select_candidate(message, principal, context, route)

        match = BOOKING_ID_RE.search(message or "")
        booking_id = match.group(0).upper() if match else None
        if not booking_id and context.get("active_booking_id"):
            # An active booking is reused for first-person booking-field questions,
            # not only messages containing "那/这个/它".
            booking_id = context["active_booking_id"]

        if action == "booking_list":
            return self._list_bookings(principal, context, route)

        if booking_id:
            result = self.booking_service.get_my_booking(principal, booking_id)
            if result.get("status") not in ("ok", "data_incomplete"):
                return self._failure(result, route)
            remember_active_booking(context, booking_id)
            return self._success(message, result, route)

        result = self.booking_service.search_my_bookings(principal, limit=3)
        if result.get("status") != "ok":
            return self._failure(result, route)
        rows = result.get("matched_bookings", [])
        if len(rows) == 1:
            detail = self.booking_service.get_my_booking(principal, rows[0]["booking_id"])
            if detail.get("status") in ("ok", "data_incomplete"):
                remember_active_booking(context, rows[0]["booking_id"])
                return self._success(message, detail, route)
            return self._failure(detail, route)
        if len(rows) > 1:
            remember_candidates(context, rows)
            return self._candidate_prompt(rows, route, result.get("audit_id"))
        return self._not_found(route, result.get("audit_id"))

    def _list_bookings(self, principal, context, route):
        result = self.booking_service.search_my_bookings(principal, limit=3)
        if result.get("status") != "ok":
            return self._failure(result, route)
        rows = result.get("matched_bookings", [])
        if not rows:
            return self._not_found(route, result.get("audit_id"))
        remember_candidates(context, rows)
        return self._candidate_prompt(rows, route, result.get("audit_id"), count_only=True)

    def _candidate_prompt(self, rows, route, audit_id, count_only=False):
        heading = f"查询到您名下最近 {len(rows)} 笔订单：" if count_only else "我找到多笔符合条件的订单，请选择要查询的一笔："
        lines = [heading]
        for i, row in enumerate(rows, 1):
            lines.append(
                f'{i}. {row.get("booking_id")}｜{row.get("room_type") or "房型未记录"}｜'
                f'入住 {str(row.get("check_in") or "日期未记录")[:10]}｜状态 {row.get("booking_status") or "未记录"}'
            )
        lines.append("您可以回复“第一笔 / 第二笔 / 第三笔”，我再查询对应订单。")
        return {
            "handled": True, "status": "needs_clarification", "intent": route["intent"],
            "action": "select_booking", "answer": "\n".join(lines),
            "data": {"matched_bookings": rows}, "needs_clarification": True,
            "needs_human": False, "audit_id": audit_id, "route": route
        }

    def _select_candidate(self, message, principal, context, route):
        ids = context.get("candidate_booking_ids") or []
        match = re.search(r"(?:第)?([一二三123])", message or "")
        if not match:
            return {
                "handled": True, "status": "needs_clarification", "intent": route["intent"],
                "action": "select_booking", "answer": "请回复第一笔、第二笔或第三笔，选择刚才列出的订单。",
                "data": None, "needs_clarification": True, "needs_human": False,
                "audit_id": None, "route": route
            }
        index = ORDINALS[match.group(1)] - 1
        if index < 0 or index >= len(ids):
            return {
                "handled": True, "status": "needs_clarification", "intent": route["intent"],
                "action": "select_booking", "answer": "这个序号不在刚才展示的订单列表中，请重新选择。",
                "data": None, "needs_clarification": True, "needs_human": False,
                "audit_id": None, "route": route
            }
        # Candidate IDs originate from the authenticated service response;
        # BookingService rechecks ownership on every detail read.
        booking_id = ids[index]
        result = self.booking_service.get_my_booking(principal, booking_id)
        if result.get("status") not in ("ok", "data_incomplete"):
            return self._failure(result, route)
        remember_active_booking(context, booking_id)
        return self._success(message, result, route)

    def _success(self, message, result, route):
        return {
            "handled": True, "status": result["status"], "intent": route["intent"],
            "action": "booking_lookup", "answer": generate_booking_answer(message, result),
            "data": {
                "booking": result.get("booking"), "property": result.get("property"),
                "cancellation_policy": result.get("cancellation_policy"),
                "missing_fields": result.get("missing_fields", [])
            },
            "needs_clarification": False, "needs_human": False,
            "audit_id": result.get("audit_id"), "route": route
        }

    @staticmethod
    def _not_found(route, audit_id):
        return {
            "handled": True, "status": "not_found", "intent": route["intent"],
            "action": "booking_lookup",
            "answer": "暂未找到您名下符合条件的订单。请核对入住信息，或联系门店工作人员。",
            "data": None, "needs_clarification": False, "needs_human": False,
            "audit_id": audit_id, "route": route
        }

    @staticmethod
    def _failure(result, route):
        status = result.get("status", "tool_error")
        if status == "unauthenticated":
            answer = "登录状态已失效，请重新登录后再查询订单。"
        elif status == "not_found":
            answer = "没有找到您有权查看的这笔订单。请核对订单编号。"
        else:
            answer = "订单查询暂时不可用，系统没有返回订单信息。请稍后重试或联系工作人员。"
        return {
            "handled": True, "status": status, "intent": route["intent"],
            "action": "booking_lookup", "answer": answer, "data": None,
            "needs_clarification": False, "needs_human": status == "tool_error",
            "audit_id": result.get("audit_id"), "route": route
        }
