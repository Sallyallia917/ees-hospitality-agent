"""Stateful orchestration for authenticated, read-only booking queries and safe handoff."""
import json
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
        if context.get("pending_action") == "clarify_facility_context" and route.get("intent") == "public_knowledge_inquiry":
            context["pending_action"] = None
            context["pending_facility_issue"] = None
        remember_intent(context, route.get("intent"), route.get("sub_intent"))
        action, intent = route.get("action"), route.get("intent")

        handled_actions = {"booking_lookup", "booking_list", "booking_selection",
                           "booking_policy_lookup", "transaction_confirmation", "transaction_handoff", "booking_issue", "service_ticket_request", "service_ticket_confirmation", "ticket_status_lookup", "clarify_facility_context", "safety_guidance"}
        if action not in handled_actions:
            return {"handled": False, "route": route}
        if action == "clarify_facility_context":
            context["pending_action"] = "clarify_facility_context"
            context["pending_facility_issue"] = str(message)
            return self._simple(route, "needs_clarification", route.get("response") or "您是在咨询设施信息，还是希望反馈入住体验问题？",
                                "clarify_facility_context", clarification=True)
        if action == "safety_guidance":
            return self._safety_incident(message, principal, context, route, history)

        if not principal_is_valid(principal):
            return self._simple(route, "unauthenticated",
                "查询个人订单前，请先在左侧完成演示身份登录。", "login_required")

        if action == "ticket_status_lookup":
            return self._ticket_status_lookup(principal, route)
        if action == "booking_selection":
            return self._select_candidate(message, principal, context, route)
        if action == "booking_list":
            return self._list_bookings(principal, context, route)
        if action == "booking_policy_lookup":
            return self._resolve_booking(message, principal, context, route, "policy")
        if action == "service_ticket_request":
            return self._service_ticket_request(message, principal, context, route)
        if action == "service_ticket_confirmation":
            return self._service_ticket_confirmation(message, principal, context, route, history)
        if action == "transaction_confirmation":
            return self._transaction(message, principal, context, route, history)
        if action == "transaction_handoff":
            if intent == "booking_issue":
                return self._booking_issue(message, principal, context, route)
            return self._transaction(message, principal, context, route, history)
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
            context["current_operation"]["request_text"] = context.get("pending_transaction_request") or message
            context["pending_transaction_request"] = None
            return self._transaction_prompt(result, route)
        if purpose == "select_issue":
            begin_operation(context, booking_id, "booking_issue")
            return self._issue_prompt(result, route)
        if purpose == "select_service_ticket":
            return self._prepare_service_ticket(result, context, route, principal)
        return self._simple(route, result["status"], generate_booking_answer(message, result),
            "booking_lookup", data={"booking": result.get("booking"), "cancellation_policy": result.get("cancellation_policy")},
            audit_id=result.get("audit_id"))

    def _transaction(self, message, principal, context, route, history=None):
        history = history or []
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
            context["pending_transaction_request"] = message
            return self._candidate_prompt(rows, route, result.get("audit_id"), purpose="select_booking_for_transaction")
        detail = self.booking_service.get_my_booking(principal, rows[0]["booking_id"])
        if detail.get("status") not in ("ok", "data_incomplete"):
            return self._failure(detail, route)
        remember_active_booking(context, rows[0]["booking_id"])
        begin_operation(context, rows[0]["booking_id"], "cancel_or_refund")
        context["current_operation"]["request_text"] = message
        return self._transaction_prompt(detail, route)

    def _transaction_prompt(self, detail, route):
        b = detail.get("booking") or {}
        policy = detail.get("cancellation_policy") or {}
        windows = policy.get("windows") or []
        policy_text = "；".join(str(item.get("label") or "") for item in windows if item.get("label"))
        policy_summary = (f"订单绑定的取消政策：{policy_text}。" if policy_text else "暂未取得完整的订单取消政策，退款资格和金额需要工作人员核验。")
        return self._simple(route, "awaiting_confirmation",
            f"我核对到订单：{b.get('room_type') or '房型未记录'}，入住 {str(b.get('check_in') or '日期未记录')[:10]}，订单号 {b.get('booking_id')}。{policy_summary}请确认是否为这笔订单提交退款申请工单？回复“确认退款”或“算了”。确认后系统会自动创建工单交由人工审核，但不会直接取消订单或执行退款。",
            "confirm_transaction", clarification=True, data={"booking": b, "cancellation_policy": policy}, audit_id=detail.get("audit_id"))

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

    def _safety_incident(self, message, principal, context, route, history=None):
        # Safety guidance must not be blocked by normal booking lookup or clarification.
        immediate = (
            "请先确保自身安全：立即远离危险区域，不要触碰门锁、电器或可疑物品，也不要自行处理危险源。"
            "如存在燃气泄漏、火情、人身威胁或未经允许进入客房，请立即联系当地紧急服务及现场值班工作人员。"
            "如果有人仍在房间内或您感到受到威胁，请前往安全、有人值守的公共区域。"
        )
        if not principal_is_valid(principal):
            return self._simple(
                route, "safety_handoff_required",
                immediate + "当前无法核验您的演示身份，因此系统没有创建个人工单；请直接联系现场工作人员。",
                "safety_guidance", needs_human=True,
                data={"ticket_created": False, "reason": "identity_not_verified"},
            )

        # Keep retries idempotent within the same incident, but do not let a
        # previous safety report suppress a distinct later incident in this chat.
        safety_fingerprint = re.sub(r"\\s+", "", str(message or "").lower())
        if context.get("safety_event_fingerprint") != safety_fingerprint:
            context["safety_event_fingerprint"] = safety_fingerprint
            context["safety_operation_id"] = str(uuid.uuid4())
        operation_id = context["safety_operation_id"]
        issue_type = (
            "UNAUTHORIZED_ROOM_ENTRY"
            if route.get("sub_intent") == "unauthorized_entry"
            else "SAFETY_INCIDENT"
        )
        result = self.ticket_service.create_ticket(
            guest_id=principal.customer_id,
            category="COMPLAINT_EXPERIENCE",
            description=str(message or "住客报告安全事件"),
            priority="URGENT",
            idempotency_key=f"{principal.customer_id}:{operation_id}:safety",
            operation_id=operation_id,
            metadata={
                "source": "ai_conversation",
                "intent": "safety_incident",
                "issue_type": issue_type,
                "user_confirmed": True,
                "requires_human_review": True,
                "handling_channel": "IMMEDIATE_ON_SITE_ESCALATION",
                "risk_level": "CRITICAL",
                "execution_boundary": "alert_ticket_only_no_emergency_dispatch",
                "conversation_history": (history or [])[-8:],
            },
        )
        if not result.get("ok"):
            return self._simple(
                route, "safety_handoff_required",
                immediate + "系统未能登记工单，请不要等待系统处理，直接联系现场工作人员及当地紧急服务。",
                "safety_guidance", needs_human=True,
                data={"ticket_created": False, "error": result.get("error")},
            )
        item = result["ticket"]
        return self._simple(
            route, "safety_ticket_created",
            immediate + f"系统已登记高优先级安全事件工单 {item['ticket_id']}，并标记为紧急人工跟进。请注意：演示系统不会自动呼叫救援或派遣现场人员，您仍需直接联系现场工作人员及当地紧急服务。",
            "safety_guidance", needs_human=True,
            data={"ticket_created": bool(result.get("created")), "ticket": item},
        )

    def _ticket_status_lookup(self, principal, route):
        rows = self.ticket_service.list_active_tickets(
            guest_id=principal.customer_id, limit=10
        )
        if not rows:
            return self._simple(
                route, "no_active_tickets",
                "目前没有查询到您名下仍在处理中的服务工单。如果您刚提交过申请，可以稍后再查；如需反馈新问题，可以直接告诉我。",
                "ticket_status_lookup", data={"tickets": []},
            )
        labels = {
            "SUBMITTED": "已提交，等待受理",
            "ASSIGNED": "已分配处理人员",
            "PROCESSING": "处理中",
            "PENDING_USER": "等待您补充信息",
            "ESCALATED": "已升级人工处理",
        }
        lines = ["查询到您名下以下处理中工单："]
        for item in rows:
            status = labels.get(item.get("status"), item.get("status") or "状态未知")
            lines.append(
                f"{item['ticket_id']}｜订单 {item.get('booking_id') or '未关联订单'}｜"
                f"{item.get('issue_type') or item.get('category')}｜{status}"
            )
        lines.append("以上为当前演示工单记录；系统不会据此推断现场人员已完成服务。")
        return self._simple(
            route, "active_tickets_found", "\\n".join(lines),
            "ticket_status_lookup", needs_human=True, data={"tickets": rows},
        )

    @staticmethod
    def _parse_invoice_fields(message, current=None):
        fields = dict(current or {})
        text = str(message or "").strip()
        email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        if email_match:
            fields["email"] = email_match.group(0)

        tax_match = re.search(
            r"(?:税号|纳税人识别号|统一社会信用代码)\s*[:：为]?\s*([0-9A-Za-z]{6,20})",
            text, re.IGNORECASE,
        )
        if tax_match:
            candidate = tax_match.group(1).upper()
            if re.fullmatch(r"[0-9A-HJ-NPQRTUWXY]{18}", candidate):
                fields["tax_id"] = candidate
                fields.pop("tax_id_invalid", None)
            else:
                fields.pop("tax_id", None)
                fields["tax_id_invalid"] = True

        title_match = re.search(
            r"(?:发票抬头|抬头|企业名称|公司名称|单位名称)\s*[:：为]?\s*([^，,；;\s]+)",
            text,
        )
        company_match = re.search(
            r"([^，,；;\s]{2,40}(?:有限责任公司|股份有限公司|有限公司|公司|企业|工作室))",
            text,
        )
        if title_match:
            fields["title"] = title_match.group(1).strip()
        elif company_match:
            fields["title"] = company_match.group(1).strip()

        if any(token in text for token in ("企业", "公司", "单位", "对公")) or fields.get("tax_id"):
            fields["invoice_type"] = "COMPANY"
        elif any(token in text for token in ("个人", "个人抬头")):
            fields["invoice_type"] = "PERSONAL"
            fields.pop("tax_id", None)
            fields.pop("tax_id_invalid", None)
        elif fields.get("invoice_type") == "PERSONAL" and any(
            token in text for token in ("姓名", "抬头")
        ):
            name_match = re.search(r"(?:姓名|抬头)\s*[:：为]?\s*([^，,；;\s]+)", text)
            if name_match:
                fields["title"] = name_match.group(1).strip()

        return fields

    @staticmethod
    def _invoice_missing_fields(fields):
        missing = []
        if fields.get("invoice_type") not in {"PERSONAL", "COMPANY"}:
            missing.append("发票类型（个人或企业）")
        if not fields.get("title"):
            missing.append("发票抬头")
        if fields.get("invoice_type") == "COMPANY":
            if not fields.get("tax_id"):
                missing.append("18 位统一社会信用代码/纳税人识别号")
        return missing

    @staticmethod
    def _invoice_details_prompt(fields):
        missing = ConversationOrchestrator._invoice_missing_fields(fields)
        if fields.get("tax_id_invalid"):
            return "企业税号格式不正确，请提供 18 位统一社会信用代码/纳税人识别号。"
        if missing:
            return "还需要补充：" + "、".join(missing) + "。接收邮箱为选填项，也可以一并提供。"
        email = fields.get("email") or "未提供（可后续由工作人员联系确认）"
        return (
            f"已记录{ '企业' if fields['invoice_type'] == 'COMPANY' else '个人' }发票信息："
            f"抬头 {fields['title']}；"
            f"{'税号 ' + fields['tax_id'] + '；' if fields.get('tax_id') else ''}"
            f"接收邮箱 {email}。请确认是否提交发票申请工单？回复“确认”或“算了”。"
        )

    def _service_ticket_request(self, message, principal, context, route):
        pending = context.get("pending_ticket_request") or {}
        if context.get("pending_action") == "collect_invoice_details":
            pending["details"] = self._parse_invoice_fields(
                message, pending.get("details") if isinstance(pending.get("details"), dict) else {}
            )
            missing = self._invoice_missing_fields(pending["details"])
            context["pending_ticket_request"] = pending
            if missing or pending["details"].get("tax_id_invalid"):
                return self._simple(
                    route, "collecting_invoice_details",
                    self._invoice_details_prompt(pending["details"]),
                    "collect_invoice_details", clarification=True,
                )
            context["pending_action"] = "confirm_service_ticket"
            return self._simple(
                route, "awaiting_ticket_confirmation",
                self._invoice_details_prompt(pending["details"]),
                "confirm_service_ticket", clarification=True, needs_human=True,
                data={"invoice_details": pending["details"]},
            )
        intent = route.get("intent")
        if not pending or pending.get("intent") != intent:
            facility_context = str(context.get("pending_facility_issue") or "")
            combined_text = facility_context + " " + str(message)
            issue_type = "BOOKING_ERROR" if intent == "booking_issue" else "INVOICE" if intent == "invoice_request" else (
                "FACILITY_COMPLAINT" if intent == "complaint" and any(x in combined_text for x in ("电梯", "设施")) else
                "HYGIENE_COMPLAINT" if any(x in message for x in ("卫生", "脏", "清洁")) and intent == "complaint" else
                "NOISE" if any(x in message for x in ("吵", "噪音")) and intent == "complaint" else
                "ROOM_MAINTENANCE" if any(x in message for x in ("空调", "维修", "漏水", "坏了")) else
                "MERCHANT_COMPLAINT" if intent == "complaint" else
                "ROOM_CLEANING" if any(x in message for x in ("打扫", "清洁", "卫生")) else
                "ROOM_AMENITY" if any(x in message for x in ("电梯", "设施")) else "OTHER")
            context["pending_ticket_request"] = {"intent": intent, "request_text": (facility_context + "；" + str(message)).strip("； "), "issue_type": issue_type}
            context["pending_facility_issue"] = None
            pending = context["pending_ticket_request"]
        result = self.booking_service.search_my_bookings(principal, limit=3)
        if result.get("status") != "ok":
            return self._failure(result, route)
        rows = result.get("matched_bookings") or []
        if not rows:
            return self._simple(route, "not_found", "没有找到您名下的订单。请先核对订单或联系工作人员；当前不会创建未关联订单的工单。",
                                "booking_lookup", needs_human=True)
        if len(rows) > 1 and not context.get("pending_ticket_booking_id"):
            remember_candidates(context, rows, pending_action="select_service_ticket")
            return self._candidate_prompt(rows, route, result.get("audit_id"), purpose="select_booking_for_service_ticket")
        booking_id = context.get("pending_ticket_booking_id") or rows[0]["booking_id"]
        detail = self.booking_service.get_my_booking(principal, booking_id)
        if detail.get("status") not in ("ok", "data_incomplete"):
            return self._failure(detail, route)
        return self._prepare_service_ticket(detail, context, route, principal)

    def _prepare_service_ticket(self, detail, context, route, principal):
        booking = detail.get("booking") or {}
        pending = context.get("pending_ticket_request") or {}
        booking_id = booking.get("booking_id")
        context["pending_ticket_booking_id"] = booking_id

        # Repeated requests reuse the existing active ticket instead of reopening
        # confirmation or creating another ticket for the same booking/issue pair.
        active = self.ticket_service.get_active_ticket(
            booking_id, pending.get("issue_type") or "OTHER",
            guest_id=principal.customer_id,
        )
        if active:
            context["pending_ticket_request"] = None
            context["pending_ticket_booking_id"] = None
            context["pending_action"] = None
            return self._active_ticket_reply(route, active, booking_id)

        pending.setdefault("operation_id", str(uuid.uuid4()))
        context["pending_ticket_request"] = pending
        if pending.get("issue_type") == "INVOICE" and not pending.get("details"):
            context["pending_action"] = "collect_invoice_details"
            return self._simple(
                route, "collecting_invoice_details",
                f"已关联订单 {booking_id}。请说明开具个人还是企业发票，并提供发票抬头；企业发票还需 18 位统一社会信用代码/纳税人识别号。接收邮箱为选填项。",
                "collect_invoice_details", clarification=True,
            )
        context["pending_action"] = "confirm_service_ticket"
        return self._simple(route, "awaiting_ticket_confirmation",
            f"已关联订单 {booking_id}。拟提交事项：{pending.get('request_text') or '住客服务请求'}。工单类别：{pending.get('issue_type') or 'OTHER'}。请确认是否提交给工作人员处理？回复“确认”或“算了”。",
            "confirm_service_ticket", clarification=True, needs_human=True,
            data={"booking": booking, "issue_type": pending.get("issue_type")})

    def _active_ticket_reply(self, route, item, booking_id):
        labels = {
            "SUBMITTED": "已提交，等待受理",
            "ASSIGNED": "已分配处理人员",
            "PROCESSING": "处理中",
            "PENDING_USER": "等待您补充信息",
            "ESCALATED": "已升级人工处理",
        }
        status = labels.get(item.get("status"), item.get("status") or "处理中")
        return self._simple(
            route, "existing_ticket",
            f"这笔订单已有同类工单 {item['ticket_id']}，当前状态：{status}。我已为您查到原工单，不会重复创建。工作人员将继续跟进。",
            "existing_ticket_reused", needs_human=True,
            data={"booking_id": booking_id, "ticket": item, "reused": True},
        )

    def _service_ticket_confirmation(self, message, principal, context, route, history=None):
        pending = context.get("pending_ticket_request") or {}
        if route.get("sub_intent") == "supplement_ticket_details":
            pending["request_text"] = (str(pending.get("request_text") or "") + "；补充：" + str(message)).strip("；")
            context["pending_ticket_request"] = pending
            return self._simple(route, "awaiting_ticket_confirmation",
                f"已补充记录：{pending['request_text']}。请确认是否提交该工单？回复“确认”或“算了”。",
                "confirm_service_ticket", clarification=True, needs_human=True)
        if route.get("sub_intent") == "reject_ticket":
            context["pending_ticket_request"] = None
            context["pending_ticket_booking_id"] = None
            context["pending_action"] = None
            return self._simple(route, "ticket_cancelled", "好的，已取消本次工单提交，没有创建工单。", "ticket_aborted")
        if pending.get("issue_type") == "INVOICE":
            invoice_details = pending.get("details") if isinstance(pending.get("details"), dict) else {}
            missing = self._invoice_missing_fields(invoice_details)
            if missing or invoice_details.get("tax_id_invalid"):
                context["pending_action"] = "collect_invoice_details"
                return self._simple(
                    route, "collecting_invoice_details",
                    self._invoice_details_prompt(invoice_details),
                    "collect_invoice_details", clarification=True,
                )
        booking_id = context.get("pending_ticket_booking_id")
        if not pending or not booking_id:
            return self._simple(route, "needs_clarification", "当前没有待确认的工单事项，请重新描述您的需求。", "service_ticket_context_missing", clarification=True)
        detail = self.booking_service.get_my_booking(principal, booking_id)
        if detail.get("status") not in ("ok", "data_incomplete"):
            return self._simple(route, "ticket_creation_blocked", "无法重新核验关联订单，没有创建工单。请稍后重试或联系工作人员。",
                                "ticket_creation_blocked", needs_human=True)
        intent = pending.get("intent")
        category = {"booking_issue": "TRANSACTION_ORDER", "invoice_request": "BILLING_DOCUMENT",
                    "complaint": "COMPLAINT_EXPERIENCE", "service_request": "STAY_SERVICE"}.get(intent, "CONSULTATION_OTHER")
        operation_id = pending.setdefault("operation_id", str(uuid.uuid4()))
        ticket = self.ticket_service.create_ticket(
            guest_id=principal.customer_id, booking_id=booking_id, category=category,
            priority="HIGH" if intent == "complaint" and any(x in str(pending.get("request_text") or "") for x in ("影响休息", "多次未处理", "严重", "无法入住")) else "NORMAL",
            description=(pending.get("request_text") or "") + (
                ("；发票信息：" + json.dumps(pending["details"], ensure_ascii=False))
                if intent == "invoice_request" and pending.get("details") else
                ("；补充信息：" + str(pending["details"]))
                if pending.get("details") else ""
            ),
            idempotency_key=f"{principal.customer_id}:{operation_id}:service",
            operation_id=operation_id,
            metadata={"source": "ai_conversation", "intent": intent,
                      "issue_type": pending.get("issue_type") or "OTHER",
                      "user_confirmed": True, "requires_human_review": True,
                      "handling_channel": ("ON_SITE" if category == "STAY_SERVICE" else
                                           "MULTI_TEAM" if pending.get("issue_type") in {"HYGIENE_COMPLAINT", "NOISE", "FACILITY_COMPLAINT", "ROOM_MAINTENANCE"} else
                                           "BACK_OFFICE" if category == "BILLING_DOCUMENT" else "MANAGER_REVIEW"),
                      "issue_location": ("BATHROOM" if any(x in str(pending.get("request_text") or "") for x in ("卫生间", "浴室", "厕所")) else
                                         "GUEST_ROOM" if any(x in str(pending.get("request_text") or "") for x in ("客房", "房间", "房内", "卧室")) else
                                         "PUBLIC_AREA" if any(x in str(pending.get("request_text") or "") for x in ("大厅", "走廊", "餐厅", "停车场", "公共区域")) else
                                         "FRONT_DESK" if "前台" in str(pending.get("request_text") or "") else "UNKNOWN"),
                      "booking_snapshot": detail.get("booking") or {},
                      "invoice_details": pending.get("details") if intent == "invoice_request" else None,
                      "execution_boundary": "ticket_only_no_service_execution"})
        if not ticket.get("ok"):
            return self._simple(route, "ticket_creation_failed", "工单创建失败，未执行任何现场服务或票据操作，请联系工作人员。",
                                "ticket_creation_failed", needs_human=True)
        item = ticket["ticket"]
        context["pending_ticket_request"] = None
        context["pending_ticket_booking_id"] = None
        context["pending_action"] = None
        if not ticket.get("created", False):
            return self._active_ticket_reply(route, item, booking_id)
        return self._simple(route, "ticket_created",
            f"已创建工单 {item['ticket_id']}，类别：{item['category']}。该工单已提交给人工处理；系统尚未实际安排服务或开具发票。",
            "automatic_ticket_created", needs_human=True, data={"ticket": item, "booking_id": booking_id})

    def _failure(self, result, route):
        status = result.get("status", "tool_error")
        if status == "unauthenticated": answer = "登录状态已失效，请重新登录后再查询订单。"
        elif status == "not_found": answer = "没有找到您有权查看的这笔订单。请核对订单编号。"
        else: answer = "订单查询暂时不可用，系统没有返回订单信息。请稍后重试或联系工作人员。"
        return self._simple(route, status, answer, "booking_lookup",
                            needs_human=status == "tool_error", audit_id=result.get("audit_id"))
