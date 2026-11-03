"""Deterministic orchestration for conversational, read-only booking lookup."""
import re
from services.identity import principal_is_valid
from services.booking_service import BookingService
from services.intent_router import route_question
from services.response_generator import generate_booking_answer

BOOKING_ID_RE = re.compile(r"\bDEMO-BOOKING-\d{4,}\b", re.IGNORECASE)
FOLLOWUP_MARKERS = ("那", "这个", "它", "这笔", "这个订单", "那早餐", "那停车")

class ConversationOrchestrator:
    def __init__(self, booking_service=None):
        self.booking_service = booking_service or BookingService()

    def handle_booking_query(self, message, principal=None, history=None, context=None):
        history, context = history or [], context or {}
        route = route_question(message, context, history)
        if route.get("action") != "booking_lookup":
            return {"handled": False, "route": route}
        if not principal_is_valid(principal):
            return {"handled": True, "status": "unauthenticated", "intent": route["intent"],
                    "action": "login_required", "answer": "查询个人订单前，请先在左侧完成演示身份登录。",
                    "data": None, "needs_clarification": False, "needs_human": False,
                    "audit_id": None, "route": route}
        match = BOOKING_ID_RE.search(message or "")
        booking_id = match.group(0).upper() if match else None
        if not booking_id and context.get("active_booking_id") and any(
            marker in (message or "") for marker in FOLLOWUP_MARKERS
        ):
            booking_id = context["active_booking_id"]
        if booking_id:
            result = self.booking_service.get_my_booking(principal, booking_id)
            if result.get("status") not in ("ok", "data_incomplete"):
                return self._failure(result, route)
            self._remember(context, booking_id)
            return self._success(message, result, route)
        result = self.booking_service.search_my_bookings(principal, limit=3)
        if result.get("status") != "ok":
            return self._failure(result, route)
        rows = result.get("matched_bookings", [])
        if len(rows) == 1:
            detail = self.booking_service.get_my_booking(principal, rows[0]["booking_id"])
            if detail.get("status") in ("ok", "data_incomplete"):
                self._remember(context, rows[0]["booking_id"])
                return self._success(message, detail, route)
            return self._failure(detail, route)
        if len(rows) > 1:
            lines = ["我找到了您名下的多笔订单。请提供订单编号，或告诉我入住日期/房型，以便确认您要查询哪一笔："]
            lines.extend(f'{i + 1}. {x["booking_id"]}｜{x.get("room_type") or "房型信息缺失"}｜入住 {str(x.get("check_in") or "")[:10]}' for i, x in enumerate(rows))
            return {"handled": True, "status": "needs_clarification", "intent": route["intent"],
                    "action": "select_booking", "answer": "\\n".join(lines),
                    "data": {"matched_bookings": rows}, "needs_clarification": True,
                    "needs_human": False, "audit_id": result.get("audit_id"), "route": route}
        return {"handled": True, "status": "not_found", "intent": route["intent"],
                "action": "booking_lookup", "answer": "暂未找到您名下符合条件的订单。请核对入住信息，或联系门店工作人员。",
                "data": None, "needs_clarification": False, "needs_human": False,
                "audit_id": result.get("audit_id"), "route": route}

    def _success(self, message, result, route):
        return {"handled": True, "status": result["status"], "intent": route["intent"],
                "action": "booking_lookup", "answer": generate_booking_answer(message, result),
                "data": {"booking": result.get("booking"), "property": result.get("property"),
                         "cancellation_policy": result.get("cancellation_policy"),
                         "missing_fields": result.get("missing_fields", [])},
                "needs_clarification": False, "needs_human": False,
                "audit_id": result.get("audit_id"), "route": route}

    @staticmethod
    def _remember(context, booking_id):
        if isinstance(context, dict):
            context["active_booking_id"] = booking_id

    @staticmethod
    def _failure(result, route):
        status = result.get("status", "tool_error")
        if status == "unauthenticated":
            answer = "登录状态已失效，请重新登录后再查询订单。"
        elif status == "not_found":
            answer = "没有找到您有权查看的这笔订单。请核对订单编号。"
        else:
            answer = "订单查询暂时不可用，系统没有返回订单信息。请稍后重试或联系工作人员。"
        return {"handled": True, "status": status, "intent": route["intent"],
                "action": "booking_lookup", "answer": answer, "data": None,
                "needs_clarification": False, "needs_human": status == "tool_error",
                "audit_id": result.get("audit_id"), "route": route}
