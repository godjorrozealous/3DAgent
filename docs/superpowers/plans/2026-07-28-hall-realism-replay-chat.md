# 大厅逼真化 + 策略驱动动画 + 复盘私聊增强 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 spec `docs/superpowers/specs/2026-07-28-hall-realism-replay-chat-design.md` 实现 7 项指挥室改造。

**Architecture:** FastAPI 编排后端解析 PLD 诊断计划驱动 3D 动画；干预线索编排层本地持久化并支持激活重放；前端 Three.js 场景明亮写实化，复盘确认与私聊合并为大弹窗。

**Tech Stack:** Vue3 + Three.js(frontend)、FastAPI + httpx(backend)、pytest + pytest-asyncio。

## Global Constraints

- 后端工作目录 `/Users/bei/DEVLOPE/3d agent/backend`，测试命令 `.venv/bin/python -m pytest tests/ -q`（现有 11 个测试不得破坏）。
- 前端不新增依赖；Three.js 从 `three` 包导入（现有 import 路径不变）。
- 2D 面板/HUD/弹窗保持暗色玻璃拟态（`glass` 样式），仅 3D 场景改明亮写实。
- PLD 意图仅支持 diagnose/exclude_tool/include_tool/recheck_tool/adjust_weight/modify_report/complete/save_strategy/general，不得假设其他意图。
- 不复述历史 action_log：摘要干预标签只用本轮增量。
- WS 新事件/字段必须与计划中的接口定义逐字一致。

## 接口契约（跨任务）

- `parse_planned_tools(text: str) -> list[str]`：agent_manager.py 模块级函数，从「诊断计划」文本提取 `(\w+DiagnosisTool)` 去重保序列表。
- `session_snapshot` 事件新增字段 `planned_tools: list[str]`（最近一轮计划工具，无则 `[]`）。
- `run_state` 新事件：`{"type":"run_state","mode":"realtime"|"replay"|null}`，run 开始/结束(含异常)时广播。
- `tool_confirm_request` 载荷新增 `raw_text: str`、`structured_data: dict`。
- 保存策略：`{"type":"save_strategy","name":"用户命名"}`；`save_strategy(name: str)` 签名变更；重名追加 `_2`/`_3`。
- 干预线索文件 `backend/data/strategy_trails.json`：`{策略名: [{"kind","tool","value","text","time"}]}`，kind ∈ `exclude|weight|override|time_range|report_modify`。
- 私聊上下文前缀：`【当前会话：{line} {time} 跳闸诊断｜{tool}】`（line/time 取自 DIAGNOSE_MESSAGE 常量拆分）。

---

### Task 1: 诊断计划解析 + 策略驱动动画（亮一下就灭）

**Files:**
- Modify: `backend/agent_manager.py`（`_mark_tools_running`、run_diagnosis thinking 分支、`__init__`）
- Test: `backend/tests/test_plan_animation.py`（新建）

**Interfaces:**
- Produces: `parse_planned_tools(text)`；`AgentManager.planned_tools: list[str]`（实例属性，快照下发用）。

- [ ] **Step 1: 写失败测试**

```python
import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS, make_manager


def test_parse_planned_tools():
    text = "诊断计划: 调用 LightningDiagnosisTool, WindDiagnosisTool | 报告结构: 概述"
    assert agent_manager.parse_planned_tools(text) == ["LightningDiagnosisTool", "WindDiagnosisTool"]
    assert agent_manager.parse_planned_tools("无工具信息") == []
    # 去重保序
    t2 = "调用 BirdDamageDiagnosisTool, LightningDiagnosisTool、BirdDamageDiagnosisTool"
    assert agent_manager.parse_planned_tools(t2) == ["BirdDamageDiagnosisTool", "LightningDiagnosisTool"]


async def test_skipped_agents_blink_and_planned_run(monkeypatch):
    stream = [
        {"event_type": "start", "payload": {}, "session_id": "s1"},
        {"event_type": "thinking", "payload": {"message": "执行诊断工具..."}, "session_id": "s1"},
        {"event_type": "complete", "payload": {"report": "r", "summary": {}}, "session_id": "s1"},
    ]
    monkeypatch.setattr(agent_manager, "DIAGNOSE_MESSAGE", "x")
    async def fake_stream(msg):
        for e in stream:
            yield e
    async def fake_session(sid):
        return {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.planned_tools = ["LightningDiagnosisTool", "WindDiagnosisTool"]
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    # 计划内:running;计划外(icing/bird):先 running 后 idle(亮一下就灭)
    lightning_states = [e["status"] for e in ws.events if e.get("type") == "agent_status" and e.get("agent") == "lightning"]
    icing_states = [e["status"] for e in ws.events if e.get("type") == "agent_status" and e.get("agent") == "icing"]
    assert "running" in lightning_states
    assert icing_states[:2] == ["running", "idle"]
```

- [ ] **Step 2: 跑测试确认失败** `.venv/bin/python -m pytest tests/test_plan_animation.py -x -q` → `parse_planned_tools` 不存在。

- [ ] **Step 3: 实现**

`agent_manager.py` 顶部（import 后）加：

```python
import re

def parse_planned_tools(text: str) -> list[str]:
    """从「诊断计划」文本提取计划调用的工具名（去重保序）。"""
    seen: dict[str, None] = {}
    for m in re.findall(r"\w+DiagnosisTool", text or ""):
        seen.setdefault(m)
    return [t for t in seen if t in TOOL_TO_AGENT]
```

`__init__` 加 `self.planned_tools: list[str] = []`。

`_mark_tools_running` 改为：

```python
    async def _mark_tools_running(self):
        """工具执行阶段：计划内席位进入 RUNNING；计划外「亮一下就灭」。"""
        planned = set(self.planned_tools)
        excluded = set()
        try:
            if self.session_id:
                session = await pld_client.get_session(self.session_id)
                excluded = set((session or {}).get("excluded_tools", []))
        except Exception:
            pass

        async def run_agent(aid: str, delay: float):
            await asyncio.sleep(delay)
            await self.set_status(aid, "running")
            await self.log(aid, f"通过 MCP 服务调用 {TOOL_AGENTS[aid]} 采集诊断数据……")

        async def blink_agent(aid: str, delay: float):
            await asyncio.sleep(delay)
            await self.set_status(aid, "running")
            await asyncio.sleep(0.6)
            await self.set_status(aid, "idle")
            await self.log(aid, "按 LLM 诊断策略，本轮未调用该工具（条件不满足）。")

        tasks = []
        for i, (aid, tool) in enumerate(TOOL_AGENTS.items()):
            if tool in planned and tool not in excluded:
                tasks.append(run_agent(aid, i * 1.2))
            else:
                tasks.append(blink_agent(aid, i * 0.3))
        await asyncio.gather(*tasks)
```

run_diagnosis thinking 分支，在 `if not tools_started and "执行诊断工具" in msg:` 之前加计划捕获（同一 elif 块内）：

```python
                    if "诊断计划" in msg:
                        parsed = parse_planned_tools(msg)
                        if parsed:
                            self.planned_tools = parsed
```

解析失败兜底：`planned_tools` 为空时 `_mark_tools_running` 视同全部计划内（把 `planned = set(self.planned_tools)` 后加 `if not planned: planned = set(TOOL_AGENTS.values())`）。

- [ ] **Step 4: 跑测试通过 + 全套回归** `.venv/bin/python -m pytest tests/ -q` 全绿。
- [ ] **Step 5: 提交** `git add backend/agent_manager.py backend/tests/test_plan_animation.py && git commit -m "feat(backend): 诊断计划解析驱动席位动画(计划外亮一下就灭)"`

### Task 2: 本轮增量 action_log + 干预线索收集

**Files:**
- Modify: `backend/agent_manager.py`（`_finish_run`、`_dispatch_objections`、审核循环、`__init__`）
- Test: `backend/tests/test_intervention_trail.py`（新建）

**Interfaces:**
- Produces: `AgentManager.intervention_trail: list[dict]`（元素 `{"kind","tool","value","text","time"}`）；`AgentManager._run_action_baseline: int`（本轮 action_log 基线，run 开始时快照）。report_summary.action_log 变为本轮增量。

- [ ] **Step 1: 写失败测试**

```python
import agent_manager
from tests.test_agent_manager import FakeWS

SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [],
           "action_log": [{"action_type": "exclude", "tool_name": "BirdDamageDiagnosisTool"},
                          {"action_type": "exclude", "tool_name": "X"}]}

async def test_report_summary_action_log_is_delta(monkeypatch):
    async def fake_stream(msg):
        yield {"event_type": "complete", "payload": {"report": "r", "summary": {}}, "session_id": "s1"}
    async def fake_session(sid):
        return SESSION
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr._action_count_at_start = 1  # 本轮开始前已有 1 条历史
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    summary_events = [e for e in ws.events if e.get("type") == "report_summary"]
    assert len(summary_events[0]["action_log"]) == 1  # 只有本轮新增的 1 条
```

- [ ] **Step 2: 确认失败**（当前下发全量 2 条）。
- [ ] **Step 3: 实现**
  - `__init__` 加 `self.intervention_trail: list[dict] = []`。
  - `run_diagnosis` 开头（broadcast reset 后）加 `self.intervention_trail = []`。
  - 新增方法：

```python
    def _trail(self, kind: str, tool: str = "", value=None, text: str = ""):
        self.intervention_trail.append({
            "kind": kind, "tool": tool, "value": value, "text": text,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
        })
```

  - `_dispatch_objections`：exclude→`self._trail("exclude", tool)`；weight→`self._trail("weight", tool, value)`；override→`self._trail("override", tool, value)`；recheck→`self._trail("recheck", tool)`（decision 为 time_range 时 `self._trail("time_range", tool, value)`，cmd 为 `f"重新检查{tool}，查询时间段{value}"`）。
  - 审核循环 modify_report 指令处（`await self.log("audit", f"按指挥员意见修改报告:{instruction}")` 后）加 `self._trail("report_modify", text=instruction)`。
  - `_finish_run` 的 summary_event：`"action_log": (session or {}).get("action_log", [])[self._action_count_at_start:]`。
- [ ] **Step 4: 测试通过 + 全回归**。
- [ ] **Step 5: 提交** `git commit -m "feat(backend): 摘要干预标签改本轮增量+干预线索收集"`

### Task 3: 实时禁干预（run_state + chat 拒绝）

**Files:**
- Modify: `backend/agent_manager.py`（`_start_run`、`run_diagnosis`、chat 分支）
- Test: `backend/tests/test_realtime_lock.py`（新建）

**Interfaces:**
- Produces: `run_state` 事件（见接口契约）；`AgentManager._run_replay: bool`。

- [ ] **Step 1: 写失败测试**

```python
import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS

async def test_chat_rejected_during_realtime_run(monkeypatch):
    gate = asyncio.Event()
    async def fake_stream(msg):
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        await gate.wait()
        yield {"event_type": "complete", "payload": {"report": "r", "summary": {}}, "session_id": "s1"}
    async def fake_session(sid):
        return {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    task = asyncio.create_task(mgr.run_diagnosis(replay=False))
    await asyncio.sleep(0.1)
    await mgr.handle_message({"type": "chat", "agent": "commander", "message": "排除鸟害工具"})
    chats = [e for e in ws.events if e.get("type") == "chat"]
    assert any("不接受干预" in c.get("message", "") for c in chats)
    states = [e for e in ws.events if e.get("type") == "run_state"]
    assert states[0]["mode"] == "realtime"
    gate.set()
    await task
    assert states[-1]["mode"] is None
```

- [ ] **Step 2: 确认失败**。
- [ ] **Step 3: 实现**
  - `__init__` 加 `self._run_replay = False`。
  - `run_diagnosis`：`try:` 块开始处加 `self._run_replay = replay; await self.broadcast({"type":"run_state","mode":"replay" if replay else "realtime"})`；函数末尾（except 之后，无论成败）加：

```python
        self._run_replay = False
        await self.broadcast({"type": "run_state", "mode": None})
```

（用 try/finally 包住主体，或直接加在现有代码路径末尾与 except 末尾——两处都加即可。）
  - `handle_message` chat 分支改为：

```python
        elif mtype == "chat":
            agent = data.get("agent", "commander")
            message = str(data.get("message", "")).strip()
            if agent in AGENTS and message:
                if self.current_task and not self.current_task.done() and not self._run_replay:
                    await self.chat_say(agent, "实时诊断执行中不接受人工干预，请在复盘重跑中进行。")
                    return
                task = asyncio.create_task(self.handle_chat(agent, message))
                self._chat_tasks.add(task)
                task.add_done_callback(self._chat_tasks.discard)
```

- [ ] **Step 4: 测试通过 + 全回归**。
- [ ] **Step 5: 提交** `git commit -m "feat(backend): 实时诊断运行期禁止人工干预(run_state 事件)"`

### Task 4: 命名保存策略 + 线索持久化

**Files:**
- Modify: `backend/agent_manager.py`（`save_strategy`、handle_message save 分支）、`backend/pld_client.py`（无改动，复用 save_skill）
- Test: `backend/tests/test_named_save.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `intervention_trail`。
- Produces: `save_strategy(name: str)`；`backend/data/strategy_trails.json`；`_load_trails()/_save_trails()` 辅助。

- [ ] **Step 1: 写失败测试**

```python
import json
import agent_manager
from tests.test_agent_manager import FakeWS

async def test_named_save_with_dedupe_and_trail(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", tmp_path / "trails.json")
    saved = {}
    async def fake_skill(name, content):
        saved["name"] = name
        return {"success": True}
    async def fake_session(sid):
        return {"active_weights": {"LightningDiagnosisTool": 1.0}, "excluded_tools": ["BirdDamageDiagnosisTool"]}
    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_skill)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr.saved_strategies = [{"name": "夏季策略"}]
    mgr.intervention_trail = [{"kind": "exclude", "tool": "BirdDamageDiagnosisTool", "value": None, "text": "", "time": "10:00:00"}]
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.save_strategy("夏季策略")
    assert saved["name"] == "夏季策略_2"  # 重名追加序号
    trails = json.loads((tmp_path / "trails.json").read_text())
    assert trails["夏季策略_2"][0]["kind"] == "exclude"
```

- [ ] **Step 2: 确认失败**（save_strategy 当前不接受 name 参数）。
- [ ] **Step 3: 实现**
  - 模块级加：

```python
import json
from pathlib import Path

TRAILS_FILE = Path(__file__).parent / "data" / "strategy_trails.json"

def _load_trails() -> dict:
    try:
        return json.loads(TRAILS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _write_trails(trails: dict):
    TRAILS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRAILS_FILE.write_text(json.dumps(trails, ensure_ascii=False, indent=1), encoding="utf-8")
```

  - `save_strategy(self, name: str = "")`：重名检查（对 `self.saved_strategies` 已有名 + trails 文件键），冲突时追加 `_2`/`_3`…；无 name 时退回 `cmd_strategy_{HHMMSS}`。保存成功后：`_write_trails` 把 `self.intervention_trail` 记入该策略名；strategy 字典加 `"trail_count": len(self.intervention_trail)`；日志文案改为「人工干预策略已保存为技能「{name}」（权重 N 项 / 排除 M 项 / 干预线索 K 条）」。
  - handle_message：`elif mtype == "save_strategy": await self.save_strategy(str(data.get("name", "")))`；`save_prompt_response` 分支改为 `await self.save_strategy(str(data.get("name", "")))`。
- [ ] **Step 4: 测试通过 + 全回归**（注意现有测试若调 save_strategy 无参需兼容默认参数）。
- [ ] **Step 5: 提交** `git commit -m "feat(backend): 策略命名保存(重名追加序号)+干预线索持久化"`

### Task 5: 激活策略自动重放干预线索

**Files:**
- Modify: `backend/agent_manager.py`（activate_skill 分支、新增 `_replay_trail`）
- Test: `backend/tests/test_trail_replay.py`（新建）

**Interfaces:**
- Consumes: Task 4 的 trails 文件、Task 3 的 `_wait_pld_idle`。
- Produces: `AgentManager._replay_trail(name: str)`。

- [ ] **Step 1: 写失败测试**

```python
import json
import agent_manager
from tests.test_agent_manager import FakeWS

async def test_activate_replays_trail(monkeypatch, tmp_path):
    trails_file = tmp_path / "trails.json"
    trails_file.write_text(json.dumps({"夏季策略": [
        {"kind": "override", "tool": "LightningDiagnosisTool", "value": "雷电流 28kA", "text": "", "time": "t"},
        {"kind": "report_modify", "tool": "", "value": None, "text": "删除第三章", "time": "t"},
        {"kind": "exclude", "tool": "BirdDamageDiagnosisTool", "value": None, "text": "", "time": "t"},
    ]}, ensure_ascii=False))
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", trails_file)
    sent = []
    async def fake_default(name):
        return {"success": True}
    async def fake_stream(msg):
        sent.append(msg)
        yield {"event_type": "complete", "payload": {"report": "new", "summary": {}}, "session_id": "s1"}
    async def fake_session(sid):
        return {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}
    monkeypatch.setattr(agent_manager.pld_client, "set_default_skill", fake_default)
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "activate_skill", "name": "夏季策略"})
    assert mgr.value_overrides["LightningDiagnosisTool"] == "雷电流 28kA"
    assert any("删除第三章" in m for m in sent)  # report_modify 重放
    assert not any("排除" in m for m in sent)    # exclude 由 PLD 技能承载,不重放
```

- [ ] **Step 2: 确认失败**。
- [ ] **Step 3: 实现**
  - 新方法：

```python
    async def _replay_trail(self, name: str):
        trail = _load_trails().get(name, [])
        if not trail:
            return
        await self.log("commander", f"策略「{name}」含 {len(trail)} 条干预线索，开始自动重放……")
        for item in trail:
            kind, tool, value, text = item.get("kind"), item.get("tool", ""), item.get("value"), item.get("text", "")
            if kind in ("override", "time_range", "external_data"):
                self.value_overrides[tool] = str(value)
                cmd = f"修改报告：将{tool}相关数值修正为{value}"
            elif kind == "report_modify":
                cmd = text
            else:
                continue  # exclude/weight/recheck 由 PLD 技能承载或属一次性动作
            try:
                await self._wait_pld_idle()
                async for event in pld_client.chat_stream(cmd):
                    p = event.get("payload", {})
                    if event.get("event_type") == "complete" and p.get("report"):
                        self.last_report = p["report"]
                        await self.broadcast({"type": "report", "content": p["report"], "done": True})
            except Exception as exc:  # noqa: BLE001
                await self.log("commander", f"线索重放失败({kind} {tool}):{exc}")
        await self._refresh_snapshot()
        await self.log("commander", f"策略「{name}」干预线索重放完成。")
```

  - activate_skill 分支末尾（`await self.send_skills()` 后）加 `await self._replay_trail(name)`。
- [ ] **Step 4: 测试通过 + 全回归**。
- [ ] **Step 5: 提交** `git commit -m "feat(backend): 激活策略自动重放干预线索"`

### Task 6: 复盘确认载荷扩充 + 私聊上下文前缀

**Files:**
- Modify: `backend/agent_manager.py`（result 分支 pending_confirms、handle_chat else 分支）
- Test: `backend/tests/test_agent_session_payload.py`（新建）

**Interfaces:**
- Produces: tool_confirm_request 增加 `raw_text`/`structured_data`；非 commander 私聊转发 PLD 并带前缀。

- [ ] **Step 1: 写失败测试**

```python
import agent_manager
from tests.test_agent_manager import FakeWS
from tests.test_replay_flow import RESULT_STREAM, SESSION

async def test_confirm_request_carries_full_payload(monkeypatch):
    async def fake_stream(msg):
        for e in RESULT_STREAM:
            yield e
    async def fake_session(sid):
        return SESSION
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    import asyncio
    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response", "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})
    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    req = [e for e in ws.events if e.get("type") == "tool_confirm_request"][0]
    assert req["raw_text"] == "raw"
    assert req["structured_data"]["fault_type"] == "雷击-绕击"

async def test_subagent_chat_forwarded_with_context_prefix(monkeypatch):
    sent = []
    async def fake_stream(msg):
        sent.append(msg)
        yield {"event_type": "complete", "payload": {"message": "收到"}, "session_id": "s1"}
    async def fake_session(sid):
        return SESSION
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    await mgr.handle_chat("lightning", "查询 19:40~19:50 的雷电数据")
    assert "【当前会话：" in sent[0] and "LightningDiagnosisTool" in sent[0]
    assert "查询 19:40~19:50" in sent[0]
```

- [ ] **Step 2: 确认失败**。
- [ ] **Step 3: 实现**
  - result 分支 `self.pending_confirms[tool] = {...}` 字典加 `"raw_text": raw, "structured_data": sd`（raw/sd 变量已存在）。
  - 模块级加 `SESSION_CONTEXT = "【当前会话：雅湖线 2025-05-08 19:46 跳闸诊断｜{tool}】"`。
  - `handle_chat` else 分支（子席位）替换为转发实现：

```python
        else:
            tool = TOOL_AGENTS.get(agent, agent)
            prefixed = SESSION_CONTEXT.format(tool=tool) + message
            await self.log(agent, f"收到针对 {tool} 的会话内要求，转发 PLDiagnosis 处理。")
            try:
                async for event in pld_client.chat_stream(prefixed):
                    etype = event.get("event_type")
                    payload = event.get("payload", {})
                    if etype == "complete":
                        if payload.get("report"):
                            self.last_report = payload["report"]
                            await self.broadcast({"type": "report", "content": payload["report"], "done": True})
                        await self.chat_say(agent, payload.get("message") or "要求已处理，报告已同步更新。")
                        await self._refresh_snapshot()
                    elif etype == "error":
                        await self.chat_say(agent, f"处理失败:{payload.get('message', '未知错误')}")
            except Exception as exc:  # noqa: BLE001
                await self.chat_say(agent, f"要求下发失败:{exc}")
```

- [ ] **Step 4: 测试通过 + 全回归**。
- [ ] **Step 5: 提交** `git commit -m "feat(backend): 确认载荷带完整结果+子席位私聊带上下文前缀转发"`

### Task 7: 3D 场景明亮写实改造

**Files:**
- Modify: `frontend/src/three/CommandRoom.js`（`_buildLights`/`_buildRoom`/MAT/makeDesk/背景雾/相机不变、席位/光束/浮牌/动画循环不变）

**Interfaces:**
- Consumes/Produces: 对外接口不变（构造、setStatus、updateStrategy、focusOn）。

- [ ] **Step 1: 改造场景**（无单测，截图验证）
  - 背景/雾：`this.scene.background = new THREE.Color(0xdfe8f0)`；`this.scene.fog = new THREE.FogExp2(0xdfe8f0, 0.004)`。
  - `_buildLights`：环境光 `new THREE.AmbientLight(0xffffff, 3.2)`；半球光 `new THREE.HemisphereLight(0xffffff, 0xb0c4d4, 1.6)`；顶部平行光 `DirectionalLight(0xfff5e6, 2.2)` 位置 (0,18,4) 模拟天窗日光；保留 screenGlow（改 0x2a6f8f, 30）。
  - MAT 改浅色系：desk `0xe8edf2`(metalness 0.3, roughness 0.5)、chair `0xcfd8e0`、dark `0x5a6672`。
  - `_buildRoom` 重写：
    - 地板：浅灰白 `0xdde4ea` roughness 0.35 metalness 0.1；GridHelper 颜色 `0x9fb3c8/0xc3d2de` opacity 0.25。
    - 白色环形外壳：后/侧墙材质 `0xeef2f5` roughness 0.9。
    - 玻璃幕墙：两侧墙前方加 `PlaneGeometry(42,10)` 材质 `MeshPhysicalMaterial({color:0xbfd9e8, transparent:true, opacity:0.25, roughness:0.1})`，位置 y=6；幕墙外天际线：远处 `PlaneGeometry(80,14)` 材质 `MeshBasicMaterial({color:0x9db8cc})` 加 canvas 渐变纹理（天蓝→远山灰）置于 z=-30 与两侧。
    - 格栅天窗：顶部 y=14 加发光顶板 `PlaneGeometry(48,42)` `MeshBasicMaterial({color:0xf4f8fb})` 朝下（rotation.x=Math.PI/2），其下格栅：两组 `BoxGeometry(48,0.12,0.3)`（z 向每 2m 一根，共 21 根）与 `BoxGeometry(0.3,0.12,42)`（x 向每 2m 一根，共 25 根），材质 `0xc9d4dc`。
    - 弧形视频墙替换平面大屏：`CylinderGeometry(20, 20, 7.5, 48, 1, true, Math.PI*0.85, Math.PI*0.3)` 材质 `MeshBasicMaterial({map: makeScreenTexture(), side: THREE.BackSide})`，位置 (0,6.8,3)，弧度朝司令席；外框改同弧度深色壳（半径 20.2）。下沿灯带保留。
    - 尘埃粒子颜色改 `0x8fa8bd` opacity 0.35。
  - 桌面席位不变（人物/信标/光束/策略浮牌保留，全息青色在亮环境下仍可辨识）。
- [ ] **Step 2: 截图验证**（前端 5173 运行中）用 `/tmp/ui_screenshots.py` 的 shot1 部分截全景，人工核对参考图要素（白壳/幕墙/天窗/弧形屏/浅地板）。
- [ ] **Step 3: 提交** `git commit -m "feat(frontend): 3D 指挥大厅明亮写实化(参考 3d66 智慧大厅)"`

### Task 8: 策略 HUD 两行展示 + 浮牌格式

**Files:**
- Modify: `frontend/src/App.vue`（buildStrategyText、HUD 卡）、`frontend/src/ws.js`（session_snapshot 存 planned_tools）、`frontend/src/store.js`
- Modify: `backend/agent_manager.py`（`_refresh_snapshot`/`_finish_run` snapshot 加 `planned_tools: self.planned_tools`）

**Interfaces:**
- Consumes: Task 1 `planned_tools`、接口契约 session_snapshot.planned_tools。

- [ ] **Step 1: 后端 snapshot 加字段**（两处 broadcast session_snapshot 加 `"planned_tools": self.planned_tools`），跑后端全回归。
- [ ] **Step 2: store.js** 加 `plannedTools: []`；ws.js session_snapshot case 加 `store.plannedTools = event.planned_tools || []`。
- [ ] **Step 3: App.vue**
  - `buildStrategyText()` 改三行：

```js
const ALL_TOOLS = ['Lightning', 'Wind', 'Icing', 'Bird']
function buildStrategyText() {
  const excluded = new Set(store.excludedTools.map(shortName))
  const planned = new Set((store.plannedTools || []).map(shortName))
  const calls = ALL_TOOLS.filter(t => !excluded.has(t))
    .map(t => `${TOOL_CN[t]}×${store.weights[`${t}DiagnosisTool`] ?? DEFAULT_WEIGHTS[t]}`)
  const excl = [
    ...[...excluded].map(t => `${TOOL_CN[t] || t}(人工)`),
    ...ALL_TOOLS.filter(t => planned.size && !planned.has(t) && !excluded.has(t)).map(t => `${TOOL_CN[t]}(条件)`),
  ]
  return [
    `策略：${store.defaultSkill || '默认'}`,
    `调用：${calls.join('、') || '无'}`,
    `排除：${excl.join('、') || '无'}`,
  ].join('\n')
}
```

  - HUD 卡改两行结构：第一行策略名 + 调用标签（cyan），第二行排除标签（红=人工、灰=条件）。保留现有 Tailwind 风格。
- [ ] **Step 4: 截图核对** HUD 与 3D 浮牌三行文本。
- [ ] **Step 5: 提交** `git commit -m "feat: 策略HUD两行展示(调用全列+排除分来源)+浮牌同步"`

### Task 9: 复盘合并大弹窗 AgentSessionModal（取代 ConfirmToolModal）

**Files:**
- Create: `frontend/src/components/AgentSessionModal.vue`
- Modify: `frontend/src/App.vue`（挂载替换）、`frontend/src/store.js`（agentSession 状态）、`frontend/src/ws.js`（打开逻辑）
- Delete: `frontend/src/components/ConfirmToolModal.vue`

**Interfaces:**
- Consumes: Task 6 的 `raw_text`/`structured_data` 载荷；ws.sendToolConfirm(tool, decision, value)。
- Produces: `store.agentSession = null | { agent, tool, fault_type, confidence, evidence, raw_text, structured_data, override, confirm: bool }`。

- [ ] **Step 1: store/ws 接线**
  - store.js：`agentSession: null`；confirmQueue 保留（驱动 confirm 模式）。
  - ws.js `tool_confirm_request` case 改：`store.agentSession = { ...event, confirm: true }`（不再 push confirmQueue；队列长度用 event 自带？简化：同时维护 confirmQueue.push 仅用于显示「队列 N」）；`confirm_queue_clear` case 加 `store.agentSession = null`。
- [ ] **Step 2: AgentSessionModal.vue**（完整组件）
  - `v-if="store.agentSession"`，`fixed inset-0 z-40 flex items-center justify-center`，卡片 `w-[720px] max-h-[85vh] glass rounded-xl flex flex-col`。
  - 顶部标题栏：智能体中文名 + tool 短名 + 倾向/置信度 + 关闭×（confirm 模式不允许直接关——不显示×；私聊模式显示）。
  - 结果区（`max-h-56 overflow-y-auto`）：structured_data 字段表（`Object.entries` 逐行 key/value，evidence 数组逐条）+ raw_text 原文块（`whitespace-pre-wrap`）。
  - 对话区：复用 `store.chatMessages[agent]` 渲染（样式抄 ChatModal 气泡）；输入框 + 发送（`sendChat(agent, text)`）。
  - 操作区（仅 `confirm` 模式）：四按钮（重新检查/数据不对去掉/调整权重/手填数据）+ 权重 number 输入 + 手填文本输入 + 时间段两个文本输入（起/止）+「无异议」。逻辑：
    - 重新检查：时间段均填写 → `sendToolConfirm(tool,'time_range', `${start}~${end}`)`，否则 `sendToolConfirm(tool,'recheck')`。
    - 去掉：`sendToolConfirm(tool,'exclude')`；调权：`sendToolConfirm(tool,'weight', Number(w))`；手填：`sendToolConfirm(tool,'override', text)`。
    - 无异议：`sendToolConfirm(tool,'ok')`。
    - 任一提交后 `store.confirmQueue.shift(); store.agentSession = store.confirmQueue[0] ? { ...store.confirmQueue[0], confirm: true } : null`。
  - 私聊模式打开入口：复盘中（store.running 且 replay）双击诊断席位时 App.vue 的 onAgentDblClick 改为：若 `store.replayMode` 且 agent 是四工具之一 → `store.agentSession = { agent, tool: TOOL_FULL[agent], confirm: false, ... }`，否则 `store.chatTarget = agentId`。
- [ ] **Step 3: store.replayMode**：ws.js `run_state` case：`store.replayMode = e.mode === 'replay'`；`store.running = e.mode !== null`（替代 commander status 推断，保留原逻辑兼容）。
- [ ] **Step 4: App.vue** 挂载 `<AgentSessionModal />` 替换 `<ConfirmToolModal />`；删除 import。
- [ ] **Step 5: 删除 ConfirmToolModal.vue**；UI 冒烟（截图复盘大弹窗）；提交 `git commit -m "feat(frontend): 复盘合并大弹窗(完整结果+私聊+快捷异议)"`

### Task 10: 命名弹窗 + 实时禁聊前端

**Files:**
- Create: `frontend/src/components/SaveStrategyModal.vue`
- Modify: `frontend/src/App.vue`（挂载）、`frontend/src/components/TopBar.vue`（保存按钮改为开弹窗）、`frontend/src/components/SavePromptModal.vue`（「保存策略」改为开命名弹窗）、`frontend/src/components/ChatModal.vue`（实时禁输入）、`frontend/src/store.js`、`frontend/src/ws.js`

**Interfaces:**
- Consumes: Task 3 run_state、Task 4 命名保存接口。
- Produces: `store.saveNaming = null | { suggested: string }`；ws `saveStrategyNamed(name)` → `send({type:'save_strategy', name})`；`respondSavePrompt(true, name)` 带 name。

- [ ] **Step 1: store/ws**
  - store.js：`saveNaming: null`。
  - ws.js：`export const openSaveNaming = () => { store.saveNaming = { suggested: '策略_' + new Date().toISOString().slice(0,10).replaceAll('-','') + '_' + new Date().toTimeString().slice(0,5).replace(':','') } }`；`export const saveStrategyNamed = (name) => send({ type: 'save_strategy', name })`；`respondSavePrompt` 改 `(save, name) => send({ type: 'save_prompt_response', save, name })`。
- [ ] **Step 2: SaveStrategyModal.vue**：`v-if="store.saveNaming"` 居中弹窗（w-96）：标题「保存诊断策略」、输入框 v-model name（预填 suggested）、说明「将保存当前权重/排除及本轮干预线索」、按钮「保存」（空名禁用）→ `saveStrategyNamed(name); store.saveNaming=null`；「取消」→ `store.saveNaming=null`。
- [ ] **Step 3: TopBar.vue** 保存按钮 `@click="openSaveNaming"`（import 替换 saveStrategy）。SavePromptModal「保存策略」按钮改 `@click="openSaveNaming(); store.savePrompt=null"`。
- [ ] **Step 4: ChatModal.vue** 输入区：`:disabled="store.running && !store.replayMode"`，placeholder 动态：`store.running && !store.replayMode ? '实时诊断执行中，复盘时可干预…' : '输入干预指令，回车发送…'`；submit 同条件 return。
- [ ] **Step 5: 截图核对 + 提交** `git commit -m "feat(frontend): 策略保存命名弹窗+实时运行期禁聊"`

### Task 11: E2E 验证（会话重置 + 全流程）

**Files:**
- Create: `/tmp/e2e_hall_upgrade.py`

- [ ] **Step 1: 重置 PLD 会话**：停 PLD(5000) → 备份并清空 `vendor/diagnosis-agent/data/sessions.json` 的 sessions 数组（保留 version）→ 重启 PLD。
- [ ] **Step 2: WS E2E 脚本**，断言：
  1. 干净会话实时诊断：`result` 事件含 BirdDamageDiagnosisTool（鸟害被调用）；`session_snapshot.planned_tools` 非空且不强制含 Icing（夏天）；
  2. 运行中发 chat → 收到「不接受干预」回复；
  3. report_summary.action_log 只含本轮（条数 ≤ 本轮操作数）；
  4. 复盘：tool_confirm_request 含 raw_text/structured_data；手填 override → snapshot.overrides 有值；
  5. `save_strategy` 带 name「E2E验证策略」→ strategy_saved.name 一致；trails 文件含该策略；
  6. `activate_skill`「E2E验证策略」→ 观察到重放日志/覆盖层恢复。
- [ ] **Step 3: 后端全回归** `.venv/bin/python -m pytest tests/ -q` 全绿。
- [ ] **Step 4: UI 截图**：明亮大厅全景、HUD 两行、复盘大弹窗、命名弹窗。
- [ ] **Step 5: 提交** E2E 记录（脚本输出存档）`git commit -m "test: 大厅升级 E2E 验证"`

## Self-Review 记录

- Spec 覆盖：§1→Task7，§2→Task1，§3→Task11，§4→Task8，§5→Task3/4/10，§6→Task6/9，§7→Task2/4/5。✅
- 类型一致性：`planned_tools`(后端)→`plannedTools`(store)；`save_strategy(name)`；`run_state.mode`；`agentSession` 字段与 Task 6 载荷一致。✅
