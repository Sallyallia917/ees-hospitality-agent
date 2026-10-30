# EES Hospitality Agent — MVP 1

RAG 酒旅知识问答原型，使用模拟门店 `DEMO-HOMESTAY-001` 与模拟政策，不代表真实门店规则。

## Run
Python 3.11/3.12：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Tests
```bash
pytest -q
python -m evals.run_evaluation
```

可选 LLM：复制 `.env.example` 为 `.env` 并配置 API key/model。不要提交密钥。

当前不连接 PMS/OTA，不查询实时房态或订单，不创建工单，不退款，不发送真实消息。


## MVP 1.1 — Business routing

The app classifies business dependency before RAG:
- Public property FAQ -> knowledge retrieval.
- Personal booking attributes/entitlements -> never infer from FAQ; no authentication or booking lookup is available in this release.
- Real-time room/parking availability -> human verification.
- Refunds and booking changes -> handoff only; no transaction is executed.
- Service requests and complaints -> handoff only; no ticket is created.
- Safety incidents -> safety response takes priority.

Order context states are UNKNOWN / UNVERIFIED / VERIFIED. The app defaults to UNKNOWN and has no user-facing control to self-assert VERIFIED. Even VERIFIED cannot return booking data until an authorized lookup tool is integrated.

Run: `pytest -q`, `python -m evals.run_evaluation`, `python -m evals.run_routing_evaluation`.

The routing test set contains 30 synthetic cases. Passing validates the coded scenarios only; it is not a measured real-world classification rate.
