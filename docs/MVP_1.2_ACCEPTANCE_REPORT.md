# EES Hospitality Agent — MVP 1.2 验收报告

- 版本：MVP 1.2（Hybrid Intent Classification & Deterministic Routing）
- 验收记录日期：2026-10-31
- 验收结论：**当前已知范围内通过**
- 线上回归结论：用户于本次对话确认，修复后的线上测试已通过
- 项目性质：独立原型；门店政策、订单及评测样本均为模拟数据

## 1. 版本目标

在 MVP 1.1 的业务路由原型上，增加规则与可选 LLM 协同的意图理解能力、多轮上下文线索和确定性业务路由，使系统能够区分公共知识咨询、订单相关咨询、实时库存询问、交易请求、服务请求、投诉和安全事件，并按数据依赖与风险边界给出相应处理路径。

## 2. 本版本交付范围

- 规则分类 + 可选 LLM 结构化意图分类；LLM 不负责授权或执行。
- 确定性业务路由，覆盖知识库回答、订单上下文不可用、人工升级、交易转人工、服务转人工及安全指引等动作。
- Streamlit 会话历史作为多轮上下文线索。
- 规则配置、单元/回归测试、合成评测集及 GitHub Actions 自动化检查。
- 交易请求只转人工，不修改订单、不退款、不创建真实工单。

## 3. 业务边界与风险控制

| 场景 | MVP 1.2 处理方式 | 当前能力边界 |
|---|---|---|
| 公共门店政策/设施 | RAG 回答 | 必须有知识库证据；样例知识为模拟数据 |
| 个人订单/房型/权益 | 标记订单依赖 | 未连接订单系统，不返回真实订单信息 |
| 实时房态/车位 | 人工核实 | 不以静态 FAQ 代替实时库存 |
| 退款/取消/改期/换房 | 交易转人工 | 不执行交易或订单变更 |
| 送物/维修/清洁 | 服务转人工 | 不声称已创建工单 |
| 投诉 | 人工升级 | 不声称已完成处理 |
| 安全事件 | 安全指引/优先升级 | 不由 LLM 覆盖确定性安全边界 |

补充原则：
- 用户自述拥有订单不等于身份认证。
- 即使界面状态显示 VERIFIED，本版本也没有订单查询工具。
- LLM 只提供意图理解建议；授权、数据依赖、风险处置和执行边界由确定性逻辑控制。
- 只有真实工具明确返回成功，系统才可以宣称操作完成。

## 4. 测试与验收证据

### 4.1 自动化测试

仓库中的 GitHub Actions workflow：`.github/workflows/tests.yml`，工作流名称为 `MVP 1.2 checks`，使用 Python 3.12，执行：

1. 安装 `requirements.txt`
2. `pytest -q`
3. RAG evaluation：`python -m evals.run_evaluation`
4. MVP 1.1 routing regression：`python -m evals.run_routing_evaluation`
5. MVP 1.2 hybrid routing evaluation：`python -m evals.run_mvp_1_2_evaluation`

合成路由案例文件：`evals/mvp_1_2_cases.json`，当前包含 E001–E071，共 71 条案例。覆盖公共知识、订单依赖、实时库存、交易请求、服务请求、投诉、安全事件、房型变更表达和政策问句等类别。

**证据边界：** 71 是评测集案例数量，不等同于 71 条全部通过。评测脚本会在运行时生成 `reports/mvp_1_2_evaluation.json` 和 `reports/mvp_1_2_evaluation.md`；本次归档未取得该次运行的报告文件及具体通过数，因此不在此报告中填写准确率或 71/71 通过率。历史 PR 的 CI 成功记录以各 PR 的 GitHub Actions 记录为准。

### 4.2 关键缺陷修复与回归

- 房型变更表达：补充“改为双床”“换成大床”等表达，避免执行请求落入普通咨询。
- 政策问句优先级：区分“酒店允许换房型吗”（政策咨询）与“帮我把大床房换为双床房”（执行请求）。
- 多轮上下文：当前轮明确的交易执行意图优先于上一轮公共 FAQ 上下文。
- 用户线上回归：用户此前报告第二轮房型变更请求仍被识别为公共 FAQ；经 PR #4 修复后，用户于 2026-10-31 确认线上测试通过。

线上回归通过仅表示用户实际测试的场景在当前线上版本中表现符合预期，不代表所有表达、所有会话或真实酒店业务流量均已验证。

## 5. 版本演进记录

| PR | 变更 | 合并 Commit |
|---|---|---|
| [#1 MVP 1.2 hybrid classification and routing](https://github.com/Sallyallia917/ees-hospitality-agent/pull/1) | 引入规则 + 可选 LLM 分类、确定性路由、多轮上下文、合成评测与 CI | `0c226dabd56894c38c6c518e39bf88607dd27fcf` |
| [#2 Fix room type change intent routing](https://github.com/Sallyallia917/ees-hospitality-agent/pull/2) | 补充房型变更表达，增加 E063–E066 | `1618a0c5bc3ecec17ee482007efc410d7f47a4e3` |
| [#3 Prioritize room-change policy questions](https://github.com/Sallyallia917/ees-hospitality-agent/pull/3) | 政策询问优先识别，保留明确执行请求的交易转人工路径；增加 E067–E069 | `36266d1f067e5aa10ffd10b46b42bbda7d6a1ef2` |
| [#4 Prioritize contextual room-change execution requests](https://github.com/Sallyallia917/ees-hospitality-agent/pull/4) | 当前轮交易意图优先于上一轮 FAQ；增加 E070–E071 | `5afafd34411a8a9b96418391abe6518ad5cf9dde` |

## 6. 已知限制与待补证据

1. **评测报告数值待归档：** 需要在当前主分支运行评测脚本，保存实际总数、通过数、失败数及报告文件。
2. **多轮评测执行器待核查：** 当前 `evals/run_mvp_1_2_evaluation.py` 读取案例中的输入，但调用 `route_question(c["input"])` 时没有把案例中的 `history` 传入。因此 E070 虽然在 JSON 中定义了 history，聚合评测脚本本身并未真正执行该上下文；应依靠独立多轮单元测试/线上回归，或在后续小改动中修正评测执行器。
3. **线上版本标识待增强：** 当前没有已归档的线上 commit SHA / build ID 截图，无法仅凭用户测试结果证明当时运行的线上构建对应哪个 commit。
4. **真实业务数据未接入：** 无真实 PMS/OTA、订单、实时库存、工单、支付或消息发送集成。
5. **真实业务效果未测量：** 没有真实客服流量、线上准确率、人工节省、客户满意度或经营指标数据。

## 7. 验收结论

MVP 1.2 可作为 EES 项目的**规则与可选 LLM 混合意图分类、确定性业务路由及风险边界原型**版本基线。根据已记录的 PR/CI 历史和用户本次线上回归确认，当前已知验收范围通过。

该结论不代表生产级系统验收，也不代表真实酒店业务效果。进入 MVP 1.3 前，建议先补齐本报告第 6 节中的评测数值与版本可观测性证据，并修正/补足多轮评测执行器的上下文传递。
