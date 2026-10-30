from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from services.retrieval import load_knowledge
from services.rag_service import answer_question,generate_with_optional_llm
from services.intent_router import route_question
from services.context_manager import default_context
ROOT=Path(__file__).parent
load_dotenv(ROOT/".env")
st.set_page_config(page_title="EES 酒旅知识助手",page_icon="🏡")
st.title("EES 酒旅知识助手")
st.caption("MVP 1.1 · 业务边界识别与回复路由 · 模拟门店与模拟政策，不连接真实订单或服务系统")
kb=load_knowledge(ROOT/"knowledge"/"property_faq.json")
with st.sidebar:
 property_id=st.selectbox("门店",["DEMO-HOMESTAY-001"])
 st.metric("知识条目",len(kb))
 st.info("退款、实时房态和订单变更不会由系统猜测。")
if "ees_context" not in st.session_state:
 st.session_state["ees_context"]=default_context()
with st.sidebar:
 st.caption("订单上下文状态")
 st.write(st.session_state["ees_context"]["order_status"])
 st.caption("当前无身份认证；此状态不能由用户自行验证。")
 if st.button("重置会话上下文"):
  st.session_state["ees_context"]=default_context()
q=st.text_input("请输入住客问题",placeholder="例如：我预订的房型有停车位吗？")
if st.button("提交问题",type="primary",disabled=not q.strip()):
 route=route_question(q,st.session_state["ees_context"])
 if route["action"]=="rag_answer":
  result=generate_with_optional_llm(q,answer_question(q,property_id,kb))
 else:
  result={"answer":route["response"],"knowledge_ids":[],"sources":[],"grounded":False,"needs_human":route["needs_human"],"reason":route["reason"],"action":route["action"]}
 st.session_state["result"]={"route":route,"result":result}
if "result" in st.session_state:
 payload=st.session_state["result"]; r=payload["result"]; st.subheader("答复"); st.write(r["answer"])
 a,b,c=st.columns(3); a.metric("有知识依据","是" if r["grounded"] else "否"); b.metric("需要人工","是" if r["needs_human"] else "否"); c.metric("动作",r["action"])
 st.caption(r["reason"])
 with st.expander("业务判断与回复路径",expanded=True):
  route=payload["route"]
  st.json({k:route[k] for k in ("intent","order_dependency","order_status","data_dependencies","knowledge_required","realtime_data_required","risk_level","action")})
 with st.expander("检索来源"): st.json(r["sources"])
st.caption("本版本不创建工单、不查询实时房态、不发送真实消息。")
