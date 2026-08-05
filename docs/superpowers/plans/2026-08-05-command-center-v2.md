# 指挥中心 v2 实现计划（策略管理 + 复盘对话路由 + 异议重跑加固）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 策略管理页面（多选删除）+ 保存策略子集勾选 + 复盘对话关键词路由与等待态 + 异议结构化落地后裸诊断重跑 + 空完成守卫。

**Architecture:** 后端 FastAPI(WebSocket) 转发 PLDiagnosis(SSE)；复盘异议拆为结构化 PLD 意图命令（权重/排除/重查/时间段，逐条单独下发）+ 自由文本后缀（改值/对话异议），随后裸诊断消息触发整轮重跑，无异议工具走 PLD 缓存复用。前端 Vue3 新增策略管理视图，对话框增加忙碌横幅/禁用/可关闭。

**Tech Stack:** Python 3.11 / FastAPI / httpx / pytest+pytest-asyncio；Vue 3 + Vite + Tailwind。

**Spec:** `docs/superpowers/specs/2026-08-05-command-center-v2-design.md`

## Global Constraints

- 后端测试命令：`cd backend && .venv/bin/python -m pytest tests/ -q`（必须 3.11 venv，系统 python3.9 跑不动）
- 提交风格：`type(scope): 中文描述`，用 `git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit`
- 前端无测试设施：前端任务以 `cd frontend && npm run build` 验证编译通过，行为靠后端事件协议测试保证
- PLD 平台（vendor/diagnosis-agent，:5000）不在本计划修改范围；仅用其既有 API：`GET/POST/DELETE /api/skills...`、`POST /chat`
- 协议命名沿用 snake_case 事件类型；后端广播事件通过 `self.broadcast(...)`
- 复盘主循环最多 5 轮；报告审核等待超时 1800s 按满意结束（现状不变）

---

### Task 1: 后端复盘重跑 v2——结构化命令先落地 + 裸诊断重跑 + 空完成守卫

**Files:**
- Modify: `backend/agent_manager.py`（`_stream_run` complete 分支 ~L405-425；`run_diagnosis` 复盘主循环 ~L465-520；`_objection_text` ~L541-562）
- Test: `backend/tests/test_replay_rerun_v2.py`（新建）
- Test: `backend/tests/test_replay_flow.py`（既有断言按新行为更新）

**Interfaces:**
- Consumes: 现有 `_objection_text(tool, d) -> str`（将被替换）
- Produces:
  - `_objection_command(tool: str, d: dict) -> tuple[str, str]`：返回 `("cmd", 文本)`（结构化 PLD 意图命令）或 `("suffix", 文本)`（拼入重跑消息后缀）；空决策返回 `("", "")`。decision 映射：recheck→cmd `重新检查{tool}`；time_range→cmd `重新检查{tool}，查询时间段{value}`；exclude→cmd `排除{tool}`；weight→cmd `将{tool}权重调整为{value}`；override→suffix `将{tool}相关数值修正为{value}`（并记录 `value_overrides`）；chat→suffix `str(value)`
  - `_stream_run` 空完成时返回 `{"_invalid": True}`，不更新 `last_report`/`run_record`
  - 重跑前广播 `confirm_queue_clear` 复位前端确认状态

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_replay_rerun_v2.py`：

```python
"""复盘重跑 v2：结构化异议单独下发 + 裸诊断消息重跑 + 空完成守卫。"""
import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS

RESULT_OK = {"event_type": "result", "payload": {
    "tool": "LightningDiagnosisTool",
    "output": {"structured_data": {"fault_type": "雷击-绕击", "confidence": 0.9,
                                   "evidence": ["证据A"]}, "raw_text": "raw"}},
    "session_id": "s1"}
COMPLETE = {"event_type": "complete", "payload": {
    "report": "# 复盘报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
    "session_id": "s1"}
COMPLETE_EMPTY = {"event_type": "complete", "payload": {"report": "", "summary": {}},
                  "session_id": "s1"}
SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls, streams):
    iters = [iter(s) for s in streams]

    async def fake_stream(msg):
        calls.append(msg)
        for e in iters.pop(0):
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_weight_objection_structured_cmd_then_bare_rerun(monkeypatch):
    """权重异议：先发独立命令，再发裸诊断消息（不带异议后缀）重跑。"""
    calls = []
    # 流1=首轮诊断, 流2=weight命令(adjust_weight 完成), 流3=裸诊断重跑
    streams = [
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "complete", "payload": {"message": "ok"}, "session_id": "s1"}],
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
    ]
    mgr = make_mgr(monkeypatch, calls, streams)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "weight", "value": 0.1})
        await asyncio.sleep(0.4)
        # 重跑轮确认（无异议）
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    assert calls[1] == "将LightningDiagnosisTool权重调整为0.1"
    assert calls[2] == calls[0]                      # 裸诊断消息
    assert "复盘异议" not in calls[2]
    # 重跑前复位了前端确认状态
    assert any(e["type"] == "confirm_queue_clear" for e in ws.events)


async def test_empty_complete_keeps_last_valid_report(monkeypatch):
    """重跑 complete 无报告（PLD 误判意图）：保留上轮报告，审核询问 empty=False。"""
    calls = []
    streams = [
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, RESULT_OK, COMPLETE],
        [{"event_type": "complete", "payload": {"message": "ok"}, "session_id": "s1"}],
        [{"event_type": "start", "payload": {}, "session_id": "s1"}, COMPLETE_EMPTY],
    ]
    mgr = make_mgr(monkeypatch, calls, streams)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "weight", "value": 0.1})
        await asyncio.sleep(0.4)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    assert mgr.last_report == "# 复盘报告"
    reviews = [e for e in ws.events if e["type"] == "report_review_request"]
    assert reviews and reviews[-1]["empty"] is False
    assert any("未产出报告" in e.get("message", "") for e in ws.events if e["type"] == "log")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_replay_rerun_v2.py -v`
Expected: FAIL（当前行为：异议拼后缀重跑；空 complete 覆盖 last_report）

- [ ] **Step 3: 实现 `_stream_run` 空完成守卫**

`backend/agent_manager.py` `_stream_run` 的 `elif etype == "complete":` 分支，在 `report = payload.get("report") or report_buf` 之后插入守卫，空报告直接返回，不写 `last_report`/`run_record`/广播：

```python
            elif etype == "complete":
                report = payload.get("report") or report_buf
                summary = payload.get("summary", {})
                if not str(report or "").strip():
                    # PLD 意图误判（重跑消息被分类为 adjust_weight 等）：空完成不算有效
                    # 诊断轮——不覆盖上一轮有效报告/摘要，不进入逐项确认与报告审核
                    await self.log("commander",
                                   "⚠ 本轮诊断流未产出报告（PLD 未识别为完整诊断），保留上一轮有效结果。")
                    return {"_invalid": True}
                self.last_report = report
                ...（其后既有逻辑不变）
```

- [ ] **Step 4: 替换 `_objection_text` 为 `_objection_command`**

整个方法替换为：

```python
    def _objection_command(self, tool: str, d: dict) -> tuple[str, str]:
        """复盘异议 → ("cmd", 独立 PLD 意图命令) 或 ("suffix", 重跑消息后缀文本)。

        结构化异议走独立命令（单一意图，PLD 不会误判为诊断/非诊断）；
        自由文本/改值类拼入【复盘异议】后缀随裸诊断消息下发。
        同时记录干预轨迹（供策略保存/快照）。
        """
        decision, value = d["decision"], d.get("value")
        if decision == "recheck":
            self._trail("recheck", tool)
            return "cmd", f"重新检查{tool}"
        if decision == "time_range":
            self._trail("time_range", tool, value)
            return "cmd", f"重新检查{tool}，查询时间段{value}"
        if decision == "exclude":
            self._trail("exclude", tool)
            return "cmd", f"排除{tool}"
        if decision == "weight":
            self._trail("weight", tool, value)
            return "cmd", f"将{tool}权重调整为{value}"
        if decision == "override":
            self._trail("override", tool, value)
            self.value_overrides[tool] = str(value)
            return "suffix", f"将{tool}相关数值修正为{value}"
        if decision == "chat":
            self._trail("chat", tool, value)
            return "suffix", str(value or "")
        return "", ""
```

- [ ] **Step 5: `run_diagnosis` 复盘主循环的异议分支重写**

把现有 `if objections:` 块（含 `parts = [...]`、`obj_text`、单个 `_stream_run(...复盘异议...)`）整段替换为：

```python
                    if objections:
                        structured: list[str] = []
                        freeform: list[str] = []
                        for tool, d in objections.items():
                            kind, text = self._objection_command(tool, d)
                            if not text:
                                continue
                            (structured if kind == "cmd" else freeform).append(text)
                        if structured or freeform:
                            all_text = "；".join(structured + freeform)
                            now = datetime.datetime.now().strftime("%H:%M:%S")
                            self.objection_log.append({
                                "time": now, "kind": "diagnosis_objection", "text": all_text})
                            await self.log(
                                "commander",
                                f"复盘异议（{len(structured) + len(freeform)} 项）统一提报司令：{all_text}。"
                                "结束当前诊断，按最新要求重新组织完整诊断。")
                            # 重跑前复位确认状态（旧队列已随本轮决策消费完毕）
                            self.pending_confirms.clear()
                            await self.broadcast({"type": "confirm_queue_clear"})
                            # ① 结构化命令逐条单独下发（单一意图）；失败降级为后缀
                            for cmd in structured:
                                ok = True
                                try:
                                    async for ev in pld_client.chat_stream(cmd):
                                        if ev.get("event_type") == "error":
                                            ok = False
                                except Exception:  # noqa: BLE001
                                    ok = False
                                if not ok:
                                    await self.log("commander",
                                                   f"异议命令下发失败，改为随重跑消息下发:{cmd}")
                                    freeform.append(cmd)
                            # ② 裸诊断消息（+自由文本后缀）整轮重跑；无异议工具命中缓存复用
                            rerun_msg = message
                            if freeform:
                                rerun_msg = (f"{message}\n【复盘异议，本次诊断必须采纳】"
                                             f"{'；'.join(freeform)}")
                            new_summary = await self._stream_run(rerun_msg, True, run_record)
                            if not new_summary.get("_invalid"):
                                summary = new_summary
                            continue
```

报告审核 `kind == "diagnosis"` 的重跑同样加守卫：

```python
                        new_summary = await self._stream_run(
                            f"{message}\n【复盘异议，本次诊断必须采纳】{instruction}", True, run_record)
                        if not new_summary.get("_invalid"):
                            summary = new_summary
                        continue
```

- [ ] **Step 6: 更新 `test_replay_flow.py` 既有断言**

`test_replay_emits_confirm_and_dispatches_objection` 中：

```python
    # 异议统一提报司令并随整轮重跑消息下发（不再逐条 chat 干预）
    rerun = [m for m in sent[1:] if "复盘异议" in m]
    assert rerun and "排除LightningDiagnosisTool" in rerun[0]
```

替换为：

```python
    # exclude 为结构化异议：先独立命令下发，再裸诊断消息重跑
    assert sent[1] == "排除LightningDiagnosisTool"
    assert sent[2] == sent[0] and "复盘异议" not in sent[2]
```

- [ ] **Step 7: 跑全部后端测试**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS（43 个）

- [ ] **Step 8: 提交**

```bash
cd "/Users/bei/DEVLOPE/3d agent" && git add backend/agent_manager.py backend/tests/test_replay_rerun_v2.py backend/tests/test_replay_flow.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(backend): 复盘异议结构化落地+裸诊断重跑+空完成守卫"
```

---

### Task 2: 后端复盘对话关键词路由

**Files:**
- Modify: `backend/agent_manager.py`（`handle_message` chat 分支 ~L158-171；新增 `_replay_agent_chat`；`tool_confirm_response` 分支 ~L196-216）
- Test: `backend/tests/test_replay_chat_routing.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `_objection_command`（`chat` 决策走 suffix）；`TOOL_AGENTS`（agent→tool 映射）
- Produces:
  - `OBJECTION_KEYWORDS: tuple[str, ...]`（模块级常量）
  - `_replay_agent_chat(agent: str, message: str) -> None`：命中关键词→记 `confirm_decisions[tool]={"decision":"chat","value":message}` + `objection_log(tool_objection/chat)` + 回显「已收到…」+ 广播 `{"type":"objection_accepted","agent","tool"}`；未命中→仅回固定提示气泡
  - 事件 `objection_accepted`（前端 Task 7 消费）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_replay_chat_routing.py`：

```python
"""复盘模式智能体对话路由：关键词命中→异议；未命中→固定提示不转发 PLD。"""
import agent_manager
from tests.test_agent_manager import FakeWS

SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls):
    async def fake_stream(msg):
        calls.append(msg)
        yield {"event_type": "complete", "payload": {}, "session_id": "s1"}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr._run_replay = True
    return mgr


async def test_keyword_hit_becomes_chat_objection(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "lightning",
                              "message": "把权重调整为0.1"})
    assert mgr.confirm_decisions["LightningDiagnosisTool"] == {
        "decision": "chat", "value": "把权重调整为0.1"}
    assert any(o.get("decision") == "chat" for o in mgr.objection_log)
    assert any(e["type"] == "objection_accepted" and e["agent"] == "lightning"
               for e in ws.events)
    chats = [e for e in ws.events if e["type"] == "chat" and e.get("from") == "agent"]
    assert any("统一上报司令" in e["message"] for e in chats)
    assert calls == []          # 未直接转发 PLD


async def test_keyword_miss_gets_fixed_hint(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "今天天气怎么样"})
    assert mgr.confirm_decisions == {}
    chats = [e for e in ws.events if e["type"] == "chat" and e.get("from") == "agent"]
    assert any("仅受理与本轮诊断相关的异议" in e["message"] for e in chats)
    assert calls == []


async def test_ok_click_does_not_override_chat_objection(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "lightning",
                              "message": "这个数据不对，重新检查"})
    # 随后点「无异议」不得吞掉已登记的对话异议
    mgr.pending_confirms["LightningDiagnosisTool"] = {"tool": "LightningDiagnosisTool"}
    mgr._confirms_done = None
    await mgr.handle_message({"type": "tool_confirm_response",
                              "tool": "LightningDiagnosisTool", "decision": "ok"})
    assert mgr.confirm_decisions["LightningDiagnosisTool"]["decision"] == "chat"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_replay_chat_routing.py -v`
Expected: FAIL（`_replay_agent_chat` 不存在；对话被转发 PLD）

- [ ] **Step 3: 实现路由**

`backend/agent_manager.py` 模块级（`SESSION_CONTEXT` 常量附近）加：

```python
# 复盘中智能体对话的异议关键词（命中→视为该工具异议，统一提报司令整轮重跑）
OBJECTION_KEYWORDS = (
    "权重", "排除", "去掉", "重新检查", "重查", "复查", "重新诊断",
    "数据", "数值", "时间段", "调整", "修正", "不对", "错误",
)
```

`handle_message` 的 `elif mtype == "chat":` 分支，在 `task = asyncio.create_task(self.handle_chat(...))` 之前插入：

```python
                if self._run_replay and agent != "commander":
                    # 复盘中与诊断智能体对话：本地关键词路由，不直接转发 PLD
                    # （转发会被意图分类器误判并劫持活跃会话）
                    await self._replay_agent_chat(agent, message)
                    return
```

（该插入点位于 `objection_log.append(user_input)` 之后；注意 `handle_message` 无 return 语义——用 if/else 包住原 `task = ...` 两行即可。）

新增方法（放在 `handle_chat` 前）：

```python
    async def _replay_agent_chat(self, agent: str, message: str):
        """复盘模式工具智能体对话：关键词命中→登记 chat 异议；未命中→固定提示。"""
        tool = TOOL_AGENTS.get(agent, agent)
        if not any(k in message for k in OBJECTION_KEYWORDS):
            await self.chat_say(
                agent, "此处仅受理与本轮诊断相关的异议（数据修正、权重调整、重新检查等），"
                       "其他事项请与司令对话。")
            return
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.objection_log.append({"time": now, "kind": "tool_objection", "tool": tool,
                                   "decision": "chat", "value": message})
        self.confirm_decisions[tool] = {"decision": "chat", "value": message}
        await self.chat_say(agent, "已收到，将随本轮异议统一上报司令重新诊断。")
        await self.broadcast({"type": "objection_accepted", "agent": agent, "tool": tool})
```

`tool_confirm_response` 分支中，`self.confirm_decisions[tool] = {...}` 赋值改为不吞已有对话异议：

```python
                existing = self.confirm_decisions.get(tool)
                if decision == "ok" and existing and existing.get("decision") != "ok":
                    pass  # 已存在对话异议，「无异议」点击不覆盖
                else:
                    self.confirm_decisions[tool] = {
                        "decision": data.get("decision", "ok"),
                        "value": data.get("value"),
                    }
```

（`decision` 变量在该分支上方已定义：`decision = data.get("decision", "ok")`。）

- [ ] **Step 4: 跑全部后端测试**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS（46 个）

- [ ] **Step 5: 提交**

```bash
cd "/Users/bei/DEVLOPE/3d agent" && git add backend/agent_manager.py backend/tests/test_replay_chat_routing.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(backend): 复盘对话关键词路由(命中记异议统一重跑/未命中固定提示)"
```

---

### Task 3: 后端保存策略子集 + 触发收紧（仅复盘且有干预）

**Files:**
- Modify: `backend/agent_manager.py`（`_finish_run` prompt 段 ~L681-687；`save_strategy` ~L793+；`handle_message` save_strategy 分支 ~L156-157；新增 `_intervention_items`）
- Test: `backend/tests/test_strategy_save_subset.py`（新建）

**Interfaces:**
- Consumes: `strategy_builder.build_skill_markdown(config)`、`strategy_builder.DEFAULT_WEIGHTS`、`self.intervention_trail`、`self.objection_log`
- Produces:
  - `_intervention_items() -> list[dict]`：每项 `{id, kind, tool, value, text, label}`；id 为下标。来源：`intervention_trail`（kind∈weight/exclude/recheck/time_range/override/report_modify/chat）+ `objection_log` 中 kind∈(diagnosis_objection, user_input) 的条目
  - `save_strategy(name: str = "", items: list[int] | None = None)`：items 为选中项 id 列表；None=全选
  - `prompt_save_strategy` 事件新增 `items` 字段；仅复盘轮且 items 非空时广播

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_strategy_save_subset.py`：

```python
"""保存策略子集：勾选部分干预生成 markdown；仅复盘轮触发保存提示。"""
import agent_manager
import strategy_builder
from tests.test_agent_manager import FakeWS

SESSION = {"status": "modifying",
           "active_weights": {"LightningDiagnosisTool": 0.1, "WindDiagnosisTool": 0.8},
           "excluded_tools": ["BirdDamageDiagnosisTool"], "action_log": []}


def make_mgr(monkeypatch):
    saved = {}

    async def fake_skill(name, content):
        saved["name"] = name
        saved["content"] = content
        return {"success": True}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_skill)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr.current_line = "雅湖线 跳闸"
    return mgr, saved


def seed_trail(mgr):
    mgr.intervention_trail = [
        {"kind": "weight", "tool": "LightningDiagnosisTool", "value": 0.1, "text": "", "time": "t"},
        {"kind": "exclude", "tool": "BirdDamageDiagnosisTool", "value": None, "text": "", "time": "t"},
        {"kind": "report_modify", "tool": "", "value": None, "text": "增加标题", "time": "t"},
    ]


async def test_save_subset_only_selected_items(monkeypatch):
    mgr, saved = make_mgr(monkeypatch)
    seed_trail(mgr)
    items = mgr._intervention_items()
    assert [i["label"] for i in items] == [
        "将LightningDiagnosisTool权重调整为0.1",
        "排除BirdDamageDiagnosisTool",
        "报告修改：增加标题",
    ]
    # 只选第 0、2 项（不含排除）
    await mgr.save_strategy("子集策略", items=[0, 2])
    content = saved["content"]
    assert "0.1" in content and "增加标题" in content
    assert "SKIP — excluded by user preference" not in content  # 未勾选排除


async def test_save_all_when_items_none(monkeypatch):
    mgr, saved = make_mgr(monkeypatch)
    seed_trail(mgr)
    await mgr.save_strategy("全选策略", items=None)
    assert "SKIP — excluded by user preference" in saved["content"]


async def test_prompt_only_after_replay_with_items(monkeypatch):
    """实时轮不弹保存提示；复盘轮带 items 列表。"""
    calls = []

    async def fake_stream(msg):
        calls.append(msg)
        yield {"event_type": "complete", "payload": {
            "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
            "session_id": "s1"}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr.intervention_trail = [
        {"kind": "weight", "tool": "LightningDiagnosisTool", "value": 0.1, "text": "", "time": "t"}]
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False, text="x")
    assert not [e for e in ws.events if e["type"] == "prompt_save_strategy"]
    mgr.status["commander"] = "idle"
    ws.events.clear()
    await mgr.run_diagnosis(replay=True)
    prompts = [e for e in ws.events if e["type"] == "prompt_save_strategy"]
    assert len(prompts) == 1
    assert prompts[0]["items"][0]["label"] == "将LightningDiagnosisTool权重调整为0.1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_strategy_save_subset.py -v`
Expected: FAIL（`_intervention_items` 不存在；save_strategy 无 items 参数；实时轮仍弹提示）

- [ ] **Step 3: 实现 `_intervention_items` + `save_strategy` 子集**

`agent_manager.py` 新增（放在 `save_strategy` 前）：

```python
    _ITEM_LABELS = {
        "weight": lambda t: f"将{t['tool']}权重调整为{t['value']}",
        "exclude": lambda t: f"排除{t['tool']}",
        "recheck": lambda t: f"重新检查{t['tool']}",
        "time_range": lambda t: f"重新检查{t['tool']}，查询时间段{t['value']}",
        "override": lambda t: f"将{t['tool']}相关数值修正为{t['value']}",
        "chat": lambda t: f"{t['tool']}：{t['value']}",
        "report_modify": lambda t: f"报告修改：{t['text']}",
    }

    def _intervention_items(self) -> list[dict]:
        """本轮可保存干预清单（保存提示弹窗展示 + 子集选择的数据源）。"""
        items = []
        for t in self.intervention_trail:
            label_fn = self._ITEM_LABELS.get(t.get("kind", ""))
            if not label_fn:
                continue
            items.append({"kind": t["kind"], "tool": t.get("tool", ""),
                          "value": t.get("value"), "text": t.get("text", ""),
                          "label": label_fn(t)})
        for o in self.objection_log:
            if o.get("kind") == "diagnosis_objection":
                items.append({"kind": "diagnosis_objection", "tool": "", "value": None,
                              "text": o["text"], "label": f"诊断要求：{o['text']}"})
            elif o.get("kind") == "user_input":
                items.append({"kind": "user_input", "tool": "", "value": None,
                              "text": o["text"], "label": f"人工指令：{o['text']}"})
        for i, it in enumerate(items):
            it["id"] = i
        return items
```

`save_strategy` 签名改为 `async def save_strategy(self, name: str = "", items: list[int] | None = None):`，方法体重写为按选中项生成（替换原「拉 session 权重/排除 + objection_log 过滤」那段配置组装，保留重名去重与 trails 持久化逻辑）：

```python
    async def save_strategy(self, name: str = "", items: list[int] | None = None):
        all_items = self._intervention_items()
        if items is not None:
            selected = [all_items[i] for i in items if isinstance(i, int) and 0 <= i < len(all_items)]
        else:
            selected = all_items
        if not selected:
            await self.log("commander", "未选择任何干预项，策略未保存。")
            return

        weights = dict(strategy_builder.DEFAULT_WEIGHTS)
        excluded: list[str] = []
        for it in selected:
            if it["kind"] == "weight" and it["tool"] in weights:
                weights[it["tool"]] = it["value"]
            elif it["kind"] == "exclude":
                excluded.append(it["tool"])

        name = name.strip() or f"cmd_strategy_{datetime.datetime.now().strftime('%H%M%S')}"
        name = re.sub(r"\s+", "_", name)
        existing = {s.get("name") for s in self.saved_strategies} | set(_load_trails().keys())
        unique, i = name, 2
        while unique in existing:
            unique = f"{name}_{i}"
            i += 1
        if unique != name:
            await self.log("commander", f"策略名「{name}」已存在，重命名为「{unique}」。")
        name = unique

        content = strategy_builder.build_skill_markdown({
            "name": name,
            "line_context": self.current_line or self.last_diagnosis_text or "transmission lines",
            "weights": weights,
            "excluded_tools": excluded,
            "template_name": "",
            "report_modifications": [it["text"] for it in selected if it["kind"] == "report_modify"],
            "commander_rules": [it["text"] for it in selected
                                if it["kind"] in ("diagnosis_objection", "user_input")],
            "custom_data": [it["label"] for it in selected if it["kind"] == "override"],
            "trail": [{"kind": it["kind"], "tool": it["tool"], "value": it["value"]}
                      for it in selected if it["kind"] in ("override", "time_range")],
        })
        # 其后：pld_client.save_skill、saved_strategies.append、records.attach_strategy、
        # _load_trails/_save_trails 持久化逻辑保持原样不变
```

注意：文件顶部需 `import strategy_builder`（已有）且用到 `strategy_builder.DEFAULT_WEIGHTS`。原方法中 `session = await pld_client.get_session(...)` 与提前 return 的整段删除（不再需要 session 快照）。

`handle_message` 的 save_strategy 分支：

```python
        elif mtype == "save_strategy":
            raw_items = data.get("items")
            items = [int(i) for i in raw_items] if isinstance(raw_items, list) else None
            await self.save_strategy(str(data.get("name", "")), items=items)
```

- [ ] **Step 4: `_finish_run` 触发收紧**

把：

```python
        n = self._count_interventions(session)
        if n > 0:
            await self.broadcast({
                "type": "prompt_save_strategy",
                "interventions": n,
                "context": "replay" if replay else "realtime",
            })
```

改为：

```python
        # 保存提示：仅复盘轮且本轮存在可保存干预项时弹出（实时轮不弹）
        if replay:
            items = self._intervention_items()
            if items:
                await self.broadcast({
                    "type": "prompt_save_strategy",
                    "interventions": len(items),
                    "items": items,
                    "context": "replay",
                })
```

（`_count_interventions` 不再被引用则删除；`local_interventions`/`_action_count_at_start` 基线滚动两行保留——别处仍用。若删除后 `_count_interventions` 无引用，连同方法一起删。）

- [ ] **Step 5: 跑全部后端测试**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS（49 个）

- [ ] **Step 6: 提交**

```bash
cd "/Users/bei/DEVLOPE/3d agent" && git add backend/agent_manager.py backend/tests/test_strategy_save_subset.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(backend): 保存策略子集勾选+仅复盘且有干预时提示"
```

---

### Task 4: 后端策略列表与删除（PLD 技能为数据源）

**Files:**
- Modify: `backend/pld_client.py`（新增 `delete_skill`）
- Modify: `backend/agent_manager.py`（`handle_message` 新增 `list_strategies`/`delete_strategies`；新增 `send_strategies`）
- Test: `backend/tests/test_strategy_manage.py`（新建）

**Interfaces:**
- Consumes: PLD `GET /api/skills`（字段 name/description/is_default/source）、`GET /api/skills/default`、`DELETE /api/skills/<name>`
- Produces:
  - `pld_client.delete_skill(name: str) -> dict`
  - 事件 `{"type":"strategies_list","strategies":[...],"default":str}`（前端 Task 5 消费）
  - 消息 `{"type":"list_strategies"}`、`{"type":"delete_strategies","names":[str]}`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_strategy_manage.py`：

```python
"""策略管理：列表来自 PLD 技能；删除逐条调 PLD DELETE，使用中默认策略跳过。"""
import agent_manager
from tests.test_agent_manager import FakeWS


def make_mgr(monkeypatch):
    deleted = []

    async def fake_list():
        return {"skills": [
            {"name": "策略A", "description": "d", "is_default": False, "source": "用户自定义"},
            {"name": "策略B", "description": "d", "is_default": False, "source": "用户自定义"},
        ]}

    async def fake_default():
        return {"default_skill": "策略B"}

    async def fake_delete(name):
        deleted.append(name)
        return {"success": True}

    monkeypatch.setattr(agent_manager.pld_client, "list_skills", fake_list)
    monkeypatch.setattr(agent_manager.pld_client, "get_default_skill", fake_default)
    monkeypatch.setattr(agent_manager.pld_client, "delete_skill", fake_delete)
    return agent_manager.AgentManager(), deleted


async def test_list_strategies_broadcast(monkeypatch):
    mgr, _ = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "list_strategies"})
    ev = [e for e in ws.events if e["type"] == "strategies_list"][-1]
    assert [s["name"] for s in ev["strategies"]] == ["策略A", "策略B"]
    assert ev["default"] == "策略B"


async def test_delete_skips_default_and_broadcasts(monkeypatch):
    mgr, deleted = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "delete_strategies", "names": ["策略A", "策略B"]})
    assert deleted == ["策略A"]          # 使用中的默认策略跳过
    assert any(e["type"] == "strategies_list" for e in ws.events)
    logs = [e["message"] for e in ws.events if e["type"] == "log"]
    assert any("策略B" in m and "跳过" in m or "删除失败" in m for m in logs)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_strategy_manage.py -v`
Expected: FAIL（`delete_skill`/分支不存在）

- [ ] **Step 3: 实现**

`backend/pld_client.py` `save_skill` 后追加：

```python
async def delete_skill(name: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.delete(f"/api/skills/{name}")).json()
```

`agent_manager.py` 新增（放在 `send_skills` 后）：

```python
    async def send_strategies(self):
        """策略管理页数据：PLD 技能列表 + 当前默认（使用中）策略名。"""
        try:
            skills = (await pld_client.list_skills()).get("skills", [])
            default = (await pld_client.get_default_skill()).get("default_skill", "")
            await self.broadcast({"type": "strategies_list",
                                  "strategies": skills, "default": default})
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"策略列表获取失败:{exc}")
```

`handle_message` 新增两个分支（放在 `reset_skills` 分支后）：

```python
        elif mtype == "list_strategies":
            await self.send_strategies()
        elif mtype == "delete_strategies":
            names = [str(n) for n in data.get("names", []) if str(n).strip()]
            try:
                default = (await pld_client.get_default_skill()).get("default_skill", "")
            except Exception:  # noqa: BLE001
                default = ""
            failed = []
            for n in names:
                if n == default:
                    failed.append(n)
                    continue
                try:
                    await pld_client.delete_skill(n)
                except Exception:  # noqa: BLE001
                    failed.append(n)
            deleted = [n for n in names if n not in failed]
            self.saved_strategies = [s for s in self.saved_strategies
                                     if s.get("name") not in deleted]
            if failed:
                await self.log("commander",
                               f"以下策略未删除（使用中或平台错误）：{'、'.join(failed)}")
            await self.send_strategies()
```

- [ ] **Step 4: 跑全部后端测试**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS（51 个）

- [ ] **Step 5: 提交**

```bash
cd "/Users/bei/DEVLOPE/3d agent" && git add backend/pld_client.py backend/agent_manager.py backend/tests/test_strategy_manage.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(backend): 策略列表/删除(PLD技能为数据源,使用中跳过)"
```

---

### Task 5: 前端策略管理页面 + 顶栏移除保存按钮

**Files:**
- Create: `frontend/src/components/StrategiesView.vue`
- Modify: `frontend/src/store.js`（新增 strategiesList/strategiesDefault）
- Modify: `frontend/src/ws.js`（strategies_list 事件、listStrategies/deleteStrategies、setView 拉取）
- Modify: `frontend/src/components/TopBar.vue`（删保存按钮、加策略页签）
- Modify: `frontend/src/App.vue`（挂载 StrategiesView）

**Interfaces:**
- Consumes: Task 4 的 `strategies_list` 事件（`strategies:[{name,description,is_default,source}]`、`default`）
- Produces: `setView('strategies')` 视图；`listStrategies()`、`deleteStrategies(names)`

- [ ] **Step 1: store/ws 协议接线**

`store.js` 在 `strategies: [],` 行后加：

```js
  strategiesList: [],    // 策略管理页：PLD 技能列表
  strategiesDefault: '', // 使用中（默认）策略名
```

`ws.js` `handle` 的 `case 'skills':` 后加：

```js
    case 'strategies_list':
      store.strategiesList = event.strategies || []
      store.strategiesDefault = event.default || ''
      break
```

`ws.js` 尾部 `setView` 改为：

```js
export const listStrategies = () => send({ type: 'list_strategies' })
export const deleteStrategies = (names) => send({ type: 'delete_strategies', names })
export function setView(v) {
  store.view = v
  if (v === 'history') requestRecords()
  if (v === 'strategies') listStrategies()
}
```

- [ ] **Step 2: StrategiesView.vue**

```vue
<script setup>
import { ref, computed } from 'vue'
import { store } from '../store'
import { setView, deleteStrategies, listStrategies } from '../ws'

const selected = ref(new Set())
const confirming = ref(false)

function toggle(name) {
  if (name === store.strategiesDefault) return
  const s = new Set(selected.value)
  s.has(name) ? s.delete(name) : s.add(name)
  selected.value = s
}

const deletable = computed(() =>
  store.strategiesList.filter((s) => s.name !== store.strategiesDefault))

function toggleAll() {
  selected.value = selected.value.size === deletable.value.length
    ? new Set()
    : new Set(deletable.value.map((s) => s.name))
}

async function doDelete() {
  deleteStrategies([...selected.value])
  selected.value = new Set()
  confirming.value = false
}
</script>

<template>
  <div class="absolute inset-0 z-10 bg-slate-950/95 flex flex-col p-4 gap-3 overflow-hidden pointer-events-auto">
    <div class="flex items-center gap-3 shrink-0">
      <span class="text-fuchsia-300 font-bold text-sm tracking-widest">◈ 干预策略管理</span>
      <button @click="listStrategies" class="text-xs px-3 py-1.5 rounded border border-slate-400/40 text-slate-300 bg-slate-700/30 hover:bg-slate-600/40">刷新</button>
      <button
        v-if="!confirming"
        :disabled="!selected.size"
        @click="confirming = true"
        class="text-xs px-3 py-1.5 rounded border border-red-400/50 text-red-300 bg-red-500/15 hover:bg-red-400/25 disabled:opacity-40 disabled:cursor-not-allowed"
      >删除所选（{{ selected.size }}）</button>
      <template v-else>
        <span class="text-xs text-red-300">确认删除 {{ selected.size }} 项策略？不可恢复。</span>
        <button @click="doDelete" class="text-xs font-bold px-3 py-1.5 rounded border border-red-400/60 text-red-200 bg-red-500/25 hover:bg-red-400/40">确认删除</button>
        <button @click="confirming = false" class="text-xs px-3 py-1.5 rounded border border-slate-500/40 text-slate-300 bg-slate-700/30">取消</button>
      </template>
      <button @click="setView('room')" class="ml-auto text-xs px-3 py-1.5 rounded border border-cyan-400/50 text-cyan-200 bg-cyan-500/15 hover:bg-cyan-400/25">返回指挥室</button>
    </div>

    <div class="flex-1 glass rounded-lg overflow-y-auto min-h-0">
      <div class="flex items-center gap-3 px-3 py-2 border-b border-slate-700/50 text-[10px] text-slate-500">
        <input type="checkbox"
          :checked="deletable.length && selected.size === deletable.length"
          @change="toggleAll" class="accent-fuchsia-400" />
        <span class="w-56">策略名</span>
        <span class="flex-1">描述</span>
        <span class="w-20">来源</span>
        <span class="w-16">状态</span>
      </div>
      <div
        v-for="s in store.strategiesList" :key="s.name"
        class="flex items-center gap-3 px-3 py-2 border-b border-slate-700/30 text-xs"
        :class="selected.has(s.name) ? 'bg-fuchsia-500/10' : ''"
      >
        <input
          type="checkbox"
          :checked="selected.has(s.name)"
          :disabled="s.name === store.strategiesDefault"
          @change="toggle(s.name)"
          class="accent-fuchsia-400 disabled:opacity-30"
        />
        <span class="w-56 truncate text-fuchsia-100" :title="s.name">{{ s.name }}</span>
        <span class="flex-1 truncate text-slate-400" :title="s.description">{{ s.description || '—' }}</span>
        <span class="w-20 text-slate-500">{{ s.source }}</span>
        <span class="w-16">
          <span v-if="s.name === store.strategiesDefault"
            class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 border border-emerald-400/40 text-emerald-300"
          >使用中</span>
        </span>
      </div>
      <div v-if="!store.strategiesList.length" class="px-3 py-6 text-center text-xs text-slate-600">
        暂无策略。复盘完成并提出异议后，可在保存提示中生成策略。
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 3: TopBar/App 接线**

`TopBar.vue`：删除整个「⬇ 保存干预策略」`<button>` 块（含 script 中 `openSaveNaming` import 的对应引用）；在历史结果按钮后加：

```vue
    <button
      @click="setView(store.view === 'strategies' ? 'room' : 'strategies')"
      class="text-xs font-bold px-3 py-1.5 rounded border border-fuchsia-400/50 text-fuchsia-200 bg-fuchsia-500/15 hover:bg-fuchsia-400/25 whitespace-nowrap"
      title="管理已保存的干预策略（PLD 技能）"
    >
      📋 策略
    </button>
```

`App.vue`：`<HistoryView v-if="store.view === 'history'" />` 后加 `<StrategiesView v-if="store.view === 'strategies'" />`，script 加 `import StrategiesView from './components/StrategiesView.vue'`。

- [ ] **Step 4: 编译验证**

Run: `cd frontend && npm run build`
Expected: 构建成功无报错

- [ ] **Step 5: 提交**

```bash
cd "/Users/bei/DEVLOPE/3d agent" && git add frontend/src/components/StrategiesView.vue frontend/src/store.js frontend/src/ws.js frontend/src/components/TopBar.vue frontend/src/App.vue
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): 策略管理页(多选删除,使用中保护)+顶栏移除保存按钮"
```

---

### Task 6: 前端保存提示弹窗——干预清单勾选

**Files:**
- Modify: `frontend/src/components/SavePromptModal.vue`（重写）
- Modify: `frontend/src/ws.js`（saveStrategyNamed 携带 items；savePrompt 数据结构）
- Modify: `frontend/src/store.js`（saveNaming 增加 selected）

**Interfaces:**
- Consumes: Task 3 的 `prompt_save_strategy`（含 `items:[{id,kind,tool,value,text,label}]`）
- Produces: `saveStrategyNamed(name, items)` 发送 `{type:'save_strategy', name, items:[id,...]}`

- [ ] **Step 1: ws/store 接线**

`ws.js` `case 'prompt_save_strategy':` 改为：

```js
    case 'prompt_save_strategy':
      store.savePrompt = { interventions: event.interventions, items: event.items || [], context: event.context }
      break
```

`saveStrategyNamed` 改为：

```js
export function saveStrategyNamed(name) {
  const items = store.saveNaming?.selected ?? null
  send({ type: 'save_strategy', name, items })
}
```

`store.js` 的 `savePrompt` 注释更新为 `// null | { interventions, items, context }`；`saveNaming` 注释更新为 `// null | { suggested, selected? }`。

- [ ] **Step 2: SavePromptModal 重写**

```vue
<script setup>
import { ref, watch } from 'vue'
import { store } from '../store'
import { respondSavePrompt, openSaveNaming } from '../ws'

const selected = ref(new Set())
const expanded = ref(false)

watch(() => store.savePrompt, (p) => {
  if (p) {
    selected.value = new Set((p.items || []).map((i) => i.id))
    expanded.value = false
  }
})

function toggle(id) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}

function save() {
  respondSavePrompt(false)
  openSaveNaming()
  store.saveNaming.selected = [...selected.value]
  store.savePrompt = null
}

function ignore() {
  respondSavePrompt(false)
  store.savePrompt = null
}
</script>

<template>
  <div
    v-if="store.savePrompt"
    class="glass absolute left-1/2 -translate-x-1/2 bottom-1/3 w-[420px] rounded-xl pointer-events-auto overflow-hidden"
    style="box-shadow: 0 0 40px rgba(251,191,36,.3)"
  >
    <div class="flex items-center gap-2 px-4 py-2.5 bg-amber-500/10 border-b border-amber-400/30">
      <span class="w-2 h-2 rounded-full bg-amber-300 animate-pulse"></span>
      <span class="text-amber-200 text-sm font-bold">策略保存提醒</span>
    </div>

    <div class="px-4 py-3 text-xs text-slate-200 leading-relaxed">
      本轮复盘存在 <span class="text-amber-300 font-bold">{{ store.savePrompt.interventions }}</span> 项人工干预，勾选需要保存的项：
    </div>

    <!-- 干预清单（默认收起前 3 项，可展开） -->
    <div class="px-4 pb-2 space-y-1">
      <label
        v-for="it in (expanded ? store.savePrompt.items : store.savePrompt.items.slice(0, 3))"
        :key="it.id"
        class="flex items-start gap-2 text-[11px] text-slate-300 cursor-pointer rounded px-2 py-1 hover:bg-amber-500/10"
      >
        <input
          type="checkbox"
          :checked="selected.has(it.id)"
          @change="toggle(it.id)"
          class="accent-amber-400 mt-0.5"
        />
        <span>{{ it.label }}</span>
      </label>
      <button
        v-if="store.savePrompt.items.length > 3"
        @click="expanded = !expanded"
        class="text-[10px] text-amber-300/80 hover:text-amber-200 px-2"
      >{{ expanded ? '▲ 收起' : `▼ 展开全部 ${store.savePrompt.items.length} 项` }}</button>
    </div>

    <div class="flex justify-end gap-2 px-4 py-2.5 border-t border-amber-400/20 bg-slate-900/50">
      <button
        @click="ignore"
        class="text-xs px-3 py-1.5 rounded bg-slate-700/40 text-slate-300 border border-slate-500/40 hover:bg-slate-600/40"
      >忽略</button>
      <button
        @click="save"
        :disabled="!selected.size"
        class="text-xs font-bold px-3 py-1.5 rounded bg-amber-500/25 text-amber-200 border border-amber-400/50 hover:bg-amber-400/40 disabled:opacity-40 disabled:cursor-not-allowed"
      >保存所选（{{ selected.size }}）</button>
    </div>
  </div>
</template>
```

- [ ] **Step 3: 编译验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
cd "/Users/bei/DEVLOPE/3d agent" && git add frontend/src/components/SavePromptModal.vue frontend/src/ws.js frontend/src/store.js
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): 保存提示弹窗干预清单勾选(默认全选可展开)"
```

---

### Task 7: 前端对话框——忙碌横幅 / 禁用 / 可关闭 / 恢复

**Files:**
- Modify: `frontend/src/store.js`（新增 agentBusy）
- Modify: `frontend/src/ws.js`（objection_accepted / tool_confirm_request / confirm_queue_clear 处理）
- Modify: `frontend/src/components/AgentSessionModal.vue`（横幅、禁用、×关闭）

**Interfaces:**
- Consumes: Task 2 的 `objection_accepted` 事件；既有 `tool_confirm_request`、`confirm_queue_clear`
- Produces: `store.agentBusy: { [agentId]: bool }`

- [ ] **Step 1: store/ws 接线**

`store.js` 在 `agentSession: null,` 行后加：

```js
  agentBusy: {},         // 复盘对话异议已上报、等待重诊断结果的智能体
```

`ws.js`：

```js
    case 'objection_accepted':
      store.agentBusy[event.agent] = true
      break
```

`case 'tool_confirm_request':` 内 `store.confirmQueue.push(event)` 前加 `store.agentBusy[event.agent] = false`（新结果到达即解除忙碌）。

`case 'confirm_queue_clear':` 内加 `store.agentBusy = {}`。

- [ ] **Step 2: AgentSessionModal**

script 顶部 computed 区加：

```js
const busy = computed(() => !!store.agentBusy[agent.value])
```

`close()` 改为：

```js
function close() {
  // 确认模式仅忙碌（异议已上报等待重跑）时允许关闭；关闭后新确认到达会自动重弹
  if (isConfirm.value && !busy.value) return
  store.agentSession = null
  if (!isConfirm.value && store.confirmQueue.length) {
    store.agentSession = { ...store.confirmQueue[0], confirm: true }
  }
}
```

模板标题栏 × 按钮 `v-if="!isConfirm"` 改为 `v-if="!isConfirm || busy"`。

标题栏下方（`<!-- 空结果标记 -->` 区块之前）加横幅：

```vue
      <!-- 异议已上报，等待司令重诊断 -->
      <div
        v-if="busy"
        class="px-4 py-2 text-[11px] text-amber-200 bg-amber-500/10 border-b border-amber-400/30 shrink-0 flex items-center gap-2"
      >
        <span class="w-2 h-2 rounded-full bg-amber-300 animate-pulse"></span>
        已上报司令，正在重新诊断，请等待新结果…（可关闭本窗口，结果到达后自动重新弹出）
      </div>
```

确认操作区 `<div v-if="isConfirm" class="border-t border-amber-400/20 ...">` 的 class 追加条件置灰：` :class="busy ? 'opacity-40 pointer-events-none' : ''"`。

- [ ] **Step 3: 编译验证**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
cd "/Users/bei/DEVLOPE/3d agent" && git add frontend/src/store.js frontend/src/ws.js frontend/src/components/AgentSessionModal.vue
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): 对话框异议上报等待态(横幅+禁用+可关闭,新结果自动重弹)"
```

---

## 收尾

- [ ] 全部后端测试：`cd backend && .venv/bin/python -m pytest tests/ -q`（51 个全绿）
- [ ] 前端构建：`cd frontend && npm run build`
- [ ] 提醒用户硬刷新页面后走一遍完整复盘流程实测
