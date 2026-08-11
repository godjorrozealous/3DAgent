# 复盘反馈三问题修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复盘对话异议升格为数据修正(override)使用户新数据生效;保存清单去掉自动合并条目消除「4 项」歧义;复盘比对补数据修正与报告修改差异。

**Architecture:** 全部改动在外层仓 backend(agent_manager.py)与 frontend 两个组件;vendor 零改动。方案 A:复用既有 value_overrides 骨架,chat 异议登记即写 override,重跑后缀改强约束指令。

**Tech Stack:** Python 3.11、pytest(asyncio 直连模式)、Vue 3 + Vite

**Spec:** `docs/superpowers/specs/2026-08-11-replay-feedback-fixes-design.md`

## Global Constraints

- vendor/diagnosis-agent 零改动、零提交
- backend 测试:`cd backend && .venv/bin/python -m pytest tests/ -q`,全部 PASS 无回归
- 既有 `decision == "chat"` 的 confirm_decisions 语义不变(仅 trail kind 新设 `chat_override`)
- `_ITEM_LABELS` 旧 `"chat"` 标签与 `save_strategy` commander_rules 的 `"chat"` 分支随新 kind 一并删除(trail 仅存在于当次运行内存,无存档兼容问题)
- OBJECTION_KEYWORDS 门槛不变

---

### Task 1: 对话异议升格为数据修正(backend)

**Files:**
- Modify: `backend/agent_manager.py`(`_replay_agent_chat` 872-889、`_objection_command` 737-739、`_ITEM_LABELS` 966-973、`save_strategy` 归类 1035-1040)
- Test: `backend/tests/test_chat_override.py`(新建)

**Interfaces:**
- Consumes: 既有 `value_overrides: dict[str, str]`(93 行)、`_trail(kind, tool, value, text)`(707-711)、`handle_message` chat 路由、FakeWS(tests/test_agent_manager.py:7)
- Produces: trail kind `chat_override`(Task 2/3 不依赖,但 `save_strategy` 归类与 `_ITEM_LABELS` 必须识别);suffix 文案 `将{tool}相关数值修正为「{value}」(以用户提供数据为准,必须采纳)`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_chat_override.py`:

```python
"""复盘对话异议升格为数据修正(override):用户新数据生效通道。"""
import agent_manager
from tests.test_agent_manager import FakeWS

SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch):
    async def fake_stream(msg, **kwargs):
        yield {"event_type": "complete", "payload": {}, "session_id": "s1"}

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr._run_replay = True
    return mgr


async def test_chat_objection_registers_override(monkeypatch):
    """对话异议登记时同步写 value_overrides(用户陈述即权威数据)。"""
    mgr = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind",
                              "message": "数据修正:风速15m/s,绝缘子串风偏角10度"})
    assert mgr.value_overrides["WindDiagnosisTool"] == "数据修正:风速15m/s,绝缘子串风偏角10度"
    assert mgr.confirm_decisions["WindDiagnosisTool"]["decision"] == "chat"


async def test_second_chat_objection_overwrites_first(monkeypatch):
    """同一工具多次对话异议:后者覆盖前者。"""
    mgr = make_mgr(monkeypatch)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "数据修正:风速15m/s"})
    await mgr.handle_message({"type": "chat", "agent": "wind", "message": "数据修正:风速12m/s"})
    assert mgr.value_overrides["WindDiagnosisTool"] == "数据修正:风速12m/s"


def test_objection_command_chat_becomes_strong_override():
    """chat 分支:trail kind=chat_override + 强约束 suffix。"""
    mgr = agent_manager.AgentManager()
    kind, text = mgr._objection_command(
        "WindDiagnosisTool", {"decision": "chat", "value": "风速15m/s,风偏角10度"})
    assert kind == "suffix"
    assert "WindDiagnosisTool" in text
    assert "风速15m/s,风偏角10度" in text
    assert "以用户提供数据为准" in text
    assert mgr.intervention_trail[-1]["kind"] == "chat_override"
    assert mgr.value_overrides["WindDiagnosisTool"] == "风速15m/s,风偏角10度"


def test_chat_override_has_label():
    """chat_override 必须进保存清单(_ITEM_LABELS 覆盖,否则干预丢失)。"""
    mgr = agent_manager.AgentManager()
    mgr._trail("chat_override", "WindDiagnosisTool", "风速15m/s")
    items = mgr._intervention_items()
    assert len(items) == 1
    assert items[0]["kind"] == "chat_override"
    assert "数据修正" in items[0]["label"]


async def test_save_strategy_treats_chat_override_as_override(monkeypatch):
    """save_strategy:chat_override 视同 override 进 custom_data 与 trail。"""
    captured = {}

    def fake_build(payload):
        captured.update(payload)
        return "md"

    async def fake_save(name, content):
        return {"success": True}

    monkeypatch.setattr(agent_manager.strategy_builder, "build_skill_markdown", fake_build)
    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_save)
    monkeypatch.setattr(agent_manager, "_load_trails", lambda: {})
    monkeypatch.setattr(agent_manager, "_write_trails", lambda t: None)
    mgr = agent_manager.AgentManager()
    mgr._trail("chat_override", "WindDiagnosisTool", "风速15m/s")
    await mgr.save_strategy("测试策略")
    assert any("数据修正" in s for s in captured["custom_data"])
    assert {"kind": "chat_override", "tool": "WindDiagnosisTool", "value": "风速15m/s"} in captured["trail"]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
.venv/bin/python -m pytest tests/test_chat_override.py -v
```

预期:5 条全 FAIL(`value_overrides` 未写、suffix 无「以用户提供数据为准」、无 `chat_override` 标签、custom_data 为空)。

- [ ] **Step 3: 实现**

`backend/agent_manager.py` 四处。

① `_replay_agent_chat`(原 883 行 `self.confirm_decisions[tool] = ...` 之后)插入:

```python
        # 对话异议升格为数据修正:用户陈述即权威数据,随快照/确认事件下发显示
        self.value_overrides[tool] = message
```

② `_objection_command` chat 分支(原 737-739)替换为:

```python
        if decision == "chat":
            self._trail("chat_override", tool, value)
            self.value_overrides[tool] = str(value)
            return "suffix", f"将{tool}相关数值修正为「{value}」(以用户提供数据为准,必须采纳)"
```

③ `_ITEM_LABELS`(原 966-973):删除 `"chat"` 行,新增:

```python
        "chat_override": lambda t: f"{t['tool']}数据修正(对话):{t['value']}",
```

④ `save_strategy` 归类(原 1035-1040):commander_rules 删除 `+ [it["label"] for it in selected if it["kind"] == "chat"]`;custom_data 与 trail 改为:

```python
            "custom_data": [it["label"] for it in selected
                            if it["kind"] in ("override", "chat_override")],
            "trail": [{"kind": it["kind"], "tool": it["tool"], "value": it["value"]}
                      for it in selected if it["kind"] in ("override", "chat_override", "time_range")],
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd backend
.venv/bin/python -m pytest tests/test_chat_override.py -v
.venv/bin/python -m pytest tests/ -q
```

预期:新测试全 PASS;全量 PASS 无回归(既有 chat 语义测试不受影响——confirm_decisions 的 `decision == "chat"` 保留)。

- [ ] **Step 5: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/agent_manager.py backend/tests/test_chat_override.py
git commit -m "feat(replay): 对话异议升格数据修正(登记override+强约束suffix+保存归类)"
```

---

### Task 2: 保存清单去重 + report_summary 补全(backend)

**Files:**
- Modify: `backend/agent_manager.py`(合并日志 561-562、`_intervention_items` 985-991、`_finish_run` summary_event 791-802)
- Test: `backend/tests/test_intervention_items.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `chat_override`(本任务测试可用 `weight`/`override` 等既有 kind,不依赖 Task 1)
- Produces: `report_summary` 事件新字段 `overrides: dict`、`report_modifies: list[str]`(Task 3 前端消费);`objection_log` 合并条目带 `auto_merged: True`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_intervention_items.py`:

```python
"""保存清单去重(auto_merged)+ report_summary 事件补全(overrides/report_modifies)。"""
import agent_manager
from tests.test_agent_manager import COMPLETE_STREAM, SESSION, FakeWS, make_manager


def test_auto_merged_entry_excluded_from_items():
    """①②提报的合并日志条目(auto_merged)不进保存清单,消除「总结」歧义。"""
    mgr = agent_manager.AgentManager()
    mgr._trail("weight", "LightningDiagnosisTool", 0.1)
    mgr._trail("override", "WindDiagnosisTool", "风速15m/s")
    mgr._trail("report_modify", text="去掉第六章")
    mgr.objection_log.append({
        "time": "12:00:00", "kind": "diagnosis_objection",
        "text": "将LightningDiagnosisTool权重调整为0.1；将WindDiagnosisTool相关数值修正为风速15m/s",
        "auto_merged": True})
    items = mgr._intervention_items()
    assert len(items) == 3
    assert not any(it["kind"] == "diagnosis_objection" for it in items)


def test_manual_diagnosis_objection_kept():
    """审核期用户手输的诊断流程异议(无 auto_merged 标记)照常进清单。"""
    mgr = agent_manager.AgentManager()
    mgr.objection_log.append({
        "time": "12:00:00", "kind": "diagnosis_objection", "text": "重新组织取数逻辑"})
    items = mgr._intervention_items()
    assert any(it["kind"] == "diagnosis_objection" and "诊断要求" in it["label"]
               for it in items)


async def test_report_summary_carries_overrides_and_report_modifies(monkeypatch):
    """report_summary 事件携带 overrides 与 report_modifies(前端比对消费)。"""
    mgr = make_manager(monkeypatch, COMPLETE_STREAM, SESSION)
    mgr.value_overrides["WindDiagnosisTool"] = "风速15m/s"
    mgr._trail("report_modify", text="去掉第六章")
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.run_diagnosis(replay=False)
    rs = [e for e in ws.events if e["type"] == "report_summary"]
    assert len(rs) == 1
    assert rs[0]["overrides"] == {"WindDiagnosisTool": "风速15m/s"}
    assert rs[0]["report_modifies"] == ["去掉第六章"]
```

> 注:`make_manager`/`COMPLETE_STREAM`/`SESSION`/`FakeWS` 从 `tests/test_agent_manager.py` 导入(该文件 45-57 行的既有测试同构)。若 `run_diagnosis(replay=False)` 在 value_overrides 预设下行为异常,检查 501 行只清 objection_log、不清 value_overrides——预设值应保留到 _finish_run。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
.venv/bin/python -m pytest tests/test_intervention_items.py -v
```

预期:3 条 FAIL(items 含第 4 项合并条目 / report_summary 无 overrides 字段)。

- [ ] **Step 3: 实现**

`backend/agent_manager.py` 三处。

① 合并日志条目(原 561-562)加标记:

```python
                            self.objection_log.append({
                                "time": now, "kind": "diagnosis_objection", "text": all_text,
                                "auto_merged": True})  # 逐项已在 trail,合并条目不进保存清单
```

② `_intervention_items`(原 986 行)跳过标记条目:

```python
        for o in self.objection_log:
            if o.get("kind") == "diagnosis_objection" and not o.get("auto_merged"):
```

(原 `if o.get("kind") == "diagnosis_objection":` 改为上行,其余不动。)

③ `_finish_run` 的 summary_event(原 791-800)增加两字段:

```python
        summary_event = {
            "type": "report_summary",
            "kind": kind,
            "summary": summary,
            "report": run_record.get("report", ""),
            "weights": weights,
            "excluded_tools": excluded,
            "overrides": dict(self.value_overrides),
            "report_modifies": [t["text"] for t in self.intervention_trail
                                if t.get("kind") == "report_modify"],
            "action_log": (session or {}).get("action_log", [])[self._action_count_at_start:],
            "time": run_record["time"],
        }
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd backend
.venv/bin/python -m pytest tests/test_intervention_items.py -v
.venv/bin/python -m pytest tests/ -q
```

预期:全 PASS。

- [ ] **Step 5: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/agent_manager.py backend/tests/test_intervention_items.py
git commit -m "feat(replay): 保存清单去除自动合并条目+report_summary携带overrides与报告修改"
```

---

### Task 3: 前端弹窗醒目改值 + 比对补全

**Files:**
- Modify: `frontend/src/components/AgentSessionModal.vue`(「已改值」行 211)
- Modify: `frontend/src/components/CompareModal.vue`(rows 13-25、diffTags 28-44)
- Test: 无(构建验证)

**Interfaces:**
- Consumes: Task 2 的 `report_summary.overrides` / `report_summary.report_modifies`(经 `store.summaries[kind]` 整事件存储,ws.js 零改动);既有 `session.override`(tool_confirm_request 携带)
- Produces: 无

- [ ] **Step 1: AgentSessionModal 已改值醒目块**

`frontend/src/components/AgentSessionModal.vue` 原 211 行:

```html
        <div v-if="session.override" class="mt-1.5 text-[11px] text-amber-300">已改值:{{ session.override }}</div>
```

替换为:

```html
        <div
          v-if="session.override"
          class="mt-1.5 rounded border border-amber-400/50 bg-amber-500/15 px-2.5 py-1.5 text-[11px] text-amber-200"
        ><span class="font-bold">以您提供的数据为准:</span>{{ session.override }}</div>
```

- [ ] **Step 2: CompareModal 数据修正行 + 差异标签**

`frontend/src/components/CompareModal.vue`:

① script 顶部 fmtE 之后加格式化函数:

```js
const fmtO = (o) => Object.entries(o || {}).map(([t, v]) => `${short(t)}:${v}`).join(';') || '无'
```

② rows 数组(原「排除工具」行之后)追加一行:

```js
    { label: '数据修正', base: fmtO(b.overrides), replay: fmtO(r.overrides), changed: fmtO(b.overrides) !== fmtO(r.overrides) },
```

③ diffTags computed return 之前追加:

```js
  const rO = rp.value?.overrides || {}
  for (const t of Object.keys(rO)) {
    tags.push({ text: `${short(t)} 数据修正`, cls: 'border-amber-400/50 bg-amber-500/15 text-amber-200' })
  }
  for (const m of rp.value?.report_modifies || []) {
    tags.push({ text: `报告修改:${m}`, cls: 'border-violet-400/50 bg-violet-500/15 text-violet-200' })
  }
```

- [ ] **Step 3: 构建验证**

```bash
cd frontend
npm run build
```

预期:构建成功无报错。

- [ ] **Step 4: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/src/components/AgentSessionModal.vue frontend/src/components/CompareModal.vue
git commit -m "feat(frontend): 确认弹窗用户数据醒目展示+复盘比对补数据修正与报告修改"
```

---

### Task 4: 全量回归 + 实测核对清单

**Files:** 无(纯验证)

**Interfaces:**
- Consumes: Task 1-3 全部完成
- Produces: 无

- [ ] **Step 1: backend 全量测试**

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

预期:全部 PASS(≥63 条,含新增 8 条)。

- [ ] **Step 2: 前端构建**

```bash
cd frontend
npm run build 2>&1 | tail -3
```

预期:成功。

- [ ] **Step 3: 实测核对(记录交用户)**

网络可达 LLM 时按原实测路径复测:1) 对话提风速15/风偏角10° → 重确认弹窗顶部应显示「以您提供的数据为准」醒目块,最终报告采纳用户数据;2) 保存提示应为 3 项(权重0.1/风速修正/去第六章),无「诊断要求」合并条目;3) 复盘比对出现「数据修正」行 + amber 数据修正标签 + violet 报告修改标签。

---

## Self-Review 记录

- Spec 覆盖:§1 升格→Task 1①②+Step 2 前端(Task 3 Step 1);_ITEM_LABELS/save 归类→Task 1③④;§2 去重→Task 2①②;§3 比对→Task 2③+Task 3 Step 2;测试 1-4→Task 1/2 Step 1;「不做的事」→无任务,符合
- 占位符:Task 2 测试有「若异常检查 501 行」注记——异步全流程测试的既有调试模式(参照 test_agent_manager.py:45),断言完整无占位
- 类型一致:`chat_override` kind 在 Task 1 产出、Task 1③④ 消费、Task 2 不依赖;`overrides: dict`、`report_modifies: list[str]` Task 2 产出、Task 3 消费;`auto_merged: True` 标记名一致
- 删除旧 `"chat"` 标签/归类分支的安全性:trail 仅存当次运行内存,存档 objections 是 objection_log(kind 为 tool_objection/diagnosis_objection,非 trail kind),无兼容面
