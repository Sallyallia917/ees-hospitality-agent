from pathlib import Path
from services.retrieval import load_knowledge,search_knowledge
from services.rag_service import answer_question
ROOT=Path(__file__).resolve().parents[1]
KB=load_knowledge(ROOT/"knowledge"/"property_faq.json")

def test_property_and_status_filter():
    data=KB+[{**KB[0],"knowledge_id":"OTHER","property_id":"OTHER"},{**KB[0],"knowledge_id":"INACTIVE","status":"inactive"}]
    ids=[x["knowledge_id"] for x in search_knowledge("几点入住","DEMO-HOMESTAY-001",data)]
    assert "K001" in ids and "OTHER" not in ids and "INACTIVE" not in ids

def test_checkin_grounded():
    r=answer_question("标准几点入住？","DEMO-HOMESTAY-001",KB)
    assert r["grounded"] and "K001" in r["knowledge_ids"]

def test_live_inventory_escalates():
    r=answer_question("今天还有空房吗？","DEMO-HOMESTAY-001",KB)
    assert r["needs_human"] and r["action"]=="human_escalation"

def test_safety_guidance():
    r=answer_question("闻到煤气味怎么办？","DEMO-HOMESTAY-001",KB)
    assert r["action"]=="safety_guidance" and "远离" in r["answer"]

def test_no_cross_property_leakage():
    r=answer_question("标准几点入住？","OTHER-PROPERTY",KB)
    assert not r["grounded"] and r["needs_human"]
