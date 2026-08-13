# 指挥室第三轮修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 四问题修复——新实时诊断清空复盘摘要卡;激活策略权重立即生效(HUD 一致);策略管理页激活按钮三处联动;历史记录全选+右键菜单删除。

**Architecture:** vendor set_default_skill 即应用活跃会话(对齐 reset 语义);backend activate_skill 补双广播+快照刷新;frontend ws.js run_state 清空、StrategiesView 激活按钮、HistoryView 全选+右键菜单。

**Tech Stack:** Python 3.11、pytest、Vue 3 + Vite

**Spec:** `docs/superpowers/specs/2026-08-12-command-center-round3-design.md`

## Global Constraints

- **嵌套仓库**:vendor/diagnosis-agent 独立 git 仓(分支 mcp_version),vendor 改动在 vendor 仓提交;backend/frontend/docs 在外层仓提交。提交一律 `git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit`(不改 git config)
- vendor 测试:`cd vendor/diagnosis-agent && .venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_diagnose_flow.py`(integration 收集错误为预存问题),全部 PASS 无回归;coverage gate 基线不达标,非本计划范围
- backend 测试:`cd backend && .venv/bin/python -m pytest tests/ -q`,全部 PASS 无回归
- 激活接口:无活跃会话时仅改全局默认(现状不变);不复位 excluded_tools(与 session create() 对齐,只动权重/技能名)
- 复盘启动(run_state replay)不得清空摘要卡(实时卡是比对基线)
- vendor `config/config.yaml` 本地含真实 API key,不得提交

---

### Task 1(vendor): set_default_skill 即应用活跃会话

**Files:**
- Modify: `vendor/diagnosis-agent/src/interfaces/web.py`(set_default_skill 879-890)
- Test: `vendor/diagnosis-agent/tests/unit/test_skill_activation.py`(新建)

**Interfaces:**
- Consumes: `container.session_manager.get_active()`(session_manager.py:136-140)、`_load_skill_weights(name)`(122-128,经 skill_loader 返回 weights dict)、`_persist()`;client fixture 模式(test_session_reset.py / test_data_overrides.py 同构)
- Produces: 无(语义变更:激活后活跃会话 active_skill_name/active_weights 立即更新)

- [ ] **Step 1: 写失败测试**

新建 `vendor/diagnosis-agent/tests/unit/test_skill_activation.py`:

```python
"""POST /api/skills/default:设置全局默认技能,并即应用到活跃会话(对齐 /api/skills/reset 语义)。"""

import pytest

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


def _mock_skill(container, monkeypatch, name="雷电策略", weights=None):
    monkeypatch.setattr(container.skill_loader, "list_skills", lambda: [name])
    monkeypatch.setattr(
        container.session_manager, "_load_skill_weights",
        lambda n: dict(weights or {}))


def test_activate_applies_to_active_session(client, monkeypatch):
    """有活跃会话:激活后 active_skill_name/active_weights 立即更新。"""
    c, container = client
    _mock_skill(container, monkeypatch, weights={"WindDiagnosisTool": 0.5})
    s = container.session_manager.create("雅湖线")
    resp = c.post("/api/skills/default", json={"name": "雷电策略"})
    assert resp.status_code == 200
    assert resp.get_json()["default_skill"] == "雷电策略"
    session = container.session_manager.get(s.session_id)
    assert session.active_skill_name == "雷电策略"
    assert session.active_weights == {"WindDiagnosisTool": 0.5}


def test_activate_skill_without_weights_keeps_session_weights(client, monkeypatch):
    """技能文件无权重:技能名更新,会话权重保持(与 create() 的 DEFAULT 回退语义不冲突)。"""
    c, container = client
    _mock_skill(container, monkeypatch, weights={})
    s = container.session_manager.create("雅湖线")
    original = dict(s.active_weights)
    resp = c.post("/api/skills/default", json={"name": "雷电策略"})
    assert resp.status_code == 200
    session = container.session_manager.get(s.session_id)
    assert session.active_skill_name == "雷电策略"
    assert session.active_weights == original


def test_activate_without_active_session_only_sets_default(client, monkeypatch):
    """无活跃会话:仅全局默认变更,不报错。"""
    c, container = client
    _mock_skill(container, monkeypatch)
    resp = c.post("/api/skills/default", json={"name": "雷电策略"})
    assert resp.status_code == 200
    assert container.session_manager._default_skill_name == "雷电策略"


def test_activate_unknown_skill_404(client, monkeypatch):
    """技能不存在 → 404(既有行为不变)。"""
    c, container = client
    monkeypatch.setattr(container.skill_loader, "list_skills", lambda: [])
    resp = c.post("/api/skills/default", json={"name": "不存在"})
    assert resp.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_skill_activation.py -v
```

预期:前 2 条 FAIL(会话字段未更新);后 2 条 PASS(现状行为)。

- [ ] **Step 3: 实现**

`src/interfaces/web.py` set_default_skill(879-890)中 `container.session_manager.set_default_skill(name)` 之后、`_persist()` 之前插入:

```python
        # 激活即生效:对齐 /api/skills/reset 语义,立即应用到活跃会话
        # (否则新策略权重要等下次新建会话才加载,HUD 缩略提示与实际不一致)
        active = container.session_manager.get_active()
        if active is not None:
            active.active_skill_name = name
            skill_weights = container.session_manager._load_skill_weights(name)
            if skill_weights:
                active.active_weights = dict(skill_weights)
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_skill_activation.py -v
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_diagnose_flow.py
```

预期:4 条全 PASS;全量 372 passed 无回归。

- [ ] **Step 5: 提交(vendor 仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/diagnosis-agent"
git add src/interfaces/web.py tests/unit/test_skill_activation.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat: 激活技能即应用活跃会话(权重/技能名立即生效,对齐reset语义)"
```

---

### Task 2(backend): activate_skill 双广播 + 快照刷新

**Files:**
- Modify: `backend/agent_manager.py`(activate_skill 路由 196-201)
- Test: `backend/tests/test_activate_skill.py`(新建)

**Interfaces:**
- Consumes: `send_skills()`(302)、`send_strategies()`(310)、`_refresh_snapshot()`(1005,内部吞异常)、Task 1 的 vendor 语义(运行时)
- Produces: 无(联动:激活后 skills/strategies_list/session_snapshot 三事件齐发)

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_activate_skill.py`:

```python
"""activate_skill 路由:激活后双广播(skills + strategies_list)+ 快照刷新。"""
import agent_manager
from tests.test_agent_manager import FakeWS


async def areturn(v):
    return v


async def test_activate_skill_broadcasts_all(monkeypatch):
    """激活后:skills、strategies_list、session_snapshot 三事件齐发(三处 UI 联动)。"""
    monkeypatch.setattr(agent_manager.pld_client, "set_default_skill",
                        lambda name: areturn({"success": True}))
    monkeypatch.setattr(agent_manager.pld_client, "list_skills",
                        lambda: areturn({"skills": [{"name": "s1"}]}))
    monkeypatch.setattr(agent_manager.pld_client, "get_default_skill",
                        lambda: areturn({"default_skill": "s1"}))
    monkeypatch.setattr(agent_manager.pld_client, "get_session",
                        lambda sid: areturn({"active_weights": {"WindDiagnosisTool": 0.5},
                                             "excluded_tools": []}))
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "activate_skill", "name": "s1"})
    types = [e["type"] for e in ws.events]
    assert "skills" in types
    assert "strategies_list" in types
    assert "session_snapshot" in types
    snap = [e for e in ws.events if e["type"] == "session_snapshot"][0]
    assert snap["weights"] == {"WindDiagnosisTool": 0.5}
    assert mgr.local_interventions == 1
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
.venv/bin/python -m pytest tests/test_activate_skill.py -v
```

预期:FAIL(strategies_list / session_snapshot 事件缺失)。

- [ ] **Step 3: 实现**

`backend/agent_manager.py` activate_skill 路由(196-201)改为:

```python
        elif mtype == "activate_skill":
            name = str(data.get("name", ""))
            await pld_client.set_default_skill(name)
            self.local_interventions += 1
            await self.log("commander", f"诊断策略已切换为「{name}」（全局默认）。")
            await self.send_skills()
            await self.send_strategies()   # 策略管理页「使用中」徽章联动
            await self._refresh_snapshot()  # HUD 权重立即刷新(vendor 已即应用活跃会话)
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd backend
.venv/bin/python -m pytest tests/test_activate_skill.py -v
.venv/bin/python -m pytest tests/ -q
```

预期:全 PASS(既有 test_agent_manager.py:146 的 activate_skill 测试:list_skills/get_default_skill 已 mock,get_session 已 mock 或 _refresh_snapshot 内部吞异常,不受影响)。

- [ ] **Step 5: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/agent_manager.py backend/tests/test_activate_skill.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(backend): 激活策略双广播+快照刷新(管理页/HUD/司令面板三处联动)"
```

---

### Task 3(frontend): 摘要卡清空 + 管理页激活按钮

**Files:**
- Modify: `frontend/src/ws.js`(run_state 分支 103-106)
- Modify: `frontend/src/components/StrategiesView.vue`(import 4、状态列 76-80)
- Test: 无(构建验证)

**Interfaces:**
- Consumes: Task 2 的三事件广播(运行时);ws.js 既有 `activateSkill` 导出(202)
- Produces: 无

- [ ] **Step 1: ws.js run_state 清空**

`frontend/src/ws.js` run_state 分支(103-106)改为:

```js
    case 'run_state':
      store.replayMode = event.mode === 'replay'
      store.running = event.mode !== null
      if (event.mode === 'realtime') {
        // 新实时诊断:上一条线路的双摘要卡与比对数据属陈旧数据,清空
        // (replay 启动不清——实时卡是比对的基线)
        store.summaries.realtime = null
        store.summaries.replay = null
        store.compare = null
        if (store.compareOpen) store.compareOpen = false
      }
      break
```

- [ ] **Step 2: StrategiesView 激活按钮**

`frontend/src/components/StrategiesView.vue`:

① import 行(4)改为:

```js
import { setView, deleteStrategies, listStrategies, activateSkill } from '../ws'
```

② 状态列(76-80)改为:

```html
        <span class="w-16">
          <span v-if="s.name === store.strategiesDefault"
            class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 border border-emerald-400/40 text-emerald-300"
          >使用中</span>
          <button v-else
            @click="activateSkill(s.name)"
            class="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-200 border border-cyan-400/40 hover:bg-cyan-400/30"
          >激活</button>
        </span>
```

(复选框 toggle 对默认策略禁用是删除保护,既有不动;激活与删除选择互不影响。)

- [ ] **Step 3: 构建验证**

```bash
cd frontend
npm run build
```

预期:构建成功无报错。

- [ ] **Step 4: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/src/ws.js frontend/src/components/StrategiesView.vue
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): 新实时诊断清空双摘要卡+策略管理页激活按钮"
```

---

### Task 4(frontend): 历史全选 + 右键菜单删除

**Files:**
- Modify: `frontend/src/components/HistoryView.vue`
- Test: 无(构建验证)

**Interfaces:**
- Consumes: 既有 selected/askDelete/doDelete(Task 5 落地,HistoryView.vue:8-29)
- Produces: 无

- [ ] **Step 1: 实现**

`frontend/src/components/HistoryView.vue`:

① script:`const confirmDelete = ref(null)` 之后加:

```js
const allSelected = computed(() =>
  filtered.value.length > 0 && filtered.value.every((r) => selected.value.has(r.id)))

function toggleAll() {
  selected.value = allSelected.value
    ? new Set()
    : new Set(filtered.value.map((r) => r.id))
}

// 行右键菜单(单删入口,替代行内按钮防误点)
const menu = ref(null) // { x, y, id }

function openMenu(e, id) {
  menu.value = {
    x: Math.min(e.clientX, window.innerWidth - 140),
    y: Math.min(e.clientY, window.innerHeight - 60),
    id,
  }
}

function closeMenu() {
  menu.value = null
}

function menuDelete() {
  const id = menu.value?.id
  closeMenu()
  if (id != null) askDelete([id])
}
```

② 记录列表容器(70 行 `<div class="w-[380px] ...">` 内,`v-for` 行之前)加全选头部:

```html
        <div class="flex items-center gap-2 px-3 py-1.5 border-b border-slate-700/50 text-[10px] text-slate-500">
          <input
            type="checkbox" :checked="allSelected" @change="toggleAll"
            class="accent-red-400"
          />
          <span>全选(当前列表 {{ filtered.length }} 条)</span>
        </div>
```

③ 行(71-94 行 v-for 块):根 div 加右键绑定;删除按钮(90-93)移除:

```html
        <div
          v-for="r in [...filtered].reverse()" :key="r.id"
          @click="requestRecord(r.id)"
          @contextmenu.prevent="openMenu($event, r.id)"
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
        </div>
```

④ 根 div(49 行)加全局点击关菜单;模板末尾(确认弹窗之后)加右键菜单:

根 div 改为:

```html
  <div class="absolute inset-0 z-10 bg-slate-950/95 flex flex-col p-4 gap-3 overflow-hidden pointer-events-auto" @click="closeMenu">
```

确认弹窗块(139-161)之后、`</div>` 之前加:

```html
    <div
      v-if="menu"
      class="fixed z-30 glass rounded border border-slate-600/50 py-1 w-[130px]"
      :style="{ left: menu.x + 'px', top: menu.y + 'px' }"
      @click.stop
    >
      <button
        @click="menuDelete"
        class="w-full text-left text-[11px] px-3 py-1.5 text-red-300 hover:bg-red-500/15"
      >删除该记录</button>
    </div>
```

(右键菜单随根容器点击自动关闭;菜单自身 @click.stop 防误关;坐标 clamp 防越出视口。)

- [ ] **Step 2: 构建验证**

```bash
cd frontend
npm run build
```

预期:构建成功无报错。

- [ ] **Step 3: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/src/components/HistoryView.vue
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): 历史记录全选+右键菜单删除(移除行内删除按钮防误点)"
```

---

### Task 5: 全量回归 + 实测核对清单

**Files:** 无(纯验证)

**Interfaces:**
- Consumes: Task 1-4 全部完成
- Produces: 无

- [ ] **Step 1: vendor 全量测试**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_diagnose_flow.py
```

预期:全部 PASS(372,含新增 4 条)。

- [ ] **Step 2: backend 全量测试**

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

预期:全部 PASS(85,含新增 1 条)。

- [ ] **Step 3: 前端构建**

```bash
cd frontend
npm run build 2>&1 | tail -3
```

预期:成功。

- [ ] **Step 4: 实测核对(记录交用户)**

1. 完成一次复盘后启动新实时诊断 → 右侧「实时诊断」「复盘诊断」双卡立即清空为等待态,比对入口消失
2. 司令面板激活新策略 → 左上 HUD 权重标签**立即**变为新策略权重(不等报告生成)
3. 策略管理页点「激活」→ 该行变「使用中」徽章,司令面板同策略变「已激活」,HUD 策略名+权重同步
4. 历史结果页:头部全选勾选当前列表(含搜索过滤后);右键记录行 → 菜单「删除该记录」→ 确认弹窗;行内不再有删除按钮

---

## Self-Review 记录

- Spec 覆盖:§1 摘要卡→Task 3 Step 1;§2 激活即生效→Task 1(vendor)+Task 2(backend 快照);§3 管理页激活+联动→Task 2(双广播)+Task 3 Step 2;§4 全选+右键→Task 4;测试 1-4→Task 1/2 Step 1;「不做的事」→无任务,符合
- 占位符:全部代码完整给出;Task 3/4 为前端无测试框架任务,构建验证即门槛(与前两轮同例)
- 类型一致:`activateSkill(name: string)` ws.js 既有导出;`run_state` 事件 `mode: 'realtime'|'replay'` 与 backend agent_manager.py:508 广播形态一致;`_load_skill_weights` 返回 dict[str,float] 与 session_manager.py:122-128 一致
- 既有测试兼容:test_agent_manager.py:146 activate_skill 测试的 mock 覆盖 list_skills/get_default_skill/get_session(send_strategies 与 _refresh_snapshot 链路),且 _refresh_snapshot 内部吞异常——Task 2 改动不破坏既有测试,已在 Step 4 注明验证点
- vendor 权重空回退:技能文件无权重时只改技能名不改权重(Task 1 测试 2 钉死),避免把会话权重清成空 dict
