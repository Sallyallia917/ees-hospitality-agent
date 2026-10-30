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


def test_order_specific_room_type_does_not_use_faq():
    r=answer_question("我预定的是什么房型？","DEMO-HOMESTAY-001",KB)
    assert r["action"]=="order_lookup_unavailable"
    assert not r["grounded"] and r["needs_human"]
    assert r["knowledge_ids"]==[]
    assert "不能根据通用 FAQ 推断房型" in r["answer"]

def test_room_upgrade_policy_still_uses_faq():
    r=answer_question("可以升级房型吗？","DEMO-HOMESTAY-001",KB)
    assert "K020" in r["knowledge_ids"]
    assert r["grounded"]

def test_live_room_type_options_escalates():
    r=answer_question("现在还有什么房型可选？","DEMO-HOMESTAY-001",KB)
    assert r["action"]=="human_escalation" and not r["grounded"]
