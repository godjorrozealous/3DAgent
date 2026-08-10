# 复盘异议分类处理 + 局部重跑 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PLD `/chat` 支持 `session_id` 续跑与 `defer_rediagnose`，复盘异议分类落地+同会话局部重跑，消除 N 倍自动链式重诊断浪费并修复会话隔离引入的复盘重跑回归。

**Architecture:** PLD（vendor 仓）`/chat` 加两个可选请求字段；backend（外层仓）`pld_client.chat_stream` 透传，复盘主循环①命令带 defer、②收尾带 session_id、权重还原带 defer。前端零改动。

**Tech Stack:** Python 3.11、Flask(SSE)、FastAPI 侧 httpx、pytest（vendor `tests/unit/` 与 backend `tests/`）

**Spec:** `docs/superpowers/specs/2026-08-10-replay-partial-rerun-design.md`

## Global Constraints

- vendor 改动与提交在 `vendor/diagnosis-agent`（独立 git 仓，分支 mcp_version）；backend 改动与提交在外层仓（分支 feature/command-center-enhancements）
- vendor 测试：`cd vendor/diagnosis-agent && .venv/bin/python -m pytest <路径> -v`；单文件跑触发 80% 覆盖率门禁告警为既有现象，忽略
- backend 测试：`cd backend && .venv/bin/python -m pytest tests/ -q`
- `chat_stream` 新参数必须 keyword-only 且带默认值，既有调用方与测试 fake 不破坏
- PLD `/chat` 不带新字段时行为与现状完全一致（自动链式重诊断保留）
- 前端零改动

---

### Task 1: PLD `/chat` 支持 session_id 续跑 + defer_rediagnose

**Files:**
- Modify: `vendor/diagnosis-agent/src/interfaces/web.py`（`/chat` 路由 74-87、`_sync_chat_stream` 89+、`_chat_stream` 会话选择块与自动链式块 197-236）
- Test: `vendor/diagnosis-agent/tests/unit/test_chat_continuation.py`（新建）

**Interfaces:**
- Consumes: `container.session_manager.get(session_id)`（`src/domain/session_manager.py:108`，不存在抛 `SessionNotFoundError`）；`SessionStatus`；`Intent` / `IntentType`（`src/core/models.py`）
- Produces: `/chat` 请求体新字段 `session_id: str | null`、`defer_rediagnose: bool`；Task 2 的 backend 依赖这两个字段

- [ ] **Step 1: 写失败测试**

新建 `vendor/diagnosis-agent/tests/unit/test_chat_continuation.py`：

```python
"""复盘编排通道：/chat 的 session_id 续跑与 defer_rediagnose。"""

import json

import pytest

from src.core.models import Event, Intent, IntentType, SessionStatus
from src.interfaces import web as web_mod
from src.interfaces.web import create_app
from src.interfaces.dependency_injection import get_container

ADJUST_INTENT = Intent(
    intent_type=IntentType.ADJUST_WEIGHT,
    confidence=1.0,
    parameters={"tool_name": "LightningDiagnosisTool", "weight": 0.5},
)


class FakeDiagnoseCmd:
    """替代自动链式重诊断：仅计数并立即 complete，避免真实 LLM 调用。"""

    calls = 0

    def __init__(self, **kwargs):
        pass

    async def execute(self, ctx):
        type(self).calls += 1
        yield Event.complete(ctx.session.session_id, {"message": "ok"})


@pytest.fixture
def client(monkeypatch):
    FakeDiagnoseCmd.calls = 0
    get_container.cache_clear()
    app = create_app()
    container = get_container()
    monkeypatch.setattr(web_mod, "DiagnoseCommand", FakeDiagnoseCmd)

    async def fake_classify(message, session=None):
        return ADJUST_INTENT

    monkeypatch.setattr(container.intent_classifier, "classify", fake_classify)
    with app.test_client() as c:
        yield c, container
    get_container.cache_clear()


def _events(resp):
    out = []
    for line in resp.get_data(as_text=True).splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[5:].strip()))
    return out


def _make_modifying_session(container, line="雅湖线"):
    s = container.session_manager.create(line)
    container.session_manager.transition(s.session_id, SessionStatus.DIAGNOSING)
    container.session_manager.transition(s.session_id, SessionStatus.MODIFYING)
    return s


def test_defer_suppresses_auto_rediagnose(client):
    """defer_rediagnose=true：命令落地但不触发自动链式重诊断。"""
    c, container = client
    s = _make_modifying_session(container)
    resp = c.post("/chat", json={
        "message": "将LightningDiagnosisTool权重调整为0.5",
        "session_id": s.session_id,
        "defer_rediagnose": True,
    })
    assert resp.status_code == 200
    evts = _events(resp)
    assert any(e["event_type"] == "complete" for e in evts)
    assert not any("自动重新诊断" in str(e.get("payload", {}).get("message", "")) for e in evts)
    assert FakeDiagnoseCmd.calls == 0
    sess = container.session_manager.get(s.session_id)
    assert sess.active_weights["LightningDiagnosisTool"] == 0.5
    assert sess.status == SessionStatus.MODIFYING


def test_default_keeps_auto_rediagnose(client):
    """不带 defer_rediagnose：自动链式重诊断保留（兼容现状）。"""
    c, container = client
    s = _make_modifying_session(container)
    resp = c.post("/chat", json={
        "message": "将LightningDiagnosisTool权重调整为0.5",
        "session_id": s.session_id,
    })
    assert resp.status_code == 200
    assert FakeDiagnoseCmd.calls == 1


def test_session_id_routes_to_specified_session(client):
    """session_id 显式指定：绕过 get_or_create/get_active，只作用于该会话。"""
    c, container = client
    a = _make_modifying_session(container, "雅湖线")
    b = _make_modifying_session(container, "京西线")  # create 后 b 为活跃会话
    resp = c.post("/chat", json={
        "message": "将LightningDiagnosisTool权重调整为0.5",
        "session_id": a.session_id,
        "defer_rediagnose": True,
    })
    assert resp.status_code == 200
    assert container.session_manager.get(a.session_id).active_weights["LightningDiagnosisTool"] == 0.5
    assert container.session_manager.get(b.session_id).active_weights["LightningDiagnosisTool"] != 0.5
    assert len(container.session_manager.list_sessions()) == 2  # 未新建会话


def test_unknown_session_id_returns_error_event(client):
    """session_id 不存在：返回 error 事件，不崩溃。"""
    c, _ = client
    resp = c.post("/chat", json={
        "message": "将LightningDiagnosisTool权重调整为0.5",
        "session_id": "sess_nope",
    })
    assert resp.status_code == 200
    evts = _events(resp)
    assert any(e["event_type"] == "error" and "会话不存在" in str(e.get("payload", {})) for e in evts)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_chat_continuation.py -v
```

预期：4 条全 FAIL（`session_id`/`defer_rediagnose` 未实现：路由忽略字段走 get_active、error 事件不存在、defer 无效）。

- [ ] **Step 3: 实现**

`src/interfaces/web.py` 三处修改。

① `/chat` 路由（原 74-87 行）：

```python
    @app.route("/chat", methods=["POST"])
    def chat():
        """流式对话接口"""
        data = request.json or {}
        user_message = data.get("message", "").strip()
        # 复盘编排通道：显式会话续跑 / 延迟自动重诊断（缺省行为不变）
        session_id = str(data.get("session_id") or "").strip() or None
        defer_rediagnose = bool(data.get("defer_rediagnose", False))

        if not user_message:
            return jsonify({"error": "消息不能为空"}), 400

        return Response(
            stream_with_context(_sync_chat_stream(user_message, session_id, defer_rediagnose)),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
```

② `_sync_chat_stream` 与 `_chat_stream` 签名透传（两个 `session_id`/`defer_rediagnose` 参数一路传入 `_chat_stream`）。

③ `_chat_stream` 会话选择块（原「诊断类意图 get_or_create，其他意图 get_active」）前面插入显式分支：

```python
            # 2. 获取会话：显式 session_id（复盘编排续跑）优先；
            #    否则诊断类意图 get_or_create，其他意图使用活跃会话
            if session_id:
                try:
                    session = container.session_manager.get(session_id)
                except Exception:
                    yield _sse_event(
                        Event.error("", f"会话不存在: {session_id}")
                    )
                    return
            elif intent_type == IntentType.DIAGNOSE:
```

（原 `if intent_type == IntentType.DIAGNOSE:` 降为 `elif`，其下 DIAGNOSE/get_active 逻辑不动。）

④ 自动链式块加 defer 门（原 197 行）：

```python
                # 自动链式诊断：排除/恢复/调整权重后无条件自动重新诊断；
                # defer_rediagnose（复盘编排批量落地命令）时跳过，由编排方收尾重跑
                if not defer_rediagnose and intent_type in (IntentType.EXCLUDE_TOOL, IntentType.INCLUDE_TOOL, IntentType.ADJUST_WEIGHT):
```

- [ ] **Step 4: 跑测试确认通过 + web 相关回归**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_chat_continuation.py tests/unit/test_web_api.py tests/unit/test_skills_api.py -v
```

预期：全部 PASS（覆盖率门禁告警忽略）。

- [ ] **Step 5: 提交（vendor 仓）**

```bash
cd vendor/diagnosis-agent
git add src/interfaces/web.py tests/unit/test_chat_continuation.py
git commit -m "feat(chat): /chat支持session_id续跑+defer_rediagnose(复盘编排通道,缺省行为不变)"
```

---

### Task 2: backend 透传 + 复盘主循环改造

**Files:**
- Modify: `backend/pld_client.py:12-27`（`chat_stream`）
- Modify: `backend/agent_manager.py`（`_stream_run` 382/392、①命令循环 570、②收尾 584、审核期异议重跑 624、权重还原 669）
- Test: `backend/tests/test_replay_partial_rerun.py`（新建）；`backend/tests/test_replay_chat_routing.py:82-97`（fake 兼容 kwargs）

**Interfaces:**
- Consumes: Task 1 的 `/chat` 字段 `session_id`、`defer_rediagnose`
- Produces: `chat_stream(message: str, *, session_id: str | None = None, defer_rediagnose: bool = False)`；`_stream_run(self, message, replay, run_record, *, session_id=None)`

- [ ] **Step 1: 更新既有测试 helper 兼容 kwargs**

`backend/tests/test_replay_chat_routing.py` 的 `make_mgr`（文件上部）与 `make_mgr_multistream:85` 中：

```python
    async def fake_stream(msg):
```

均改为：

```python
    async def fake_stream(msg, **kwargs):
```

（`calls.append(msg)` 等既有断言不变。）

- [ ] **Step 2: 写失败测试**

新建 `backend/tests/test_replay_partial_rerun.py`：

```python
"""复盘局部重跑：①命令带 defer、②收尾带 session_id、还原带 defer。"""
import asyncio

import agent_manager
from tests.test_agent_manager import FakeWS

RESULT_OK = {"event_type": "result", "session_id": "s1",
             "payload": {"tool_name": "LightningDiagnosisTool",
                         "output": {"fault_type": "雷击", "confidence": 0.9,
                                    "evidence": "e", "raw_text": "r", "structured_data": {}}}}
COMPLETE = {"event_type": "complete", "session_id": "s1",
            "payload": {"report": "报告正文", "summary": {"fault_type": "雷击", "confidence": 0.9}}}
SESSION = {"status": "modifying",
           "active_weights": {"LightningDiagnosisTool": 1.0},
           "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls, streams):
    iters = [iter(s) for s in streams]

    async def fake_stream(msg, **kwargs):
        calls.append((msg, kwargs))
        for e in iters.pop(0):
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_objection_cmds_defer_rerun_session_id_restore_defer(monkeypatch):
    """权重异议复盘全流程：校验三类 chat_stream 调用的编排参数。"""
    calls = []
    streams = [
        [dict(RESULT_OK), dict(COMPLETE)],   # 首轮诊断
        [dict(RESULT_OK), dict(COMPLETE)],   # ①命令(auto-chain已被defer,直接complete)
        [dict(RESULT_OK), dict(COMPLETE)],   # ②收尾重跑
        [dict(COMPLETE)],                    # 还原指令
    ]
    mgr = make_mgr(monkeypatch, calls, streams)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.3)
        # 首轮逐项确认：权重异议（结构化命令路径）
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool",
                                  "decision": "weight", "value": 0.1})
        await asyncio.sleep(0.6)
        # 重跑轮逐项确认：无异议
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.3)
        # 重跑轮审核：满意结束
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())

    assert len(calls) == 4
    first, cmd, rerun, restore = calls
    # 首轮：编排参数为空
    assert first[1] == {}
    # ①结构化命令：defer_rediagnose
    assert "权重调整为0.1" in cmd[0]
    assert cmd[1].get("defer_rediagnose") is True
    # ②收尾重跑：session_id 续跑
    assert rerun[1].get("session_id") == "s1"
    # 还原指令：defer_rediagnose
    assert "权重调整为1.0" in restore[0]
    assert restore[1].get("defer_rediagnose") is True
```

> 注：streams 数量按实际消费调试——若①/②/还原的流被合并消费（同一次 chat_stream 内多个事件），以运行报错（`iters.pop(0)` IndexError 或剩余未消费）为准增减空流；断言的 4 次调用与参数不变。

- [ ] **Step 3: 跑测试确认失败**

```bash
cd backend
.venv/bin/python -m pytest tests/test_replay_partial_rerun.py -v
```

预期：FAIL（`first[1] == {}` 通过但 `cmd[1].get("defer_rediagnose")` 为 None、无第 4 次调用参数等）。

- [ ] **Step 4: 实现**

① `backend/pld_client.py`：

```python
async def chat_stream(message: str, *, session_id: str | None = None,
                      defer_rediagnose: bool = False) -> AsyncIterator[dict]:
    """调用 PLDiagnosis /chat，逐条产出 SSE 事件 dict。

    事件结构: {"event_type": start|thinking|content|status|complete|error, "payload": {...}, "session_id": ...}
    session_id / defer_rediagnose 为复盘编排通道参数，缺省不携带。
    """
    body: dict = {"message": message}
    if session_id:
        body["session_id"] = session_id
    if defer_rediagnose:
        body["defer_rediagnose"] = True
    async with httpx.AsyncClient(timeout=_timeout) as client:
        async with client.stream(
            "POST", f"{PLD_BASE}/chat", json=body
        ) as resp:
```

（函数体其余部分不动。）

② `backend/agent_manager.py` 五处：

- `_stream_run(self, message: str, replay: bool, run_record: dict, *, session_id: str | None = None)`；其内 `pld_client.chat_stream(message)` → `pld_client.chat_stream(message, session_id=session_id)`
- ①命令循环（约 570 行）：`pld_client.chat_stream(cmd)` → `pld_client.chat_stream(cmd, defer_rediagnose=True)`
- ②收尾重跑（约 584 行）：`await self._stream_run(rerun_msg, True, run_record)` → `await self._stream_run(rerun_msg, True, run_record, session_id=self.session_id)`
- 审核期诊断流程异议重跑（约 624 行）：同样追加 `session_id=self.session_id`
- 权重还原（约 669 行）：`pld_client.chat_stream(f"将{tool}权重调整为{orig}")` → `pld_client.chat_stream(f"将{tool}权重调整为{orig}", defer_rediagnose=True)`

实时诊断首轮（524/531 行）与复盘首轮调用 `_stream_run` 保持不传 `session_id`。

- [ ] **Step 5: 跑全部 backend 测试**

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

预期：全部 PASS（含既有 60 条无回归）。

- [ ] **Step 6: 提交（外层仓）**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/pld_client.py backend/agent_manager.py backend/tests/test_replay_partial_rerun.py backend/tests/test_replay_chat_routing.py
git commit -m "feat(replay): 异议分类落地+同会话局部重跑(命令defer+收尾session_id续跑+还原defer)"
```

---

### Task 3: 双仓全量回归

**Files:** 无（纯验证）

**Interfaces:**
- Consumes: Task 1、Task 2 全部完成
- Produces: 无

- [ ] **Step 1: vendor 全量单测**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit -q 2>&1 | tail -3
```

预期：`passed` 计数 ≥ 356 且无 failed/error；覆盖率门禁（80%）不达标为既有问题（基线 75.9%），记录数值即可，不阻塞。

- [ ] **Step 2: backend 全量测试**

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

预期：全部 PASS。

- [ ] **Step 3: 端到端验证（跳过并记录）**

当前网络不可达配置的 LLM（172.18.179.2:20017），无法实跑诊断。在报告中记录「待网络恢复后：复盘发权重异议→确认①不重跑整轮、②重跑仅重取被异议工具、HUD 权重变化符合预期」。

---

## Self-Review 记录

- Spec 覆盖：session_id 续跑→Task 1③；defer→Task 1④；pld_client 透传→Task 2①；主循环①②/还原→Task 2②；测试 1-6→Task 1 Step 1（vendor 1-3+兼容）与 Task 2 Step 2（backend 4-6）；前端零改动（无任务，符合 spec）
- 占位符：Task 2 测试的 streams 数量有「按实际消费调试」注记——这是异步流测试的既有模式（参照 test_replay_chat_routing.py 同构用例），断言本身完整无占位
- 类型一致：`session_id: str | None`、`defer_rediagnose: bool`、`_stream_run(..., *, session_id=None)` 跨任务一致；`FakeDiagnoseCmd` 仅替换自动链式路径（web.py 模块级 import，monkeypatch 模块属性生效）
