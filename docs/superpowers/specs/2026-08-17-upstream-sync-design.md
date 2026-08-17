# 上游改造适配设计(微气象专家 + 知识库关联 + 流式报告)

日期:2026-08-17
状态:已确认(专家阵容/知识库形态/关联范围/KB部署/Mock升级均经用户逐条确认)

## 背景

三个上游仓库更新,本项目适配:
- **Mock_lightning**(mcp_version):重建干净版,含雷电/微气象/风偏等新接口(localhost:8000)
- **Cluade_PLDiagonsis-mcp-version**(mcp_version):鸟害工具禁用,新增微气象 MCP(8005);雷电/风偏/微气象工具 schema 重写;报告生成改流式(report_chunk);新增 /api/history-relation 知识库关联
- **fault-knowledge-base**:知识库问答(localhost:8503,POST /query {question}→{answer});需 U 盘数据+内网 LLM,本项目仅对接+优雅降级

**铁律(用户明确)**:复盘流程、策略保存、复盘比对等定稿逻辑一律不动;流式仅改展示链路;知识库不改变报告内容本体。

## 用户确认的决策

1. 专家阵容:鸟害→微气象(原位替换,鸟害彻底移除)
2. 知识库形态:摘要卡「历史关联」按钮 + 独立弹窗
3. 关联范围:仅当前会话摘要卡(历史记录页不加)
4. KB 部署:对接+优雅降级(服务不可用给提示,不影响诊断)
5. Mock:直接同步上游重建版

## 设计

### 1. Mock 平台同步(vendor/mock-lightning,嵌套仓)

- `git pull origin mcp_version` 同步上游重建版
- 按上游 README 修两处硬编码:`src/txt_parser.py` TXT_DIR 改相对路径 `Path(__file__).parent.parent / "接口"`;`src/app.py` 图片挂载改 `"可视化监拍图片"`(目录已存在)
- 验证:`python src/setup.py` 启动,localhost:8000/docs 可见,getWeather 等新接口存在

### 2. vendor 工具层:鸟害→微气象(vendor/diagnosis-agent)

手工择取上游改动(本地有 skills/replay/data_overrides 等上游没有的定制,不做整文件覆盖):

- `config/tools/lightning.yaml`、`wind.yaml`、`weather.yaml`:采用上游新版(雷电:fault_type/confidence/evidence/details;风偏:wind_speed_ms/wind_description/details;微气象:temperature_c/humidity_pct/humidity_description/details,MCP :8005)
- `config/tools/bird.yaml`:加 `enabled: false`
- `src/infrastructure/adapters/registry.py`:注册时跳过 `enabled: false` 工具(上游 5 行)
- `src/core/models.py`:`DEFAULT_WEIGHTS` 改为 Lightning 1.0 / Icing 0.9 / Wind 1.0 / Weather 1.0(上游值)
- `mcp-services/weather-service`、`wind-service`、`lightning-service`:同步上游版本(对接新 mock 接口;bird-service 保留目录但不再启动)
- `dev.sh`/启动脚本:8004 鸟害 → 8005 微气象
- 既有会话权重中残留 BirdDamageDiagnosisTool:工具未注册即不执行,无需迁移

### 3. 流式报告(vendor → backend → frontend,仅展示链路)

**vendor**(移植上游,合并本地 data_overrides):
- 新增 `src/domain/report_sanitizer.py`(LaTeX→纯文本,上游完整文件)
- `report_composer.py`:`compose()` 尾部抽为 `finalize_response()`;新增 `compose_stream()`(与 compose 同 prompt,**保留本地 data_overrides 参数**传入 _build_prompt;逐块 yield);_build_prompt 加图片 base64 占位替换 + 禁 LaTeX 规则;_format_response 末尾过 sanitize_report
- `core/models.py`:EventType.REPORT_CHUNK + Event.report_chunk()
- `diagnose.py`:compose 调用改 compose_stream 累积循环,逐块 `yield Event.report_chunk(...)`;finalize_response 收尾。复盘(recheck/重跑)走同一 DiagnoseCommand,自然流式,业务流程零改动
- web.py SSE 为通用序列化(`yield _sse_event(event)`),report_chunk 自动流出,无需改

**backend**:
- 诊断流消费循环(agent_manager.py:475 `elif etype == "content"`)扩为 `elif etype in ("content", "report_chunk")`——report_chunk 走同一 report_buf 累积 + `report` 广播(done:False)。complete 时最终全文覆盖(既有逻辑不变,清洗后全文入库/存档/比对)
- 前端 ws.js report 事件已是全量覆盖式渲染,**无需改动**即获得逐字效果

### 4. 知识库关联(vendor 端点 + backend 转发 + 前端按钮弹窗)

**vendor**(移植上游):
- `core/config.py`:KnowledgeBaseConfig(KB_ 前缀 env,base_url 默认 http://localhost:8503);`config/config.yaml` 加 knowledge_base 段;dependency_injection 合并该段(上游 6 行)
- `core/models.py`:DiagnosisSession 加 `history_relation_cache: Optional[List[Dict[str, str]]]`
- `diagnose.py`:execute_tools 后从雷电输出 details 提取 province/voltage 存入 fault_context.additional_info(幂等;补齐时作废 history_relation_cache)(上游 16 行)
- `web.py`:POST /api/history-relation(上游完整端点:两问串行、会话缓存、_persist;KB 不可达 502)

**backend**:
- `pld_client.py`:`history_relation(session_id)` POST /api/history-relation(超时 310s,KB 查询慢)
- `agent_manager.py`:WS 路由 `history_relation` → 调 pld_client → 广播 `history_relation` 事件 {sections 或 error};不占 local_interventions

**frontend**:
- store:`historyRelation = {}`(sessionId 无关,当前会话一份:{ status: 'idle'|'loading'|'ready'|'error', sections, error })
- ws.js:`report_summary` 到达时后台预取(发 history_relation 请求,与上游"流式开始即预取"同效);`history_relation` 事件写 store;`run_state` realtime 开跑时重置为 idle(旧会话缓存失效)
- SummaryCard(ReportViewer.vue):有数据时加「历史关联」按钮(样式同「查看报告」,outline 变体)→ `store.historyModal = true`
- 新组件 `HistoryRelationModal.vue`:标题「历史关联」;loading 转圈;ready 显示 sections(标题+answer 经轻量 md 渲染,复用 ReportModal renderMd 抽到共用或简单内联);error 显示「知识库服务未启动或查询失败,请确认 fault-knowledge-base 已启动(端口 8503)」
- 历史记录页不加(已确认)

### 5. 前端/backend 专家阵容

- backend `agent_manager.py`:AGENTS bird→weather(「微气象诊断智能体」, WeatherDiagnosisTool :8005);TOOL_TO_AGENT 同步;文件头注释 12 行同步
- frontend `App.vue`:TOOL_CN Bird→Weather(微气象)、DEFAULT_WEIGHTS Bird→Weather 1.0、ALL_TOOLS Bird→Weather;78 行映射 bird→weather
- store.agents 由 backend init 驱动,无需改;HUD/司令面板/确认队列自动跟随

## 不做的事

- 复盘流程/策略保存/复盘比对/确认队列/ok_tools 等业务逻辑零改动
- 知识库不改动报告内容本体(不拼接进 report 文本)
- 历史记录页不加历史关联
- fault-knowledge-base 仓库本身的改造(LLM 地址硬编码等,用户暂不实部署)
- vendor 的 skills/会话/复盘定制功能不回向对齐上游
- bird-service 目录不删除(仅停用)

## 测试

### vendor(pytest)
1. registry:enabled:false 工具不注册;weather 工具正常注册
2. compose_stream:逐块 yield 且 finalize 后 report/summary 与 compose 一致(含 data_overrides 块、LaTeX 清洗)
3. /api/history-relation:mock KB /query,断言两问生成(有/无 province 两种)、会话缓存命中、KB 不可达 502
4. diagnose 流:report_chunk 事件序列 + complete 全文一致
5. 全量回归(--ignore=tests/integration/test_diagnose_flow.py)

### backend(pytest)
6. report_chunk 事件累积进 report_buf 并广播 done:False;complete 覆盖
7. history_relation 路由:成功广播 sections / vendor 502 时广播 error
8. 全量回归

### frontend
无测试框架;npm run build + 人工核对:报告逐字流式;摘要卡历史关联按钮→弹窗;KB 未启动降级提示;鸟害智能体消失、微气象出现

## 风险与说明

- KB 查询串行两问、KB 超时 300s:预取在后台进行不阻塞诊断;用户点击时未就绪显示加载态
- 本地 LLM(ollama gemma4:12b)流式输出 vendor 已支持(stream_chat 既有)
- 复盘报告同样流式(同一 compose 链路),仅展示层变化;复盘存档/比对用 complete 清洗后全文,不受影响
- 旧会话(存量的 sessions.json)无 history_relation_cache 字段,pydantic 默认值兼容
- mock 升级后旧接口若被其他工具依赖:覆冰 icing-service 上游未改,依赖接口保持
