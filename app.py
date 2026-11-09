from datetime import date
import hmac
import os
import uuid
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from services.auth_service import authenticate_demo_user
from services.booking_service import BookingService
from services.identity import principal_is_valid
from services.retrieval import load_knowledge
from services.rag_service import answer_question, generate_with_optional_llm
from services.intent_router import route_question
from services.context_manager import default_context, clear_dialogue_state
from services.conversation_orchestrator import ConversationOrchestrator
from services.ticket_service import TicketService, STATUSES

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
st.set_page_config(page_title="EES 酒旅服务助手", page_icon="🏡", layout="wide")

st.title("EES 酒旅服务助手")
st.caption(
    "MVP 1.9 · 多轮上下文 + 订单只读查询 + MECE 统一工单演示。"
    "所有订单、账号和政策均为合成演示数据，不连接真实酒店系统。"
)

if "ees_context" not in st.session_state:
    st.session_state.ees_context = default_context()
if "ees_history" not in st.session_state:
    st.session_state.ees_history = []
if "ees_booking_service" not in st.session_state:
    st.session_state.ees_booking_service = BookingService()
if "ees_conversation_orchestrator" not in st.session_state:
    st.session_state.ees_conversation_orchestrator = ConversationOrchestrator(
        st.session_state.ees_booking_service
    )
if "ees_ticket_service" not in st.session_state:
    ticket_db_path = os.getenv("EES_TICKET_DB_PATH", str(ROOT / "data" / "tickets.sqlite3"))
    st.session_state.ees_ticket_service = TicketService(ticket_db_path)
st.session_state.ees_conversation_orchestrator.ticket_service = st.session_state.ees_ticket_service

def clear_authentication():
    st.session_state.pop("ees_principal", None)
    st.session_state.pop("ees_booking_results", None)
    st.session_state.pop("ees_selected_booking", None)
    st.session_state.pop("ees_qa_result", None)
    st.session_state.pop("qa_question", None)
    clear_dialogue_state(st.session_state.ees_context)
    st.session_state.ees_history = []

principal = st.session_state.get("ees_principal")
if principal is not None and not principal_is_valid(principal):
    clear_authentication()
    st.warning("演示登录已过期，请重新登录。")
    principal = None

with st.sidebar:
    st.subheader("演示账户")
    if principal is None:
        with st.form("demo_login_form"):
            account_id = st.text_input("演示账号")
            demo_pin = st.text_input("演示 PIN", type="password")
            login_submitted = st.form_submit_button("登录", type="primary")
        if login_submitted:
            auth = authenticate_demo_user(account_id.strip(), demo_pin)
            if auth["ok"]:
                st.session_state.ees_principal = auth["principal"]
                st.session_state.pop("ees_booking_results", None)
                clear_dialogue_state(st.session_state.ees_context)
                st.session_state.ees_history = []
                st.session_state.pop("ees_qa_result", None)
                st.session_state.pop("qa_question", None)
                st.success("演示身份验证成功。")
                st.rerun()
            else:
                st.error("账号或 PIN 不正确。")
    else:
        st.success("已通过演示身份认证")
        st.caption(f"认证方式：{principal.auth_method}")
        st.caption(f"有效期至：{principal.expires_at}")
        if st.button("退出登录"):
            clear_authentication()
            st.rerun()
    st.divider()
    st.caption("演示环境说明")
    st.info("订单查询为只读；取消政策仅展示，不执行取消或退款。")

tab_qa, tab_booking, tab_tickets = st.tabs(["门店知识问答", "我的订单", "工单跟踪"])

with tab_qa:
    kb = load_knowledge(ROOT / "knowledge" / "property_faq.json")
    property_id = st.selectbox("知识库门店", ["DEMO-HOMESTAY-001"], key="qa_property")
    st.caption(f"知识条目：{len(kb)}")
    q = st.text_input("请输入住客问题", placeholder="例如：入住时间是什么？", key="qa_question")
    if st.button("提交问题", type="primary", disabled=not q.strip(), key="qa_submit"):
        conversational = st.session_state.ees_conversation_orchestrator.handle_booking_query(
            q, principal=st.session_state.get("ees_principal"),
            history=st.session_state.ees_history, context=st.session_state.ees_context
        )
        if conversational["handled"]:
            route = conversational["route"]
            result = {
                "answer": conversational["answer"], "knowledge_ids": [], "sources": [],
                "grounded": False, "needs_human": conversational["needs_human"],
                "reason": route["reason"], "action": conversational["action"],
                "booking_status": conversational["status"],
                "booking_data": conversational["data"],
                "needs_clarification": conversational["needs_clarification"],
                "audit_id": conversational["audit_id"],
            }
        else:
            route = conversational["route"]
            if route["action"] == "rag_answer":
                result = generate_with_optional_llm(q, answer_question(q, property_id, kb))
            else:
                result = {
                    "answer": route["response"], "knowledge_ids": [], "sources": [],
                    "grounded": False, "needs_human": route["needs_human"],
                    "reason": route["reason"], "action": route["action"],
                }
        st.session_state.ees_qa_result = {"route": route, "result": result}
        st.session_state.ees_history.append({
            "intent": route["intent"], "sub_intent": route["sub_intent"], "question": q
        })
        st.session_state.ees_history = st.session_state.ees_history[-8:]
    if "ees_qa_result" in st.session_state:
        payload = st.session_state.ees_qa_result
        result, route = payload["result"], payload["route"]
        st.subheader("答复")
        st.write(result["answer"])
        c1, c2, c3 = st.columns(3)
        c1.metric("有知识依据", "是" if result["grounded"] else "否")
        c2.metric("需要人工", "是" if result["needs_human"] else "否")
        c3.metric("动作", result["action"])
        st.caption(result["reason"])
        with st.expander("业务判断与回复路径"):
            st.json({k: route[k] for k in (
                "intent", "sub_intent", "classification_method", "order_dependency",
                "order_status", "data_dependencies", "knowledge_required",
                "realtime_data_required", "risk_level", "action"
            )})
        if result.get("booking_data"):
            data = result["booking_data"]
            st.markdown("#### 已验证的订单信息")
            st.json(data.get("booking") or {})
            if data.get("missing_fields"):
                st.warning("部分关联数据缺失：" + "、".join(data["missing_fields"]))
            if result.get("audit_id"):
                st.caption("订单查询审计编号：" + result["audit_id"])
        with st.expander("检索来源"):
            st.json(result["sources"])

with tab_booking:
    st.subheader("我的订单")
    if principal is None:
        st.info("请先在左侧完成演示身份认证。未认证状态不能查询订单。")
    else:
        st.caption("仅返回当前演示身份所属订单。默认最多显示最近三笔；可按入住日期、房型、门店和订单状态筛选。")
        with st.form("booking_search_form"):
            c1, c2 = st.columns(2)
            date_from = c1.date_input("入住日期起", value=None)
            date_to = c2.date_input("入住日期止", value=None)
            room_type = st.text_input("房型包含", placeholder="例如：双床")
            property_filter = st.selectbox(
                "门店", ["全部", "DEMO-HOMESTAY-001", "DEMO-HOTEL-002"]
            )
            status_filter = st.selectbox(
                "订单状态", ["全部", "confirmed", "completed", "cancelled"]
            )
            search_submitted = st.form_submit_button("查询我的订单", type="primary")
        if search_submitted:
            filters = {}
            if date_from:
                filters["check_in_from"] = date_from.isoformat()
            if date_to:
                filters["check_in_to"] = date_to.isoformat()
            if room_type.strip():
                filters["room_type"] = room_type.strip()
            if property_filter != "全部":
                filters["property_id"] = property_filter
            if status_filter != "全部":
                filters["booking_status"] = status_filter
            response = st.session_state.ees_booking_service.search_my_bookings(
                principal, filters=filters, limit=3
            )
            st.session_state.ees_booking_results = response
            st.session_state.pop("ees_selected_booking", None)

        response = st.session_state.get("ees_booking_results")
        if response:
            if response["status"] == "ok":
                rows = response["matched_bookings"]
                st.caption(f"查询成功 · 返回 {len(rows)} 笔（最多三笔）")
                labels = {
                    f'{row["booking_id"]}｜{row["room_type"]}｜{row["check_in"][:10]}': row["booking_id"]
                    for row in rows
                }
                selected_label = st.selectbox("选择订单查看详情", list(labels.keys()))
                selected_id = labels[selected_label]
                if st.button("查看订单详情", key="booking_detail_button"):
                    st.session_state.ees_selected_booking = selected_id
                if st.session_state.get("ees_selected_booking"):
                    detail = st.session_state.ees_booking_service.get_my_booking(
                        principal, st.session_state.ees_selected_booking
                    )
                    if detail["status"] in ("ok", "data_incomplete"):
                        booking = detail["booking"]
                        prop = detail["property"]
                        policy = detail["cancellation_policy"]
                        st.markdown("#### 订单信息")
                        status = booking.get("booking_status", "unknown")
                        status_labels = {
                            "confirmed": "已确认",
                            "completed": "已完成",
                            "cancelled": "已取消",
                        }
                        c_status, c_room, c_dates = st.columns(3)
                        c_status.metric("订单状态", status_labels.get(status, status))
                        c_room.metric("房型", booking.get("room_type") or "未提供")
                        c_dates.metric("入住日期", str(booking.get("check_in") or "")[:10] or "未提供")
                        st.caption("订单状态来自演示订单数据；当前版本仅查询和展示，不修改订单状态。")
                        st.json(booking)
                        st.markdown("#### 房源信息")
                        if prop:
                            st.write(f'**{prop["property_name"]}** · {prop["property_type"]}')
                            location = prop.get("location") or {}
                            st.write(f'{location.get("city", "")} · {location.get("address_display", "")}')
                            st.write("设施：" + "、".join(prop.get("facilities") or []))
                            st.write("入住说明：" + str(prop.get("check_in_instructions") or "暂无"))
                        else:
                            st.warning("房源信息不完整。")
                        st.markdown("#### 订单绑定的取消政策")
                        if policy:
                            st.caption(
                                f'政策编号：{policy["policy_id"]} · 版本：{policy["version"]} · 时区：{policy["timezone"]}'
                            )
                            for window in policy.get("windows", []):
                                st.write("• " + window.get("label", "规则说明缺失"))
                            st.warning("以上为订单绑定政策的展示，不代表已计算实时退款金额，也不会执行取消或退款。")
                        else:
                            st.warning("未找到该订单绑定的政策，不能推断取消规则。")
                        if detail.get("missing_fields"):
                            st.warning("数据缺失：" + "、".join(detail["missing_fields"]))
                        st.caption(f'审计事件编号：{detail["audit_id"]}')
                    else:
                        st.error("订单详情暂不可用，请稍后重试或联系人工。")
                st.caption(f'查询审计事件编号：{response["audit_id"]}')
            elif response["status"] == "not_found":
                st.info("没有找到符合条件的本人订单。")
            elif response["status"] == "unauthenticated":
                clear_authentication()
                st.error("登录状态已失效，请重新登录。")
            else:
                st.error("订单查询暂不可用，系统未返回订单数据。")


with tab_tickets:
    st.subheader("对话自动创建的工单")
    st.caption("工单由 AI 对话中的确认动作自动创建；本页面仅用于查看和跟踪，不提供住客手动创建入口。")
    if principal is None:
        st.info("请先完成演示身份认证。")
    else:
        mine = st.session_state.ees_ticket_service.list_tickets(guest_id=principal.customer_id)
        if mine:
            status_labels = {
                "SUBMITTED": "已提交，等待人工接单",
                "ASSIGNED": "已指派",
                "PROCESSING": "处理中",
                "PENDING_USER": "等待住客反馈",
                "RESOLVED": "已解决",
                "CLOSED": "已关闭",
                "ESCALATED": "已升级人工处理",
            }
            category_labels = {
                "TRANSACTION_ORDER": "交易与订单",
                "STAY_SERVICE": "住宿服务",
                "COMPLAINT_EXPERIENCE": "投诉与体验",
                "BILLING_DOCUMENT": "票据与财务",
                "CONSULTATION_OTHER": "咨询与其他",
            }
            for ticket in mine:
                with st.expander(f'{ticket["ticket_id"]} · {category_labels.get(ticket["category"], ticket["category"])} · {status_labels.get(ticket["status"], ticket["status"])}'):
                    st.write(ticket["description"])
                    st.caption(f'关联订单：{ticket.get("booking_id") or "无"} · 优先级：{ticket["priority"]} · 创建：{ticket["created_at"]}')
                    if ticket.get("metadata"):
                        st.json(ticket["metadata"])
                    st.json(ticket["history"])
        else:
            st.caption("当前没有由对话自动创建的工单。请在对话中提出订单问题或退款申请。")

    st.divider()
    st.markdown("#### 员工处理工作台（演示）")
    configured_staff_pin = os.getenv("EES_DEMO_STAFF_PIN", "")
    if not configured_staff_pin:
        st.info("员工工作台默认关闭。请在本地 .env 配置 EES_DEMO_STAFF_PIN 后启用；不要在公开演示环境使用真实客户数据。")
    else:
        with st.form("demo_staff_login_form"):
            staff_pin_input = st.text_input("演示员工 PIN", type="password")
            staff_login = st.form_submit_button("进入员工工作台")
        if staff_login:
            st.session_state.ees_demo_staff_authenticated = hmac.compare_digest(
                staff_pin_input, configured_staff_pin
            )
        if st.session_state.get("ees_demo_staff_authenticated"):
            if st.button("退出员工工作台", key="staff_logout"):
                st.session_state.ees_demo_staff_authenticated = False
                st.rerun()
            all_tickets = st.session_state.ees_ticket_service.list_tickets(staff=True)
            if not all_tickets:
                st.caption("暂无待处理工单。")
            else:
                ticket_labels = {f'{t["ticket_id"]} · {t["category"]} · {t["status"]}': t["ticket_id"] for t in all_tickets}
                selected_label = st.selectbox("选择工单", list(ticket_labels.keys()), key="staff_ticket_select")
                selected_id = ticket_labels[selected_label]
                selected = st.session_state.ees_ticket_service.get_ticket(selected_id, staff=True)["ticket"]
                st.write(selected["description"])
                st.caption("当前状态：" + selected["status"])
                next_status = st.selectbox("更新状态", sorted(STATUSES), key="staff_ticket_status")
                staff_note = st.text_input("处理备注", key="staff_ticket_note")
                assignee = st.text_input("指派员工（演示标识）", key="staff_ticket_assignee")
                if st.button("保存工单状态", key="staff_ticket_update"):
                    updated = st.session_state.ees_ticket_service.update_ticket(
                        selected_id, next_status, actor="demo-staff", note=staff_note,
                        assigned_to=assignee.strip() or None
                    )
                    if updated["ok"]:
                        st.success("状态已更新。")
                        st.rerun()
                    else:
                        st.error("状态更新失败：" + updated["error"])
        else:
            st.warning("请先通过演示员工 PIN 验证。员工 PIN 仅用于本地原型隔离，不构成生产级 RBAC。")

st.divider()
st.caption(
    "能力边界：当前订单能力使用合成数据进行身份认证与只读查询；"
    "AI 对话确认后可自动创建本地演示工单；一级类别采用交易与订单、住宿服务、投诉与体验、票据与财务、咨询与其他，"
    "具体问题通过 issue_type 标记；不连接真实 PMS/OTA，不执行退款或现场服务，不连接真实派单系统。"
)
