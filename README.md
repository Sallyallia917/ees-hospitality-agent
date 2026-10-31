# EES Hospitality Agent — MVP 1.2

面向民宿与酒店服务场景的 AI 业务路由原型。演示门店 `DEMO-HOMESTAY-001`、政策、案例均为模拟数据，不代表真实门店规则或生产效果。

## Run
Python 3.11/3.12:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

可选 LLM：复制 `.env.example` 为 `.env`，配置兼容 OpenAI Chat Completions 的 API key、base URL 和 model。未配置或调用失败时自动使用规则分类。不要提交密钥。

## Tests and evaluation
```bash
pytest -q
python -m evals.run_evaluation
python -m evals.run_routing_evaluation
python -m evals.run_mvp_1_2_evaluation
```

MVP 1.2 加入规则 + 可选 LLM 结构化意图分类、确定性业务路由、多轮上下文线索，以及 60+ 条合成业务路由评测案例。评测报告写入 `reports/mvp_1_2_evaluation.json` 和 `reports/mvp_1_2_evaluation.md`。

## Business boundaries
- 公共门店政策/设施问题：进入知识库 RAG；回答必须有知识证据。
- 个人订单、房型、订单权益：不进入公共 FAQ；当前版本不连接订单系统。
- 实时房态/车位：转人工核实，不以静态知识回答。
- 退款、取消、改期、换房：仅转人工，不执行交易。
- 送物、维修、清洁、投诉：当前版本仅提示人工处理，不声称工单已创建。
- 安全事件：最高优先级安全响应。
- 用户自述有订单不等于身份认证；即使状态为 VERIFIED，本版本仍没有订单查询工具。
- LLM 只提供意图理解建议，不决定授权、不执行工具；安全、交易、订单、实时库存等确定性边界不由 LLM 覆盖。

## Version scope
- MVP 1.2: hybrid classification, routing, context-aware follow-up, evaluation.
- MVP 1.3: simulated booking store and authorized read-only booking lookup (not included yet).
- No real PMS/OTA, payment, inventory API, ticket system, or real message sending.
