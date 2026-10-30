import json
from pathlib import Path
from services.intent_router import route_question
ROOT=Path(__file__).resolve().parents[1]
def run():
    cases=json.loads((ROOT/"evals/mvp_1_2_cases.json").read_text(encoding="utf-8"))
    rows=[]
    for c in cases:
        r=route_question(c["input"])
        checks={"intent":r["intent"]==c["expected_intent"],
          "action":r["action"]==c["expected_action"],
          "order_dependency":r["order_dependency"]==c["expected_order_dependency"],
          "safety_gate":not(c["expected_intent"]=="safety_incident" and r["action"]!="safety_guidance"),
          "no_fake_execution":r["action"] not in {"booking_updated","refund_completed","ticket_created"}}
        rows.append({"case_id":c["case_id"],"input":c["input"],"pass":all(checks.values()),"checks":checks,
          "expected_intent":c["expected_intent"],"actual_intent":r["intent"],"expected_action":c["expected_action"],
          "actual_action":r["action"],"expected_order_dependency":c["expected_order_dependency"],
          "actual_order_dependency":r["order_dependency"]})
    passed=sum(x["pass"] for x in rows)
    report={"version":"1.2","dataset":"synthetic","total":len(rows),"passed":passed,"failed":len(rows)-passed,
      "intent_accuracy":sum(x["checks"]["intent"] for x in rows)/len(rows),
      "action_accuracy":sum(x["checks"]["action"] for x in rows)/len(rows),
      "order_dependency_accuracy":sum(x["checks"]["order_dependency"] for x in rows)/len(rows),"cases":rows}
    (ROOT/"reports").mkdir(exist_ok=True)
    (ROOT/"reports/mvp_1_2_evaluation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (ROOT/"reports/mvp_1_2_evaluation.md").write_text("# EES MVP 1.2 路由评测\n\n"+
      f"- 模拟案例：{report['total']}\n- 全项通过：{passed}\n- 存在失败：{report['failed']}\n"+
      f"- 意图分类匹配率：{report['intent_accuracy']:.1%}\n- 路由动作匹配率：{report['action_accuracy']:.1%}\n"+
      f"- 订单依赖判断匹配率：{report['order_dependency_accuracy']:.1%}\n\n"+
      "> 本报告仅反映合成测试集表现，不代表真实住客流量准确率或生产效果。未配置 LLM 时使用规则回退。\n",encoding="utf-8")
    return report
if __name__=="__main__":
    r=run(); print({k:r[k] for k in ("total","passed","failed","intent_accuracy","action_accuracy","order_dependency_accuracy")})
