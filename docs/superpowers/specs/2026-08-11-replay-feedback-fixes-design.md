# 复盘反馈三问题修复设计(对话新数据升格override + 保存清单去重 + 比对补全)

日期:2026-08-11
状态:已确认

## 背景(用户实测反馈,2026-08-10 晚)

复盘流程实测暴露三个问题:

1. **对话新数据不生效**:对风偏智能体对话提出「风速15、绝缘子串风偏角10度」,司令重新诊断后风偏工具仍返回 18m/s/12°,重确认弹窗依旧展示旧数据——用户数据未生效
2. **保存策略数量歧义**:实测做了 3 项干预(雷电权重0.1、风速15、报告去掉第六章),保存提示却称 4 项,第 4 项「诊断要求:将雷电权重设置为0.1 数据是,风速15m/s」像是前两项的合并总结
3. **复盘比对差异不全**:策略差异标签只显示雷电权重0.1,数据修正与报告修改完全缺失

## 根因

### 问题 1

对话异议(`_replay_agent_chat` 登记 `decision="chat"`)经 `_objection_command`(agent_manager.py:737-739)只产出**自由文本后缀**,拼入②号重跑消息(584-587)。该文本仅能影响最终报告 LLM 的措辞,而:

- 被异议工具的子报告本轮**命中缓存未重跑**(局部重跑设计:仅 recheck 工具重取)
- 即使重跑,mock 数据平台固定返回 18m/s/12°,工具层无用户数据注入通道
- PLD 意图体系**没有「修改数据」意图**(命令仅 调权/排除/恢复/复查/改报告),用户逻辑①(数据发给智能体执行)无承载体

既有「手填数据(override)」机制即用户逻辑②的现成骨架:`value_overrides[tool]` 随 `tool_confirm_request`(453 行)与 `session_snapshot` 下发,弹窗显示「已改值」,重跑后缀指令报告 LLM 采纳修正值。

### 问题 2

`_intervention_items()`(975-994)合并两个来源:

- `intervention_trail` 逐项干预(权重0.1 / 风速15 / 去第六章)
- `objection_log` 中 `kind="diagnosis_objection"` 的条目——①②提报时把 N 项异议拼成一段合并文本记入(561-562),该合并条目即第 4 项「总结」,与逐项重复

注意:审核期用户手输的诊断流程异议(625-626)也是 `diagnosis_objection`,属真实独立条目,不能一刀切删除。

### 问题 3

前端 `CompareModal.vue` 实际读 `store.summaries.realtime/replay`(即 `report_summary` 事件),策略差异标签只计算 weights/excluded 差集。`report_summary` 事件不带 `overrides` 与报告修改信息;且因问题 1 未生效,风速差异本就不存在。`replay_compare` 事件(850-854)虽存在但组件未消费,不在本次改动范围。

## 设计

### 1. 对话异议升格为数据修正(方案 A,用户已选定)

文件:`backend/agent_manager.py`

- **`_replay_agent_chat`**:登记 chat 异议时同时执行 `self.value_overrides[tool] = message`(用户原文)——用户数据立即进入 HUD 快照与重确认弹窗「已改值」
- **`_objection_command` chat 分支**:
  - trail kind 记为 `chat_override`(与手填 `override` 区分来源)
  - `self.value_overrides[tool] = str(value)`(幂等兜底,与登记处一致)
  - suffix 改为与手填数据同构的强约束指令:`将{tool}相关数值修正为「{value}」(以用户提供数据为准,必须采纳)`
- **`_ITEM_LABELS` 与策略保存归类**:`_ITEM_LABELS` 新增 `chat_override` 标签(如 `{tool}数据修正(对话):{value}`),否则该干预会从保存清单消失;`save_strategy` 的 `custom_data`/`params` 归类(1038-1040 行)把 `chat_override` 视同 `override`
- **语义**:用户陈述即权威数据;同一工具多次对话异议,后者覆盖前者(dict 赋值天然语义)
- OBJECTION_KEYWORDS 门槛不变;非异议对话仍固定提示

文件:`frontend/src/components/AgentSessionModal.vue`

- 「已改值」行(211 行附近)样式从普通文本提为醒目块(amber 边框+底色),确保重确认时用户数据一眼可见

### 2. 保存清单去重

文件:`backend/agent_manager.py`

- ①②提报的合并日志条目(561-562)增加标记 `"auto_merged": True`
- `_intervention_items()` 处理 `diagnosis_objection` 时跳过 `auto_merged` 条目
- 审核期手输异议(625-626)不打标,照常进入清单
- 效果:实测场景保存提示 = 3 项,无「总结」条目

### 3. 比对补全

文件:`backend/agent_manager.py`(`_finish_run`,791-802)

- `report_summary` 事件增加两字段(实时/复盘均携带,实时侧通常为空):
  - `overrides`: `dict(self.value_overrides)`
  - `report_modifies`: `[t["text"] for t in self.intervention_trail if t["kind"] == "report_modify"]`

文件:`frontend/src/components/CompareModal.vue`

- 比对表格增加「数据修正」行:实时侧显示「无」,复盘侧格式化 `overrides`(如 `Wind:风速15,风偏角10°`),有差异标「生效」
- 策略差异标签增加:
  - override 标签(amber 色系):`{工具} 数据修正`
  - 报告修改标签(violet 色系):`报告修改:{文本}`

### 不做的事

- PLD(vendor)零改动:不新增「修改数据」意图/命令(方案 B 留作后续评估)
- `replay_compare` 事件及其消费端不动(组件本就未消费)
- OBJECTION_KEYWORDS、确认队列、多轮循环(上限5)、权重快照还原机制全部保留

## 测试

### backend(pytest)

1. 对话异议:`_replay_agent_chat` 后 `value_overrides[tool]` 含用户原文;`_objection_command` chat 分支返回 suffix 含「以用户提供数据为准」且 trail kind 为 `chat_override`
2. 同工具两次对话异议:后者覆盖前者
3. `_intervention_items`:含 auto_merged 合并条目 + 3 项逐项干预时,清单 = 3 项(逐项)且无「诊断要求」合并条目;审核期手输 diagnosis_objection 仍入清单
4. `_finish_run` 的 report_summary 事件含 `overrides` 与 `report_modifies` 字段

### 前端

无测试框架;`npm run build` 构建通过 + 人工核对弹窗/比对面板样式。

## 风险与说明

- chat 升格 override 把「提问类」对话异议也当数据处理——OBJECTION_KEYWORDS 已过滤纯闲聊,残余误判的影响仅是报告 LLM 收到一条「必须采纳」指令,属可接受副作用
- `value_overrides` 目前不随复盘结束清空(既有行为),升格后同样保留,HUD 持续显示用户数据直至下次诊断;不新增清理逻辑
- 问题 1 的彻底方案(子报告层面按用户数据重写)为方案 B,需 vendor 新增意图+命令+额外 LLM 调用,本次不实施
