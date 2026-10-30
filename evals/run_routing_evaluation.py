import json
from pathlib import Path
from services.intent_router import route_question

ROOT=Path(__file__).resolve().parents[1]

def run():
    cases=json.loads((ROOT/"evals"/"routing_cases.json").read_text(encoding="utf-8"))
    rows=[]
    for case in cases:
        actual=route_question(case["input"])
        passed=(actual["intent"]==case["expected_intent"] and
                actual["action"]==case["expected_action"] and
                actual["order_dependency"]==case["expected_order_dependency"])
        rows.append({"case_id":case["case_id"],"input":case["input"],"pass":passed,
                     "expected_intent":case["expected_intent"],"actual_intent":actual["intent"],
                     "expected_action":case["expected_action"],"actual_action":actual["action"],
                     "expected_order_dependency":case["expected_order_dependency"],
                     "actual_order_dependency":actual["order_dependency"]})
    report={"total":len(rows),"passed":sum(x["pass"] for x in rows),
            "failed":sum(not x["pass"] for x in rows),"cases":rows}
    (ROOT/"reports").mkdir(exist_ok=True)
    (ROOT/"reports"/"routing_evaluation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (ROOT/"reports"/"routing_evaluation.md").write_text(
      "# MVP 1.1 路由评测\n\n"+
      f"- 测试案例：{report['total']}\n- 通过：{report['passed']}\n- 失败：{report['failed']}\n\n"+
      "> 测试基于模拟业务语料，不代表真实业务准确率。\n",encoding="utf-8")
    return report

if __name__=="__main__":
    result=run()
    print({k:result[k] for k in ("total","passed","failed")})
