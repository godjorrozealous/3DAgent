# 指挥室增强设计：布局优化 + 报告摘要 + 模板/策略管理 + 交互式复盘

日期：2026-07-27
状态：已获用户分节批准（布局/审核员+司令员/复盘方案 A）

## 背景

输电线路智能诊断全息指挥室（Vue3 + Three.js 前端 :5173，FastAPI 编排后端 :8100，PLDiagnosis :5000，MCP 诊断服务 :8001-8004，Mock 数据平台 :8000）。用户提出 6 项修改意见，经四轮澄清（16 个决策点）形成本设计。

## 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 3D 缩小方式 | 两侧面板加宽 + 3D 视角拉远（两者都做） |
| 复盘工具确认 | 阻塞式逐步确认，仅复盘中（首轮实时诊断不弹） |
| 比对弹窗内容 | 摘要指标级对比 |
| 策略信息展示 | HUD 面板 + 3D 标牌（两者都要） |
| 策略激活作用域 | 全局默认（POST /api/skills/default） |
| 模板激活行为 | 激活即重整报告 |
| 模板管理 UI | 嵌在审核员直聊弹窗 |
| 干预界定 | 仅操作性干预（排除/恢复/调权/复查/改报告/模板/策略切换） |
| 异议处理 | 三类操作（recheck/exclude/adjust_weight）+ 手动改值 |
| 手动改值同步 | 展示 + 报告同步改（自动发 modify_report） |
| 报告审核确认 | 循环确认直到满意 |
| 双摘要排布 | 上下双摘要卡 |
| 保存提醒形式 | 单独弹窗，位于指挥部中部（司令员席位上方） |
| 摘要卡字段 | 上一项目同款（线路/电压/故障时间/类型/置信度 + 操作记录） |
| 复盘策略保存 | 询问保存 + 差异标签 |

## 1. 布局与事件流

### 1.1 面板加宽 + 3D 缩小
- 左侧面板 280px → 340px；右侧报告面板 320px → 460px（容纳双摘要卡）。
- 3D 相机默认视角拉远约 25%，场景内容/交互不变，用户仍可自由缩放。

### 1.2 事件流不再遮挡状态矩阵
- 左侧面板内：事件流 `flex-1 min-h-0 overflow-y-auto`（内部滚动，新消息自动滚底）；状态矩阵固定高度钉在底部。

## 2. 报告栏：线路标识 + 双摘要卡 + 查看报告弹窗 + 比对

- 顶部线路标题行：「±800kV 雅湖线 · 2025-05-08 19:46 跳闸」（取自摘要 line_name/fault_time）。
- 上下两张摘要卡：上「实时诊断」、下「复盘诊断」（无复盘时占位"尚未复盘"）。
  - 字段：线路名称/电压等级/故障时间/故障类型/置信度% + 操作记录（action_log）标签。
  - 每卡「查看报告」按钮 → 中央遮罩弹窗展示完整 markdown，点 × 或遮罩关闭。
- 两卡均有结果时底部出现「比对」按钮 → 弹窗：指标级对比表（故障类型/置信度/主诊断工具/权重/排除列表，差异项高亮「生效」）+ 两策略差异标签。现有 ReplayPanel 并入此弹窗。
- 数据流：后端 `run_history` 已存每轮 summary+report；诊断 `complete` 时推送 `report_summary` 事件（`kind: realtime|replay`，含 summary/report/weights/excluded_tools/action_log），前端分卡渲染。

## 3. 报告审核智能体

### 3.1 章节调整
- 审核员直聊输入章节修改指令（如"删除第三章"）→ 后端以 modify_report 意图转发 PLD → 推送新报告全文 + 更新摘要卡 → 记入 action_log，计入人工干预。

### 3.2 模板管理（嵌在审核员直聊弹窗下半部）
- 模板列表（名称 + 「当前激活」徽标），每模板带「激活」「删除」。
- 「+ 上传模板」：.md/.docx/.pdf，经后端转发 PLD `POST /api/templates/upload`（自动解析）。
- **激活即重整**：后端依次调 `POST /api/templates/activate` + 自动向 PLD 发 modify_report 指令（"请严格按当前激活模板的章节结构重整报告"）→ 报告面板刷新。模板变更计入人工干预。
- 后端新增 WebSocket 消息：`list_templates` / `upload_template`（base64 文件）/ `activate_template` / `delete_template`，及 REST 备选 `POST /api/templates/upload`（multipart 转发）。

## 4. 司令员

### 4.1 策略筛选/激活（嵌在司令员直聊弹窗下半部）
- 策略列表来自 PLD `GET /api/skills`（名称/描述/来源：系统|用户自定义）。
- 「激活」→ PLD `POST /api/skills/default`（全局默认策略）；已激活显示「已激活」。
- 「重置默认」→ `POST /api/skills/reset`（默认权重 + 清空排除）。
- 策略切换计入人工干预。

### 4.2 策略信息展示（双份）
- HUD：顶栏下方紧凑信息卡——当前策略名 + 排除工具（红标签）+ 非默认权重（琥珀标签）。
- 3D：司令员席位旁全息浮牌（canvas 纹理），显示策略名 + 排除/权重摘要，随 session_snapshot 实时更新。

### 4.3 保存策略提醒弹窗
- 诊断 complete 时后端检查本轮 action_log：有操作性干预 → 推送 `prompt_save_strategy` 事件（含干预条数）。
- 前端在司令员席位上方（指挥部中部）弹提醒窗：「本轮存在 N 项人工干预，是否保存为诊断策略？」+「保存策略」「忽略」按钮。
- 「保存策略」走现有保存流程（写入 PLD 技能库）→ 策略列表自动刷新。无干预不弹。

## 5. 复盘重跑交互流（方案 A：结果级阻塞）

技术约束：PLD 诊断为单条 SSE 流，无法在工具间暂停服务端执行。阻塞体现在前端确认队列 + 异议后重诊断。

### 5.1 工具结果确认
- 仅复盘（replay）流程启用。
- 每个工具 `result` 事件到达 → 立即在指挥部中部弹确认窗：工具名/倾向/置信度/首条证据 +「无异议」「有异议」。
- 弹窗排队逐个强制处理；用户未处理完所有弹窗，复盘不进入审核环节。
- 「有异议」选项：
  - 重新检查 → 记为 `recheck_tool` 指令；
  - 数据不对去掉 → `exclude_tool`；
  - 调整权重 → `adjust_weight`（输入新权重）；
  - 手动改值 → 输入新数值文本：记入覆盖层（前端席位/摘要展示改后值）+ 自动生成 modify_report 指令（"将 {tool} 的 {字段} 改为 {值}"）。
- 所有确认完成后，后端把异议指令逐条下发 PLD（每条可能触发重诊断，需等会话离开 diagnosing 再发下一条，复用 `_wait_pld_idle`）；最终重诊断结果作为复盘报告。

### 5.2 报告审核循环
- 复盘报告生成 → 弹「报告是否符合要求？」（附「查看报告」）→「有意见」输入修改指令 → modify_report → 重新展示并再次询问，循环至「符合要求」。

### 5.3 司令员整合 + 策略保存 + 比对
- 确认完毕 → 司令员签发复盘报告 → 复盘摘要卡更新。
- 本轮有干预 → 弹保存提醒（同 4.3）；保存后复盘卡显示与实时策略的差异标签。
- 报告栏「比对」按钮可用（见 2）。

## 6. 后端改动清单（backend/）

- `pld_client.py`：新增 list_skills / set_default_skill / reset_skills / list_templates / upload_template（multipart）/ activate_template / delete_template / get_default_skill。
- `agent_manager.py`：
  - complete 时推送 `report_summary`（区分 realtime/replay，含 action_log——需 PLD 会话接口提供，已确认 `/api/sessions/<id>` 返回 action_log）；
  - 干预追踪：本轮 action_log 增量判断 → `prompt_save_strategy`；
  - 复盘模式：result 事件 → 推送 `tool_confirm_request` 并登记待确认项（SSE 流继续消费，不暂停——PLD 服务端无法中途暂停）；
  - 跟踪前端逐条返回的 `tool_confirm_response`；当 SSE 流 complete **且**所有确认均已处理 → 顺序下发异议指令（每条之间复用 `_wait_pld_idle` 等会话离开 diagnosing）；
  - 审核确认循环状态机（`report_review_request` / `report_review_response`）；
  - 模板/策略 WS 消息转发；
  - 手动改值覆盖层存储（`value_overrides`，随 session_snapshot 下发）。

## 7. 前端改动清单（frontend/src/）

- `App.vue`：左 340px / 右 460px；新增保存提醒弹窗、工具确认弹窗、审核确认弹窗（均指挥部中部居中）。
- `three/CommandRoom.js`：相机拉远 25%；司令员席位旁全息策略浮牌（session_snapshot 驱动更新）。
- `components/EventStream.vue`：固定滚动区，不再挤压状态矩阵。
- `components/ReportViewer.vue`：重写为 线路标题 + 双摘要卡 + 查看报告弹窗 + 比对按钮。
- `components/ReplayPanel.vue`：并入比对弹窗（指标对比 + 策略差异标签）。
- `components/ChatModal.vue`：审核员目标时下半部嵌模板管理区块；司令员目标时嵌策略管理区块 + 顶部策略信息。
- 新增 `components/ConfirmToolModal.vue`（工具结果确认 + 异议表单）、`components/SavePromptModal.vue`（保存策略提醒）、`components/ReportModal.vue`（查看报告弹窗）。
- `store.js`：summaries{realtime,replay}、templates、skills、confirmQueue、savePrompt、valueOverrides。
- `ws.js`：新事件 handler + 发送方法（confirm 响应、模板/策略操作、审核确认响应）。

## 8. 错误处理

- PLD 调用失败（429/超时）：对应弹窗显示错误并重试按钮；异议指令下发失败记入事件流并继续下一条。
- 复盘中途 PLD error 事件：复盘终止，确认队列清空，状态复位，事件流提示。
- 模板上传格式不符：PLD 返回错误透传到审核员弹窗。

## 9. 验证

- E2E 脚本（/tmp）：布局与事件流为纯前端，截图验证；复盘交互流用 WebSocket 脚本模拟确认/异议/审核循环，断言 report_summary(realtime+replay)、prompt_save_strategy、比对数据齐备。
