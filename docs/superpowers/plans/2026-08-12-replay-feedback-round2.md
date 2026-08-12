# 复盘反馈第二轮修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复盘四问题修复——无异议跨轮记忆(重跑不再重复确认)、data_overrides 结构化通道(用户数据进报告)、LLM 意图分类(对话异议语义路由)、历史记录删除(单删+多删+二次确认)。

**Architecture:** vendor/diagnosis-agent 增 data_overrides 会话字段+/chat 透传+报告 prompt 权威数据块+纯分类 /api/classify 端点;backend 增 ok_tools 跨轮记忆、重跑透传、_replay_agent_chat 意图映射重接、delete_records WS 路由;frontend HistoryView 增选择与删除 UI。

**Tech Stack:** Python 3.11、pytest、Vue 3 + Vite

**Spec:** `docs/superpowers/specs/2026-08-12-replay-feedback-round2-design.md`

## Global Constraints

- **嵌套仓库**:vendor/diagnosis-agent 是独立 git 仓(分支 mcp_version),vendor 改动在 vendor 仓提交;backend/frontend/docs 在外层仓提交。提交一律 `git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit`(不改 git config)
- vendor 测试:`cd vendor/diagnosis-agent && .venv/bin/python -m pytest tests/ -q`,全部 PASS 无回归
- backend 测试:`cd backend && .venv/bin/python -m pytest tests/ -q`,全部 PASS 无回归
- /api/classify 端点**零副作用**:不获取/创建会话、不执行命令、不写持久化
- data_overrides 缺省不传时 /chat 行为与报告 prompt 完全不变
- 实时诊断路径行为不变(ok_tools 仅复盘确认环节消费;data_overrides 实时侧为空)
- 既有 trail kind(weight/exclude/recheck/time_range/override/chat_override/report_modify)与 `_ITEM_LABELS` 语义不变;新 decision kind `report_modify` 复用既有 report_modify trail
- vendor `config/config.yaml` 本地含真实 API key,**不得提交**(仓内为占位符版本)

---

### Task 1(vendor): data_overrides 通道

**Files:**
- Modify: `vendor/diagnosis-agent/src/core/models.py`(DiagnosisSession 202 行 `report_overrides` 之后)
- Modify: `vendor/diagnosis-agent/src/interfaces/web.py`(/chat 74-78 解析、92/95/120 签名传递、151-162 会话获取后合并)
- Modify: `vendor/diagnosis-agent/src/application/commands/diagnose.py`(compose 调用 239-244)
- Modify: `vendor/diagnosis-agent/src/domain/report_composer.py`(compose 33-43、_build_prompt 116-124 与 180 行「## 诊断工具输出」之前)
- Test: `vendor/diagnosis-agent/tests/unit/test_data_overrides.py`(新建)

**Interfaces:**
- Consumes: 既有 `DiagnosisSession`(models.py:189)、`ReportComposer._build_prompt`、test_session_reset.py 的 client fixture 模式
- Produces: `session.data_overrides: Dict[str, str]`(Task 3 backend 经 /chat 写入);`compose(..., data_overrides=None)`;`/chat` 请求体新可选字段 `data_overrides`

- [ ] **Step 1: 写失败测试**

新建 `vendor/diagnosis-agent/tests/unit/test_data_overrides.py`:

```python
"""data_overrides 结构化通道:会话字段 + /chat 合并 + 报告 prompt 权威数据块。"""

import pytest

from src.core.models import Intent, IntentType, SessionStatus
from src.domain.report_composer import ReportComposer
from src.interfaces.web import create_app
from src.interfaces.dependency_injection import get_container


@pytest.fixture
def client(monkeypatch):
    get_container.cache_clear()
    app = create_app()
    container = get_container()
    container.session_manager._sessions.clear()
    container.session_manager._active_session_id = None
    monkeypatch.setattr(container.session_manager, "repository", None)
    with app.test_client() as c:
        yield c, container
    get_container.cache_clear()


def test_session_model_has_data_overrides():
    """DiagnosisSession 新增 data_overrides 字段,默认空 dict。"""
    from src.core.models import DiagnosisSession
    s = DiagnosisSession(session_id="s1", line_name="雅湖线")
    assert s.data_overrides == {}
    s.data_overrides["WindDiagnosisTool"] = "风速15m/s"
    assert s.data_overrides["WindDiagnosisTool"] == "风速15m/s"


def test_chat_merges_data_overrides(client, monkeypatch):
    """/chat 携带 data_overrides → 合并进会话(后者覆盖前者);general 意图不执行命令。"""
    c, container = client
    s = container.session_manager.create("雅湖线")

    async def fake_classify(message, session=None):
        return Intent(intent_type=IntentType.GENERAL, confidence=1.0)

    monkeypatch.setattr(container.intent_classifier, "classify", fake_classify)
    resp = c.post("/chat", json={
        "message": "随便说说", "session_id": s.session_id,
        "data_overrides": {"WindDiagnosisTool": "风速15m/s,风偏角10度"}})
    assert resp.status_code == 200
    list(resp.iter_lines())  # 消费 SSE 流
    assert container.session_manager.get(s.session_id).data_overrides == {
        "WindDiagnosisTool": "风速15m/s,风偏角10度"}


def test_chat_without_data_overrides_unchanged(client, monkeypatch):
    """缺省不传 data_overrides:会话字段保持空,行为不变。"""
    c, container = client
    s = container.session_manager.create("雅湖线")

    async def fake_classify(message, session=None):
        return Intent(intent_type=IntentType.GENERAL, confidence=1.0)

    monkeypatch.setattr(container.intent_classifier, "classify", fake_classify)
    resp = c.post("/chat", json={"message": "随便说说", "session_id": s.session_id})
    assert resp.status_code == 200
    list(resp.iter_lines())
    assert container.session_manager.get(s.session_id).data_overrides == {}


def test_prompt_injects_authoritative_block_before_tool_outputs():
    """_build_prompt:权威数据块存在且位于「## 诊断工具输出」之前。"""
    composer = ReportComposer(llm_service=None)
    prompt = composer._build_prompt(
        {}, None, None, None, "", "",
        data_overrides={"WindDiagnosisTool": "风速15m/s,风偏角10度"})
    assert "用户提供的修正数据" in prompt
    assert "必须采纳" in prompt
    assert "WindDiagnosisTool: 风速15m/s,风偏角10度" in prompt
    assert prompt.index("用户提供的修正数据") < prompt.index("## 诊断工具输出")


def test_prompt_without_overrides_has_no_block():
    """data_overrides 为 None/空:无权威数据块(实时路径行为不变)。"""
    composer = ReportComposer(llm_service=None)
    for overrides in (None, {}):
        prompt = composer._build_prompt(
            {}, None, None, None, "", "", data_overrides=overrides)
        assert "用户提供的修正数据" not in prompt
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_data_overrides.py -v
```

预期:5 条全 FAIL(字段不存在 / TypeError: _build_prompt 无 data_overrides 参数)。

- [ ] **Step 3: 实现**

① `src/core/models.py` DiagnosisSession(202 行 `report_overrides` 之后)插入:

```python
    data_overrides: Dict[str, str] = Field(default_factory=dict)
```

② `src/interfaces/web.py` 三处:

/chat 路由(74-78 行解析区)加:

```python
        data_overrides = data.get("data_overrides") or None
```

`_sync_chat_stream` 与 `_chat_stream` 签名加 `data_overrides: dict | None = None` 并逐层传递(84 行调用处、92-96 行、120 行)。

`_chat_stream` 在会话获取完成(151 行之后)、`_append_chat_message(session, "user", message)`(162 行)之前插入:

```python
            # 复盘数据修正通道:用户提供的权威数据合并进会话,报告生成时强制采纳
            if data_overrides:
                session.data_overrides.update(
                    {str(k): str(v) for k, v in data_overrides.items()})
```

(持久化由既有 259 行 `container.session_manager._persist()` 覆盖。)

③ `src/application/commands/diagnose.py` compose 调用(239-244)改为:

```python
        composed = await self.report_composer.compose(
            tool_outputs, None, session.session_id, fault_context, action_log_data,
            weights=session.active_weights,
            active_template_name=session.active_template_name,
            active_skill_name=session.active_skill_name,
            data_overrides=session.data_overrides or None,
        )
```

④ `src/domain/report_composer.py` 两处:

`compose()` 签名(33-43)加参数并在 68-70 透传:

```python
        data_overrides: Optional[Dict[str, str]] = None,
```

```python
        prompt = self._build_prompt(
            tool_outputs, fault_context, action_log, weights, template_md, skill_md,
            data_overrides=data_overrides,
        )
```

`_build_prompt` 签名(116-124)加 `data_overrides: Optional[Dict[str, str]] = None`;在「## 诊断工具输出」块(180 行 `lines.extend(["## 诊断工具输出", ""])` 之前)插入:

```python
        if data_overrides:
            lines.extend([
                "## 用户提供的修正数据(权威数据,必须采纳,优先级高于工具输出)",
                "",
                "以下数据由用户(指挥员)直接提供,为权威数据。涉及对应工具的章节分析与诊断结论"
                "必须以此数据为准;若与工具输出冲突,以用户数据为准。",
                "",
            ])
            for tool_name, value in data_overrides.items():
                lines.append(f"- {tool_name}: {value}")
            lines.append("")
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_data_overrides.py -v
.venv/bin/python -m pytest tests/ -q
```

预期:新测试全 PASS;全量 PASS 无回归。

- [ ] **Step 5: 提交(vendor 仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/diagnosis-agent"
git add src/core/models.py src/interfaces/web.py src/application/commands/diagnose.py src/domain/report_composer.py tests/unit/test_data_overrides.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat: data_overrides 结构化通道(会话字段+/chat合并+报告prompt权威数据块)"
```

---

### Task 2(vendor): /api/classify 纯分类端点

**Files:**
- Modify: `vendor/diagnosis-agent/src/interfaces/web.py`(reset 端点 426-444 之后)
- Test: `vendor/diagnosis-agent/tests/unit/test_classify_endpoint.py`(新建)

**Interfaces:**
- Consumes: `container.intent_classifier.classify(message, session)`(intent_classifier.py:22,纯 LLM 调用零副作用)、`Intent`(models.py:226:intent_type/confidence/parameters)、client fixture(test_data_overrides.py 同构)
- Produces: `POST /api/classify {message, session_id?} → {intent_type: str, confidence: float, parameters: dict}`(Task 4 backend pld_client.classify 消费)

- [ ] **Step 1: 写失败测试**

新建 `vendor/diagnosis-agent/tests/unit/test_classify_endpoint.py`:

```python
"""POST /api/classify:纯意图分类(零副作用),复盘对话异议的语义识别通道。"""

import pytest

from src.core.models import Intent, IntentType
from src.interfaces.web import create_app
from src.interfaces.dependency_injection import get_container


@pytest.fixture
def client(monkeypatch):
    get_container.cache_clear()
    app = create_app()
    container = get_container()
    container.session_manager._sessions.clear()
    container.session_manager._active_session_id = None
    monkeypatch.setattr(container.session_manager, "repository", None)
    with app.test_client() as c:
        yield c, container
    get_container.cache_clear()


def test_classify_returns_intent(client, monkeypatch):
    """正常分类:返回 intent_type/confidence/parameters;会话不变更。"""
    c, container = client

    async def fake_classify(message, session=None):
        assert session is None  # 未传 session_id
        return Intent(intent_type=IntentType.ADJUST_WEIGHT, confidence=0.95,
                      parameters={"tool_name": "LightningDiagnosisTool", "weight": 0.1})

    monkeypatch.setattr(container.intent_classifier, "classify", fake_classify)
    resp = c.post("/api/classify", json={"message": "调整雷电权重0.1"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"intent_type": "adjust_weight", "confidence": 0.95,
                    "parameters": {"tool_name": "LightningDiagnosisTool", "weight": 0.1}}
    assert container.session_manager._sessions == {}  # 零副作用:未创建会话


def test_classify_with_session_context(client, monkeypatch):
    """携带 session_id:取会话作分类上下文(不变更会话状态)。"""
    c, container = client
    s = container.session_manager.create("雅湖线")
    seen = {}

    async def fake_classify(message, session=None):
        seen["session"] = session
        return Intent(intent_type=IntentType.GENERAL, confidence=1.0)

    monkeypatch.setattr(container.intent_classifier, "classify", fake_classify)
    resp = c.post("/api/classify", json={"message": "风速10m/s", "session_id": s.session_id})
    assert resp.status_code == 200
    assert seen["session"].session_id == s.session_id
    assert resp.get_json()["intent_type"] == "general"


def test_classify_unknown_session_falls_back_none(client, monkeypatch):
    """session_id 取不到会话:按 None 上下文分类,不报错。"""
    c, container = client

    async def fake_classify(message, session=None):
        assert session is None
        return Intent(intent_type=IntentType.GENERAL, confidence=1.0)

    monkeypatch.setattr(container.intent_classifier, "classify", fake_classify)
    resp = c.post("/api/classify", json={"message": "x", "session_id": "sess_nope"})
    assert resp.status_code == 200


def test_classify_empty_message_400(client):
    """空消息 → 400。"""
    c, _ = client
    resp = c.post("/api/classify", json={"message": "  "})
    assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_classify_endpoint.py -v
```

预期:4 条 FAIL(404 路由不存在)。

- [ ] **Step 3: 实现**

`src/interfaces/web.py` reset 端点(426-444 行)之后插入:

```python
    @app.route("/api/classify", methods=["POST"])
    def classify_intent():
        """纯意图分类(零副作用):复盘对话异议的语义识别通道。

        不获取/创建会话、不执行任何命令、不写持久化;
        session_id 仅用于提取上下文参数(权重值/工具名)。
        """
        data = request.json or {}
        message = str(data.get("message", "")).strip()
        if not message:
            return jsonify({"error": "消息不能为空"}), 400
        session = None
        sid = str(data.get("session_id") or "").strip()
        if sid:
            try:
                session = container.session_manager.get(sid)
            except Exception:  # noqa: BLE001
                session = None
        intent = asyncio.run(container.intent_classifier.classify(message, session))
        return jsonify({
            "intent_type": intent.intent_type.value,
            "confidence": intent.confidence,
            "parameters": intent.parameters or {},
        })
```

(web.py 顶部已 `import asyncio`、`from flask import ... request, jsonify`,无需新增 import。)

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_classify_endpoint.py -v
.venv/bin/python -m pytest tests/ -q
```

预期:全 PASS。

- [ ] **Step 5: 提交(vendor 仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/diagnosis-agent"
git add src/interfaces/web.py tests/unit/test_classify_endpoint.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat: /api/classify 纯意图分类端点(零副作用,复盘对话语义识别通道)"
```

---

### Task 3(backend): ok_tools 跨轮记忆 + 重跑透传 data_overrides

**Files:**
- Modify: `backend/pld_client.py`(chat_stream 12-23 加参数;文件末尾加 classify)
- Modify: `backend/agent_manager.py`(`__init__` 93 行后、run_diagnosis 497 行区、tool_confirm_response 249-257、_stream_run 393-395 与 446-456、_replay_agent_chat 892 行区)
- Test: `backend/tests/test_ok_tools.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 /chat data_overrides 字段(运行时);Task 2 的 /api/classify(pld_client.classify 本任务落地,Task 4 消费)
- Produces: `mgr.ok_tools: set[str]`;`pld_client.chat_stream(..., data_overrides=None)`;`pld_client.classify(message, session_id=None) -> dict`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_ok_tools.py`:

```python
"""ok_tools 跨轮无异议记忆 + 重跑透传 data_overrides。"""
import asyncio

import agent_manager
from tests.test_agent_manager import FakeWS

RESULT_WIND = {"event_type": "result", "session_id": "s1", "payload": {
    "tool": "WindDiagnosisTool",
    "output": {"raw_text": "风偏报告", "structured_data": {
        "fault_type": "风偏", "confidence": 0.8, "evidence": ["e"]}}}}
RESULT_LIGHTNING = {"event_type": "result", "session_id": "s1", "payload": {
    "tool": "LightningDiagnosisTool",
    "output": {"raw_text": "雷电报告", "structured_data": {
        "fault_type": "雷击", "confidence": 0.9, "evidence": ["e"]}}}}
COMPLETE = {"event_type": "complete", "session_id": "s1", "payload": {
    "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}}}
SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, events, captured=None):
    async def fake_stream(msg, **kwargs):
        if captured is not None:
            captured.update(kwargs)
        for e in events:
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_ok_tool_auto_confirmed_on_rerun(monkeypatch):
    """重跑时 ok_tools 内工具:不广播确认弹窗,自动登记 ok 决策。"""
    mgr = make_mgr(monkeypatch, [RESULT_WIND, COMPLETE])
    mgr.ok_tools.add("WindDiagnosisTool")
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    summary = await mgr._stream_run("msg", True, {}, session_id="s1")
    assert not summary.get("_invalid")
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "ok"
    assert "WindDiagnosisTool" not in mgr.pending_confirms
    assert not any(e["type"] == "tool_confirm_request" for e in ws.events)


async def test_non_ok_tool_still_asks(monkeypatch):
    """不在 ok_tools 的工具:照常广播确认弹窗。"""
    mgr = make_mgr(monkeypatch, [RESULT_WIND, RESULT_LIGHTNING, COMPLETE])
    mgr.ok_tools.add("WindDiagnosisTool")
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.1)
        await mgr.handle_message({
            "type": "tool_confirm_response", "tool": "LightningDiagnosisTool",
            "decision": "ok"})

    await asyncio.gather(mgr._stream_run("msg", True, {}, session_id="s1"), respond())
    reqs = [e for e in ws.events if e["type"] == "tool_confirm_request"]
    assert [r["tool"] for r in reqs] == ["LightningDiagnosisTool"]


async def test_confirm_ok_populates_and_objection_discards(monkeypatch):
    """弹窗选无异议 → 进 ok_tools;对话异议 → 移出 ok_tools。"""
    mgr = make_mgr(monkeypatch, [])
    mgr.pending_confirms["WindDiagnosisTool"] = {"type": "tool_confirm_request"}
    await mgr.handle_message({
        "type": "tool_confirm_response", "tool": "WindDiagnosisTool", "decision": "ok"})
    assert "WindDiagnosisTool" in mgr.ok_tools
    mgr.pending_confirms["LightningDiagnosisTool"] = {"type": "tool_confirm_request"}
    await mgr.handle_message({
        "type": "tool_confirm_response", "tool": "LightningDiagnosisTool",
        "decision": "weight", "value": 0.1})
    assert "LightningDiagnosisTool" not in mgr.ok_tools

    async def fake_classify(message, session_id=None):
        return {"intent_type": "general", "confidence": 1.0, "parameters": {}}

    monkeypatch.setattr(agent_manager.pld_client, "classify", fake_classify)
    await mgr._replay_agent_chat("wind", "风速15m/s")
    assert "WindDiagnosisTool" not in mgr.ok_tools


async def test_ok_tools_cleared_on_new_run(monkeypatch):
    """每次新诊断/复盘开跑:ok_tools 清零(从零记忆)。"""
    mgr = make_mgr(monkeypatch, [COMPLETE])
    mgr.ok_tools.add("WindDiagnosisTool")
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.run_diagnosis(replay=False)
    assert mgr.ok_tools == set()


async def test_rerun_passes_data_overrides(monkeypatch):
    """复盘流携带 value_overrides → chat_stream 收到 data_overrides 透传。"""
    captured = {}
    mgr = make_mgr(monkeypatch, [COMPLETE], captured=captured)
    mgr.value_overrides["WindDiagnosisTool"] = "风速15m/s"
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr._stream_run("msg", True, {}, session_id="s1")
    assert captured["data_overrides"] == {"WindDiagnosisTool": "风速15m/s"}


async def test_realtime_run_without_overrides_omits_field(monkeypatch):
    """实时诊断或无改值:不携带 data_overrides(行为不变)。"""
    captured = {}
    mgr = make_mgr(monkeypatch, [COMPLETE], captured=captured)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr._stream_run("msg", False, {})
    assert "data_overrides" not in captured
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
.venv/bin/python -m pytest tests/test_ok_tools.py -v
```

预期:6 条 FAIL(ok_tools 属性不存在 / classify 不存在 / data_overrides 未透传)。注:`test_confirm_ok_populates_and_objection_discards` 中 `_replay_agent_chat` 依赖 Task 4 的 classify 重接,本任务先实现 classify 透传与 general 兜底最小版(见 Step 3 ④),Task 4 完成全部意图映射。

- [ ] **Step 3: 实现**

① `backend/pld_client.py` chat_stream(12-23)加参数:

```python
async def chat_stream(message: str, *, session_id: str | None = None,
                      defer_rediagnose: bool = False,
                      data_overrides: dict | None = None) -> AsyncIterator[dict]:
```

body 构造处(19-23)加:

```python
    if data_overrides:
        body["data_overrides"] = data_overrides
```

文件末尾新增:

```python
async def classify(message: str, session_id: str | None = None) -> dict:
    """调用 PLD /api/classify 纯意图分类(零副作用)。"""
    body: dict = {"message": message}
    if session_id:
        body["session_id"] = session_id
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{PLD_BASE}/api/classify", json=body)
        resp.raise_for_status()
        return resp.json()
```

② `backend/agent_manager.py`:

`__init__`(93 行 `self.value_overrides` 之后)加:

```python
        self.ok_tools: set[str] = set()               # 复盘跨轮「无异议」记忆(重跑自动确认)
```

`run_diagnosis`(497 行 `self.intervention_trail = []` 之后)加:

```python
        self.ok_tools.clear()  # 每次新诊断/复盘从零记忆
```

`tool_confirm_response`(249-257 区):`else` 分支登记决策后、`del self.pending_confirms[tool]` 之前加:

```python
                if decision == "ok":
                    self.ok_tools.add(tool)
                else:
                    self.ok_tools.discard(tool)
```

`_stream_run` stream_kwargs(393-395)加:

```python
        if replay and self.value_overrides:
            stream_kwargs["data_overrides"] = dict(self.value_overrides)
```

`_stream_run` replay result 分支(446-456)改为:

```python
                    if replay:
                        if tool in self.ok_tools:
                            # 跨轮无异议记忆:此前已确认的工具重跑不再询问,自动 ok
                            self.confirm_decisions[tool] = {"decision": "ok"}
                        else:
                            self.pending_confirms[tool] = {
                                "type": "tool_confirm_request",
                                "agent": aid, "tool": tool,
                                "fault_type": fault, "confidence": conf,
                                "evidence": evid,
                                "raw_text": raw, "structured_data": sd,
                                "override": self.value_overrides.get(tool),
                                "empty": empty,
                            }
                            await self.broadcast(self.pending_confirms[tool])
```

③ `_replay_agent_chat`(877-896)最小重写(完整意图映射在 Task 4;本任务仅打通 classify + general 兜底,删除关键词门槛):

```python
    async def _replay_agent_chat(self, agent: str, message: str):
        """复盘模式工具智能体对话:PLD /api/classify 语义路由(本步:general 兜底数据修正)。"""
        tool = TOOL_AGENTS.get(agent, agent)
        try:
            await pld_client.classify(message, session_id=self.session_id)
        except Exception:  # noqa: BLE001
            pass  # 分类不可用不阻断:按数据修正兜底
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.objection_log.append({"time": now, "kind": "tool_objection", "tool": tool,
                                   "decision": "chat", "value": message})
        self.confirm_decisions[tool] = {"decision": "chat", "value": message}
        self.value_overrides[tool] = message
        self.ok_tools.discard(tool)
        self.pending_confirms.pop(tool, None)
        if not self.pending_confirms and self._confirms_done:
            self._confirms_done.set()
        await self.chat_say(agent, "已收到，将随本轮异议统一上报司令重新诊断。")
        await self.broadcast({"type": "objection_accepted", "agent": agent, "tool": tool})
```

④ 删除 `OBJECTION_KEYWORDS`(63-67 行,含注释行);`handle_message` 174-177 行注释改为:

```python
                    # 复盘中与诊断智能体对话:经 PLD /api/classify 纯分类端点语义路由
                    # (零副作用,不劫持活跃会话),由 _replay_agent_chat 登记异议
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd backend
.venv/bin/python -m pytest tests/test_ok_tools.py -v
.venv/bin/python -m pytest tests/ -q
```

预期:全 PASS(既有 test_chat_override.py 的 chat 语义保留——decision "chat" 与 value_overrides 写入不变)。

- [ ] **Step 5: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/pld_client.py backend/agent_manager.py backend/tests/test_ok_tools.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(replay): ok_tools跨轮无异议记忆+重跑透传data_overrides+classify客户端"
```

---

### Task 4(backend): 对话异议 LLM 意图映射

**Files:**
- Modify: `backend/agent_manager.py`(_replay_agent_chat 全量映射、_objection_command 714-742 加 report_modify 分支)
- Test: `backend/tests/test_replay_intent.py`(新建)

**Interfaces:**
- Consumes: Task 3 的 `pld_client.classify`(已落地)与 `_replay_agent_chat` 最小版(本任务替换为全量映射)
- Produces: decision kind `report_modify`(`_objection_command` 新分支 → ("suffix", f"修改报告:{value}") + report_modify trail,`_ITEM_LABELS["report_modify"]` 既有标签直接覆盖)

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_replay_intent.py`:

```python
"""复盘对话异议 LLM 意图映射:classify → 结构化决策/数据修正/报告修改/固定提示。"""
import agent_manager
from tests.test_agent_manager import FakeWS


def make_mgr(monkeypatch, classify_resp=None, classify_exc=None):
    async def fake_classify(message, session_id=None):
        if classify_exc:
            raise classify_exc
        return classify_resp or {"intent_type": "general", "confidence": 1.0,
                                 "parameters": {}}

    monkeypatch.setattr(agent_manager.pld_client, "classify", fake_classify)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr._run_replay = True
    return mgr


async def test_adjust_weight_maps_to_weight_decision(monkeypatch):
    """「调整权重0.1」→ adjust_weight → weight 决策;不写 value_overrides。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "adjust_weight", "confidence": 0.95,
        "parameters": {"tool_name": "LightningDiagnosisTool", "weight": 0.1}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "lightning",
                              "message": "调整权重0.1"})
    assert mgr.confirm_decisions["LightningDiagnosisTool"] == {
        "decision": "weight", "value": 0.1}
    assert mgr.value_overrides == {}


async def test_adjust_weight_without_value_falls_back_to_data_fix(monkeypatch):
    """adjust_weight 未提取到权重值 → 按数据修正兜底。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "adjust_weight", "confidence": 0.8, "parameters": {}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "调整权重"})
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "chat"
    assert mgr.value_overrides["WindDiagnosisTool"] == "调整权重"


async def test_general_maps_to_data_fix(monkeypatch):
    """「风速10m/s」(general)→ 数据修正,无需关键词。"""
    mgr = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "风速10m/s"})
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "chat"
    assert mgr.value_overrides["WindDiagnosisTool"] == "风速10m/s"


async def test_recheck_and_exclude_mapping(monkeypatch):
    """recheck_tool / exclude_tool → 对应结构化决策;tool 取 parameters.tool_name。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "recheck_tool", "confidence": 0.9,
        "parameters": {"tool_name": "LightningDiagnosisTool"}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "重新检查雷电"})
    assert mgr.confirm_decisions["LightningDiagnosisTool"]["decision"] == "recheck"

    mgr2 = make_mgr(monkeypatch, {
        "intent_type": "exclude_tool", "confidence": 0.9,
        "parameters": {"tool_name": "IcingDiagnosisTool"}})
    await mgr2.connect(FakeWS())
    await mgr2.handle_message({"type": "chat", "agent": "wind", "message": "排除覆冰"})
    assert mgr2.confirm_decisions["IcingDiagnosisTool"]["decision"] == "exclude"


async def test_modify_report_maps_to_report_modify(monkeypatch):
    """「去掉第六章」→ modify_report → report_modify 决策(trail 复用既有 kind)。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "modify_report", "confidence": 0.9, "parameters": {}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "去掉第六章"})
    assert mgr.confirm_decisions["WindDiagnosisTool"] == {
        "decision": "report_modify", "value": "去掉第六章"}
    assert mgr.value_overrides == {}
    kind, text = mgr._objection_command(
        "WindDiagnosisTool", {"decision": "report_modify", "value": "去掉第六章"})
    assert kind == "suffix"
    assert "修改报告" in text and "去掉第六章" in text
    assert mgr.intervention_trail[-1]["kind"] == "report_modify"


async def test_unsupported_intent_fixed_hint(monkeypatch):
    """include_tool/complete 等 → 固定提示,不登记决策。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "include_tool", "confidence": 0.9,
        "parameters": {"tool_name": "IcingDiagnosisTool"}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "恢复覆冰"})
    assert mgr.confirm_decisions == {}
    assert mgr.value_overrides == {}
    assert any("界面按钮" in e.get("message", "") for e in ws.events
               if e.get("type") == "chat")


async def test_classify_failure_falls_back_to_data_fix(monkeypatch):
    """classify 异常(PLD 不可达)→ 数据修正兜底,链路不中断。"""
    mgr = make_mgr(monkeypatch, classify_exc=ConnectionError("down"))
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "风速10m/s"})
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "chat"
    assert mgr.value_overrides["WindDiagnosisTool"] == "风速10m/s"


async def test_unknown_tool_name_falls_back_to_chat_agent(monkeypatch):
    """parameters.tool_name 非标准工具名 → 用对话所在智能体工具。"""
    mgr = make_mgr(monkeypatch, {
        "intent_type": "recheck_tool", "confidence": 0.9,
        "parameters": {"tool_name": "雷电工具"}})
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "重新检查"})
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "recheck"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
.venv/bin/python -m pytest tests/test_replay_intent.py -v
```

预期:8 条 FAIL(映射未实现:adjust_weight 等仍走 chat 兜底;report_modify 分支不存在)。

- [ ] **Step 3: 实现**

`backend/agent_manager.py` 两处。

① `_replay_agent_chat`(Task 3 最小版)整体替换为:

```python
    async def _replay_agent_chat(self, agent: str, message: str):
        """复盘模式工具智能体对话:PLD /api/classify(零副作用)语义路由。

        adjust_weight/recheck/exclude → 结构化异议;modify_report → 报告修改异议;
        general 及其他 → 数据修正(在智能体对话框发言,语境即针对该工具数据);
        分类失败 → 同 general 兜底,链路不中断。
        """
        tool = TOOL_AGENTS.get(agent, agent)
        try:
            resp = await pld_client.classify(message, session_id=self.session_id)
            itype = str(resp.get("intent_type", "general"))
            params = resp.get("parameters") or {}
        except Exception:  # noqa: BLE001
            itype, params = "general", {}
        target = str(params.get("tool_name") or "")
        if target not in TOOL_TO_AGENT:
            target = tool
        decision: str
        value = None
        if itype == "adjust_weight" and params.get("weight") is not None:
            decision, value = "weight", params.get("weight")
        elif itype == "recheck_tool":
            decision = "recheck"
        elif itype == "exclude_tool":
            decision = "exclude"
        elif itype == "modify_report":
            decision, value = "report_modify", message
        elif itype in ("complete", "save_strategy", "load_strategy",
                       "list_sessions", "switch_session", "include_tool"):
            await self.chat_say(
                agent, "复盘对话中请使用界面按钮完成该操作"
                       "(权重/排除/复查/数据修正/报告修改可直接告知我)。")
            return
        else:  # general / diagnose / 未识别 → 数据修正
            decision, value = "chat", message
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.objection_log.append({"time": now, "kind": "tool_objection", "tool": target,
                                   "decision": decision, "value": value})
        self.confirm_decisions[target] = {"decision": decision, "value": value}
        if decision == "chat":
            # 数据修正:用户陈述即权威数据,随快照/确认事件下发显示
            self.value_overrides[target] = message
        self.ok_tools.discard(target)
        # 对话异议即视为该工具的确认:释放确认等待,确认轮可正常完成进入整轮重跑
        self.pending_confirms.pop(target, None)
        if not self.pending_confirms and self._confirms_done:
            self._confirms_done.set()
        await self.chat_say(agent, "已收到，将随本轮异议统一上报司令重新诊断。")
        await self.broadcast({"type": "objection_accepted", "agent": agent, "tool": target})
```

② `_objection_command`(738 行 `if decision == "chat":` 之前)插入:

```python
        if decision == "report_modify":
            self._trail("report_modify", text=str(value))
            return "suffix", f"修改报告:{value}"
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd backend
.venv/bin/python -m pytest tests/test_replay_intent.py -v
.venv/bin/python -m pytest tests/ -q
```

预期:全 PASS。注意既有 `test_chat_override.py` 的 `make_mgr` mock 了 chat_stream 但未 mock classify——该文件测试走 `handle_message chat` → `_replay_agent_chat` 会真实调 classify 抛异常(连接失败)→ 兜底 general → 行为与既有断言一致,应仍 PASS;若因网络等待变慢,在该文件 make_mgr 中补 mock classify 抛异常使其快速失败。

- [ ] **Step 5: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/agent_manager.py backend/tests/test_replay_intent.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(replay): 对话异议LLM意图映射(调权/复查/排除/报告修改/数据修正兜底)"
```

---

### Task 5: 记录删除(backend + frontend)

**Files:**
- Modify: `backend/records.py`(文件末尾)
- Modify: `backend/agent_manager.py`(handle_message 275-282 get_record 分支之后)
- Modify: `frontend/src/ws.js`(212 行 requestRecord 之后)
- Modify: `frontend/src/components/HistoryView.vue`
- Test: `backend/tests/test_records_delete.py`(新建)

**Interfaces:**
- Consumes: 既有 `records._load/_write`、`send_records`(agent_manager.py:351)、ws.js `send`、store.records/store.recordDetail
- Produces: `records.delete_records(ids: list[int]) -> int`;WS 消息 `{type:"delete_records", ids:[...]}` → 广播 records_list;ws.js `deleteRecords(ids)`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_records_delete.py`:

```python
"""记录删除:delete_records 单删/多删/幂等 + WS delete_records 路由。"""
import json

import agent_manager
import records
from tests.test_agent_manager import FakeWS


def setup_tmp(monkeypatch, tmp_path):
    f = tmp_path / "diagnosis_records.json"
    monkeypatch.setattr(records, "RECORDS_FILE", f)
    return f


def test_delete_single_and_multi(monkeypatch, tmp_path):
    """删单条/多条:文件内容正确,返回删除条数。"""
    setup_tmp(monkeypatch, tmp_path)
    ids = [records.create_record(f"线路{i}", "12:00:00")["id"] for i in range(3)]
    assert records.delete_records([ids[0]]) == 1
    assert [r["id"] for r in records.list_records()] == [ids[1], ids[2]]
    assert records.delete_records([ids[1], ids[2]]) == 2
    assert records.list_records() == []


def test_delete_nonexistent_is_noop(monkeypatch, tmp_path):
    """删除不存在的 id:返回 0,文件不变(幂等不报错)。"""
    setup_tmp(monkeypatch, tmp_path)
    rec = records.create_record("线路A", "12:00:00")
    assert records.delete_records([999]) == 0
    assert len(records.list_records()) == 1
    assert records.get_record(rec["id"]) is not None


async def test_ws_delete_records_broadcasts_list(monkeypatch, tmp_path):
    """WS delete_records 路由:删除后广播最新 records_list。"""
    setup_tmp(monkeypatch, tmp_path)
    ids = [records.create_record(f"线路{i}", "12:00:00")["id"] for i in range(2)]
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "delete_records", "ids": [ids[0]]})
    rl = [e for e in ws.events if e["type"] == "records_list"]
    assert len(rl) == 1
    assert [r["id"] for r in rl[0]["records"]] == [ids[1]]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
.venv/bin/python -m pytest tests/test_records_delete.py -v
```

预期:3 条 FAIL(delete_records 不存在 / WS 路由不存在)。

- [ ] **Step 3: 实现**

① `backend/records.py` 文件末尾加:

```python
def delete_records(ids: list[int]) -> int:
    """按 id 批量删除记录,返回实际删除条数(幂等)。"""
    recs = _load()
    drop = set(ids)
    keep = [r for r in recs if r.get("id") not in drop]
    deleted = len(recs) - len(keep)
    if deleted:
        _write(keep)
    return deleted
```

② `backend/agent_manager.py` handle_message(275-282 get_record 分支之后)加:

```python
        elif mtype == "delete_records":
            ids = []
            raw_ids = data.get("ids")
            if isinstance(raw_ids, list):
                for v in raw_ids:
                    try:
                        ids.append(int(v))
                    except (TypeError, ValueError):
                        continue
            deleted = records.delete_records(ids)
            if deleted:
                await self.log("commander", f"已删除 {deleted} 条诊断记录。")
            await self.send_records()
```

③ `frontend/src/ws.js`(212 行 requestRecord 之后)加:

```js
export const deleteRecords = (ids) => send({ type: 'delete_records', ids })
```

④ `frontend/src/components/HistoryView.vue`:

script 区(第 4 行 import 行)改为:

```js
import { requestRecord, setView, deleteRecords } from '../ws'
```

`const keyword = ref('')` 之后加:

```js
const selected = ref(new Set())
const confirmDelete = ref(null) // { ids: number[], lines: string[] }

function toggleSelect(id) {
  const s = new Set(selected.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  selected.value = s
}

function askDelete(ids) {
  const lines = store.records.filter((r) => ids.includes(r.id))
    .map((r) => `#${r.id} ${r.line} (${r.time})`)
  confirmDelete.value = { ids, lines }
}

function doDelete() {
  const ids = confirmDelete.value?.ids || []
  if (ids.length) deleteRecords(ids)
  if (store.recordDetail && ids.includes(store.recordDetail.id)) store.recordDetail = null
  selected.value = new Set()
  confirmDelete.value = null
}
```

模板顶栏(「返回指挥室」按钮之前)加:

```html
      <button
        v-if="selected.size"
        @click="askDelete([...selected])"
        class="text-xs px-3 py-1.5 rounded border border-red-400/50 text-red-200 bg-red-500/15 hover:bg-red-400/25"
      >删除选中({{ selected.size }})</button>
```

记录列表行(44-55 行 `v-for` 块)改为带复选框与行内删除:

```html
        <div
          v-for="r in [...filtered].reverse()" :key="r.id"
          @click="requestRecord(r.id)"
          class="px-3 py-2 border-b border-slate-700/40 cursor-pointer hover:bg-cyan-500/10 flex items-start gap-2"
          :class="store.recordDetail?.id === r.id ? 'bg-cyan-500/15' : ''"
        >
          <input
            type="checkbox" :checked="selected.has(r.id)"
            @click.stop="toggleSelect(r.id)"
            class="mt-0.5 accent-red-400 shrink-0"
          />
          <div class="flex-1 min-w-0">
            <div class="text-xs text-cyan-100 truncate" :title="r.line">{{ r.line }}</div>
            <div class="text-[10px] text-slate-500 mt-0.5 flex gap-2 flex-wrap">
              <span>#{{ r.id }} · {{ r.time }}</span>
              <span v-if="r.has_replay" class="text-emerald-300">已复盘</span>
              <span v-for="s in r.strategies" :key="s" class="text-fuchsia-300">{{ s }}</span>
            </div>
          </div>
          <button
            @click.stop="askDelete([r.id])"
            class="text-[10px] px-1.5 py-0.5 rounded border border-red-400/40 text-red-300/80 hover:bg-red-500/20 shrink-0"
          >删除</button>
        </div>
```

模板根 div 内末尾(`</template>` 之前)加确认弹窗:

```html
    <div
      v-if="confirmDelete"
      class="absolute inset-0 z-20 bg-slate-950/70 flex items-center justify-center"
      @click.self="confirmDelete = null"
    >
      <div class="glass rounded-lg p-4 w-[360px] border border-red-400/30">
        <div class="text-red-300 text-sm font-bold mb-2">确认删除 {{ confirmDelete.ids.length }} 条记录?</div>
        <div class="text-[11px] text-slate-300 mb-3 max-h-32 overflow-y-auto">
          <div v-for="l in confirmDelete.lines" :key="l" class="py-0.5">{{ l }}</div>
        </div>
        <div class="text-[10px] text-slate-500 mb-3">删除后不可恢复。</div>
        <div class="flex justify-end gap-2">
          <button
            @click="confirmDelete = null"
            class="text-xs px-3 py-1.5 rounded border border-slate-500/50 text-slate-300 hover:bg-slate-700/30"
          >取消</button>
          <button
            @click="doDelete"
            class="text-xs px-3 py-1.5 rounded border border-red-400/50 text-red-200 bg-red-500/20 hover:bg-red-400/30"
          >确认删除</button>
        </div>
      </div>
    </div>
```

- [ ] **Step 4: 跑测试 + 前端构建**

```bash
cd backend
.venv/bin/python -m pytest tests/test_records_delete.py -v
.venv/bin/python -m pytest tests/ -q
cd ../frontend
npm run build
```

预期:backend 全 PASS;前端构建成功无报错。

- [ ] **Step 5: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/records.py backend/agent_manager.py backend/tests/test_records_delete.py frontend/src/ws.js frontend/src/components/HistoryView.vue
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat: 历史记录删除(单删+多选批删+自定义确认框)"
```

---

### Task 6: 全量回归 + 实测核对清单

**Files:** 无(纯验证)

**Interfaces:**
- Consumes: Task 1-5 全部完成
- Produces: 无

- [ ] **Step 1: vendor 全量测试**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/ -q
```

预期:全部 PASS(含新增 9 条)。

- [ ] **Step 2: backend 全量测试**

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

预期:全部 PASS(≥78 条,含新增 17 条)。

- [ ] **Step 3: 前端构建**

```bash
cd frontend
npm run build 2>&1 | tail -3
```

预期:成功。

- [ ] **Step 4: 实测核对(记录交用户)**

GLM 可达时按原实测路径复测:
1. 复盘第一轮对风偏选「无异议」→ 之后对雷电提异议触发重跑 → 风偏**不再**弹确认框,仅问雷电
2. 对话提「风速15m/s、风偏角10度」→ 重确认显示「以您提供的数据为准」→ 最终报告与结论**采用用户数据**(非 18m/s/12°)
3. 对话框直接输入「调整权重0.1」→ 执行调权(非数据修正);输入「风速10m/s」→ 直接识别为数据修正,无需关键词
4. 历史结果页:行内删除单条;勾选多条 → 「删除选中(n)」→ 确认框列出线路名 → 删除后列表刷新、详情清空

---

## Self-Review 记录

- Spec 覆盖:§1 ok_tools→Task 3②+测试 1-4;§2 data_overrides→Task 1(vendor)+Task 3①②透传+测试 5;§3 意图分类→Task 2(端点)+Task 4(映射)+测试;§4 删除→Task 5;「不做的事」→无任务,符合
- 占位符:所有测试与实现代码完整给出;Task 3 ③的「最小版」与 Task 4 的「全量替换」是刻意的两步 TDD 拆分,均含完整代码
- 类型一致:`data_overrides: Dict[str,str]`(vendor 模型)= pld_client `data_overrides: dict`(backend)= /chat body 字段;`pld_client.classify` 返回 `{intent_type: str, confidence: float, parameters: dict}` 与 Task 2 端点响应一致;decision kind `report_modify` 在 Task 4 产出并被 `_objection_command` 新分支消费,`_ITEM_LABELS["report_modify"]` 既有;`ok_tools: set[str]` Task 3 产出/消费
- Task 3 与 Task 4 的 _replay_agent_chat 交接:Task 3 ③为最小版(general 兜底),Task 4 ①整体替换;Task 3 测试 `test_confirm_ok_populates_and_objection_discards` 用 general mock,两版本行为一致,无顺序依赖风险
- 既有测试兼容:test_chat_override.py 未 mock classify → 真实调用连接失败走兜底(Step 4 已注明处理);chat 决策语义(decision "chat" + value_overrides 写入)两版本保留
