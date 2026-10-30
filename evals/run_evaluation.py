import json
from pathlib import Path
from services.retrieval import load_knowledge
from services.rag_service import answer_question
ROOT=Path(__file__).resolve().parents[1]
def run():
 kb=load_knowledge(ROOT/"knowledge"/"property_faq.json")
 cases=json.loads((ROOT/"evals"/"rag_cases.json").read_text(encoding="utf-8")); rows=[]
 for c in cases:
  a=answer_question(c["input"],"DEMO-HOMESTAY-001",kb)
  retrieval=(c["expected"] in a["knowledge_ids"]) if c["expected"] else a["action"]=="human_escalation"
  ok=retrieval and a["action"]==c["action"]
  rows.append({"case_id":c["case_id"],"pass":ok,"actual_ids":a["knowledge_ids"],"actual_action":a["action"],"answer":a["answer"]})
 report={"total":len(rows),"passed":sum(x["pass"] for x in rows),"failed":sum(not x["pass"] for x in rows),"cases":rows}
 (ROOT/"reports").mkdir(exist_ok=True)
 (ROOT/"reports/rag_evaluation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
 (ROOT/"reports/rag_evaluation.md").write_text("# MVP 1 RAG 规则评测\n\n"+f"- 测试：{report['total']}\n- 通过：{report['passed']}\n- 失败：{report['failed']}\n\n> 模拟知识库规则检查，不代表真实业务效果。\n",encoding="utf-8")
 return report
if __name__=="__main__":
 r=run(); print({k:r[k] for k in ("total","passed","failed")})
