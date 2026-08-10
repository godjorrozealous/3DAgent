# 实时诊断与复盘会话隔离 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实时诊断永远基于激活技能权重，复盘残留会话（MODIFYING/RECHECKING/EXCLUDED）不再被实时诊断复用，技能权重按名缓存。

**Architecture:** 改动全部在 PLD（`vendor/diagnosis-agent`，独立 git 仓库）：`SessionManager.get_or_create()` 入口分流 + `SessionManager.__init__` 启动收口 stale 会话 + `SkillLoader` 权重缓存。backend/frontend 零改动。

**Tech Stack:** Python 3.11、Pydantic v2、pytest（vendor 仓 `tests/unit/`）

**Spec:** `docs/superpowers/specs/2026-08-10-session-isolation-design.md`（外层仓）

## Global Constraints

- 代码改动与提交都在 **vendor 仓**：`cd vendor/diagnosis-agent` 后操作 git（外层仓不跟踪 vendor 内容）
- 测试命令统一用 vendor 虚拟环境：`cd vendor/diagnosis-agent && .venv/bin/python -m pytest <路径> -v`
- 可复用状态集合：仅 `SessionStatus.PENDING`、`SessionStatus.DIAGNOSING`
- stale 收口状态集合：`SessionStatus.MODIFYING`、`SessionStatus.RECHECKING` → 置为 `SessionStatus.COMPLETED`
- 既有测试不得回归（`tests/unit/test_session_manager.py` 已有 20+ 用例）

---

### Task 1: `get_or_create()` 入口分流

**Files:**
- Modify: `vendor/diagnosis-agent/src/domain/session_manager.py:120-164`（`get_or_create` 方法）
- Test: `vendor/diagnosis-agent/tests/unit/test_session_manager.py`

**Interfaces:**
- Consumes: 既有 `SessionManager.create()`、`transition()`、`SessionStatus` 枚举（`src/core/models.py:14-21`）
- Produces: `get_or_create()` 仅复用 `PENDING`/`DIAGNOSING` 会话；模块级常量 `REUSABLE_STATUSES: set[SessionStatus]`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_session_manager.py` 的 `test_get_or_create_creates_new_when_completed` 之后追加：

```python
def test_get_or_create_skips_modifying_session(session_manager: SessionManager) -> None:
    """MODIFYING（复盘上下文）会话不被实时诊断复用。"""
    first = session_manager.create("京西线")
    session_manager.transition(first.session_id, SessionStatus.DIAGNOSING)
    session_manager.transition(first.session_id, SessionStatus.MODIFYING)

    second = session_manager.get_or_create("京西线")
    assert second.session_id != first.session_id


def test_get_or_create_skips_rechecking_session(session_manager: SessionManager) -> None:
    """RECHECKING（复盘复查）会话不被实时诊断复用。"""
    first = session_manager.create("京西线")
    session_manager.transition(first.session_id, SessionStatus.DIAGNOSING)
    session_manager.transition(first.session_id, SessionStatus.RECHECKING)

    second = session_manager.get_or_create("京西线")
    assert second.session_id != first.session_id


def test_get_or_create_skips_excluded_session(session_manager: SessionManager) -> None:
    """EXCLUDED 会话不被实时诊断复用。"""
    first = session_manager.create("京西线")
    session_manager.transition(first.session_id, SessionStatus.DIAGNOSING)
    session_manager.transition(first.session_id, SessionStatus.EXCLUDED)

    second = session_manager.get_or_create("京西线")
    assert second.session_id != first.session_id


def test_get_or_create_reuses_diagnosing_session(session_manager: SessionManager) -> None:
    """DIAGNOSING（进行中/卡死恢复场景）会话仍被复用。"""
    first = session_manager.create("京西线")
    session_manager.transition(first.session_id, SessionStatus.DIAGNOSING)

    second = session_manager.get_or_create("京西线")
    assert second.session_id == first.session_id
```

- [ ] **Step 2: 跑测试确认 3 个新 skip 用例失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_session_manager.py -k "skips_modifying or skips_rechecking or skips_excluded or reuses_diagnosing" -v
```

预期：`skips_modifying` / `skips_rechecking` / `skips_excluded` 三个 FAIL（旧逻辑会复用）；`reuses_diagnosing` PASS。

- [ ] **Step 3: 实现分流**

`src/domain/session_manager.py`：在 `SessionManager` 类前加模块级常量，并改 `get_or_create()` 的循环条件：

```python
# 实时诊断可复用的会话状态（进行中/卡死恢复场景）；
# MODIFYING/RECHECKING/EXCLUDED 属复盘上下文，一律新建会话
REUSABLE_STATUSES = {SessionStatus.PENDING, SessionStatus.DIAGNOSING}
```

`get_or_create()` 中把：

```python
        for sess in self._sessions.values():
            if sess.status == SessionStatus.COMPLETED:
                continue
```

改为：

```python
        for sess in self._sessions.values():
            if sess.status not in REUSABLE_STATUSES:
                continue
```

- [ ] **Step 4: 跑全部 session_manager 测试**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_session_manager.py -v
```

预期：全部 PASS（含既有 `test_get_or_create_reuses_same_line` 等，无回归）。

- [ ] **Step 5: 提交（vendor 仓）**

```bash
cd vendor/diagnosis-agent
git add src/domain/session_manager.py tests/unit/test_session_manager.py
git commit -m "fix(session): 实时诊断不再复用复盘上下文会话(get_or_create仅复用PENDING/DIAGNOSING)"
```

---

### Task 2: 启动收口 stale 会话

**Files:**
- Modify: `vendor/diagnosis-agent/src/domain/session_manager.py:29-45`（`__init__`）
- Test: `vendor/diagnosis-agent/tests/unit/test_session_manager.py`

**Interfaces:**
- Consumes: `src/infrastructure/session_repository.py` 的 `SessionRepository(file_path: Optional[Path])`、`save_all()` / `load_all()`；Task 1 的 `SessionStatus` 用法
- Produces: 模块级常量 `STALE_STATUSES: set[SessionStatus]`；`SessionManager.__init__` 加载持久化会话后把 stale 会话置为 `COMPLETED` 并持久化

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_session_manager.py` 追加（文件顶部 import 区域补 `from pathlib import Path`、`from src.infrastructure.session_repository import SessionRepository`，如已存在则不重复）：

```python
def test_init_collapses_stale_sessions(tmp_path, event_bus, state_machine) -> None:
    """启动加载时，MODIFYING/RECHECKING 残留会话被收口为 COMPLETED。"""
    repo_file = tmp_path / "sessions.json"
    repo = SessionRepository(repo_file)

    # 先用一个带仓库的 manager 制造两个残留会话并持久化
    m1 = SessionManager(event_bus, state_machine, repository=repo)
    s1 = m1.create("京西线")
    m1.transition(s1.session_id, SessionStatus.DIAGNOSING)
    m1.transition(s1.session_id, SessionStatus.MODIFYING)
    s2 = m1.create("雅湖线")
    m1.transition(s2.session_id, SessionStatus.DIAGNOSING)
    m1.transition(s2.session_id, SessionStatus.RECHECKING)
    m1._persist()

    # 模拟重启：新建 manager 从同一文件加载
    m2 = SessionManager(event_bus, state_machine, repository=SessionRepository(repo_file))
    loaded = {s.session_id: s for s in m2.list_sessions()}
    assert loaded[s1.session_id].status == SessionStatus.COMPLETED
    assert loaded[s2.session_id].status == SessionStatus.COMPLETED


def test_init_keeps_diagnosing_sessions(tmp_path, event_bus, state_machine) -> None:
    """DIAGNOSING 会话不受收口影响（保留卡死恢复入口）。"""
    repo_file = tmp_path / "sessions.json"
    m1 = SessionManager(event_bus, state_machine, repository=SessionRepository(repo_file))
    s1 = m1.create("京西线")
    m1.transition(s1.session_id, SessionStatus.DIAGNOSING)
    m1._persist()

    m2 = SessionManager(event_bus, state_machine, repository=SessionRepository(repo_file))
    loaded = {s.session_id: s for s in m2.list_sessions()}
    assert loaded[s1.session_id].status == SessionStatus.DIAGNOSING
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_session_manager.py -k "collapses_stale or keeps_diagnosing" -v
```

预期：`collapses_stale` FAIL（状态仍是 MODIFYING/RECHECKING）；`keeps_diagnosing` PASS。

- [ ] **Step 3: 实现收口**

`src/domain/session_manager.py`：模块级常量（放在 Task 1 的 `REUSABLE_STATUSES` 旁）：

```python
# 重启后事实上无法继续复盘的残留状态，启动时收口为 COMPLETED
STALE_STATUSES = {SessionStatus.MODIFYING, SessionStatus.RECHECKING}
```

`__init__` 中把：

```python
        if repository is not None:
            self._sessions = repository.load_all()
            self._active_session_id = None
```

改为：

```python
        if repository is not None:
            self._sessions = repository.load_all()
            stale = [
                s for s in self._sessions.values() if s.status in STALE_STATUSES
            ]
            for sess in stale:
                sess.status = SessionStatus.COMPLETED
                logger.info(f"收口残留会话: {sess.session_id} -> COMPLETED")
            self._active_session_id = None
            if stale:
                self._persist()
```

- [ ] **Step 4: 跑全部 session_manager 测试**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_session_manager.py -v
```

预期：全部 PASS。

- [ ] **Step 5: 提交（vendor 仓）**

```bash
cd vendor/diagnosis-agent
git add src/domain/session_manager.py tests/unit/test_session_manager.py
git commit -m "fix(session): 启动收口MODIFYING/RECHECKING残留会话为COMPLETED"
```

---

### Task 3: 技能权重缓存（含共享 loader）

**Files:**
- Modify: `vendor/diagnosis-agent/src/domain/skill_loader.py`（`__init__:43-51`、`load:53-78`、`save:159-178`、`delete:180-200`）
- Modify: `vendor/diagnosis-agent/src/domain/session_manager.py:97-106`（`_load_skill_weights`，改用共享 loader 实例，否则每次新建 loader 缓存无效）
- Test: `vendor/diagnosis-agent/tests/unit/test_skill_loader_weights.py`

**Interfaces:**
- Consumes: 既有 `SkillLoader(skills_dir)`、`load() -> tuple[str, dict]`、`save()`、`delete()`
- Produces:
  - `SkillLoader._weights_cache: Dict[str, dict]`（与 `_cache` 同生命周期）
  - `session_manager` 模块级共享实例 `_shared_skill_loader = SkillLoader()`，`_load_skill_weights()` 改用它

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_skill_loader_weights.py` 的 `TestSkillLoaderWeights` 类中追加：

```python
    def test_save_updates_weights_cache(self, tmp_path):
        """save() 后权重缓存同步更新，load() 返回新权重。"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        skill_file = skill_dir / "strategy.md"
        skill_file.write_text("# 策略\n\n```yaml\nweights:\n  LightningDiagnosisTool: 1.0\n```\n")

        loader = SkillLoader(str(skill_dir))
        _, weights1 = loader.load("strategy")
        assert weights1["LightningDiagnosisTool"] == 1.0

        loader.save("strategy", "# 策略\n\n```yaml\nweights:\n  LightningDiagnosisTool: 0.5\n```\n")
        _, weights2 = loader.load("strategy")
        assert weights2["LightningDiagnosisTool"] == 0.5

    def test_delete_clears_weights_cache(self, tmp_path):
        """delete() 后权重缓存清除，load() 回退为默认内容+空权重。"""
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        (skill_dir / "strategy.md").write_text("# 策略\n\n```yaml\nweights:\n  LightningDiagnosisTool: 0.7\n```\n")

        loader = SkillLoader(str(skill_dir))
        _, weights1 = loader.load("strategy")
        assert weights1["LightningDiagnosisTool"] == 0.7

        loader.delete("strategy")
        _, weights2 = loader.load("strategy")
        assert weights2 == {}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_skill_loader_weights.py -k "save_updates or delete_clears" -v
```

预期：两条 FAIL（当前 `load()` 缓存命中时仍实时解析，但 `save()` 更新 `_cache` 后其实能过——若意外 PASS，看 Step 3 说明）。

> 说明：当前实现 `save()` 会更新 `_cache` 内容、`load()` 命中缓存时重新 `_extract_weights`，这两条测试在旧代码下**可能恰好 PASS**。此时不视为阻塞——它们的真实价值是锁定缓存失效语义，防止后续缓存实现引入「save 后仍返回旧权重」的回归。直接继续 Step 3 实现显式权重缓存。

- [ ] **Step 3: 实现权重缓存**

`src/domain/skill_loader.py`：

`__init__` 中 `self._cache: Dict[str, str] = {}` 之后加：

```python
        self._weights_cache: Dict[str, dict] = {}
```

`load()` 改为：

```python
    def load(self, skill_name: str) -> tuple[str, dict]:
        """加载指定技能文件的内容和权重配置（内容+权重均按技能名缓存）。"""
        if skill_name in self._cache:
            logger.debug(f"命中缓存: {skill_name}")
            return self._cache[skill_name], self._weights_cache[skill_name]

        skill_path = self._skills_dir / f"{skill_name}.md"
        if not skill_path.exists():
            logger.warning(f"技能文件不存在: {skill_path}，返回默认内容")
            return DEFAULT_SKILL_CONTENT, {}

        content = skill_path.read_text(encoding="utf-8")
        self._cache[skill_name] = content
        self._weights_cache[skill_name] = self._extract_weights(content)
        logger.info(f"已加载技能: {skill_name}")
        return content, self._weights_cache[skill_name]
```

`save()` 末尾（`self._cache[skill_name] = content` 之后）加：

```python
        self._weights_cache[skill_name] = self._extract_weights(content)
```

`delete()` 中 `self._cache.pop(skill_name, None)` 之后加：

```python
        self._weights_cache.pop(skill_name, None)
```

`src/domain/session_manager.py` 的 `_load_skill_weights()`：模块级（`REUSABLE_STATUSES` 旁）加共享实例，方法改用它：

```python
# 共享技能加载器：保证权重缓存在多次会话创建间生效
_shared_skill_loader = SkillLoader()
```

```python
    def _load_skill_weights(self, skill_name: str) -> dict[str, float]:
        """从技能文件加载权重配置（经共享 loader，命中权重缓存）"""
        try:
            _, weights = _shared_skill_loader.load(skill_name)
            return weights
        except Exception:
            return {}
```

- [ ] **Step 4: 跑 skill_loader 与 session_manager 全部测试**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_skill_loader_weights.py tests/unit/test_skill_loader.py tests/unit/test_session_manager.py -v
```

预期：全部 PASS。

- [ ] **Step 5: 提交（vendor 仓）**

```bash
cd vendor/diagnosis-agent
git add src/domain/skill_loader.py src/domain/session_manager.py tests/unit/test_skill_loader_weights.py
git commit -m "feat(skill): 技能权重按名缓存(save/delete同步失效)+会话创建走共享loader"
```

---

### Task 4: 存量清理 + 全量回归

**Files:**
- Modify（数据，非 git 跟踪）: `vendor/diagnosis-agent/data/sessions.json`

**Interfaces:**
- Consumes: Task 1-3 全部完成
- Produces: 无代码接口；清理后的 `sessions.json`

- [ ] **Step 1: 确认 PLD 未运行**

```bash
lsof -iTCP:5000 -sTCP:LISTEN
```

预期：无输出（PLD 停止时才可改数据文件；若在运行，先 `cd "/Users/bei/DEVLOPE/3d agent" && ./dev.sh stop`）。

- [ ] **Step 2: 删除残留会话 sess_81233047**

```bash
cd vendor/diagnosis-agent
.venv/bin/python - <<'EOF'
import json
from pathlib import Path

p = Path("data/sessions.json")
data = json.loads(p.read_text(encoding="utf-8"))
before = len(data["sessions"])
data["sessions"] = [s for s in data["sessions"] if s.get("session_id") != "sess_81233047"]
assert len(data["sessions"]) == before - 1, "未找到 sess_81233047"
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"已删除残留会话，剩余 {len(data['sessions'])} 个")
EOF
```

预期：输出 `已删除残留会话，剩余 0 个`。

- [ ] **Step 3: vendor 全量测试回归**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit -q
```

预期：全部 PASS。

- [ ] **Step 4: backend 测试回归（外层仓，确认零改动无副作用）**

```bash
cd "/Users/bei/DEVLOPE/3d agent/backend"
.venv/bin/python -m pytest tests/ -q
```

预期：全部 PASS。

- [ ] **Step 5: 端到端验证（可选但推荐）**

```bash
cd "/Users/bei/DEVLOPE/3d agent" && ./dev.sh start
```

浏览器发起一次「雅湖线 2025-05-08」实时诊断，观察 HUD 雷电权重为 1.0（而非 0.1）。验证后 `./dev.sh stop`。

---

## Self-Review 记录

- Spec 覆盖：入口分流→Task 1；启动收口→Task 2；权重缓存→Task 3；存量清理+测试→Task 4。全覆盖
- 占位符：无；所有测试与实现代码均为完整可执行内容
- 类型一致：`REUSABLE_STATUSES` / `STALE_STATUSES` / `_weights_cache` / `_shared_skill_loader` 命名跨任务一致；`SessionRepository(file_path)` 签名与 `test_session_repository.py:24` 既有用法一致
