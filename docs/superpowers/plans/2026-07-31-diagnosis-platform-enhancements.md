# 诊断平台五项增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复复盘异议不重跑/空报告问题，策略生成对齐旧项目自包含 skill 逻辑，实时诊断报告生成即完成，指挥室改深色系，支持自由文本线路输入+排队诊断+历史结果集。

**Architecture:** 后端 FastAPI（`backend/agent_manager.py` 编排 + `pld_client.py` 对接 PLDiagnosis:5000）；新增 `strategy_builder.py`（确定性构建 skill Markdown）、`records.py`（结果集 JSON 持久化）、`skills/comprehensive_diagnosis.md`（基线）。前端 Vue3：`TopBar.vue`/两个弹窗改造，新增 `HistoryView.vue`，`CommandRoom.js` 仅改材质灯光。前后端经 WebSocket JSON 事件通信。

**Tech Stack:** Python 3 + FastAPI + httpx + pytest（asyncio_mode=auto）；Vue3 + Three.js + Tailwind。

**Spec:** `docs/superpowers/specs/2026-07-31-diagnosis-platform-enhancements-design.md`

## Global Constraints

- 最小改动原则：不重构与需求无关的代码；复用现有 WS 事件与弹窗模式。
- 后端测试：`cd backend && python3 -m pytest tests/ -v`（pytest.ini 已配 asyncio_mode=auto）。
- 测试模式：monkeypatch `agent_manager.pld_client.*`，`FakeWS`/`make_manager` 从 `tests/test_agent_manager.py` 复用。
- 提交信息风格（沿用 git log）：`type(scope): 中文描述`，type ∈ feat/fix/test/refactor，scope ∈ backend/frontend/docs。
- git 无全局身份配置，每次提交用 `git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit ...`，**不得**修改 git config。
- 不新增 Python 依赖（不引入 pyyaml，weights YAML 块用字符串拼接）。
- 基线 skill 来源：已克隆的旧项目在 `/tmp/pldiag_mcp/skills/comprehensive_diagnosis.md`；若不存在则从 GitHub 重新克隆 `https://github.com/y1018429125-ship-it/Cluade_PLDiagonsis-mcp-version.git`（branch `mcp_version`）。

---

### Task 1: strategy_builder 确定性 skill 构建器 + 基线 skill

**Files:**
- Create: `backend/strategy_builder.py`
- Create: `backend/skills/comprehensive_diagnosis.md`（从旧项目复制）
- Test: `backend/tests/test_strategy_builder.py`

**Interfaces:**
- Produces: `strategy_builder.build_skill_markdown(config: dict, skills_dir: Path = SKILLS_DIR) -> str`。config keys：`name, line_context, weights, excluded_tools, template_name, commander_rules, report_modifications, custom_data, trail`（trail 元素 `{kind, tool, value, text}`）。Task 2 的 `save_strategy` 依赖此签名。

- [ ] **Step 1: 复制基线 skill 并写失败测试**

```bash
mkdir -p "/Users/bei/DEVLOPE/3d agent/backend/skills"
cp /tmp/pldiag_mcp/skills/comprehensive_diagnosis.md "/Users/bei/DEVLOPE/3d agent/backend/skills/comprehensive_diagnosis.md"
# 若 /tmp/pldiag_mcp 不存在：git clone --depth 1 --branch mcp_version https://github.com/y1018429125-ship-it/Cluade_PLDiagonsis-mcp-version.git /tmp/pldiag_mcp 后再 cp
```

写 `backend/tests/test_strategy_builder.py`：

```python
"""strategy_builder：确定性构建完整自包含 Skill Markdown。"""
import strategy_builder

BASE = """---
name: comprehensive_diagnosis
description: base
---

# 输电线路综合诊断

```yaml
weights:
  LightningDiagnosisTool: 1.0
  IcingDiagnosisTool: 0.9
```

## 工具调用策略

| Tool | Weight | Call Condition |
|------|--------|---------------|
| LightningDiagnosisTool | 1.0 | Always call |
| IcingDiagnosisTool | 0.9 | Call when temp <= 5C |
"""


def _base_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "comprehensive_diagnosis.md").write_text(BASE, encoding="utf-8")
    return d


def _config(**over):
    cfg = {
        "name": "夏季策略",
        "line_context": "500kV雅湖线",
        "weights": {"LightningDiagnosisTool": 0.5, "IcingDiagnosisTool": 0.9},
        "excluded_tools": ["IcingDiagnosisTool"],
        "template_name": "",
        "commander_rules": ["雷电诊断必须结合地形数据"],
        "report_modifications": ["删除第三章"],
        "custom_data": ["将LightningDiagnosisTool相关数值修正为雷电流 28kA"],
        "trail": [{"kind": "override", "tool": "LightningDiagnosisTool", "value": "雷电流 28kA", "text": ""},
                  {"kind": "exclude", "tool": "IcingDiagnosisTool", "value": None, "text": ""}],
    }
    cfg.update(over)
    return cfg


def test_frontmatter_and_base_body(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert md.startswith("---\nname: 夏季策略")
    assert "500kV雅湖线" in md
    assert "# 输电线路综合诊断" in md  # 基线正文保留


def test_weights_block_updated(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert "LightningDiagnosisTool: 0.5" in md
    assert "weights:" in md


def test_excluded_tool_marked_skip(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert "**SKIP — excluded by user preference**" in md
    assert "**SKIP IcingDiagnosisTool entirely**" in md


def test_personalized_sections(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert "## 司令决策规则（必须遵循）" in md and "雷电诊断必须结合地形数据" in md
    assert "## 报告撰写规则（必须遵循）" in md and "删除第三章" in md
    assert "## 用户自定义数据记录" in md and "雷电流 28kA" in md
    assert "## 参数修改记录（已烘入，激活即生效）" in md


def test_weight_change_listed(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert "override default 1.0" in md  # 0.5 vs 默认 1.0


def test_missing_base_returns_empty_body(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=d)
    assert md.startswith("---\nname: 夏季策略")  # 不崩溃
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "/Users/bei/DEVLOPE/3d agent/backend" && python3 -m pytest tests/test_strategy_builder.py -v`
Expected: FAIL（`ModuleNotFoundError: strategy_builder`）

- [ ] **Step 3: 实现 strategy_builder.py**

创建 `backend/strategy_builder.py`：

```python
"""策略技能构建器：代码层确定性构建完整自包含 Skill Markdown。

对齐旧项目 Cluade_PLDiagonsis-mcp-version save_skill.py 的逻辑：
基线 comprehensive_diagnosis.md 全文 + frontmatter + weights 更新
+ 排除工具 SKIP 标记 + 个性化章节（司令决策规则/报告撰写规则/参数修改/自定义数据）。
"""
import re
from datetime import datetime
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"
BASE_SKILL_NAME = "comprehensive_diagnosis"
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

DEFAULT_WEIGHTS = {
    "LightningDiagnosisTool": 1.0,
    "IcingDiagnosisTool": 0.9,
    "WindDiagnosisTool": 0.8,
    "BirdDamageDiagnosisTool": 0.6,
}


def build_skill_markdown(config: dict, skills_dir: Path = SKILLS_DIR) -> str:
    frontmatter = _build_frontmatter(config["name"], config.get("line_context") or "transmission lines")
    body = _load_base_body(skills_dir)
    body = _mark_excluded(body, config.get("excluded_tools") or [])
    body = _update_weights(body, config.get("weights") or {})
    return f"{frontmatter}\n\n{body}\n\n{_build_personalized(config)}"


def _build_frontmatter(name: str, line: str) -> str:
    return f"""---
name: {name}
description: |
  USE THIS SKILL when diagnosing power transmission line faults for {line}.
  ALWAYS activate when the input contains line name "{line}" combined with
  fault/trip/abnormal/flashover/ground/short-circuit keywords.
  Applies to 220kV/500kV/750kV/1000kV transmission lines.
  DO NOT use for distribution lines (below 110kV) or non-power-system diagnostics.
---"""


def _load_base_body(skills_dir: Path) -> str:
    path = skills_dir / f"{BASE_SKILL_NAME}.md"
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    m = FRONTMATTER_PATTERN.match(content)
    return content[m.end():].strip() if m else content.strip()


def _mark_excluded(body: str, excluded: list) -> str:
    for tool in excluded:
        pattern = rf"(\|\s*\*?{re.escape(tool)}\*?\s*\|[^|]+\|)([^|]*)\|"
        body = re.sub(pattern, rf"\1 **SKIP — excluded by user preference** |", body)
    return body


def _update_weights(body: str, weights: dict) -> str:
    if not weights:
        return body
    lines = "\n".join(f"  {t}: {w}" for t, w in weights.items())
    return re.sub(r"```yaml\s*\nweights:.*?```",
                  f"```yaml\nweights:\n{lines}\n```", body, flags=re.DOTALL)


def _build_personalized(config: dict) -> str:
    sections = ["# 基于本次诊断会话的个性化优化\n"]
    excluded = config.get("excluded_tools") or []
    if excluded:
        sections.append("## 排除的工具\n")
        for t in excluded:
            sections.append(f"- **SKIP {t} entirely** — do not include it in the diagnosis plan or report.")
        sections.append("")
    changes = [(t, w) for t, w in (config.get("weights") or {}).items()
               if t in DEFAULT_WEIGHTS and float(w) != DEFAULT_WEIGHTS[t]]
    if changes:
        sections.append("## 权重调整\n")
        for t, w in changes:
            sections.append(f"- {t}: use weight {w} (override default {DEFAULT_WEIGHTS[t]})")
        sections.append("")
    rules = config.get("commander_rules") or []
    if rules:
        sections.append("## 司令决策规则（必须遵循）\n")
        sections.append("When planning and orchestrating the diagnosis, the commander MUST apply these rules:")
        for r in rules:
            sections.append(f"- **{r}**")
        sections.append("")
    mods = config.get("report_modifications") or []
    if mods:
        sections.append("## 报告撰写规则（必须遵循）\n")
        sections.append("When composing the report, apply the following rules IN ADDITION to the standard template structure:")
        for r in mods:
            sections.append(f"- **{r}**")
        sections.append("")
    trail = [t for t in (config.get("trail") or [])
             if t.get("kind") in ("override", "time_range", "external_data")]
    if trail:
        sections.append("## 参数修改记录（已烘入，激活即生效）\n")
        for t in trail:
            sections.append(f"- {t.get('kind')}: {t.get('tool', '')} -> {t.get('value')}")
        sections.append("")
    custom = config.get("custom_data") or []
    if custom:
        sections.append("## 用户自定义数据记录\n")
        for c in custom:
            sections.append(f"- {c}")
        sections.append("")
    if config.get("template_name"):
        sections.append("## 模板引用\n")
        sections.append(f"- Use template **{config['template_name']}** as the report structure guide.")
        sections.append("")
    sections.append(f"---\n\n*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(sections)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "/Users/bei/DEVLOPE/3d agent/backend" && python3 -m pytest tests/test_strategy_builder.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/strategy_builder.py backend/skills/comprehensive_diagnosis.md backend/tests/test_strategy_builder.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(backend): 策略skill确定性构建器+基线skill(对齐旧项目save_skill逻辑)"
```

---

### Task 2: save_strategy 接入构建器 + objection_log 全程记录 + 移除激活重放

**Files:**
- Modify: `backend/agent_manager.py`（__init__、handle_message 的 tool_confirm_response/chat 分支、activate_skill 分支、save_strategy；删除 `_replay_trail`）
- Test: `backend/tests/test_named_save.py`（追加断言）、删除 `backend/tests/test_trail_replay.py`

**Interfaces:**
- Consumes: `strategy_builder.build_skill_markdown(config)`（Task 1）。
- Produces: `AgentManager.objection_log: list[dict]`，元素 `{time, kind, text?, tool?, decision?, value?}`，kind ∈ `tool_objection | custom_data | report_modify | diagnosis_objection | user_input`。Task 3 写入 `diagnosis_objection`；Task 6 把 objection_log 存入结果集。

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_named_save.py` 末尾追加：

```python
async def test_save_strategy_builds_full_skill(monkeypatch, tmp_path):
    """保存策略生成完整自包含 skill：含 frontmatter/基线正文/个性化章节。"""
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", tmp_path / "trails.json")
    saved = {}

    async def fake_skill(name, content):
        saved["content"] = content
        return {"success": True}

    async def fake_session(sid):
        return {"active_weights": {"LightningDiagnosisTool": 1.0},
                "excluded_tools": ["BirdDamageDiagnosisTool"]}

    monkeypatch.setattr(agent_manager.pld_client, "save_skill", fake_skill)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    mgr.current_line = "500kV雅湖线 跳闸"
    mgr.intervention_trail = [{"kind": "override", "tool": "LightningDiagnosisTool",
                               "value": "雷电流 28kA", "text": "", "time": "t"}]
    mgr.objection_log = [
        {"kind": "report_modify", "text": "删除第三章"},
        {"kind": "diagnosis_objection", "text": "雷电诊断要考虑地形"},
        {"kind": "custom_data", "text": "将LightningDiagnosisTool相关数值修正为雷电流 28kA"},
    ]
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.save_strategy("全量策略")
    content = saved["content"]
    assert content.startswith("---\nname: 全量策略")
    assert "输电线路综合诊断" in content          # 基线正文
    assert "SKIP BirdDamageDiagnosisTool entirely" in content
    assert "## 司令决策规则（必须遵循）" in content and "雷电诊断要考虑地形" in content
    assert "## 报告撰写规则（必须遵循）" in content and "删除第三章" in content
    assert "## 用户自定义数据记录" in content


async def test_objection_log_records_confirm_and_chat(monkeypatch, tmp_path):
    """复盘确认异议与用户直聊均写入 objection_log。"""
    monkeypatch.setattr(agent_manager, "TRAILS_FILE", tmp_path / "t.json")
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"

    async def fake_stream(msg):
        yield {"event_type": "complete", "payload": {"report": "r", "summary": {}}, "session_id": "s1"}

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    ws = FakeWS()
    await mgr.connect(ws)
    mgr.pending_confirms["LightningDiagnosisTool"] = {"tool": "LightningDiagnosisTool"}
    mgr._confirms_done = __import__("asyncio").Event()
    await mgr.handle_message({"type": "tool_confirm_response",
                              "tool": "LightningDiagnosisTool",
                              "decision": "override", "value": "雷电流 28kA"})
    assert mgr.objection_log[0]["kind"] == "custom_data"
    await mgr.handle_message({"type": "chat", "agent": "commander", "message": "排除鸟害工具"})
    kinds = [o["kind"] for o in mgr.objection_log]
    assert "user_input" in kinds
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "/Users/bei/DEVLOPE/3d agent/backend" && python3 -m pytest tests/test_named_save.py -v`
Expected: 新 2 个测试 FAIL（objection_log 不存在 / skill 内容不符）

- [ ] **Step 3: 修改 agent_manager.py**

3a. 文件头 import 区加：

```python
import strategy_builder
```

3b. `__init__` 末尾追加：

```python
        self.objection_log: list[dict] = []     # 全程异议/意见/用户输入记录（供 skill 与结果集）
        self.current_line: str = ""             # 当前诊断线路文本（Task 6 使用）
        self.current_record_id: int | None = None  # 当前诊断对应的结果集记录 id（Task 6 使用）
```

3c. `handle_message` 的 `tool_confirm_response` 分支，在 `self.confirm_decisions[tool] = {...}` 之前插入：

```python
            decision = data.get("decision", "ok")
            if decision != "ok":
                now = datetime.datetime.now().strftime("%H:%M:%S")
                if decision == "override":
                    self.objection_log.append({
                        "time": now, "kind": "custom_data", "tool": tool,
                        "text": f"将{tool}相关数值修正为{data.get('value')}"})
                else:
                    self.objection_log.append({
                        "time": now, "kind": "tool_objection", "tool": tool,
                        "decision": decision, "value": data.get("value")})
```

3d. `handle_message` 的 `chat` 分支，在 `task = asyncio.create_task(...)` 之前插入（用户输入全程记录）：

```python
                self.objection_log.append({
                    "time": datetime.datetime.now().strftime("%H:%M:%S"),
                    "kind": "user_input",
                    "text": f"[{AGENTS[agent]['name']}] {message}"})
```

3e. `activate_skill` 分支删除最后一行 `await self._replay_trail(name)`（轨迹已烘入 skill，激活无需重放），并**删除整个 `_replay_trail` 方法**（agent_manager.py:213-237）。

3f. `save_strategy` 中替换 content 构建段（agent_manager.py:695-703 的 lines 拼装）为：

```python
        content = strategy_builder.build_skill_markdown({
            "name": name,
            "line_context": self.current_line or "transmission lines",
            "weights": weights,
            "excluded_tools": excluded,
            "template_name": "",
            "report_modifications": [o["text"] for o in self.objection_log if o["kind"] == "report_modify"],
            "commander_rules": [o["text"] for o in self.objection_log
                                if o["kind"] in ("diagnosis_objection", "user_input")],
            "custom_data": [o["text"] for o in self.objection_log if o["kind"] == "custom_data"],
            "trail": list(self.intervention_trail),
        })
```

3g. 删除 `backend/tests/test_trail_replay.py`（激活重放行为已移除）。

- [ ] **Step 4: 运行全部后端测试**

Run: `cd "/Users/bei/DEVLOPE/3d agent/backend" && python3 -m pytest tests/ -v`
Expected: 全 PASS（含原 test_named_save 两个用例——它们不断言 content）

- [ ] **Step 5: Commit**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/agent_manager.py backend/tests/test_named_save.py
git rm backend/tests/test_trail_replay.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(backend): 保存策略生成完整自包含skill+全程异议记录objection_log+移除激活重放"
```

---

### Task 3: 复盘流程修复——空结果标记 + 异议分类 + 诊断异议重跑

**Files:**
- Modify: `backend/agent_manager.py`（抽取 `_stream_run`；`run_diagnosis` 重构；`tool_confirm_request` 增加 `empty`；`report_review_request` 增加 `empty`；审核循环支持 `kind`）
- Test: `backend/tests/test_review_objection.py`（新）

**Interfaces:**
- Produces:
  - `AgentManager._stream_run(message: str, replay: bool, run_record: dict) -> dict`（返回 complete 的 summary；出错抛异常）。
  - `AgentManager.run_diagnosis(replay: bool = False, text: str = "")`——签名向后兼容（Task 6 用 `text`）。
  - WS 事件：`tool_confirm_request` 新增 `empty: bool`；`report_review_request` 新增 `empty: bool`；`report_review_response` 接受 `kind: "report"|"diagnosis"`。Task 4 前端依赖。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_review_objection.py`：

```python
"""复盘报告审核：诊断类异议触发完整重跑；报告类异议仅改报告；空结果标记。"""
import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS

RESULT_OK = {"event_type": "result", "payload": {
    "tool": "LightningDiagnosisTool",
    "output": {"structured_data": {"fault_type": "雷击-绕击", "confidence": 0.9,
                                   "evidence": ["证据A"]}, "raw_text": "raw"}},
    "session_id": "s1"}
RESULT_EMPTY = {"event_type": "result", "payload": {
    "tool": "WindDiagnosisTool", "output": {"structured_data": {}, "raw_text": ""}},
    "session_id": "s1"}
COMPLETE = {"event_type": "complete", "payload": {
    "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
    "session_id": "s1"}
SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls):
    async def fake_stream(msg):
        calls.append(msg)
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        yield RESULT_OK
        yield COMPLETE

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_diagnosis_objection_triggers_full_rerun(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.2)
        # 第一轮逐项确认
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.2)
        # 第一轮报告审核：诊断类异议
        await mgr.handle_message({"type": "report_review_response", "satisfied": False,
                                  "instruction": "雷电诊断要考虑地形", "kind": "diagnosis"})
        await asyncio.sleep(0.4)
        # 重跑后的逐项确认
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.2)
        # 重跑后的报告审核：满意
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    # 第二次诊断流携带异议上下文
    assert any("雷电诊断要考虑地形" in c and "复盘异议" in c for c in calls[1:])
    assert any(o["kind"] == "diagnosis_objection" for o in mgr.objection_log)
    reviews = [e for e in ws.events if e["type"] == "report_review_request"]
    assert len(reviews) == 2


async def test_report_objection_only_modifies_report(monkeypatch):
    calls = []
    mgr = make_mgr(monkeypatch, calls)
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "LightningDiagnosisTool", "decision": "ok"})
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "report_review_response", "satisfied": False,
                                  "instruction": "删除第三章", "kind": "report"})
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    # 报告类异议原文下发，不加重跑前缀，不重跑诊断
    assert "删除第三章" in calls[-1] and "复盘异议" not in calls[-1]
    assert any(o["kind"] == "report_modify" for o in mgr.objection_log)


async def test_empty_result_flagged_in_confirm(monkeypatch):
    async def fake_stream(msg):
        yield {"event_type": "start", "payload": {}, "session_id": "s1"}
        yield RESULT_EMPTY
        yield COMPLETE

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)

    async def respond():
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "tool_confirm_response",
                                  "tool": "WindDiagnosisTool", "decision": "recheck"})
        await asyncio.sleep(0.2)
        await mgr.handle_message({"type": "report_review_response", "satisfied": True})

    await asyncio.gather(mgr.run_diagnosis(replay=True), respond())
    confirms = [e for e in ws.events if e["type"] == "tool_confirm_request"]
    assert confirms[0]["empty"] is True
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "/Users/bei/DEVLOPE/3d agent/backend" && python3 -m pytest tests/test_review_objection.py -v`
Expected: FAIL（`empty` 字段不存在 / kind 未处理 / 无重跑）

- [ ] **Step 3: 重构 run_diagnosis 并抽取 _stream_run**

3a. 在 `AgentManager` 中新增 `_stream_run`（内容为现 run_diagnosis 里 `async for event in pld_client.chat_stream(...)` 循环体的迁移，`empty` 标记为新增）：

```python
    async def _stream_run(self, message: str, replay: bool, run_record: dict) -> dict:
        """执行一轮 PLD 诊断流：转发事件、更新席位、复盘中收集逐项确认并下发异议。

        返回 complete 事件的 summary；PLD 报错抛 RuntimeError 由调用方捕获。
        """
        report_buf = ""
        summary: dict = {}
        tools_started = False
        tools_done: set[str] = set()
        started_logged = False
        async for event in pld_client.chat_stream(message):
            etype = event.get("event_type")
            payload = event.get("payload", {})
            sid = event.get("session_id")
            if sid:
                self.session_id = sid

            if etype == "start":
                if not started_logged:
                    started_logged = True
                    await self.log("commander", "PLDiagnosis 主智能体已受理，开始意图解析与诊断规划。")
            elif etype == "thinking":
                msg = (payload.get("message") or "").strip()
                if msg and not msg.startswith(("{", '"')):
                    await self.log("commander", msg)
                if "诊断计划" in msg:
                    parsed = parse_planned_tools(msg)
                    if parsed:
                        self.planned_tools = parsed
                        await self._refresh_snapshot()
                if not tools_started and "执行诊断工具" in msg:
                    tools_started = True
                    await self._mark_tools_running()
                if "生成诊断报告" in msg:
                    await self.set_status("audit", "running")
                    await self.log("audit", "接收各诊断工具原始输出，生成规范化综合报告……")
            elif etype == "result":
                tool = payload.get("tool", "")
                aid = TOOL_TO_AGENT.get(tool)
                output = payload.get("output", {}) or {}
                sd = output.get("structured_data", {}) or {}
                if aid:
                    tools_done.add(aid)
                    if self.status[aid] == "running":
                        await self.set_status(aid, "completed")
                    fault = sd.get("fault_type", "—")
                    conf = sd.get("confidence", "—")
                    evid = (sd.get("evidence") or ["—"])[0]
                    raw = output.get("raw_text", "")
                    empty = not raw and not sd
                    if empty:
                        await self.log(aid, f"⚠ {tool} 未返回有效结果。")
                    else:
                        await self.log(aid, f"{tool} 返回：倾向「{fault}」，置信度 {conf}；证据：{evid}")
                    if raw:
                        report_buf += f"\n\n## 📡 {AGENTS[aid]['name']}原始诊断\n\n{raw}\n"
                        await self.broadcast({"type": "report", "content": report_buf, "done": False})
                    if replay:
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
            elif etype == "content":
                chunk = payload.get("content", "")
                if chunk:
                    report_buf += chunk
                    await self.broadcast({"type": "report", "content": report_buf, "done": False})
            elif etype == "complete":
                report = payload.get("report") or report_buf
                summary = payload.get("summary", {})
                self.last_report = report
                run_record["summary"] = summary
                run_record["report"] = report
                run_record["tools_run"] = sorted(tools_done)
                await self.broadcast({"type": "report", "content": report, "done": True})
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
            elif etype == "error":
                raise RuntimeError(payload.get("message", "PLDiagnosis 返回错误"))
        return summary
```

3b. `run_diagnosis` 整体替换为（保留原 try/except/finally 结构，流处理移出；审核循环加 kind；签名加 `text` 供 Task 6 使用）：

```python
    async def run_diagnosis(self, replay: bool = False, text: str = ""):
        message = text or DIAGNOSE_MESSAGE
        self.current_line = message
        await self.broadcast({"type": "report", "content": "", "done": False, "reset": True})
        self.intervention_trail = []
        # 每轮开跑重置本轮计划，防止上一轮「诊断计划」残留被误用
        self.planned_tools = []
        if not replay:
            self.objection_log = []
        run_record: dict = {"replay": replay, "time": datetime.datetime.now().strftime("%H:%M:%S")}
        summary: dict = {}
        try:
            self._run_replay = replay
            self.current_task = asyncio.current_task()
            await self.broadcast({"type": "run_state", "mode": "replay" if replay else "realtime"})
            await self.set_status("commander", "running")
            # 等待进行中的 chat 干预任务完成，避免其触发的自动重诊断与本次诊断冲突
            if self._chat_tasks:
                await asyncio.gather(*list(self._chat_tasks), return_exceptions=True)
            await self._wait_pld_idle()
            if replay:
                await self.log("commander", "【复盘】按已保存的人工干预策略重新执行诊断，验证策略是否生效。")
            else:
                await self.log("commander", f"接收到任务：{message}")

            summary = await self._stream_run(message, replay, run_record)

            if replay:
                # 报告审核循环：报告问题→仅改报告；诊断问题→司令收集意见重跑完整诊断；最多 5 轮
                for _ in range(5):
                    self._review_event = asyncio.Event()
                    self._review_response = {}
                    await self.broadcast({
                        "type": "report_review_request",
                        "empty": not bool((self.last_report or "").strip()),
                    })
                    try:
                        await asyncio.wait_for(self._review_event.wait(), timeout=1800)
                    except asyncio.TimeoutError:
                        break
                    if self._review_response.get("satisfied"):
                        break
                    instruction = str(self._review_response.get("instruction", "")).strip()
                    if not instruction:
                        break
                    now = datetime.datetime.now().strftime("%H:%M:%S")
                    if self._review_response.get("kind", "report") == "diagnosis":
                        self.objection_log.append({
                            "time": now, "kind": "diagnosis_objection", "text": instruction})
                        await self.log("commander",
                                       f"复盘异议（诊断流程）：{instruction}，司令收集意见后重新组织完整诊断。")
                        summary = await self._stream_run(
                            f"{message}\n【复盘异议，本次诊断必须采纳】{instruction}", True, run_record)
                        continue
                    await self.log("audit", f"按指挥员意见修改报告:{instruction}")
                    self._trail("report_modify", text=instruction)
                    self.objection_log.append({
                        "time": now, "kind": "report_modify", "text": instruction})
                    await self._wait_pld_idle()
                    async for ev in pld_client.chat_stream(instruction):
                        p = ev.get("payload", {})
                        if ev.get("event_type") == "complete" and p.get("report"):
                            self.last_report = p["report"]
                            await self.broadcast({"type": "report", "content": p["report"], "done": True})
            await self._finish_run(run_record, summary, replay)
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"诊断流程异常：{exc}")
            await self.set_status("commander", "error")
            if replay:
                self.pending_confirms.clear()
                self.confirm_decisions.clear()
                await self.broadcast({"type": "confirm_queue_clear"})
                await self.log("commander", "【复盘】流程异常终止，确认队列已清空，状态已复位。")
            for aid in TOOL_AGENTS:
                if self.status[aid] == "running":
                    await self.set_status(aid, "idle")
            if self.status["audit"] == "running":
                await self.set_status(aid, "idle")
        finally:
            self._run_replay = False
            await self.broadcast({"type": "run_state", "mode": None})
```

注意：原 `report_buf`、`tools_started` 等局部变量全部移入 `_stream_run`；`_finish_run(run_record, summary, replay)` 调用不变。

- [ ] **Step 4: 运行全部后端测试**

Run: `cd "/Users/bei/DEVLOPE/3d agent/backend" && python3 -m pytest tests/ -v`
Expected: 全 PASS（原 test_replay_flow / test_agent_manager 行为保持不变：report_review_request 仍按轮广播、confirm 事件字段为超集）

- [ ] **Step 5: Commit**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/agent_manager.py backend/tests/test_review_objection.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "fix(backend): 复盘诊断类异议触发完整重跑+空结果标记+报告/诊断异议分类"
```

---

### Task 4: 前端复盘交互——异议类型选择 + 空结果标记

**Files:**
- Modify: `frontend/src/components/ReportReviewModal.vue`
- Modify: `frontend/src/components/AgentSessionModal.vue`
- Modify: `frontend/src/ws.js`、`frontend/src/store.js`

**Interfaces:**
- Consumes: WS `tool_confirm_request.empty`、`report_review_request.empty`（Task 3）。
- Produces: `sendReportReview(satisfied, instruction, kind)`；`store.reportReviewEmpty: boolean`。

- [ ] **Step 1: store.js / ws.js 接线**

`store.js` 在 reactive 对象中追加字段：

```js
  reportReviewEmpty: false, // 复盘报告为空标记（report_review_request.empty）
```

`ws.js` 修改：

```js
    case 'report_review_request':
      store.reportReviewPending = true
      store.reportReviewEmpty = !!event.empty
      break
```

`ws.js` 末尾替换 sendReportReview：

```js
export const sendReportReview = (satisfied, instruction, kind) =>
  send({ type: 'report_review_response', satisfied, instruction, kind })
```

`ws.js` 的 `confirm_queue_clear` 分支追加 `store.reportReviewEmpty = false`。

- [ ] **Step 2: ReportReviewModal.vue 加异议类型**

script 部分：

```js
const opinionKind = ref('report')

watch(() => store.reportReviewPending, (pending) => {
  if (pending) {
    opinionOpen.value = false
    instruction.value = ''
    opinionKind.value = 'report'
  }
})

function submitRevision() {
  const text = instruction.value.trim()
  if (!text) return
  sendReportReview(false, text, opinionKind.value)
  store.reportReviewPending = false
}
```

模板：内容区文本改为动态：

```html
      <div class="px-4 py-3 text-xs text-slate-200 leading-relaxed">
        <template v-if="store.reportReviewEmpty">⚠ 复盘报告内容为空，请提交「诊断流程问题」要求重新执行诊断。</template>
        <template v-else>复盘报告已生成，是否符合要求？</template>
      </div>
```

意见输入区上方（`<div v-if="opinionOpen" class="px-4 pb-3">` 内部 textarea 之前）加类型单选：

```html
        <div class="flex flex-col gap-1 mb-2 text-[11px]">
          <label class="flex items-center gap-1.5 text-slate-300 cursor-pointer">
            <input type="radio" value="report" v-model="opinionKind" class="accent-emerald-400" />
            报告表述问题（仅由报告智能体修改报告）
          </label>
          <label class="flex items-center gap-1.5 text-slate-300 cursor-pointer">
            <input type="radio" value="diagnosis" v-model="opinionKind" class="accent-amber-400" />
            诊断流程问题（司令收集意见后重新执行完整诊断）
          </label>
        </div>
```

- [ ] **Step 3: AgentSessionModal.vue 空结果标记**

在结果区 `<div v-if="hasResult" ...>` 之前插入：

```html
      <div
        v-if="session.empty"
        class="px-4 py-2 text-[11px] text-amber-300 bg-amber-500/10 border-b border-amber-400/30 shrink-0"
      >⚠ 该智能体本轮未返回有效结果，可点击「重新检查」要求重跑该工具</div>
```

- [ ] **Step 4: 前端构建验证**

Run: `cd "/Users/bei/DEVLOPE/3d agent/frontend" && npm run build`
Expected: 构建成功无报错

- [ ] **Step 5: Commit**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/src/components/ReportReviewModal.vue frontend/src/components/AgentSessionModal.vue frontend/src/ws.js frontend/src/store.js
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): 复盘报告异议分类(报告/诊断)+智能体空结果标记"
```

---

### Task 5: 实时诊断完成即可复盘（解除保存策略依赖）

**Files:**
- Modify: `frontend/src/components/TopBar.vue:43`

**Interfaces:**
- Consumes: `store.summaries.realtime`（report_summary 事件已存在）。

- [ ] **Step 1: 修改复盘按钮 disabled 条件与提示**

`TopBar.vue` 复盘按钮改为：

```html
    <button
      :disabled="store.running || !store.connected || !store.summaries.realtime"
      @click="replay"
      class="text-xs font-bold px-3 py-1.5 rounded border border-emerald-400/50 text-emerald-200 bg-emerald-500/15 hover:bg-emerald-400/25 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
      title="实时诊断完成后即可复盘：逐项确认各智能体结果并审核报告"
    >
      ↻ 复盘重跑
    </button>
```

- [ ] **Step 2: 构建验证**

Run: `cd "/Users/bei/DEVLOPE/3d agent/frontend" && npm run build`
Expected: 成功

- [ ] **Step 3: Commit**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/src/components/TopBar.vue
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "fix(frontend): 实时诊断报告生成即完成会话,复盘不再依赖保存策略"
```

---

### Task 6: 后端——自由文本诊断目标 + 排队 + 结果集持久化

**Files:**
- Create: `backend/records.py`
- Modify: `backend/agent_manager.py`（_start_run、handle_message、run_diagnosis finally、_finish_run、save_strategy、connect、SESSION_CONTEXT 用法）
- Test: `backend/tests/test_records.py`、`backend/tests/test_diagnosis_queue.py`

**Interfaces:**
- Produces:
  - `records.create_record(line, time) -> dict`、`records.attach_realtime(rid, report, summary)`、`records.attach_replay(rid, report, summary)`、`records.set_objections(rid, objections)`、`records.attach_strategy(rid, name)`、`records.list_records() -> list`、`records.get_record(rid) -> dict|None`；模块级 `RECORDS_FILE` 可被 monkeypatch。
  - WS 入：`start_diagnosis{text}`、`cancel_queued{index}`、`list_records`、`get_record{id}`。
  - WS 出：`diagnosis_queue{current, queue:[{text,time}]}`、`records_list{records:[{id,line,time,has_replay,strategies,objections}]}`、`record_detail{record}`。Task 7 前端依赖。

- [ ] **Step 1: 实现 records.py 并写测试**

创建 `backend/records.py`：

```python
"""诊断结果集持久化：每次诊断（实时+复盘）写入 backend/data/diagnosis_records.json。"""
import json
from pathlib import Path

RECORDS_FILE = Path(__file__).parent / "data" / "diagnosis_records.json"


def _load() -> list:
    try:
        return json.loads(RECORDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write(recs: list):
    RECORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORDS_FILE.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")


def list_records() -> list:
    return _load()


def get_record(rid: int):
    return next((r for r in _load() if r.get("id") == rid), None)


def create_record(line: str, time: str) -> dict:
    recs = _load()
    rec = {
        "id": max((r.get("id", 0) for r in recs), default=0) + 1,
        "line": line, "time": time,
        "realtime": None, "replays": [],
        "objections": [], "strategies": [],
    }
    recs.append(rec)
    _write(recs)
    return rec


def _update(rid: int, fn):
    recs = _load()
    for r in recs:
        if r.get("id") == rid:
            fn(r)
            _write(recs)
            return


def attach_realtime(rid: int, report: str, summary: dict):
    _update(rid, lambda r: r.__setitem__("realtime", {"report": report, "summary": summary}))


def attach_replay(rid: int, report: str, summary: dict):
    _update(rid, lambda r: r.setdefault("replays", []).append({"report": report, "summary": summary}))


def set_objections(rid: int, objections: list):
    _update(rid, lambda r: r.__setitem__("objections", list(objections)))


def attach_strategy(rid: int, name: str):
    _update(rid, lambda r: r.setdefault("strategies", []).append(name))
```

创建 `backend/tests/test_records.py`：

```python
import records


def test_record_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "RECORDS_FILE", tmp_path / "recs.json")
    rec = records.create_record("500kV雅湖线 跳闸", "10:00:00")
    assert rec["id"] == 1
    records.attach_realtime(rec["id"], "# 实时报告", {"fault_type": "雷击"})
    records.attach_replay(rec["id"], "# 复盘报告", {"fault_type": "雷击"})
    records.set_objections(rec["id"], [{"kind": "diagnosis_objection", "text": "要考虑地形"}])
    records.attach_strategy(rec["id"], "夏季策略")
    got = records.get_record(1)
    assert got["realtime"]["report"] == "# 实时报告"
    assert got["replays"][0]["report"] == "# 复盘报告"
    assert got["objections"][0]["text"] == "要考虑地形"
    assert got["strategies"] == ["夏季策略"]
    assert len(records.list_records()) == 1


def test_corrupt_file_returns_empty(tmp_path, monkeypatch):
    f = tmp_path / "recs.json"
    f.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(records, "RECORDS_FILE", f)
    assert records.list_records() == []
```

创建 `backend/tests/test_diagnosis_queue.py`：

```python
"""诊断排队：运行中提交新线路入队，当前完成后自动开始下一个；可取消排队。"""
import asyncio
import agent_manager
from tests.test_agent_manager import FakeWS

COMPLETE_STREAM = [
    {"event_type": "start", "payload": {}, "session_id": "s1"},
    {"event_type": "complete", "payload": {
        "report": "# 报告", "summary": {"fault_type": "雷击", "confidence": 0.9}},
     "session_id": "s1"},
]
SESSION = {"status": "modifying", "active_weights": {}, "excluded_tools": [], "action_log": []}


def make_mgr(monkeypatch, calls, gate):
    async def fake_stream(msg):
        calls.append(msg)
        if len(calls) == 1:
            await gate.wait()  # 第一轮诊断挂起，模拟执行中
        for e in COMPLETE_STREAM:
            yield e

    async def fake_session(sid):
        return SESSION

    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", fake_stream)
    monkeypatch.setattr(agent_manager.pld_client, "get_session", fake_session)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    return mgr


async def test_queue_and_auto_start(monkeypatch):
    calls = []
    gate = asyncio.Event()
    mgr = make_mgr(monkeypatch, calls, gate)
    ws = FakeWS()
    await mgr.connect(ws)

    await mgr.handle_message({"type": "start_diagnosis", "text": "线路A 跳闸"})
    await asyncio.sleep(0.1)
    await mgr.handle_message({"type": "start_diagnosis", "text": "线路B 跳闸"})
    assert len(mgr.diagnosis_queue) == 1
    assert mgr.diagnosis_queue[0]["text"] == "线路B 跳闸"
    queues = [e for e in ws.events if e["type"] == "diagnosis_queue"]
    assert queues[-1]["queue"][0]["text"] == "线路B 跳闸"

    gate.set()  # 第一轮放行
    await asyncio.sleep(0.5)
    assert calls[0] == "线路A 跳闸"
    assert "线路B 跳闸" in calls  # 自动开始下一线路
    assert mgr.diagnosis_queue == []


async def test_cancel_queued(monkeypatch):
    calls = []
    gate = asyncio.Event()
    mgr = make_mgr(monkeypatch, calls, gate)
    ws = FakeWS()
    await mgr.connect(ws)
    await mgr.handle_message({"type": "start_diagnosis", "text": "线路A 跳闸"})
    await asyncio.sleep(0.1)
    await mgr.handle_message({"type": "start_diagnosis", "text": "线路B 跳闸"})
    await mgr.handle_message({"type": "cancel_queued", "index": 0})
    assert mgr.diagnosis_queue == []
    gate.set()
    await asyncio.sleep(0.5)
    assert "线路B 跳闸" not in calls
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "/Users/bei/DEVLOPE/3d agent/backend" && python3 -m pytest tests/test_records.py tests/test_diagnosis_queue.py -v`
Expected: FAIL（records 不存在 / 排队未实现）

- [ ] **Step 3: 修改 agent_manager.py**

3a. import 区加：

```python
import records
```

3b. `__init__` 末尾追加：

```python
        self.diagnosis_queue: list[dict] = []   # 排队中的诊断（运行中提交的新线路）
```

3c. `SESSION_CONTEXT` 改为动态线路。常量定义处（agent_manager.py:59）改为：

```python
SESSION_CONTEXT = "【当前会话：{line}｜{tool}】"
```

`handle_chat` 非 commander 分支的 `prefixed` 行改为：

```python
            prefixed = SESSION_CONTEXT.format(line=self.current_line or "未知线路", tool=tool) + message
```

3d. `handle_message` 的 `start_diagnosis` 分支改为：

```python
        if mtype == "start_diagnosis":
            await self._start_run(replay=False, text=str(data.get("text", "")).strip())
```

并新增两个分支（放在 `report_review_response` 分支之后）：

```python
        elif mtype == "cancel_queued":
            idx = int(data.get("index", -1))
            if 0 <= idx < len(self.diagnosis_queue):
                item = self.diagnosis_queue.pop(idx)
                await self.log("commander", f"已取消排队诊断：{item['text']}")
                await self._broadcast_queue()
        elif mtype == "list_records":
            await self.send_records()
        elif mtype == "get_record":
            rec = records.get_record(int(data.get("id", -1)))
            if rec:
                await self.broadcast({"type": "record_detail", "record": rec})
```

3e. `_start_run` 替换为：

```python
    async def _start_run(self, replay: bool, text: str = ""):
        if self.current_task and not self.current_task.done():
            if not replay and text:
                self.diagnosis_queue.append({
                    "text": text,
                    "time": datetime.datetime.now().strftime("%H:%M:%S"),
                })
                await self.log("commander",
                               f"诊断执行中，已将「{text}」加入排队（第 {len(self.diagnosis_queue)} 位）。")
                await self._broadcast_queue()
            else:
                await self.log("commander", "已有诊断任务在执行中，请等待完成后再发起。")
            return
        self.current_task = asyncio.create_task(self.run_diagnosis(replay=replay, text=text))
```

3f. 新增两个方法（放在 `_start_run` 之后）：

```python
    async def _broadcast_queue(self):
        await self.broadcast({
            "type": "diagnosis_queue",
            "current": self.current_line,
            "queue": list(self.diagnosis_queue),
        })

    async def send_records(self):
        try:
            summaries = [{
                "id": r.get("id"), "line": r.get("line", ""), "time": r.get("time", ""),
                "has_replay": bool(r.get("replays")),
                "strategies": r.get("strategies", []),
                "objections": [o.get("text", "") for o in r.get("objections", []) if o.get("text")],
            } for r in records.list_records()]
            await self.broadcast({"type": "records_list", "records": summaries})
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"诊断记录读取失败:{exc}")
```

3g. `connect` 方法末尾（`await ws.send_json({...init...})` 之后）加：

```python
        await self._broadcast_queue()
```

3h. `run_diagnosis`（Task 3 版本）中，`message = text or DIAGNOSE_MESSAGE` 行之后加广播：

```python
        await self._broadcast_queue()
```

`finally` 块替换为（自动开始排队中的下一线路）：

```python
        finally:
            self._run_replay = False
            await self.broadcast({"type": "run_state", "mode": None})
            if not replay and self.diagnosis_queue:
                nxt = self.diagnosis_queue.pop(0)
                await self._broadcast_queue()
                await self.log("commander", f"开始排队中的下一线路诊断：{nxt['text']}")
                self.current_task = asyncio.create_task(
                    self.run_diagnosis(replay=False, text=nxt["text"]))
```

3i. `_finish_run` 末尾追加结果集持久化（方法最后）：

```python
        # 结果集持久化：实时建档，复盘追加；异议快照随轮更新
        try:
            if replay:
                if self.current_record_id is not None:
                    records.attach_replay(self.current_record_id, run_record.get("report", ""), summary)
                    records.set_objections(self.current_record_id, self.objection_log)
            else:
                rec = records.create_record(self.current_line, run_record["time"])
                self.current_record_id = rec["id"]
                records.attach_realtime(rec["id"], run_record.get("report", ""), summary)
                records.set_objections(rec["id"], self.objection_log)
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"诊断记录持久化失败：{exc}")
```

3j. `save_strategy` 在 `self.saved_strategies.append(strategy)` 之后加：

```python
        if self.current_record_id is not None:
            records.attach_strategy(self.current_record_id, name)
```

- [ ] **Step 4: 运行全部后端测试**

Run: `cd "/Users/bei/DEVLOPE/3d agent/backend" && python3 -m pytest tests/ -v`
Expected: 全 PASS（旧测试直接调 `run_diagnosis(replay=...)` 走默认 DIAGNOSE_MESSAGE，行为不变）

- [ ] **Step 5: Commit**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/records.py backend/agent_manager.py backend/tests/test_records.py backend/tests/test_diagnosis_queue.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(backend): 自由文本诊断目标+多线路排队顺序执行+结果集JSON持久化"
```

---

### Task 7: 前端——自由文本输入 + 队列展示 + 历史结果视图

**Files:**
- Modify: `frontend/src/components/TopBar.vue`（整体替换）
- Modify: `frontend/src/store.js`、`frontend/src/ws.js`
- Create: `frontend/src/components/HistoryView.vue`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Consumes: Task 6 的 WS 事件与入参。
- Produces: `store.lineText/diagQueue/currentLine/view/records/recordDetail`；`setView(v)`、`requestRecords()`、`requestRecord(id)`、`cancelQueued(i)`。

- [ ] **Step 1: store.js 字段调整**

删除 `LINES` 导出与 `selectedLine` 字段，追加：

```js
  lineText: '雅湖线 2025-05-08 19:46 发生跳闸，请进行故障综合诊断',
  diagQueue: [],         // 排队中的诊断 [{ text, time }]
  currentLine: '',       // 当前执行中的诊断文本
  view: 'room',          // 'room' | 'history'
  records: [],           // 结果集列表（records_list）
  recordDetail: null,    // 结果集详情（record_detail）
```

- [ ] **Step 2: ws.js 接线**

删除 `LINES` 的 import。`startDiagnosis` 改为：

```js
export function startDiagnosis() {
  const text = store.lineText.trim()
  if (text) send({ type: 'start_diagnosis', text })
}
```

`handle` 的 switch 追加：

```js
    case 'diagnosis_queue':
      store.currentLine = event.current || ''
      store.diagQueue = event.queue || []
      break
    case 'records_list':
      store.records = event.records || []
      break
    case 'record_detail':
      store.recordDetail = event.record
      break
```

末尾追加导出：

```js
export const cancelQueued = (index) => send({ type: 'cancel_queued', index })
export const requestRecords = () => send({ type: 'list_records' })
export const requestRecord = (id) => send({ type: 'get_record', id })
export function setView(v) {
  store.view = v
  if (v === 'history') requestRecords()
}
```

- [ ] **Step 3: TopBar.vue 整体替换**

```vue
<script setup>
import { store } from '../store'
import { startDiagnosis, openSaveNaming, replay, cancelQueued, setView } from '../ws'
</script>

<template>
  <header class="glass flex items-center gap-3 px-4 py-2 rounded-lg pointer-events-auto">
    <div class="flex items-center gap-2 shrink-0">
      <div class="w-2.5 h-2.5 rotate-45 bg-cyan-400 shadow-[0_0_10px_#22d3ee]"></div>
      <h1 class="text-cyan-300 font-bold tracking-widest neon-text text-sm whitespace-nowrap">
        输电线路智能诊断 · 全息指挥室
      </h1>
    </div>

    <input
      v-model="store.lineText"
      placeholder="输入线路跳闸信息，如：500kV雅湖线 #12杆塔 2026-07-31 14:23 跳闸"
      class="w-72 bg-slate-900/80 border border-cyan-500/40 text-cyan-100 text-xs rounded px-2 py-1.5 outline-none focus:border-cyan-300 placeholder:text-slate-600"
    />

    <button
      :disabled="!store.connected || !store.lineText.trim()"
      @click="startDiagnosis"
      class="text-xs font-bold px-4 py-1.5 rounded transition-all whitespace-nowrap"
      :class="store.running
        ? 'bg-amber-500/20 text-amber-300 border border-amber-400/50 hover:bg-amber-400/30'
        : 'bg-cyan-500/20 text-cyan-200 border border-cyan-400/60 hover:bg-cyan-400/30 hover:shadow-[0_0_16px_rgba(34,211,238,.5)]'"
      :title="store.running ? '诊断执行中，点击将新线路加入排队' : '开始实时诊断'"
    >
      {{ store.running ? '＋ 加入诊断队列' : '▶ 启动智能诊断' }}
    </button>

    <button
      :disabled="store.running || !store.connected || !store.sessionId"
      @click="openSaveNaming"
      class="text-xs font-bold px-3 py-1.5 rounded border border-fuchsia-400/50 text-fuchsia-200 bg-fuchsia-500/15 hover:bg-fuchsia-400/25 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
      title="将当前会话的权重/排除/异议/自定义数据保存为完整策略技能"
    >
      ⬇ 保存干预策略
    </button>

    <button
      :disabled="store.running || !store.connected || !store.summaries.realtime"
      @click="replay"
      class="text-xs font-bold px-3 py-1.5 rounded border border-emerald-400/50 text-emerald-200 bg-emerald-500/15 hover:bg-emerald-400/25 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
      title="实时诊断完成后即可复盘：逐项确认各智能体结果并审核报告"
    >
      ↻ 复盘重跑
    </button>

    <button
      @click="setView(store.view === 'room' ? 'history' : 'room')"
      class="text-xs font-bold px-3 py-1.5 rounded border border-sky-400/50 text-sky-200 bg-sky-500/15 hover:bg-sky-400/25 whitespace-nowrap"
      title="查看已完成的诊断结果集"
    >
      {{ store.view === 'room' ? '🗂 历史结果' : '🛖 指挥室' }}
    </button>

    <!-- 诊断队列 -->
    <div v-if="store.currentLine || store.diagQueue.length" class="flex items-center gap-1 text-[10px] shrink-0">
      <span
        v-if="store.currentLine"
        class="px-1.5 py-0.5 rounded bg-amber-500/15 border border-amber-400/40 text-amber-200 truncate max-w-[140px]"
        :title="store.currentLine"
      >诊断中:{{ store.currentLine }}</span>
      <span
        v-for="(q, i) in store.diagQueue" :key="i"
        class="px-1.5 py-0.5 rounded bg-slate-500/15 border border-slate-400/40 text-slate-300 truncate max-w-[120px]"
        :title="q.text"
      >
        等待{{ i + 1 }}:{{ q.text }}
        <button @click="cancelQueued(i)" class="text-red-300 hover:text-red-200 ml-0.5">✕</button>
      </span>
    </div>

    <div class="ml-auto flex items-center gap-2 text-xs shrink-0">
      <span
        class="w-2 h-2 rounded-full"
        :class="store.connected ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]' : 'bg-red-400 animate-pulse'"
      ></span>
      <span :class="store.connected ? 'text-emerald-300' : 'text-red-300'">
        {{ store.connected ? '链路已建立' : '链路中断' }}
      </span>
    </div>
  </header>
</template>
```

- [ ] **Step 4: 创建 HistoryView.vue**

创建 `frontend/src/components/HistoryView.vue`：

```vue
<script setup>
import { computed, ref } from 'vue'
import { store } from '../store'
import { requestRecord, setView } from '../ws'

const keyword = ref('')

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return store.records
  return store.records.filter((r) =>
    [r.line, r.time, ...(r.strategies || []), ...(r.objections || [])]
      .join(' ').toLowerCase().includes(k))
})

function viewReport(title, content) {
  store.reportModal = { title, content: content || '（空）' }
}

function objectionText(o) {
  return o.text || `${o.tool || ''} ${o.decision || ''}${o.value != null ? ' = ' + o.value : ''}`
}
</script>

<template>
  <div class="absolute inset-0 z-10 bg-slate-950/95 flex flex-col p-4 gap-3 overflow-hidden pointer-events-auto">
    <div class="flex items-center gap-3 shrink-0">
      <span class="text-cyan-300 font-bold text-sm tracking-widest">◈ 诊断结果集</span>
      <input
        v-model="keyword"
        placeholder="关键字搜索（线路 / 策略 / 复盘要求）…"
        class="flex-1 max-w-md bg-slate-900/80 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 outline-none focus:border-cyan-300 placeholder:text-slate-600"
      />
      <button
        @click="setView('room')"
        class="text-xs px-3 py-1.5 rounded border border-cyan-400/50 text-cyan-200 bg-cyan-500/15 hover:bg-cyan-400/25"
      >返回指挥室</button>
    </div>

    <div class="flex-1 flex gap-3 min-h-0">
      <!-- 记录列表 -->
      <div class="w-[380px] shrink-0 glass rounded-lg overflow-y-auto">
        <div
          v-for="r in [...filtered].reverse()" :key="r.id"
          @click="requestRecord(r.id)"
          class="px-3 py-2 border-b border-slate-700/40 cursor-pointer hover:bg-cyan-500/10"
          :class="store.recordDetail?.id === r.id ? 'bg-cyan-500/15' : ''"
        >
          <div class="text-xs text-cyan-100 truncate" :title="r.line">{{ r.line }}</div>
          <div class="text-[10px] text-slate-500 mt-0.5 flex gap-2 flex-wrap">
            <span>#{{ r.id }} · {{ r.time }}</span>
            <span v-if="r.has_replay" class="text-emerald-300">已复盘</span>
            <span v-for="s in r.strategies" :key="s" class="text-fuchsia-300">{{ s }}</span>
          </div>
        </div>
        <div v-if="!filtered.length" class="text-slate-600 text-xs text-center py-8">暂无记录</div>
      </div>

      <!-- 详情 -->
      <div class="flex-1 glass rounded-lg overflow-y-auto p-4 min-w-0">
        <template v-if="store.recordDetail">
          <div class="text-cyan-200 text-sm font-bold mb-1">{{ store.recordDetail.line }}</div>
          <div class="text-[10px] text-slate-500 mb-3">#{{ store.recordDetail.id }} · {{ store.recordDetail.time }}</div>

          <div class="flex gap-2 mb-3 flex-wrap">
            <button
              v-if="store.recordDetail.realtime"
              @click="viewReport('实时诊断报告', store.recordDetail.realtime.report)"
              class="text-xs px-3 py-1.5 rounded bg-cyan-500/20 text-cyan-200 border border-cyan-400/40 hover:bg-cyan-400/30"
            >实时诊断报告</button>
            <button
              v-for="(rp, i) in store.recordDetail.replays" :key="i"
              @click="viewReport('复盘报告' + (store.recordDetail.replays.length > 1 ? ' ' + (i + 1) : ''), rp.report)"
              class="text-xs px-3 py-1.5 rounded bg-emerald-500/20 text-emerald-200 border border-emerald-400/40 hover:bg-emerald-400/30"
            >复盘报告{{ store.recordDetail.replays.length > 1 ? ' ' + (i + 1) : '' }}</button>
          </div>

          <div v-if="store.recordDetail.objections?.length" class="mb-3">
            <div class="text-amber-300 text-[10px] font-bold mb-1">复盘要求与异议</div>
            <div
              v-for="(o, i) in store.recordDetail.objections" :key="i"
              class="text-[11px] text-slate-300 border border-slate-600/40 bg-slate-800/50 rounded px-2 py-1 mb-1"
            >
              <span class="text-slate-500">[{{ o.kind }} {{ o.time }}]</span> {{ objectionText(o) }}
            </div>
          </div>

          <div v-if="store.recordDetail.strategies?.length">
            <div class="text-fuchsia-300 text-[10px] font-bold mb-1">保存的策略</div>
            <span
              v-for="s in store.recordDetail.strategies" :key="s"
              class="inline-block text-[11px] px-1.5 py-0.5 mr-1 rounded bg-fuchsia-500/15 border border-fuchsia-400/40 text-fuchsia-200"
            >{{ s }}</span>
          </div>
        </template>
        <div v-else class="text-slate-600 text-xs text-center py-16">选择左侧记录查看详情</div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 5: App.vue 接入视图切换**

script 顶部 import 区加：

```js
import HistoryView from './components/HistoryView.vue'
```

模板：3D 画布与 HUD 两个顶层 div 加 `v-show`（保持 CommandRoom 实例不销毁），并在 HUD 之后加 HistoryView：

```html
    <!-- 3D WebGL 画布 -->
    <div ref="canvasHost" class="absolute inset-0" v-show="store.view === 'room'"></div>

    <!-- HUD 覆盖层 -->
    <div class="absolute inset-0 pointer-events-none flex flex-col p-3 gap-2" v-show="store.view === 'room'">
```

在 `<!-- 双击智能体弹出的直聊终端 -->` 之前插入：

```html
    <!-- 历史结果集视图 -->
    <HistoryView v-if="store.view === 'history'" />
```

- [ ] **Step 6: 构建验证**

Run: `cd "/Users/bei/DEVLOPE/3d agent/frontend" && npm run build`
Expected: 成功（注意全局搜索确认 `LINES`/`selectedLine` 无残留引用：`grep -rn "LINES\|selectedLine" src/`）

- [ ] **Step 7: Commit**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/src/components/TopBar.vue frontend/src/components/HistoryView.vue frontend/src/App.vue frontend/src/store.js frontend/src/ws.js
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): 自由文本线路输入+诊断队列展示+历史结果集视图(搜索/报告/异议/策略)"
```

---

### Task 8: 指挥室深色系改造

**Files:**
- Modify: `frontend/src/three/CommandRoom.js`（仅颜色/灯光常量）

**Interfaces:**
- 无接口变化；布局、人物、交互、状态色（STATUS 映射 0x0e7490/0xfbbf24/0x34d399/0xf87171）保持不变。

- [ ] **Step 1: 替换场景/灯光/材质颜色**

`CommandRoom.js` 精确替换：

| 行 | 旧 | 新 |
|---|---|---|
| 55 | `desk: ... color: 0xe8edf2, metalness: 0.3, roughness: 0.5` | `color: 0x233148, metalness: 0.5, roughness: 0.4` |
| 56 | `chair: ... color: 0xcfd8e0` | `color: 0x2a3a52` |
| 336 | `scene.background = new THREE.Color(0xdfe8f0)` | `0x0b1220` |
| 337 | `FogExp2(0xdfe8f0, 0.004)` | `FogExp2(0x0b1220, 0.004)` |
| 364 | `AmbientLight(0xffffff, 3.2)` | `AmbientLight(0x8fa3c8, 0.7)` |
| 365 | `HemisphereLight(0xffffff, 0xb0c4d4, 1.6)` | `HemisphereLight(0x3a4a6b, 0x0a0f1a, 0.6)` |
| 368 | `DirectionalLight(0xfff5e6, 2.2)` | `DirectionalLight(0x9fc8ff, 0.5)` |
| 371 | `PointLight(0x2a6f8f, 30, 40)` | `PointLight(0x22d3ee, 40, 40)` |
| 380 | 地板 `color: 0xdde4ea, roughness: 0.35, metalness: 0.1` | `color: 0x141b2a, roughness: 0.4, metalness: 0.3` |
| 386 | `GridHelper(48, 48, 0x9fb3c8, 0xc3d2de)` | `GridHelper(48, 48, 0x1e3a5f, 0x182742)` |
| 393 | 墙 `color: 0xeef2f5` | `color: 0x101828` |
| 405 | skyline `color: 0x9db8cc` | `color: 0x1c2f4a` |
| 410 | 玻璃 `color: 0xbfd9e8, ... opacity: 0.25` | `color: 0x2a4a6b, ... opacity: 0.35` |
| 426 | 顶棚 `color: 0xf4f8fb` | `color: 0x16233a` |
| 431 | beam `color: 0xc9d4dc` | `color: 0x1c2942` |
| 485 | 粒子 `color: 0x8fa8bd` | `color: 0x4a6a9a` |
| 594 | lamp `PointLight(0xffe0b3, ...)` | `PointLight(0x9fd8ff, ...)`（强度不变） |

席位状态灯（684 行附近）、屏幕青色发光（468/507/621）、指挥官台（537 0x111c2e）保持不变——本就是深色/发光元素。

- [ ] **Step 2: 构建 + 人工目验**

Run: `cd "/Users/bei/DEVLOPE/3d agent/frontend" && npm run build`
然后 `npm run dev`，浏览器打开确认：整体深色、屏幕发光突出、人物与席位状态灯清晰可辨、与 HUD 深色玻璃风格统一。如局部过暗/过亮，仅微调上表数值。

- [ ] **Step 3: Commit**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/src/three/CommandRoom.js
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): 指挥室大厅改深色系(藏蓝深灰材质+冷色灯光),与UI主题统一"
```

---

## Self-Review 记录

- Spec 覆盖：W1→Task 3/4；W2→Task 1/2；W3→Task 5（含 Task 7 TopBar 中的按钮最终态）；W4→Task 8；W5→Task 6/7。✔
- 类型一致性：`build_skill_markdown` config keys 在 Task 1/2 一致；`_stream_run`/`run_diagnosis(replay, text)` 在 Task 3/6 一致；WS 事件名（diagnosis_queue/records_list/record_detail/report_review_request.empty/tool_confirm_request.empty）前后端一致。✔
- Task 5 的 TopBar 按钮改动会被 Task 7 的整体替换覆盖——Task 5 独立交付后端语义验证（小步快走），Task 7 为终态，两者不冲突。✔
- 已知取舍：删除 `test_trail_replay.py`（激活重放被"轨迹烘入 skill"替代，用户已确认）。
