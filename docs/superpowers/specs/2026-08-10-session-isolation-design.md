# 实时诊断与复盘会话隔离设计

日期：2026-08-10
状态：已确认（方案 A）

## 背景与问题

PLD（vendor/diagnosis-agent）只有一个会话池，实时诊断与复盘共用：

- **实时诊断**：意图 = DIAGNOSE → `SessionManager.get_or_create()` 复用「同线路 + 未完成」的任意会话
- **复盘**：意图 = 异议/重查 → `get_active()` 取当前会话，在其上调整权重/排除后重跑，期间状态为 `MODIFYING`/`RECHECKING`

「未完成」包含复盘上下文状态（`MODIFYING` 等）。复盘异常中断（关闭页面、PLD 重启）后，会话带着被干预的权重（实测 `LightningDiagnosisTool: 0.1`）持久化到 `data/sessions.json`；重启后会话被恢复，下一次同线路实时诊断被该残留会话截胡，使用了复盘残留的权重而非激活技能 md 的权重。

实测证据：`data/sessions.json` 中 `sess_81233047`（雅湖线，status=modifying，雷电权重 0.1）；两个 `comprehensive_diagnosis.md`（backend 侧基线模板与 vendor 侧运行时权威）中雷电权重均为 1.0，泄漏与文件无关。

## 目标模型

1. 实时诊断永远以当前激活技能（md 文件）的权重为准；权重按技能名缓存，技能未变更时直接命中缓存
2. 复盘会话与实时诊断解耦：复盘产生的权重/排除/复查等修改，任何情况下都不泄漏进实时诊断
3. 复盘仍沿用同一会话进行复现与干预（既有机制不变，这是正确行为）

## 设计内容

### 1. `get_or_create()` 入口分流（核心）

文件：`vendor/diagnosis-agent/src/domain/session_manager.py`

- **可复用状态**：仅 `PENDING`、`DIAGNOSING`（对应「卡死会话恢复」场景）
- **不复用状态**：`MODIFYING`、`RECHECKING`、`EXCLUDED`（均为复盘上下文），遇到即新建会话
- 新建会话权重走既有逻辑：从当前激活技能 md 提取（`session_manager.py:83-89`）

`get_or_create()` 仅被 DIAGNOSE 意图调用（复盘链路走 `get_active()`），改动不影响复盘。

### 2. 技能权重缓存

文件：`vendor/diagnosis-agent/src/domain/skill_loader.py`

- `load()` 已缓存技能内容；在此基础上将 `_extract_weights()` 的结果按技能名缓存（`_weights_cache`）
- `save()` / `delete()` 时同步失效对应技能的权重缓存（与现有内容缓存同生命周期）
- 缓存按技能名隔离，切换默认技能天然不串；无需在切换技能时额外失效

### 3. 启动时收口 stale 会话

文件：`vendor/diagnosis-agent/src/domain/session_manager.py`（`__init__`，`repository.load_all()` 之后）

- 将持久化会话中处于 `MODIFYING` / `RECHECKING` 状态的会话标记为 `COMPLETED`
- 依据：PLD 重启后 backend 的复盘编排状态已丢失，这些会话事实上无法继续复盘
- 作用：卫生性兜底（入口分流已能堵住泄漏），同时避免会话池无限堆积

### 4. 存量清理

- 删除 `vendor/diagnosis-agent/data/sessions.json` 中的 `sess_81233047` 残留会话（复盘产物已保存在诊断结果集中，会话本体无保留价值）
- 备份文件 `sessions.json.bak-*` 不动

## 影响面

- **backend**：零改动
- **frontend**：零改动
- **PLD（vendor/diagnosis-agent）**：`session_manager.py`、`skill_loader.py` 两个文件 + 数据清理

## 测试

vendor 侧新增单元测试（pytest）：

1. `MODIFYING` / `RECHECKING` / `EXCLUDED` 状态的会话不被 `get_or_create()` 复用（同线路也新建）
2. `PENDING` / `DIAGNOSING` 状态的同线路会话仍被复用（卡死恢复不回归）
3. 技能权重缓存：`save()` 更新技能文件后，缓存失效并返回新权重
4. 启动收口：持久化的 `MODIFYING` 会话在加载后变为 `COMPLETED`

## 风险与说明

- 复盘正常流程结束时 backend 已有权重自动还原逻辑（commit 0e9831f），本设计是其异常路径的兜底，两者不冲突
- 若未来需要「复盘会话彻底独立（fork replay 会话）」，可在本设计基础上加 `kind` 字段演进，本次不做（YAGNI）
