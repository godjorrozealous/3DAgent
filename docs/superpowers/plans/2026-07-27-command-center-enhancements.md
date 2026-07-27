# 指挥室增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 布局优化 + 报告双摘要/比对 + 模板与策略管理 + 保存提醒 + 交互式复盘（结果级阻塞方案 A）

**Architecture:** 沿用现有链路（前端 :5173 → 编排后端 :8100 → PLDiagnosis :5000 → MCP :8001-8004 → Mock :8000）。后端 AgentManager 增加：report_summary 事件、干预追踪、复盘确认队列、异议下发、审核循环、模板/策略转发；前端新增 3 个弹窗组件、重写 ReportViewer、ChatModal 内嵌管理区块、3D 策略浮牌。

**Tech Stack:** FastAPI + httpx + asyncio（后端）；Vue3 + Tailwind + Three.js（前端）；pytest + pytest-asyncio（后端单测）。

**Spec:** `docs/superpowers/specs/2026-07-27-command-center-enhancements-design.md`

## Global Constraints

- 项目**非 git 仓库**：省略 commit 步骤，以任务完成 + 验证脚本通过作为检查点。
- 后端 venv：`backend/.venv`（Python 3.11）；启动 `cd backend && .venv/bin/python -m uvicorn main:app --port 8100`。
- 前端禁止破坏现有 WS 事件（init/agent_status/log/chat/report/session_snapshot/strategy_saved/replay_compare）。
- 与 PLD 的所有交互只经 `backend/pld_client.py`，禁止前端直连 :5000。
- 干预界定：仅操作性干预（exclude/include/adjust_weight/recheck/modify_report/模板变更/策略切换）。
- 复盘阻塞为**结果级**：SSE 流不暂停，确认队列在前端逐个强制处理。
- LLM 端点 Kimi k3 要求 temperature=1.0（vendor 配置已改好，勿动）。

## WS 协议（全部任务的契约）

**后端 → 前端（新增）:**

```json
{"type":"report_summary","kind":"realtime|replay","summary":{...},"report":"md","weights":{},"excluded_tools":[],"action_log":[],"time":"HH:MM:SS"}
{"type":"prompt_save_strategy","interventions":3,"context":"realtime|replay"}
{"type":"tool_confirm_request","agent":"lightning","tool":"LightningDiagnosisTool","fault_type":"雷击-绕击","confidence":0.985,"evidence":"...","override":null}
{"type":"report_review_request"}
{"type":"templates","templates":[{"name":"x.docx","is_active":true}]}
{"type":"skills","skills":[{"name":"comprehensive_diagnosis","description":"...","source":"系统","is_default":true}],"default_skill":"comprehensive_diagnosis"}
```

**前端 → 后端（新增）:**

```json
{"type":"list_templates"}   {"type":"activate_template","name":"x.docx"}   {"type":"delete_template","name":"x.docx"}
{"type":"list_skills"}      {"type":"activate_skill","name":"s"}           {"type":"reset_skills"}
{"type":"tool_confirm_response","tool":"LightningDiagnosisTool","decision":"ok|recheck|exclude|weight|override","value":"可选:权重数值或改值文本"}
{"type":"report_review_response","satisfied":true,"instruction":"可选"}
{"type":"save_prompt_response","save":true}
```

模板文件上传走 REST：`POST http://localhost:8100/api/templates/upload`（multipart，后端转发 PLD）。

---

### Task 1: pld_client 增加策略/模板 API + 单测基建

**Files:**
- Modify: `backend/pld_client.py`
- Create: `backend/tests/test_pld_client.py`
- Modify: `backend/tests/__init__.py`（新建空文件）

**Interfaces:**
- Produces（后续任务依赖的精确签名）:
  - `async def list_skills() -> dict` → `{"skills":[...]}`
  - `async def get_default_skill() -> dict` → `{"default_skill":str,"available_skills":[...]}`
  - `async def set_default_skill(name: str) -> dict`
  - `async def reset_skills() -> dict`
  - `async def list_templates() -> dict` → `{"templates":[...]}`
  - `async def upload_template(file_bytes: bytes, filename: str) -> dict`
  - `async def activate_template(name: str) -> dict`
  - `async def delete_template(name: str) -> dict`

- [ ] **Step 1: 安装测试依赖**

```bash
cd "/Users/bei/DEVLOPE/3d agent/backend" && .venv/bin/python -m pip install pytest pytest-asyncio 2>&1 | tail -2 || uv pip install --python .venv/bin/python pytest pytest-asyncio
```

并在 `backend/tests/__init__.py` 旁创建 `backend/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 2: 写失败测试** `backend/tests/test_pld_client.py`

```python
import httpx
import pytest
import pld_client


class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append((request.method, request.url.path))
        key = (request.method, request.url.path)
        body = self.routes.get(key, {"ok": True})
        return httpx.Response(200, json=body)


@pytest.fixture
def mock_transport(monkeypatch):
    routes = {
        ("GET", "/api/skills"): {"skills": [{"name": "s1"}]},
        ("GET", "/api/skills/default"): {"default_skill": "s1", "available_skills": ["s1"]},
        ("POST", "/api/skills/default"): {"success": True, "default_skill": "s1"},
        ("POST", "/api/skills/reset"): {"success": True},
        ("GET", "/api/templates"): {"templates": [{"name": "t.docx", "is_active": False}]},
        ("POST", "/api/templates/upload"): {"success": True, "template": {"name": "t.docx"}},
        ("POST", "/api/templates/activate"): {"success": True, "active_template": "t.docx"},
        ("DELETE", "/api/templates/t.docx"): {"success": True},
    }
    transport = MockTransport(routes)
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw["transport"] = transport
        return real(*a, **kw)

    monkeypatch.setattr(pld_client.httpx, "AsyncClient", factory)
    return transport


async def test_skills_and_templates(mock_transport):
    assert (await pld_client.list_skills())["skills"][0]["name"] == "s1"
    assert (await pld_client.get_default_skill())["default_skill"] == "s1"
    assert (await pld_client.set_default_skill("s1"))["success"] is True
    assert (await pld_client.reset_skills())["success"] is True
    assert (await pld_client.list_templates())["templates"][0]["name"] == "t.docx"
    assert (await pld_client.upload_template(b"data", "t.docx"))["success"] is True
    assert (await pld_client.activate_template("t.docx"))["active_template"] == "t.docx"
    assert (await pld_client.delete_template("t.docx"))["success"] is True
    methods = [m for m, _ in mock_transport.requests]
    assert "DELETE" in methods and "POST" in methods
```

- [ ] **Step 3: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pld_client.py -v`
Expected: FAIL `AttributeError: module 'pld_client' has no attribute 'list_skills'`

- [ ] **Step 4: 实现**（追加到 `backend/pld_client.py`，复用文件已有 `PLD_BASE` 与超时风格）

```python
# ---------- 策略（技能） ----------
async def list_skills() -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.get("/api/skills")).json()


async def get_default_skill() -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.get("/api/skills/default")).json()


async def set_default_skill(name: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.post("/api/skills/default", json={"name": name})).json()


async def reset_skills() -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.post("/api/skills/reset")).json()


# ---------- 模板 ----------
async def list_templates() -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.get("/api/templates")).json()


async def upload_template(file_bytes: bytes, filename: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=60) as c:
        files = {"file": (filename, file_bytes)}
        return (await c.post("/api/templates/upload", files=files)).json()


async def activate_template(name: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.post("/api/templates/activate", json={"template_name": name})).json()


async def delete_template(name: str) -> dict:
    async with httpx.AsyncClient(base_url=PLD_BASE, timeout=30) as c:
        return (await c.delete(f"/api/templates/{name}")).json()
```

- [ ] **Step 5: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pld_client.py -v`
Expected: 1 passed

---

### Task 2: report_summary 事件（双摘要数据源）

**Files:**
- Modify: `backend/agent_manager.py`（`_finish_run` / `run_diagnosis`）
- Test: `backend/tests/test_agent_manager.py`

**Interfaces:**
- Consumes: `pld_client.get_session(session_id) -> dict`（含 `action_log`/`active_weights`/`excluded_tools`/`status`）
- Produces: WS 事件 `report_summary`（见协议表）；`AgentManager.last_summaries: dict[str, dict]`，键 `"realtime"|"replay"`，值为完整 report_summary 事件体（供复盘比对与后续任务读取）。

- [ ] **Step 1: 写失败测试** `backend/tests/test_agent_manager.py`

```python
import json
import pytest
import agent_manager


class FakeWS:
    def __init__(self):
        self.events = []

    async def send_json(self, e):
        self.events.append(e)

    # WebSocket 协议兼容
    async def accept(self):
        pass


def make_manager(monkeypatch, stream_events, session):
    async def fake_stream(msg):
        for e in stream_events:
            yield e

    async def fake_session(sid):
        return session

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


COMPLETE_STREAM = [
    {"event_type": "start", "payload": {}, "session_id": "s1"},
    {"event_type": "complete", "payload": {
        "report": "# 报告", "summary": {"fault_type": "雷击-绕击", "confidence": 0.98}},
     "session_id": "s1"},
]

SESSION = {"status": "modifying", "active_weights": {"LightningDiagnosisTool": 1.0},
           "excluded_tools": [], "action_log": []}


async def test_report_summary_event(monkeypatch):
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION)
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.run_diagnosis(replay=False)
    rs = [e for e in ws.events if e["type"] == "report_summary"]
    assert len(rs) == 1
    assert rs[0]["kind"] == "realtime"
    assert rs[0]["summary"]["fault_type"] == "雷击-绕击"
    assert rs[0]["report"] == "# 报告"
    assert "action_log" in rs[0] and "weights" in rs[0]
    assert mgr.last_summaries["realtime"]["summary"]["confidence"] == 0.98


async def test_report_summary_replay_kind(monkeypatch):
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=True)
    rs = [e for e in ws.events if e["type"] == "report_summary"]
    assert rs[0]["kind"] == "replay"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_manager.py -v`
Expected: FAIL（无 report_summary 事件）

- [ ] **Step 3: 实现**

`backend/agent_manager.py` `__init__` 增加：

```python
        self.last_summaries: dict[str, dict] = {}   # "realtime"|"replay" -> report_summary 事件体
```

`_finish_run` 中 `self.run_history.append(run_record)` 之后、状态日志之前插入：

```python
        kind = "replay" if replay else "realtime"
        summary_event = {
            "type": "report_summary",
            "kind": kind,
            "summary": summary,
            "report": run_record.get("report", ""),
            "weights": weights,
            "excluded_tools": excluded,
            "action_log": (session or {}).get("action_log", []),
            "time": run_record["time"],
        }
        self.last_summaries[kind] = summary_event
        await self.broadcast(summary_event)
```

注意：`_finish_run` 当前签名 `(self, run_record, summary, replay)`，`session` 变量已在函数内获取，直接可用。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_manager.py -v`
Expected: 2 passed

---

### Task 3: 干预追踪 + prompt_save_strategy

**Files:**
- Modify: `backend/agent_manager.py`
- Test: `backend/tests/test_agent_manager.py`（追加）

**Interfaces:**
- Produces:
  - `AgentManager.local_interventions: int`（模板/策略类操作计数，Task 4 递增）
  - WS 事件 `prompt_save_strategy`（见协议表）
  - `AgentManager._count_interventions(session_before: int, session: dict) -> int`：返回 `(len(session.action_log) - session_before) + self.local_interventions`

- [ ] **Step 1: 写失败测试（追加）**

```python
SESSION_WITH_ACTIONS = {"status": "modifying", "active_weights": {},
                        "excluded_tools": ["BirdDamageDiagnosisTool"],
                        "action_log": [{"action_type": "exclude", "parameters": {}}]}


async def test_prompt_save_strategy_on_intervention(monkeypatch):
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION_WITH_ACTIONS)
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.run_diagnosis(replay=False)
    prompts = [e for e in ws.events if e["type"] == "prompt_save_strategy"]
    assert len(prompts) == 1
    assert prompts[0]["interventions"] >= 1
    assert prompts[0]["context"] == "realtime"


async def test_no_prompt_without_intervention(monkeypatch):
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION)
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.run_diagnosis(replay=False)
    assert not [e for e in ws.events if e["type"] == "prompt_save_strategy"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_manager.py -k prompt -v`
Expected: FAIL（无 prompt_save_strategy 事件）

- [ ] **Step 3: 实现**

`__init__` 增加：

```python
        self.local_interventions: int = 0        # 模板/策略类操作（PLD action_log 之外的干预）
        self._action_count_at_start: int = 0     # 本轮开始时 PLD action_log 长度
```

`run_diagnosis` 在 `await self._wait_pld_idle()` 之后插入（记录基线并清零本地计数）：

```python
            try:
                if self.session_id:
                    pre = await pld_client.get_session(self.session_id)
                    self._action_count_at_start = len((pre or {}).get("action_log", []))
            except Exception:
                self._action_count_at_start = 0
            self.local_interventions = 0
```

新增方法：

```python
    def _count_interventions(self, session: dict | None) -> int:
        delta = len((session or {}).get("action_log", [])) - self._action_count_at_start
        return max(delta, 0) + self.local_interventions
```

`_finish_run` 在 broadcast `session_snapshot` 之后插入：

```python
        n = self._count_interventions(session)
        if n > 0:
            await self.broadcast({
                "type": "prompt_save_strategy",
                "interventions": n,
                "context": "replay" if replay else "realtime",
            })
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_manager.py -v`
Expected: 4 passed

---

### Task 4: 模板/策略 WS 转发 + REST 上传代理

**Files:**
- Modify: `backend/agent_manager.py`（`handle_message` + 新方法）
- Modify: `backend/main.py`（REST 上传代理）
- Test: `backend/tests/test_agent_manager.py`（追加）

**Interfaces:**
- Consumes: Task 1 全部 pld_client 函数。
- Produces:
  - `AgentManager.send_templates(ws=None)` → 广播/单发 `templates` 事件（templates 项附带 `is_active`：比较 PLD 返回项的 `is_active` 字段或当前会话 `active_template_name`）
  - `AgentManager.send_skills()` → 广播 `skills` 事件（含 `default_skill`）
  - WS 入站消息处理：`list_templates/activate_template/delete_template/list_skills/activate_skill/reset_skills`
  - REST: `POST /api/templates/upload`（8100 代理）
  - 副作用：`activate_template` 触发自动重整（向 PLD 发 modify_report 指令）；模板/策略操作递增 `local_interventions` 并广播 `session_snapshot` 刷新。

- [ ] **Step 1: 写失败测试（追加）**

```python
async def test_skill_and_template_messages(monkeypatch):
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION)
    calls = []

    async def fake_send(msg):  # 捕获自动重整指令
        calls.append(msg)
        return
        yield  # pragma: no cover

    async def fake_stream(msg):
        calls.append(msg)
        yield {"event_type": "complete", "payload": {"report": "r", "summary": {}}, "session_id": "s1"}

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "list_templates",
                        lambda: {"templates": [{"name": "t.docx", "is_active": False}]})
    monkeypatch.setattr(agent_manager.pld_client, "activate_template",
                        lambda name: {"success": True, "active_template": name})
    monkeypatch.setattr(agent_manager.pld_client, "list_skills",
                        lambda: {"skills": [{"name": "s1", "description": "d", "is_default": True, "source": "系统"}]})
    monkeypatch.setattr(agent_manager.pld_client, "get_default_skill",
                        lambda: {"default_skill": "s1", "available_skills": ["s1"]})
    monkeypatch.setattr(agent_manager.pld_client, "set_default_skill",
                        lambda name: {"success": True})

    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "list_templates"})
    assert any(e["type"] == "templates" for e in ws.events)
    await mgr.handle_message({"type": "list_skills"})
    skills_ev = [e for e in ws.events if e["type"] == "skills"]
    assert skills_ev and skills_ev[0]["default_skill"] == "s1"
    await mgr.handle_message({"type": "activate_skill", "name": "s1"})
    assert mgr.local_interventions == 1
    await mgr.handle_message({"type": "activate_template", "name": "t.docx"})
    assert mgr.local_interventions == 2
    assert any("模板" in c for c in calls)  # 自动重整指令已下发
```

注意 `monkeypatch.setattr` 对 async 函数需用 `async def` 版本；上面 lambda 返回 dict 的地方要包一层：

```python
def areturn(value):
    async def f(*a, **kw):
        return value
    return f
```

将各 lambda 替换为 `areturn({...})` 形式（`fake_stream` 保持异步生成器）。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_manager.py -k skill_and_template -v`
Expected: FAIL（`templates`/`skills` 事件不存在，无 local_interventions 变化）

- [ ] **Step 3: 实现**（`backend/agent_manager.py`）

`handle_message` 末尾追加分支：

```python
        elif mtype == "list_templates":
            await self.send_templates()
        elif mtype == "activate_template":
            await self.activate_template(str(data.get("name", "")))
        elif mtype == "delete_template":
            await pld_client.delete_template(str(data.get("name", "")))
            await self.send_templates()
        elif mtype == "list_skills":
            await self.send_skills()
        elif mtype == "activate_skill":
            name = str(data.get("name", ""))
            await pld_client.set_default_skill(name)
            self.local_interventions += 1
            await self.log("commander", f"诊断策略已切换为「{name}」（全局默认）。")
            await self.send_skills()
        elif mtype == "reset_skills":
            await pld_client.reset_skills()
            self.local_interventions += 1
            await self.log("commander", "已重置为默认诊断策略。")
            await self.send_skills()
            await self._refresh_snapshot()
        elif mtype == "save_prompt_response":
            if data.get("save"):
                await self.save_strategy()
```

新增方法：

```python
    async def send_templates(self):
        try:
            data = await pld_client.list_templates()
            await self.broadcast({"type": "templates", "templates": data.get("templates", [])})
        except Exception as exc:  # noqa: BLE001
            await self.log("audit", f"模板列表获取失败:{exc}")

    async def send_skills(self):
        try:
            skills = (await pld_client.list_skills()).get("skills", [])
            default = (await pld_client.get_default_skill()).get("default_skill", "")
            await self.broadcast({"type": "skills", "skills": skills, "default_skill": default})
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"策略列表获取失败:{exc}")

    async def activate_template(self, name: str):
        if not name:
            return
        result = await pld_client.activate_template(name)
        if not result.get("success"):
            await self.log("audit", f"模板「{name}」激活失败。")
            return
        self.local_interventions += 1
        await self.log("audit", f"模板「{name}」已激活，按模板章节结构重整报告……")
        await self.send_templates()
        # 激活即重整：走 modify_report 意图
        async for event in pld_client.chat_stream("请严格按当前激活模板的章节结构重整当前诊断报告"):
            if event.get("event_type") == "complete":
                report = event.get("payload", {}).get("report")
                if report:
                    self.last_report = report
                    await self.broadcast({"type": "report", "content": report, "done": True})
        await self._refresh_snapshot()
```

`backend/main.py` 增加 REST 代理（文件顶部 import 处加 `from fastapi import UploadFile`，并 `import pld_client`）:

```python
@app.post("/api/templates/upload")
async def upload_template_proxy(file: UploadFile):
    data = await file.read()
    return await pld_client.upload_template(data, file.filename or "template.md")
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_manager.py -v`
Expected: 5 passed

---

### Task 5: 复盘确认队列 + 异议下发 + 手动改值

**Files:**
- Modify: `backend/agent_manager.py`
- Test: `backend/tests/test_replay_flow.py`

**Interfaces:**
- Produces:
  - `AgentManager.pending_confirms: dict[str, dict]`（tool → 待确认的 tool_confirm_request 体）
  - `AgentManager.confirm_decisions: dict[str, dict]`（tool → {decision, value?}）
  - `AgentManager.value_overrides: dict[str, str]`（tool → 改后数值文本，随 session_snapshot 下发为 `overrides` 字段）
  - `AgentManager._dispatch_objections() -> None`：按 confirm_decisions 顺序下发 recheck/exclude/adjust_weight/modify_report 指令
  - WS 入站：`tool_confirm_response`；WS 出站：`tool_confirm_request`（协议表）

- [ ] **Step 1: 写失败测试** `backend/tests/test_replay_flow.py`

```python
import asyncio
import pytest
import agent_manager
from test_agent_manager import FakeWS  # tests 包内复用


RESULT_STREAM = [
    {"event_type": "start", "payload": {}, "session_id": "s1"},
    {"event_type": "result", "payload": {
        "tool": "LightningDiagnosisTool",
        "output": {"structured_data": {"fault_type": "雷击-绕击", "confidence": 0.985,
                                       "evidence": ["证据A"]}, "raw_text": "raw"}},
     "session_id": "s1"},
    {"event_type": "complete", "payload": {
        "report": "# 复盘报告", "summary": {"fault_type": "雷击-绕击", "confidence": 0.9}},
     "session_id": "s1"},
]

SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, sent):
    async def fake_stream(msg):
        sent.append(msg)
        for e in RESULT_STREAM:
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_replay_emits_confirm_and_dispatches_objection(monkeypatch):
    sent = []
    mgr = make_mgr(monkeypatch, sent)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "exclude"})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    confirms = [e for e in ws.events if e["type"] == "tool_confirm_request"]
    assert len(confirms) == 1
    assert confirms[0]["tool"] == "LightningDiagnosisTool"
    assert confirms[0]["fault_type"] == "雷击-绕击"
    assert mgr.confirm_decisions["LightningDiagnosisTool"]["decision"] == "exclude"
    # 异议已下发（exclude 指令文本）
    assert any("排除" in m for m in sent[1:])  # sent[0] 是诊断消息本身


async def test_realtime_no_confirm(monkeypatch):
    sent = []
    mgr = make_mgr(monkeypatch, sent)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    assert not [e for e in ws.events if e["type"] == "tool_confirm_request"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_replay_flow.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**（`backend/agent_manager.py`）

`__init__` 增加：

```python
        self.pending_confirms: dict[str, dict] = {}
        self.confirm_decisions: dict[str, dict] = {}
        self.value_overrides: dict[str, str] = {}
        self._confirms_done: asyncio.Event | None = None
```

`handle_message` 增加分支：

```python
        elif mtype == "tool_confirm_response":
            tool = str(data.get("tool", ""))
            if tool in self.pending_confirms:
                self.confirm_decisions[tool] = {
                    "decision": data.get("decision", "ok"),
                    "value": data.get("value"),
                }
                del self.pending_confirms[tool]
                if not self.pending_confirms and self._confirms_done:
                    self._confirms_done.set()
```

`run_diagnosis` 在 `etype == "result"` 分支末尾（推送子报告之后）增加：

```python
                        if replay and aid:
                            self.pending_confirms[tool] = {
                                "type": "tool_confirm_request",
                                "agent": aid, "tool": tool,
                                "fault_type": fault, "confidence": conf,
                                "evidence": evid,
                                "override": self.value_overrides.get(tool),
                            }
                            await self.broadcast(self.pending_confirms[tool])
```

`run_diagnosis` 的 `etype == "complete"` 分支中，`_finish_run` 调用前插入（仅 replay）：

```python
                    if replay:
                        self._confirms_done = asyncio.Event()
                        if self.pending_confirms:
                            await self.log("commander", "等待指挥员逐项确认各工具诊断结果……")
                            try:
                                await asyncio.wait_for(self._confirms_done.wait(), timeout=1800)
                            except asyncio.TimeoutError:
                                await self.log("commander", "确认等待超时，按无异议继续。")
                                self.pending_confirms.clear()
                        await self._dispatch_objections()
```

新增异议下发：

```python
    async def _dispatch_objections(self):
        """复盘确认后的异议处理：逐条下发 PLD（recheck/exclude/adjust_weight/手动改值）。"""
        objections = {t: d for t, d in self.confirm_decisions.items() if d["decision"] != "ok"}
        self.confirm_decisions.clear()
        if not objections:
            return
        final_report = None
        for tool, d in objections.items():
            await self._wait_pld_idle()
            decision, value = d["decision"], d.get("value")
            if decision == "recheck":
                cmd = f"重新检查{tool}"
            elif decision == "exclude":
                cmd = f"排除{tool}"
            elif decision == "weight":
                cmd = f"将{tool}权重调整为{value}"
            elif decision == "override":
                self.value_overrides[tool] = str(value)
                cmd = f"修改报告：将{tool}相关数值修正为{value}"
            else:
                continue
            await self.log("commander", f"下发复盘异议:{cmd}")
            try:
                async for event in pld_client.chat_stream(cmd):
                    p = event.get("payload", {})
                    if event.get("event_type") == "complete" and p.get("report"):
                        final_report = p["report"]
            except Exception as exc:  # noqa: BLE001
                await self.log("commander", f"异议下发失败({tool}):{exc}")
        if final_report:
            self.last_report = final_report
            await self.broadcast({"type": "report", "content": final_report, "done": True})
        await self._refresh_snapshot()
```

`session_snapshot` 广播处（`_finish_run` 与 `_refresh_snapshot`）增加 `"overrides": self.value_overrides` 字段。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/ -v`
Expected: 全部 passed（含此前 5 个）

---

### Task 6: 复盘报告审核循环

**Files:**
- Modify: `backend/agent_manager.py`
- Test: `backend/tests/test_replay_flow.py`（追加）

**Interfaces:**
- Produces: WS 出站 `report_review_request`；WS 入站 `report_review_response {satisfied, instruction?}`；循环上限 5 轮（防死循环）。

- [ ] **Step 1: 写失败测试（追加）**

```python
async def test_report_review_loop(monkeypatch):
    sent = []
    mgr = make_mgr(monkeypatch, sent)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        # 第一轮:不满意,要求删第三章
        await mgr.handle_message({"type": "report_review_response",
                                  "satisfied": False, "instruction": "删除第三章"})
        await asyncio.sleep(0.3)
        # 第二轮:满意
        await mgr.handle_message({"type": "report_review_response",
                                  "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    reviews = [e for e in ws.events if e["type"] == "report_review_request"]
    assert len(reviews) == 2
    assert any("删除第三章" in m for m in sent[1:])
```

注意：本测试流中无 result 事件时 `pending_confirms` 为空，确认阶段直接跳过；测试用的 `make_mgr` 流包含一个 result，因此 respond 需先发一条 tool_confirm_response。相应调整：在 respond() 开头加 `await mgr.handle_message({"type":"tool_confirm_response","tool":"LightningDiagnosisTool","decision":"ok"})`。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_replay_flow.py -k review_loop -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`__init__` 增加 `self._review_event: asyncio.Event | None = None`、`self._review_response: dict = {}`。

`handle_message` 增加：

```python
        elif mtype == "report_review_response":
            self._review_response = data
            if self._review_event:
                self._review_event.set()
```

`run_diagnosis` 的 replay 分支在 `_dispatch_objections()` 之后插入：

```python
                        for _ in range(5):
                            await self.broadcast({"type": "report_review_request"})
                            self._review_event = asyncio.Event()
                            self._review_response = {}
                            try:
                                await asyncio.wait_for(self._review_event.wait(), timeout=1800)
                            except asyncio.TimeoutError:
                                break
                            if self._review_response.get("satisfied"):
                                break
                            instruction = str(self._review_response.get("instruction", "")).strip()
                            if not instruction:
                                break
                            await self.log("audit", f"按指挥员意见修改报告:{instruction}")
                            await self._wait_pld_idle()
                            async for ev in pld_client.chat_stream(instruction):
                                p = ev.get("payload", {})
                                if ev.get("event_type") == "complete" and p.get("report"):
                                    self.last_report = p["report"]
                                    await self.broadcast({"type": "report", "content": p["report"], "done": True})
```

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/ -v`
Expected: 全部 passed

---

### Task 7: 前端 store/ws 协议层

**Files:**
- Modify: `frontend/src/store.js`
- Modify: `frontend/src/ws.js`

**Interfaces:**
- Produces（UI 任务依赖）:
  - `store.summaries = { realtime: null, replay: null }`（report_summary 事件体）
  - `store.templates = []`、`store.skills = []`、`store.defaultSkill = ''`
  - `store.confirmQueue = []`（tool_confirm_request 数组，响应后 shift）
  - `store.savePrompt = null | {interventions, context}`
  - `store.reportReviewPending = false`
  - `store.reportModal = null | {title, content}`、`store.compareOpen = false`
  - `store.valueOverrides = {}`（session_snapshot.overrides）
  - ws.js 发送方法：`listTemplates()/activateTemplate(name)/deleteTemplate(name)/listSkills()/activateSkill(name)/resetSkills()/sendToolConfirm(tool, decision, value?)/sendReportReview(satisfied, instruction?)/respondSavePrompt(save)`

- [ ] **Step 1: store.js 增字段**（在现有 reactive store 对象中追加）

```js
  summaries: { realtime: null, replay: null },
  templates: [],
  skills: [],
  defaultSkill: '',
  confirmQueue: [],
  savePrompt: null,
  reportReviewPending: false,
  reportModal: null,
  compareOpen: false,
  valueOverrides: {},
```

- [ ] **Step 2: ws.js onEvent 分发增加**

```js
    if (e.type === 'report_summary') {
      store.summaries[e.kind] = e
    } else if (e.type === 'prompt_save_strategy') {
      store.savePrompt = { interventions: e.interventions, context: e.context }
    } else if (e.type === 'tool_confirm_request') {
      store.confirmQueue.push(e)
    } else if (e.type === 'report_review_request') {
      store.reportReviewPending = true
    } else if (e.type === 'templates') {
      store.templates = e.templates
    } else if (e.type === 'skills') {
      store.skills = e.skills; store.defaultSkill = e.default_skill
    } else if (e.type === 'session_snapshot') {
      // 保留现有 weights/excludedTools 逻辑,追加:
      store.valueOverrides = e.overrides || {}
    }
```

发送方法（沿用现有 send 风格）:

```js
export const listTemplates = () => send({ type: 'list_templates' })
export const activateTemplate = (name) => send({ type: 'activate_template', name })
export const deleteTemplate = (name) => send({ type: 'delete_template', name })
export const listSkills = () => send({ type: 'list_skills' })
export const activateSkill = (name) => send({ type: 'activate_skill', name })
export const resetSkills = () => send({ type: 'reset_skills' })
export const sendToolConfirm = (tool, decision, value) =>
  send({ type: 'tool_confirm_response', tool, decision, value })
export const sendReportReview = (satisfied, instruction) =>
  send({ type: 'report_review_response', satisfied, instruction })
export const respondSavePrompt = (save) =>
  send({ type: 'save_prompt_response', save })
```

- [ ] **Step 3: 验证构建**

Run: `cd frontend && npx vite build 2>&1 | tail -3`
Expected: built successfully

---

### Task 8: 布局 + 事件流滚动 + 3D 相机拉远

**Files:**
- Modify: `frontend/src/App.vue`（宽度 `w-[280px]`→`w-[340px]`、`w-[320px]`→`w-[460px]`）
- Modify: `frontend/src/components/EventStream.vue`（根容器加 `min-h-0`，消息列表 `flex-1 min-h-0 overflow-y-auto`）
- Modify: `frontend/src/three/CommandRoom.js`（相机初始位置拉远约 25%：找到相机 `position.set(...)`，各分量 ×1.25；或 controls 的初始 target 不变仅增大半径）

**Interfaces:**
- Consumes: 无新接口。

- [ ] **Step 1: App.vue 改两处宽度类**
- [ ] **Step 2: EventStream.vue 根元素确保 `class="...flex flex-col min-h-0"`，消息列表容器 `flex-1 min-h-0 overflow-y-auto`（现状若为 flex-1 无 min-h-0 则修正）；状态矩阵块保持原样（flex-none）**
- [ ] **Step 3: CommandRoom.js 相机 `position.set(x, y, z)` 三分量 ×1.25**
- [ ] **Step 4: 截图验证**

用 /tmp/shot/shot3.js 改输出名运行，确认：两侧加宽、3D 显小、状态矩阵固定在底部不被事件流挤压（可向事件流注入 50 条 mock log 再截一张）。

---

### Task 9: ReportViewer 重写 + ReportModal + CompareModal

**Files:**
- Modify: `frontend/src/components/ReportViewer.vue`（重写）
- Create: `frontend/src/components/ReportModal.vue`
- Create: `frontend/src/components/CompareModal.vue`
- Modify: `frontend/src/App.vue`（挂载两个新弹窗；移除 `<ReplayPanel/>`）
- Delete: `frontend/src/components/ReplayPanel.vue`

**Interfaces:**
- Consumes: `store.summaries`、`store.reportModal`、`store.compareOpen`、`store.LINES`。
- Produces: `SummaryCard` 内联组件（ReportViewer 内部）：props `{title, data}`。

- [ ] **Step 1: ReportModal.vue**——中央遮罩弹窗：`store.reportModal` 非空时显示 `{title, content}`，markdown 渲染（沿用现有 marked 渲染方式，若无则纯文本 pre-wrap），× 与遮罩点击关闭（`store.reportModal = null`）。
- [ ] **Step 2: CompareModal.vue**——`store.compareOpen` 时显示；从 `store.summaries.realtime/replay` 计算对比行（故障类型/置信度/主诊断工具/权重/排除列表），差异行 emerald 高亮 + 「生效」徽标（逻辑直接迁移自 ReplayPanel.vue 的 rows computed）；底部策略差异标签区（两卡 excluded/weights 的差集）。
- [ ] **Step 3: ReportViewer.vue 重写**：
  - 顶部线路标题行：`{{ store.LINES[0].line }} · {{ store.LINES[0].tower }}`
  - 两张摘要卡（实时/复盘）：线路名称/电压等级/故障时间/故障类型/置信度% + action_log 标签（字段缺失显示 —）；每卡「查看报告」→ `store.reportModal = {title, content: data.report}`；无数据卡显示占位（"等待诊断……" / "尚未复盘"）。
  - 底部「比对」按钮：`v-if="store.summaries.realtime && store.summaries.replay"` → `store.compareOpen = true`。
- [ ] **Step 4: App.vue 挂载 `<ReportModal/><CompareModal/>`，删除 ReplayPanel 引用与文件**
- [ ] **Step 5: 截图验证**——向 store 注入 mock summaries 后截图三张（双摘要卡/报告弹窗/比对弹窗）。

---

### Task 10: ChatModal 内嵌模板管理（审核员）+ 策略管理（司令员）

**Files:**
- Modify: `frontend/src/components/ChatModal.vue`

**Interfaces:**
- Consumes: Task 7 全部 ws 方法与 `store.templates/skills/defaultSkill`；REST 上传 `fetch('/api/templates/upload', {method:'POST', body: FormData})`。
- Produces: 无新接口。

- [ ] **Step 1: 打开弹窗时按需拉取**：`watch(store.chatTarget)`，为 audit → `listTemplates()`；为 commander → `listSkills()`。
- [ ] **Step 2: 审核员模板区块**（消息区与输入区之间，`v-if="store.chatTarget==='audit'"`）：模板列表（名称 + 「当前激活」徽标 + 激活/删除按钮）；「+ 上传模板」隐藏 file input（.md/.docx/.pdf），FormData POST `/api/templates/upload`，完成后 `listTemplates()`。
- [ ] **Step 3: 司令员策略区块**（`v-if="store.chatTarget==='commander'"`）：策略列表（名称/描述/来源标签），激活按钮（`activateSkill(name)`，`defaultSkill===name` 显示「已激活」）；「重置默认」按钮（`resetSkills()`）。
- [ ] **Step 4: 截图验证**——mock store.templates/skills 后双击席位截图两个弹窗。

---

### Task 11: 策略 HUD 信息卡 + 3D 策略浮牌

**Files:**
- Modify: `frontend/src/App.vue`（顶栏下方信息卡）
- Modify: `frontend/src/three/CommandRoom.js`（司令员席位旁浮牌）

**Interfaces:**
- Consumes: `store.defaultSkill`、`store.weights`、`store.excludedTools`（现有）、`store.sessionId`；CommandRoom 需暴露 `updateStrategy(text)` 方法，由 App.vue 的 onEvent 在 session_snapshot/skills 事件时调用。

- [ ] **Step 1: HUD 信息卡**：顶栏下方居中偏左小卡——「策略：{{ store.defaultSkill || '默认' }}」+ 排除工具红标签 + 非默认权重琥珀标签（迁移现有 TopBar 干预 chips 逻辑，TopBar 中重复的可移除）。
- [ ] **Step 2: 3D 浮牌**：CommandRoom.js 中司令员席位（[0,0,-8]）旁加 canvas 纹理 Plane（约 3.2×1.6，位置 [3.4, 2.6, -8]，面向相机），`updateStrategy(text)` 重绘纹理；App.vue 中 room 实例暴露并在 session_snapshot 时拼文本（策略名 + 排除 ×N + 权重非默认项）调用。
- [ ] **Step 3: 截图验证**——mock 策略数据后截图确认 HUD 卡与 3D 浮牌。

---

### Task 12: 三个交互弹窗（保存提醒/工具确认/审核确认）

**Files:**
- Create: `frontend/src/components/SavePromptModal.vue`
- Create: `frontend/src/components/ConfirmToolModal.vue`
- Create: `frontend/src/components/ReportReviewModal.vue`
- Modify: `frontend/src/App.vue`（挂载）

**Interfaces:**
- Consumes: `store.savePrompt/confirmQueue/reportReviewPending`;`respondSavePrompt/sendToolConfirm/sendReportReview`。

- [ ] **Step 1: SavePromptModal**：`store.savePrompt` 非空时显示（指挥部中部，bottom-1/3 居中）；文案「本轮存在 {{interventions}} 项人工干预，是否保存为诊断策略？」；「保存策略」→ `respondSavePrompt(true)` + 置空；「忽略」→ `respondSavePrompt(false)` + 置空。
- [ ] **Step 2: ConfirmToolModal**：`store.confirmQueue[0]` 存在时显示；展示工具中文名/倾向/置信度/证据（override 存在时显示"已改值：xxx"）；按钮区：「无异议」→ `sendToolConfirm(tool,'ok')` 后 shift 队列；「有异议」展开四个选项：重新检查(recheck)/数据不对去掉(exclude)/调整权重(weight+数值输入)/手动改值(override+文本输入)，确认后 `sendToolConfirm(tool, decision, value)` 并 shift。
- [ ] **Step 3: ReportReviewModal**：`store.reportReviewPending` 时显示；「查看报告」→ 打开 ReportModal 显示 replay 报告；「符合要求」→ `sendReportReview(true)` + 置 false；「有意见」+ 文本输入 → `sendReportReview(false, instruction)` + 置 false。
- [ ] **Step 4: 截图验证**——mock 三个状态各截一张。

---

### Task 13: E2E 验证 + 最终截图

**Files:**
- Create: `/tmp/e2e_interactive_replay.py`

- [ ] **Step 1: E2E 脚本**：WS 连 8100 → start_diagnosis → 等 report_summary(realtime) → chat 干预（排除鸟害）→ 等 prompt_save_strategy → save_prompt_response(save=true) → 等 strategy_saved → replay → 每收到 tool_confirm_request 回复（第一个 exclude、其余 ok）→ 等 report_review_request → 第一轮（satisfied=false, instruction="删除第三章"）→ 第二轮 satisfied=true → 等 report_summary(replay) → 断言：两 kind 摘要齐备、复盘 action_log 非空、prompt_save_strategy 出现。
- [ ] **Step 2: 全量单测**：`cd backend && .venv/bin/python -m pytest tests/ -v` 全绿。
- [ ] **Step 3: 前端截图**：运行态（事件中 + 双摘要 + 比对）三连截。
- [ ] **Step 4: 恢复/确认六服务全部在线**（8100/5000/8000/8001-8004/5173）。

---

## Self-Review 记录

- Spec 覆盖：§1 布局/滚动 → Task 8；§2 报告栏 → Task 2/9；§3 审核员 → Task 4/10；§4 司令员 → Task 3/4/10/11/12(SavePrompt)；§5 复盘 → Task 5/6/12/13；协议契约 → Global 协议表。
- 已知取舍：replay_compare 事件后端保留但前端不再使用（CompareModal 改由双 summary 本地计算）；首轮实时诊断不弹确认（按用户决策）。
