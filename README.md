# EES Hospitality Agent — MVP 1.4

面向民宿与酒店服务场景的 AI 服务助手原型。演示门店、账户、订单、政策和案例均为合成数据，不代表真实门店规则或生产效果。

## Run
Python 3.11/3.12:
\`\`\`bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
\`\`\`

可选 LLM：复制 \`.env.example\` 为 \`.env\`，配置兼容 OpenAI Chat Completions 的 API key、base URL 和 model。未配置或调用失败时，系统回退到规则分类和确定性回复。不要提交密钥。

## MVP 1.4 capabilities
- **多意图识别**：区分公共知识咨询、订单列表、订单详情/权益、订单选择、订单异常、实时库存、交易变更、现场服务、投诉和安全事件。
- **多轮对话状态**：维护最近意图、当前订单、候选订单、待执行的选择步骤和对话阶段；支持“我有几笔订单 → 第二笔 → 我的早餐含早吗”这类连续查询。
- **订单只读查询**：订单列表默认最多返回最近三笔；支持序号选择；每次详情读取仍由 BookingService 校验登录身份和订单归属。
- **混合式 LLM + 规则**：规则负责安全、交易、实时库存及订单业务边界；可选 LLM 辅助解释含糊表达。LLM 不拥有授权权力，也不直接执行订单操作。
- **证据约束回复**：订单答复仅使用 BookingService 返回字段；可选 LLM 只负责自然语言表达，未配置或调用失败时使用确定性模板。
- **RAG 保持独立**：公共门店政策/设施问题进入知识库检索；个人订单事实不从公共 FAQ 推断。
- **身份切换清理**：退出或认证过期时清除订单上下文、候选订单和对话历史，避免跨身份复用会话数据。

## Architecture
\`\`\`text
Streamlit UI / Session
        |
        v
ConversationOrchestrator
        |
        +--> SemanticClassifier (rules + optional LLM)
        |          |
        |          v
        |     IntentRouter (deterministic policy)
        |
        +--> ContextManager (dialogue state / candidate slots)
        |
        +--> BookingService --> BookingRepository (synthetic data)
        |          |
        |          +--> identity & ownership validation
        |          +--> audit events
        |          +--> evidence-bound response generator
        |
        +--> RAG retrieval --> optional LLM answer verbalization
        |
        +--> Human handoff / safety guidance
\`\`\`

## Safety and business boundaries
- 用户说“我有订单”不等于身份认证；个人订单查询必须先通过演示身份认证。
- 订单编号不是凭证；BookingService 每次读取都校验订单归属，不向其他客户泄露订单是否存在。
- 订单列表、详情和权益均为只读；不执行取消、退款、改期或换房。
- 订单错误、投诉、维修、送物等需要工作人员核实或现场执行；当前版本不声称已创建工单。
- 实时房态/车位需要实时系统；当前版本转人工核实，不用静态知识库回答库存。
- 安全事件优先级最高。
- 演示 PIN 和身份状态不是生产级认证；不连接真实 PMS/OTA、支付、库存、工单或消息发送系统。

## Tests and evaluation
\`\`\`bash
pytest -q
python -m evals.run_evaluation
python -m evals.run_routing_evaluation
python -m evals.run_mvp_1_2_evaluation
\`\`\`
新增 \`tests/test_dialogue_context_refactor.py\` 覆盖订单列表意图、第一人称订单字段、订单异常转人工、上下文续问、候选订单序号选择和身份校验。自动化测试通过不代表真实酒店系统集成或线上浏览器验收。

## Version history
- MVP 1.2: 规则 + 可选 LLM 意图分类、确定性业务路由和路由评测。
- MVP 1.3: 合成订单数据、演示身份认证、只读订单服务、订单归属校验和审计。
- MVP 1.3.1: 对话入口接入订单只读查询。
- **MVP 1.4: 订单列表/选择、多轮对话状态、个人订单语义识别、订单异常转人工及证据约束回复。**
