# Changelog

本文件记录 EES Hospitality Agent 的可验证版本演进。日期以 GitHub PR/commit 时间为准；未从 GitHub 核实的具体日期不在此猜测。

## [MVP 1.2] — 2026-10-31 验收归档

### Added
- 规则与可选 LLM 结构化意图分类。
- 确定性业务路由与业务边界控制。
- Streamlit 多轮上下文线索。
- 71 条合成路由案例（E001–E071）。
- GitHub Actions 自动化测试与评测流程。

### Fixed
- 房型变更表达的识别覆盖。
- 房型变更政策咨询与明确执行请求的区分。
- 当前轮明确交易请求优先于上一轮 FAQ 上下文。

### Validation
- PR #1–#4 已合并；各 PR 的 CI 成功情况见对应 GitHub Actions 记录。
- 用户于 2026-10-31 确认，PR #4 修复后的线上多轮房型变更回归测试通过。
- 线上回归只覆盖用户实际执行的场景，不代表全部场景或生产流量准确率。

### Known limitations
- 不连接真实 PMS/OTA、订单、实时库存、工单、支付或消息发送系统。
- 不执行退款、取消、改期、换房；相关请求转人工。
- 评测集为合成数据，不代表真实业务准确率。
- 当前 MVP 1.2 聚合评测脚本尚未把案例中的 history 传给 route_question；E070 的上下文场景需由独立单元测试/线上回归补充验证，后续应修正评测执行器。

## PR / commit history

| PR | Summary | Merge commit |
|---|---|---|
| [#1](https://github.com/Sallyallia917/ees-hospitality-agent/pull/1) | MVP 1.2 hybrid classification, deterministic routing, context clues, evaluation and CI | `0c226dabd56894c38c6c518e39bf88607dd27fcf` |
| [#2](https://github.com/Sallyallia917/ees-hospitality-agent/pull/2) | Expand room-change expressions; add E063–E066 | `1618a0c5bc3ecec17ee482007efc410d7f47a4e3` |
| [#3](https://github.com/Sallyallia917/ees-hospitality-agent/pull/3) | Prioritize room-change policy questions; add E067–E069 | `36266d1f067e5aa10ffd10b46b42bbda7d6a1ef2` |
| [#4](https://github.com/Sallyallia917/ees-hospitality-agent/pull/4) | Prioritize current-turn contextual room-change execution; add E070–E071 | `5afafd34411a8a9b96418391abe6518ad5cf9dde` |
