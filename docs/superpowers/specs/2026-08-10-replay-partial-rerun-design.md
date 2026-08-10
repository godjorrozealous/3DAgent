# 复盘异议分类处理 + 局部重跑设计

日期：2026-08-10
状态：已确认

## 背景

### 现状流程

复盘确认轮收集异议后（`backend/agent_manager.py:543-585`）：

1. 结构化命令（调权/排除/恢复/复查）逐条经 `chat_stream` 下发 PLD——**每条都触发 PLD 的自动链式整轮重诊断**（`vendor/.../web.py:197-236`，排除/恢复/调权后无条件重跑）
2. 再发一条裸诊断消息整轮重跑收尾（`diagnose.py:182-215` 缓存命中的工具不重跑）

### 问题

1. **N 倍浪费**：N 条结构化异议 → N 次自动链式重诊断（每次全量 LLM 报告再生）+ 1 次收尾重跑
2. **回归（本次设计必须修复）**：会话隔离改造（`2026-08-10-session-isolation-design.md` Task 1）后，`get_or_create()` 不再复用 MODIFYING 会话。而 PLD 诊断结束态是 MODIFYING（`diagnose.py:276`），复盘②号收尾重跑（DIAGNOSE 意图）会新建会话——**丢失①号命令刚应用的权重/排除调整和工具缓存**，异议不落生、工具全量重跑。复盘首轮（实时会话 COMPLETED 被跳过）行为不变、是正确的
3. **还原浪费**：复盘结束权重还原（commit 0e9831f，`agent_manager.py:657-676`）逐条发恢复指令，每条同样触发一次自动链式整轮重诊断，而还原后根本不需要重诊断

### 用户目标模型

各智能体随时提要求 → 报告生成前统一处理：涉及取数的重取（单工具）、不涉及的只微调（调权）→ 所有结果一并交报告智能体重出 → 用户再确认（多轮，上限 5，保留现状循环）。

## 设计

### 1. PLD `/chat` 支持显式会话延续（修回归 + 支撑局部重跑）

文件：`vendor/diagnosis-agent/src/interfaces/web.py`

- 请求体新增可选字段 `session_id`
- 提供时：经 `session_manager.get(session_id)` 直接取该会话（跳过 `get_or_create` 与线路匹配），意图分类与命令路由不变；会话不存在 → 返回 error 事件
- 不提供时：行为完全不变（实时诊断走 `get_or_create`，隔离语义不受影响）
- DIAGNOSE 意图在 MODIFYING 会话上可执行（状态机允许 MODIFYING→DIAGNOSING，无需改状态机）

### 2. PLD `/chat` 支持延迟重诊断（消除 N 倍浪费）

文件：`vendor/diagnosis-agent/src/interfaces/web.py`

- 请求体新增可选字段 `defer_rediagnose: bool`（默认 false）
- 为 true 且意图为排除/恢复/调权时：执行命令后**跳过自动链式重诊断块**，会话停留 MODIFYING，等待编排方发起收尾诊断
- 默认 false：现状不变（司令直聊干预等既有路径不受影响）

### 3. backend `pld_client.chat_stream` 参数透传

文件：`backend/pld_client.py`

- 签名扩展：`chat_stream(message: str, *, session_id: str | None = None, defer_rediagnose: bool = False)`
- 两个参数仅在提供时放入请求 JSON

### 4. backend 复盘主循环改造

文件：`backend/agent_manager.py`

- **①结构化命令**：`chat_stream(cmd, defer_rediagnose=True)`——只落地命令（调权/排除/恢复），不触发 N 次整轮重诊断；recheck 命令本身即单工具重取（`recheck.py:46-62` 清缓存+重执行），天然满足「涉及取数就再取一次」
- **②收尾重跑**：`_stream_run` 在复盘异议循环内传 `session_id=self.session_id`——续跑同一会话：①落地的调整生效、缓存命中工具零调用、仅被 recheck 的工具重取，一次 LLM 报告再生
- **权重还原指令**（finally 块）：同样加 `defer_rediagnose=True`，消除还原期的整轮重诊断浪费
- **实时诊断与复盘首轮**：不传 `session_id`（保持新会话、技能清洁权重，行为不变）
- freeform 自由文本异议：现状保留（拼入②号重跑消息，由 PLD 意图分类器处理）
- 多轮确认循环（上限 5）、报告阶段 `modify_report`、权重快照+结束还原机制：全部保留

### 5. 前端

零改动。

## 效果

| | 现状（含回归） | 新设计 |
|---|---|---|
| N 条结构化异议 | N 次自动链式重诊断 + 1 次新会话全量重跑（调整丢失） | N 条命令落地（无重诊断）+ 1 次同会话局部重跑 |
| 工具执行 | 全部重取 | 仅被 recheck 的重取，其余缓存命中 |
| 权重还原 | M 条还原指令 → M 次整轮重诊断 | 0 次 |

## 测试

### vendor（pytest）

1. `/chat` 带 `session_id`：绕过 `get_or_create` 直接在指定会话执行（MODIFYING 会话可诊断续跑）；不存在 → error 事件
2. `/chat` 带 `defer_rediagnose: true` + 调权意图：权重已改、无自动链式重诊断事件、会话停留 MODIFYING
3. 不带新字段：自动链式与 `get_or_create` 行为与现状一致（兼容回归）

### backend（pytest，mock `pld_client.chat_stream`）

4. 复盘异议循环：①命令调用含 `defer_rediagnose=True`；②收尾 `_stream_run` 含 `session_id`
5. 实时诊断首轮与复盘首轮：不传 `session_id`/`defer_rediagnose`
6. 权重还原指令：含 `defer_rediagnose=True`

## 风险与说明

- `session_id` 续跑是显式编排通道，只由 backend 复盘循环使用；实时诊断入口不接触它，会话隔离语义（实时永远新会话+技能权重）不被削弱
- ①命令失败降级逻辑保留（降级为②号消息的自由文本后缀）
- ①与②之间用户放弃复盘 → 会话停留 MODIFYING → 由启动收口机制（session-isolation Task 2）兜底
