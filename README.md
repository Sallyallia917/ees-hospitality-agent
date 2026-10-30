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
