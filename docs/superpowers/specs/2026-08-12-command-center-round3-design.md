# 指挥室第三轮修复设计(摘要卡清理 + 激活权重即生效 + 管理页激活联动 + 历史全选/右键删除)

日期:2026-08-12
状态:已确认(四节设计均经用户逐条确认;问题3 仅激活按钮,不加内容查看)

## 背景(用户实测反馈,2026-08-12 午)

第三轮实测暴露四个问题:

1. **复盘报告残留**:启动新的实时诊断时,右侧「复盘诊断」摘要卡仍显示上一条线路的复盘报告
2. **策略缩略权重不一致**:激活新策略后,左上策略 HUD 卡显示新策略名但权重仍是旧值;下次报告生成后才恢复一致
3. **策略管理页无激活入口**:只有司令对话框的策略面板能激活,管理页只能删除;两处状态需联动
4. **历史记录交互**:缺全选;行内删除按钮易误点且不美观,希望改右键菜单形式

## 根因

### 问题 1

`store.summaries.replay`(ReportViewer.vue:116 摘要卡数据源)只在 `report_summary` 事件时覆盖(ws.js:70-72),**从不清空**。新实时诊断开跑时 backend 仅广播 `report reset`(agent_manager.py:496,清主报告区),双摘要卡与比对数据(`store.compare`)不受影响 → 跨线路陈旧数据显示。

### 问题 2(动态更新断链,两层)

- **vendor**:`POST /api/skills/default`(web.py:879-890)只改 `_default_skill_name`(session_manager.py:188-190)。技能权重仅在**新建会话**时加载(session_manager.py:94,108-113),当前活跃会话的 `active_weights`/`active_skill_name` 不变。对照组 `/api/skills/reset`(web.py:854-861)会立即把 DEFAULT_WEIGHTS 应用到活跃会话——激活接口漏了同等动作
- **backend**:`activate_skill` 路由(agent_manager.py:196-201)只 `send_skills()`(HUD 策略名更新),**未调 `_refresh_snapshot()`**(对比 `reset_skills` 路由 207 行有)→ HUD 权重(store.weights,源自 session_snapshot)停留旧值,直到下次诊断建新会话+快照刷新才恢复

### 问题 3

- StrategiesView.vue 无激活按钮(仅「使用中」徽章);司令面板(ChatModal.vue:158-165)已有激活
- backend `activate_skill` 只广播 `skills` 事件(ChatModal/HUD 消费),**不广播 `strategies_list`**(StrategiesView 消费)→ 即便激活,管理页徽章不刷新,两处不联动

### 问题 4

HistoryView.vue 无全选;行内「删除」按钮紧邻线路名,点击区域重叠易误触。

## 设计

### 1. 新实时诊断清空摘要卡(纯 frontend)

文件:`frontend/src/ws.js`

- `run_state` 分支:`event.mode === 'realtime'` 时
  - `store.summaries.realtime = null; store.summaries.replay = null`(实时卡同属上条线路陈旧数据,一并清)
  - `store.compare = null`(比对口随数据失效关闭入口)
- `mode === 'replay'` **不清**:实时卡是复比对基线,必须保留
- 纯前端改动,backend 事件形态不变(run_state 开跑即广播,agent_manager.py:508)

### 2. 激活即应用活跃会话(vendor + backend)

**vendor/diagnosis-agent**:

- `set_default_skill`(web.py:879-890):设置全局默认后,若存在活跃会话(`session_manager.get_active()`),立即应用:
  ```python
  session.active_skill_name = name
  weights = session_manager._load_skill_weights(name)
  if weights:
      session.active_weights = weights
  ```
  并 `_persist()`(既有调用覆盖)。无活跃会话时仅设全局默认(现状)
- 语义与 `/api/skills/reset` 一致(激活=立即生效);不复位 excluded_tools(reset 才复位,激活与 create() 对齐只动权重/技能名)

**backend**:

- `activate_skill` 路由(agent_manager.py:196-201)`send_skills()` 后补 `await self._refresh_snapshot()` → HUD 权重立即刷新

### 3. 管理页激活 + 三处联动(backend + frontend)

**backend**:

- `activate_skill` 路由补 `await self.send_strategies()` → StrategiesView 徽章即时刷新
- 联动链路(两入口任一激活):`activate_skill` → `send_skills()`(司令面板+HUD 策略名)+ `send_strategies()`(管理页徽章)+ `_refresh_snapshot()`(HUD 权重)

**frontend** `StrategiesView.vue`:

- 行尾「状态」列:默认策略显示「使用中」徽章(既有);非默认策略显示「激活」按钮(`@click="activateSkill(s.name)"`,样式仿 ChatModal 158-165 行)
- import 加 `activateSkill`(ws.js 既有导出,无需新封装)

### 4. 历史全选 + 右键菜单删除(纯 frontend)

文件:`frontend/src/components/HistoryView.vue`

- **全选**:列表头部加一行(复选框 + 「记录」列题),复选框勾选 = 选中当前 filtered 全部记录(仿 StrategiesView toggleAll 19-23 行,作用于 filtered 而非全量)
- **右键菜单**:行内「删除」按钮移除;行加 `@contextmenu.prevent="openMenu($event, r.id)"` → 在鼠标位置浮出小菜单(「删除该记录」单项),点击页面任意处/ESC 关闭;菜单项点击 → 复用既有 `askDelete([id])` 确认弹窗
- 复选框与批量「删除选中(n)」保持现状(右键是单删的新形式,复选框服务批量)

## 不做的事

- 策略内容(markdown)查看弹窗(用户确认不需要)
- vendor 激活接口不复位 excluded_tools、不动 replay 会话的权重快照/还原机制
- 复盘启动时的摘要卡清理(实时基线保留是比对功能前提)
- ChatModal 策略面板、HUD 卡结构不动

## 测试

### vendor(pytest)

1. `set_default_skill`:有活跃会话 → 会话 `active_skill_name`/`active_weights` 立即更新并持久化;无活跃会话 → 仅全局默认变更;技能不存在 → 404(既有行为)
2. 激活后新建诊断不受影响(create() 路径既有测试覆盖)

### backend(pytest)

3. `activate_skill` 路由:断言 `_refresh_snapshot` 与 `send_strategies` 被调用(monkeypatch 两方法计数;pld_client.set_default_skill mock)
4. 既有 activate_skill 行为(skills 广播、local_interventions 计数)不变

### 前端

无测试框架;`npm run build` 通过 + 人工核对:新实时诊断后双卡清空;激活后 HUD 权重即变;管理页激活三处联动;全选/右键菜单/批量删除交互。

## 风险与说明

- 激活应用于活跃会话:复盘进行中激活会改变当前会话权重——与司令对话框调权同属会话级干预,复盘权重快照/还原机制(finally 块)不覆盖激活场景(激活是全局策略切换,语义上本就不该还原),可接受
- run_state realtime 清空是乐观前端行为:诊断失败时双卡显示「等待诊断/尚未复盘」而非旧数据,符合「陈旧数据不应展示」的预期
- 右键菜单为自定义实现(无第三方依赖),需注意菜单不越出视口(简单 clamp)
