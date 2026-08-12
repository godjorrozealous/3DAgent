# 复盘反馈第二轮修复设计(无异议跨轮记忆 + data_overrides 通道 + LLM 意图分类 + 记录删除)

日期:2026-08-12
状态:已确认(四节设计均经用户逐条确认)

## 背景(用户实测反馈,2026-08-11)

复盘流程第二轮实测暴露四个问题:

1. **重复确认**:复盘第一轮对某工具选「无异议」后,后续轮次因其他工具异议触发重跑时,该工具仍再次弹出确认框要求重复选择
2. **用户数据不进报告**:对话提「风速15m/s、风偏角10度」后,重确认弹窗显示「以您提供的数据为准」,但最终报告与结论仍基于工具缓存的原始服务数据(18m/s/12°),结论错误
3. **对话意图僵硬**:对话框输入「调整权重0.1」不执行调权(上一轮「对话一律升格数据修正」改动误吞);输入「风速10m/s」必须加「数据修正」关键词才识别
4. **历史记录无法删除**:历史结果页缺少单条删除与多选批量删除能力

## 根因

### 问题 1

- `backend/agent_manager.py` 复盘主循环每轮 `confirm_decisions.clear()`(549 行),无任何跨轮记忆
- vendor `diagnose.py:220-224` 对命中缓存的工具也重发 result 事件 → backend 446-456 行对每个 result 一律广播 `tool_confirm_request`
- 已确认工具本身命中缓存不重取(局部重跑既有设计),但确认环节无对应豁免

### 问题 2

- 复盘异议 suffix 仅拼入②号重跑消息,只到达**规划 prompt**(diagnose.py:119-120)
- `ReportComposer.compose`(report_composer.py:33-97)的 prompt 仅含 tool_outputs(缓存原始数据)、fault_context、action_log、weights、skill——用户修正数据**从未进入报告生成环节**
- 结论摘要(```conclusion 块)与报告同一 LLM 产出,数据不进 prompt 则结论必然沿用旧数据

### 问题 3

- `OBJECTION_KEYWORDS` 关键词门槛(agent_manager.py:64):「风速10m/s」无关键词 → 固定提示拒绝
- 上一轮改动(chat 一律升格 override):「调整权重0.1」命中「权重」关键词登记 chat 异议 → 变成数据修正「修正为『调整权重0.1』」而非调权

### 问题 4

- `backend/records.py` 仅 list/get/create/update 系函数,无 delete;WS 仅 list_records/get_record 路由;`HistoryView.vue` 无选择与删除 UI
- 存储为单文件 `backend/data/diagnosis_records.json`,删除实现简单

## 设计

### 1. 无异议跨轮记忆(纯 backend)

文件:`backend/agent_manager.py`

- 新增实例属性 `self.ok_tools: set[str]`,`run_diagnosis` 开始时清空(每次新诊断/复盘从零记忆)
- 用户在确认弹窗选「无异议」(`decision == "ok"`)→ `self.ok_tools.add(tool)`
- 重跑 `_stream_run` 收到 result 事件时,若 `tool in self.ok_tools`:
  - 自动登记 `self.confirm_decisions[tool] = {"decision": "ok"}`
  - **不广播 `tool_confirm_request`**(HUD agent 状态/结果事件照常下发,仅跳过弹窗)
- 用户对已 ok 工具提出异议(对话异议或弹窗改选)→ `self.ok_tools.discard(tool)`,恢复正常确认流
- 效果:第 2 轮起仅询问「未曾无异议」的工具;与缓存重取的豁免语义一致

### 2. 结构化 data_overrides 通道(vendor + backend,用户选定方案 B)

**vendor/diagnosis-agent**(四处小改):

1. `src/core/models.py` `DiagnosisSession` 新增字段:
   `data_overrides: Dict[str, str] = Field(default_factory=dict)`(随 sessions.json 持久化)
2. `src/interfaces/web.py` `/chat`:请求体接受 `data_overrides: dict[str,str]`(可选,缺省 None 不变);非空时合并进 `session.data_overrides`(后者覆盖前者)
3. `src/application/commands/diagnose.py`:`DiagnoseCommand.execute` 调 `report_composer.compose(...)` 时传 `data_overrides=session.data_overrides or None`
4. `src/domain/report_composer.py`:
   - `compose()` 新增可选参数 `data_overrides: Optional[Dict[str, str]] = None`,透传 `_build_prompt`
   - `_build_prompt` 在「## 诊断工具输出」**之前**注入:
     ```
     ## 用户提供的修正数据(权威数据,必须采纳,优先级高于工具输出)

     - {tool}: {value}
     ```
     并附指令:涉及该工具的章节与结论必须以此数据为准,若与工具输出冲突以用户数据为准

**backend**:

- `pld_client.chat_stream` 新增可选参数 `data_overrides: dict | None = None`,非空时写入请求体
- 复盘②重跑消息:`data_overrides=dict(self.value_overrides)` 随 session_id 一并发送
- 确认弹窗显示不变(原始服务数据 + 醒目「以您提供的数据为准」块,既有)

**效果**:报告正文与结论摘要(同一 LLM 产出)强制基于用户数据;override 持久化于会话,多轮重跑持续生效

### 3. LLM 意图分类(vendor 新增纯分类端点 + backend 重接)

**vendor/diagnosis-agent**:

- 新增 `POST /api/classify`,请求 `{message: str, session_id?: str}` → 响应 `{intent_type, confidence, parameters}`
- 实现:复用既有 `container.intent_classifier.classify(message, session)`(纯 LLM 调用,零会话变更、零命令执行);session_id 存在时取会话作上下文(提升参数提取准确率),不存在/取不到时传 None
- 从根上杜绝「转发 PLD 劫持活跃会话」风险

**backend**:

- `pld_client` 新增 `async def classify(message: str, session_id: str | None = None) -> dict`(普通 POST,非流式)
- `_replay_agent_chat` 重写:
  - **删除 OBJECTION_KEYWORDS 门槛**(关键词列表一并删除)
  - 调 `classify(message, session_id=self.session_id)`,按 `intent_type` 映射:
    | intent_type | 映射 |
    |---|---|
    | adjust_weight | `confirm_decisions[tool] = {"decision": "adjust", "value": weight}`;tool 取 `parameters.tool_name`,缺省/未识别用对话所在智能体工具;weight 缺省则按数据修正兜底 |
    | recheck_tool | `{"decision": "recheck"}`(tool 同上规则) |
    | exclude_tool | `{"decision": "exclude"}`(tool 同上规则) |
    | modify_report | `_trail("report_modify", text=message)`,登记 chat 确认决策 |
    | general / diagnose / 其他未列意图 | **数据修正**:`value_overrides[tool] = message` + `confirm_decisions[tool] = {"decision": "chat"}`(即既有 chat_override 通道;在智能体对话框发言,语境即针对该工具数据) |
    | complete / save_strategy / load_strategy / list_sessions / switch_session / include_tool | 固定提示「复盘对话中请使用界面按钮完成该操作」 |
  - 分类调用异常(PLD 不可达等)→ 按 general 兜底为数据修正(保持上一轮行为,不引入新失败面)
- `_objection_command` chat 分支(chat_override trail + 强约束 suffix)**保留不动**
- 代价:每次对话异议 +1 次 LLM 调用(用户已确认接受)

### 4. 记录删除(backend + frontend)

**backend**:

- `records.py` 新增 `delete_records(ids: list[int]) -> int`:过滤重写 JSON,返回实际删除条数
- `agent_manager.py` WS 路由:`{"type": "delete_records", "ids": [...]}` → 调 `delete_records` → 向客户端发送最新记录列表(复用既有 records_list 消息形态)
- ids 为空/全不存在 → 删除数 0,照常回发列表(幂等,不报错)

**frontend** `HistoryView.vue`:

- 列表行首复选框;行内删除按钮(单删)
- 顶部出现「删除选中(n)」按钮(仅当有勾选)
- 删除前弹自定义确认框:列出将删记录的线路名+时间,「确认删除/取消」
- 删除后:若正在查看详情的记录被删 → 清空详情 pane;勾选态清空;列表随广播刷新
- `ws.js` 新增 `deleteRecords(ids)` 发送封装

## 不做的事

- 缓存工具的 result 事件仍由 vendor 重发(diagnose.py:220-224 不动)——豁免在 backend 确认环节实现,vendor 行为不变
- 工具子报告层面按用户数据重写(仍留作后续方案 B 评估;本次仅报告生成层采纳)
- `replay_compare` 事件及其消费端不动
- 确认队列、多轮循环(上限5)、权重快照还原、chat_override 既有测试语义全部保留
- 实时诊断路径不传 data_overrides(realtime 侧 value_overrides 通常为空,行为不变)

## 测试

### backend(pytest)

1. **ok_tools 跨轮记忆**:第一轮对 wind 确认 ok → 模拟重跑 result 事件 → 不广播 tool_confirm_request 且 confirm_decisions 自动 ok;ok 后提异议 → 移出 ok_tools,下轮照常询问
2. **重跑透传**:② 重跑 chat_stream 调用收到 `data_overrides == dict(value_overrides)`
3. **意图映射**(mock pld_client.classify):
   - 「调整权重0.1」→ adjust_weight → confirm_decisions 为 adjust,**不写** value_overrides
   - 「风速10m/s」→ general → value_overrides 写入 + decision chat
   - 「去掉第六章」→ modify_report → report_modify trail
   - classify 抛异常 → 兜底数据修正
4. **delete_records**:删单条/多条/不存在 id,返回条数与文件内容正确;WS delete_records 路由回发最新列表

### vendor(pytest)

5. `/api/classify`:mock intent_classifier,验证请求/响应形态、session_id 上下文传递、取不到会话时 None 兜底
6. `/chat` 带 `data_overrides`:合并进 session.data_overrides 并持久化;缺省不传时行为不变
7. `ReportComposer._build_prompt`:含 data_overrides 时 prompt 含「权威数据」块且位于工具输出之前;不含时无该块(纯函数直测)

### 前端

无测试框架;`npm run build` 构建通过 + 人工核对删除交互与复盘弹窗豁免

## 风险与说明

- general 兜底为数据修正:在复盘智能体对话框内,用户发言语境即针对该工具;残余误判影响仅为报告 LLM 收到一条「必须采纳」指令,可接受
- data_overrides 随会话持久化,复盘结束后不清空(与 value_overrides 既有行为一致);下次诊断新建会话不携带
- /api/classify 与 /chat 共用 intent_classifier,GLM 不可达时 classify 内部 fallback 为 general(既有异常处理),backend 再兜底数据修正,链路不中断
- ok_tools 仅存内存,不持久化;页面刷新后记忆清零(与新复盘从零记忆语义一致)
