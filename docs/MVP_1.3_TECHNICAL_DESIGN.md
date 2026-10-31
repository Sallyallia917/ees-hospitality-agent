# EES Hospitality Agent — MVP 1.3 Technical Design

- 状态：设计基线（待评审）
- 架构风格：现有 Streamlit 单体应用内的分层模块化设计
- 数据：本地 JSON 合成订单数据；不接真实 PMS/OTA
- 核心原则：LLM 不认证、不授权、不直接访问存储、不执行交易

## 1. 设计目标

在 MVP 1.2 的意图路由之后增加受控只读查询链路。将身份认证、订单归属授权、数据访问、结果校验拆成独立职责，便于单元测试、替换真实服务和审计。

## 2. 逻辑架构

```text
住客输入
  -> MVP 1.2 Hybrid Intent Classifier
  -> Deterministic Intent Router
       | public FAQ -> Existing RAG
       | safety -> Safety Guidance
       | transaction -> Human Handoff
       | realtime -> Human Verification
       | booking inquiry
             -> Authentication Gate
             -> Verified Principal (session-bound)
             -> Booking Query Service
                    -> Ownership Authorization
                    -> Read-only Booking Repository
                    -> Field Allowlist / DTO
             -> Result Validator
             -> Response Composer
             -> Audit Event
```

## 3. 模块职责与建议文件

| 模块 | 建议路径 | 职责 |
|---|---|---|
| Demo Auth Adapter | services/auth_service.py | 校验演示凭据，返回 principal；不接受聊天文本中的 VERIFIED 声明 |
| Principal / Session | services/identity.py | 定义认证主体、会话状态与过期语义 |
| Booking Repository | services/booking_repository.py | 从 JSON 加载演示订单，只提供读取接口 |
| Booking Query Service | services/booking_service.py | 认证门槛、订单归属校验、多订单列表与选择、字段白名单 |
| DTO / Schema | services/booking_schemas.py | 规范化查询结果与状态，拒绝未知字段 |
| Audit | services/audit.py | 记录结构化审计事件，不记录明文凭据 |
| Data | data/demo_customers.json、data/demo_bookings.json | 合成住客和订单 |
| Tests | tests/test_mvp_1_3_*.py | 认证、授权、字段、异常、集成测试 |
| Evals | evals/mvp_1_3_cases.json、evals/run_mvp_1_3_evaluation.py | 场景级安全与功能评测 |

文件路径为设计建议，实施前核对仓库现状，避免覆盖现有模块。

## 4. 核心数据契约

### 4.1 Principal

```json
{
  "principal_id": "DEMO-CUSTOMER-001",
  "customer_id": "CUST-001",
  "auth_method": "demo_pin",
  "authenticated_at": "ISO-8601",
  "expires_at": "ISO-8601",
  "is_authenticated": true
}
```

principal 由认证服务生成；禁止从用户自然语言或 LLM 输出构造 principal。

### 4.2 Booking record（内部存储）

```json
{
  "booking_id": "DEMO-BOOKING-1001",
  "customer_id": "CUST-001",
  "property_id": "DEMO-HOMESTAY-001",
  "booking_status": "confirmed",
  "room_type": "大床房",
  "check_in": "2026-11-12",
  "check_out": "2026-11-14",
  "guest_count": 2,
  "breakfast_entitlement": true,
  "parking_entitlement": "需现场确认",
  "source_channel": "demo_direct"
}
```

以上为契约示例，不是实际用户订单。真实数据集必须使用虚构值。

### 4.3 Query result

建议统一返回：
- status：ok / unauthenticated / not_found / forbidden / ambiguous / data_incomplete / tool_error
- booking_summary：只含允许展示的字段
- missing_fields：缺失字段名
- message_code：由应用映射为用户提示
- audit_id：审计事件标识

不要把数据库原始 record 直接传给 LLM 或 UI。

## 5. 认证与授权

### 认证
- 演示账号凭据只存在于 demo auth adapter 配置/数据中，不放进聊天 prompt。
- 认证成功后在 Streamlit session state 保存 principal；设置明确过期时间。
- 重置会话时清除 principal 和已选择订单。
- 前端展示状态仅用于可视化；服务层每次调用都重新检查 principal。

### 授权
- 先验证 principal 有效，再按 customer_id 查询其订单。
- 单订单查询：仅返回 principal.customer_id 拥有的记录。
- 多订单：只列出本人订单的脱敏摘要；用户选择后再次执行归属校验。
- 任意 booking_id 作为输入都不能绕过 customer_id 归属校验。
- 对不存在和不属于本人的订单，面向用户采用不泄露资源存在性的统一响应；内部审计可区分拒绝原因。

### 生产替换边界
当前 demo PIN 方案仅用于演示流程。生产系统应由可信身份提供方完成认证，使用短时签名令牌/会话、速率限制、账户锁定策略、密钥管理、CSRF/重放防护及合规审计。不得将当前 demo adapter 描述为安全生产认证。

## 6. 工具接口（应用内部函数，不是开放给 LLM 的任意工具）

建议接口：
- authenticate_demo_user(account_id, demo_pin) -> AuthResult
- list_my_bookings(principal) -> list[BookingSummary]
- get_my_booking(principal, booking_id) -> BookingQueryResult

安全要求：
1. 所有查询函数显式接收 principal。
2. Repository 不暴露写入、更新、删除接口。
3. Service 层完成 ownership check。
4. 输出 DTO 采用字段白名单。
5. LLM 只能收到已验证、最小化的 DTO 用于语言表达；更稳妥的 MVP 默认由模板生成关键订单字段，避免模型改写日期、房型和权益。
6. 任何工具错误均 fail closed，不回退到 RAG 猜测个人订单信息。

## 7. 意图与上下文集成

- MVP 1.2 的 safety、transaction、realtime 分支保持现有优先级。
- booking_related_inquiry 进入认证门槛。
- 未认证：返回 authenticate_required，不调用 repository。
- 已认证：如用户未指定订单且本人仅有一笔订单，可直接查询；多笔订单则返回选择状态。
- 用户指定订单号时仍须校验归属。
- 多轮上下文仅用于解析“那早餐呢”等指代，不可作为认证凭证。
- 会话重置清空 principal、selected_booking_id、历史查询结果。

## 8. 错误处理与可观测性

结构化日志字段建议：request_id、principal_id（内部演示 ID）、booking_id（内部 ID）、intent、action、result_status、duration_ms、error_code。不得记录 PIN、完整手机号或完整订单原始内容。

建议状态：
- AUTH_REQUIRED
- AUTH_EXPIRED
- BOOKING_NOT_FOUND_OR_FORBIDDEN
- MULTIPLE_BOOKINGS
- FIELD_NOT_MAINTAINED
- REPOSITORY_ERROR
- INVALID_TOOL_RESULT

日志用于开发演示，不声称具备生产级监控能力。

## 9. 测试策略

### 单元测试
- 认证成功/失败/过期
- 无 principal 时 repository 未被调用
- 本人订单可读
- 他人订单拒绝
- 伪造 booking_id 不越权
- 多订单必须选择
- 字段白名单剔除敏感字段
- 空字段不补全
- repository 异常 fail closed
- reset 清理身份与选择状态

### 集成测试
- 订单意图 -> 未认证 -> 认证 -> 查询 -> 结构化结果
- 订单意图 -> 认证 -> 多订单选择 -> 再次授权 -> 查询
- FAQ 不触发订单工具
- transaction 不触发订单工具
- safety 不等待认证

### 评测集
每个 case 至少包含 input、history、principal_fixture、selected_booking_id、expected_intent、expected_status、expected_action、must_not。评测报告分开统计功能通过率与安全硬门槛；安全违规次数必须为 0 才能通过验收。

## 10. 交付顺序

1. 建立合成客户/订单数据与 schema。
2. 实现 repository（只读）。
3. 实现 demo auth adapter 与 principal 生命周期。
4. 实现 booking service（归属授权、字段白名单、多订单选择）。
5. 集成 intent router 与 Streamlit UI。
6. 加单元/集成/评测脚本及 CI。
7. 本地和线上演示验收，记录已验证场景与未验证边界。

## 11. 技术决策记录

- ADR-01：保留单体应用，避免为作品集引入不必要分布式复杂度。
- ADR-02：认证与授权分离，订单归属在服务端每次检查。
- ADR-03：LLM 只参与理解与表达，不拥有身份、权限或数据库访问能力。
- ADR-04：只读 repository，不实现交易写接口。
- ADR-05：模拟认证明确标注 demo-only；生产身份认证作为替换点而非虚构能力。
