# EES Hospitality Agent — MVP 1.8 (vertical-slice preview)

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

## MVP 1.8 capabilities (two-day vertical slice)
- **对话行为识别模块**：新增历史指代、补充、纠正、状态查询、投诉等 dialogue-act 识别；历史指代型投诉不再默认落入公共 FAQ。
- **服务工单持久化**：新增 SQLite TicketService，支持创建、查询、列表、指派、状态更新及状态历史。
- **工单安全边界**：住客读取按 guest_id 校验归属；非法状态流转拒绝；创建支持幂等键；解决后仍未解决可重新进入处理中。
- **对话自动建单**：住客在对话中提出订错/退款诉求，系统核验本人订单并要求确认；确认后自动创建 REFUND_REQUEST 工单，关联订单、政策快照、原始诉求和最近对话上下文。住客界面不提供手动建单表单。
- **工单跟踪与处理**：住客可查看对话自动创建的工单；演示员工工作台可更新工单状态，员工工作台尚无生产级 RBAC。

## MVP 1.6 capabilities
- **多意图识别**：区分公共知识咨询、订单列表、订单详情/权益、订单选择、订单异常、实时库存、交易变更、现场服务、投诉和安全事件。
- **多轮对话状态**：维护最近意图、当前订单、候选订单、待执行的选择步骤和对话阶段；支持“我有几笔订单 → 第二笔 → 我的早餐含早吗”这类连续查询。
- **订单只读查询**：订单列表默认最多返回最近三笔；支持序号选择；每次详情读取仍由 BookingService 校验登录身份和订单归属。
- **混合式 LLM + 规则**：规则负责安全、交易、实时库存及订单业务边界；可选 LLM 辅助解释含糊表达。LLM 不拥有授权权力，也不直接执行订单操作。
- **证据约束回复**：订单答复仅使用 BookingService 返回字段；可选 LLM 只负责自然语言表达，未配置或调用失败时使用确定性模板。
- **RAG 保持独立**：公共门店政策/设施问题进入知识库检索；个人订单事实不从公共 FAQ 推断。
- **身份切换清理**：退出或认证过期时清除订单上下文、候选订单、操作记录和对话历史，避免跨身份复用会话数据。
- **多订单、多操作状态**：区分当前操作与会话内历史操作；每笔取消/退款或订单问题独立关联订单、确认状态和处理结果。
- **连续订单处理**：一笔操作确认/结束后，用户可以在同一会话重新选择另一笔订单，不再沿用上一笔活动订单。
- **状态边界**：用户确认后自动创建本地演示退款工单；这只代表申请已登记，不代表真实客服已接单，也不代表订单已取消或退款成功。

## MVP 1.8 ticket lifecycle
`SUBMITTED -> ASSIGNED -> PROCESSING -> PENDING_USER -> RESOLVED -> CLOSED`；支持从处理阶段升级 `ESCALATED`，以及住客反馈未解决后从 `RESOLVED/CLOSED` 重新进入 `PROCESSING`。

工单数据保存在本地 `data/tickets.sqlite3`。这是单实例演示持久化，不是生产级数据库部署。

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
        +--> TicketService (confirmed refund request -> SQLite ticket)
        |
        +--> Human handoff / safety guidance
\`\`\`

## Safety and business boundaries
- 用户说“我有订单”不等于身份认证；个人订单查询必须先通过演示身份认证。
- 订单编号不是凭证；BookingService 每次读取都校验订单归属，不向其他客户泄露订单是否存在。
- 订单列表、详情和权益均为只读；不执行取消、退款、改期或换房。
- 退款申请场景：用户选择订单并确认后自动创建本地演示退款工单；订单错误但未提出退款、投诉、维修、送物等其他场景仍按当前人工升级策略处理。
- 实时房态/车位需要实时系统；当前版本转人工核实，不用静态知识库回答库存。
- 安全事件优先级最高。
- 演示 PIN 和身份状态不是生产级认证；不连接真实 PMS/OTA、支付、库存、工单或消息发送系统。

## Version scope and changes

### MVP 1.5 — 订单取消/退款与异常处理闭环
- **修改范围**：意图分类、确定性路由、订单选择、取消政策查询、取消/退款确认、订单错误转人工及登录状态清理。
- **主要修复**：区分“查询取消政策”与“申请取消/退款”；取消/退款前要求明确订单对象和用户确认；订单订错先选订单再收集问题，避免直接误转或把政策问答当交易执行。
- **新增场景**：查询本人订单绑定的取消政策；多笔订单时按序号/房型/房源/日期选单；确认取消退款后安全提示转人工；订单信息错误时关联具体订单再收集详情。
- **边界**：只读合成订单；不执行取消、退款或修改，不创建真实工单。

### MVP 1.6 — 多订单、多操作会话状态管理
- **修改范围**：ContextManager、ConversationOrchestrator 与多订单回归测试。
- **主要修复**：修复单个 `active_booking_id` 在确认后残留，导致后续退款/订错请求错误复用上一笔订单的问题。
- **新增能力**：用 `current_operation` 管理当前待处理操作，用 `booking_operations` 保存同一会话内已结束的多笔操作；每笔记录独立关联订单、操作类型、用户确认与演示转接状态。
- **新增场景**：同一会话先确认订单 A 退款，再选择订单 B 退款；确认 A 后再反馈 B 订错；取消当前操作不影响此前已完成的操作记录。
- **边界**：会话内记录为演示状态，不持久化到 CRM/工单系统；不表示真实工单已创建或业务订单状态已变化。

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
- MVP 1.4: 订单列表/选择、多轮对话状态、个人订单语义识别、订单异常转人工及证据约束回复。
- MVP 1.5: 订单取消/退款与异常处理闭环、订单级政策查询和显式确认。
- **MVP 1.6: 多订单、多操作会话状态；支持同一会话连续处理不同订单，并保留各笔操作记录。**
- **MVP 1.8 preview: 对话确认后自动创建退款工单，关联订单/政策/会话上下文；SQLite 持久化、幂等、工单状态流转与住客跟踪。**
