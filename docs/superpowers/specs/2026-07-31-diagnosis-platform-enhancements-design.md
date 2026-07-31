# 诊断平台五项增强设计

日期：2026-07-31
状态：已获用户批准
分支：feature/command-center-enhancements

## 背景

电力线路跳闸诊断多智能体系统：FastAPI 后端（`backend/agent_manager.py` 编排，对接 PLDiagnosis 平台 localhost:5000）+ Vue3/Three.js 前端（3D 指挥室）。用户提出五项修改，已逐项确认交互方案。

## W1 复盘流程修复

### 问题
- 复盘异议不重跑：`_dispatch_objections`（agent_manager.py:436）只对异议工具逐条发聊天指令；报告异议仅转发 PLD 改文本（agent_manager.py:400-407），均不重新执行诊断。
- 空报告：缺少空结果兜底，报告为空仍进入"问异议"。

### 设计
后端：
- 每个智能体结果为空时标记 `empty: true`，随复盘确认请求广播；报告为空时不进入异议询问，标记异常由用户决定重跑。
- 报告确认弹窗的异议分两类：
  - **报告问题**：走现有逻辑，意见转发 PLD 改报告，不重跑诊断。
  - **诊断问题**：司令收集意见后重新执行完整复盘流程（携带用户意见作为上下文重走各智能体+报告），循环直到用户确认满意。
- 逐项暂停确认机制保持不变；确认弹窗对空结果显示"未返回结果"并提供「重跑该智能体」（只重跑该工具）。
- 所有确认/异议/意见写入 `objection_log`，供 W2（写 skill）与 W5（结果集）使用。

前端：
- ReportReviewModal：异议时先选类型（报告问题/诊断问题）+ 填意见。
- AgentSessionModal：空结果异常标记 + 单体重跑按钮。

## W2 策略生成对齐旧项目

### 问题
当前 `save_strategy`（agent_manager.py:669-722）只生成两节提示文本（权重+排除），激活后 AI 不知道应调用哪些工具。

### 设计（对齐旧项目 Cluade_PLDiagonsis-mcp-version 的 save_skill.py）
- 复制旧项目 `skills/comprehensive_diagnosis.md` → `backend/skills/` 作为基线（用户确认：不从 PLD 平台实时读取）。
- 新增 `backend/strategy_builder.py`，代码层确定性构建（不用 LLM）完整自包含 Markdown：
  1. YAML frontmatter（含触发描述：线路名+故障关键词即激活）；
  2. 基线正文全文；
  3. 更新 weights YAML 代码块；
  4. 工具调用策略表中排除工具标记 `**SKIP — excluded by user preference**`；
  5. 个性化章节：
     - 排除的工具与权重调整（旧项目已有）；
     - 报告修改意见 →「报告撰写规则（必须遵循）」（旧项目已有）；
     - **复盘异议 →「司令决策规则」**（驱动司令下次做相应决策）；
     - 参数修改轨迹（改值/调权）烘入，激活后无需重放；
     - 用户自定义数据输入的操作记录。
- `save_strategy` 改为构建完整 Markdown 后经 `pld_client.save_skill` POST 到 PLD `/api/skills`。
- 激活方式不变：`set_default_skill` 设全局默认 skill（用户确认保持现状）。

## W3 实时诊断完成时机

- 收到 PLD `complete` 且报告非空 → 本次诊断会话即完成。
- 复盘按钮不再依赖已保存策略（修改 TopBar.vue:43 的 `disabled` 条件，原为要求 `store.strategies.length`）。
- 保存策略变为纯可选动作；实时诊断运行期间禁聊/禁干预保持现状。

## W4 指挥室深色系改造

- 仅修改 `frontend/src/three/CommandRoom.js` 的材质与灯光：房间墙面/地板/弧形屏改藏蓝深灰系，屏幕改冷色发光，灯光压暗并加氛围点光，与前端深色 UI 主题统一。
- 不动布局、人物（军官/研究员）、席位交互；不引入 FBX（kongzhi.FBX 暂不使用）。

## W5 线路输入 + 排队 + 结果集

### 线路输入
- TopBar 下拉框改为纯自由文本输入（如"500kV雅湖线 #12杆塔 2026-07-31 14:23:05.123 跳闸"）。
- 后端 `DIAGNOSE_MESSAGE`（agent_manager.py:57）改为模板，用用户输入构造诊断指令。

### 诊断排队
- 后端新增诊断队列：运行中收到新诊断请求 → 入队（现状是直接拒绝，agent_manager.py:259-261）；当前诊断完成后自动开始下一个。
- 队列状态实时广播；前端新增队列显示区（当前诊断 + 等待中的线路列表）。

### 结果集（历史记录）
- 每次诊断（实时+复盘）持久化到 `backend/data/diagnosis_records.json`：线路、时间、实时报告、复盘报告、异议记录（objection_log）、关联策略。
- 前端主界面加视图切换（3D 指挥室 / 历史结果），结果页提供：
  - 关键字搜索；
  - 记录列表；
  - 详情展开：实时诊断报告、复盘报告、异议记录与保存的策略。

## 错误处理
- 智能体返回空：标记异常 + 允许单体重跑（W1）。
- 队列为空时完成事件不触发新诊断；排队期间允许取消等待中的任务。
- 结果集 JSON 文件损坏时后端启动跳过并报 warning，不阻塞服务。

## 测试
- 后端 pytest：strategy_builder 构建逻辑、诊断队列顺序执行与取消、结果持久化读写。
- 前端手动验证：复盘全流程（确认/两类异议/重跑）、排队执行、结果集搜索、深色系场景。

## 明确不做（YAGNI）
- 不解析/转换 kongzhi.FBX（用户决定暂不导入）。
- 策略激活不做按诊断选择（保持全局默认）。
- 结果集不用 SQLite（JSON 文件足够）。
