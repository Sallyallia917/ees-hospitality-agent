from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from services.retrieval import load_knowledge
from services.rag_service import answer_question,generate_with_optional_llm
ROOT=Path(__file__).parent
load_dotenv(ROOT/".env")
st.set_page_config(page_title="EES 酒旅知识助手",page_icon="🏡")
st.title("EES 酒旅知识助手")
st.caption("MVP 1 · 模拟门店与模拟政策，不连接真实订单或服务系统")
kb=load_knowledge(ROOT/"knowledge"/"property_faq.json")
with st.sidebar:
 property_id=st.selectbox("门店",["DEMO-HOMESTAY-001"])
 st.metric("知识条目",len(kb))
 st.info("退款、实时房态和订单变更不会由系统猜测。")
q=st.text_input("请输入住客问题",placeholder="例如：标准几点入住？")
if st.button("提交问题",type="primary",disabled=not q.strip()):
 st.session_state["result"]=generate_with_optional_llm(q,answer_question(q,property_id,kb))
if "result" in st.session_state:
 r=st.session_state["result"]; st.subheader("答复"); st.write(r["answer"])
 a,b,c=st.columns(3); a.metric("有知识依据","是" if r["grounded"] else "否"); b.metric("需要人工","是" if r["needs_human"] else "否"); c.metric("动作",r["action"])
 st.caption(r["reason"])
 with st.expander("检索来源"): st.json(r["sources"])
st.caption("本版本不创建工单、不查询实时房态、不发送真实消息。")
