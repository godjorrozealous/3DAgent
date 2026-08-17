# 上游改造适配实施计划(微气象专家 + 知识库关联 + 流式报告)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 适配上游三仓更新——诊断专家鸟害→微气象(工具/服务/Mock/前后端联动)、报告流式输出、报告生成后知识库历史关联(摘要卡按钮+弹窗,优雅降级)。

**Architecture:** mock 仓直接同步上游重建版;vendor 手工择取上游改动(工具 yaml/registry/models/composer/diagnose/web,保留本地 skills/replay/data_overrides 定制);backend 透传 report_chunk + 转发 history_relation;frontend 专家映射替换 + 摘要卡按钮 + HistoryRelationModal。

**Tech Stack:** Python 3.11、pytest、Vue 3 + Vite、FastAPI、Flask

**Spec:** `docs/superpowers/specs/2026-08-17-upstream-sync-design.md`

## Global Constraints

- **三仓提交边界**:vendor/diagnosis-agent(分支 mcp_version)、vendor/mock-lightning(分支 mcp_version)、外层仓(backend/frontend/dev.sh/docs)各自提交。一律 `git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit`(不改 git config);mock/vendor 仓**不 push 上游**
- vendor 测试:`cd vendor/diagnosis-agent && .venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_diagnose_flow.py`,基线 372 passed 无回归
- backend 测试:`cd backend && .venv/bin/python -m pytest tests/ -q`,基线 85 passed 无回归
- **铁律**:复盘流程/策略保存/复盘比对/确认队列/ok_tools 逻辑零改动;知识库不改变报告文本本体;历史记录页不加历史关联
- vendor `config/config.yaml` 本地含真实 API key,不得提交(config.yaml 的 knowledge_base 段改动用 `git add -p` 或手工只提交该段——**改为不提交 config.yaml**,KB 有默认值 localhost:8503,本地文件手工补即可)
- 上游参考:vendor 仓已 fetch origin/mcp_version(db46531);上游文件用 `git show origin/mcp_version:<path>` 取
- frontend 无测试框架:`npm run build` 通过即门槛

---

### Task 1(mock 仓): 同步上游重建版 + 路径相对化

**Files:**
- Modify: `vendor/mock-lightning`(整仓 reset 到 origin/mcp_version=20e90eb)
- Modify: `vendor/mock-lightning/src/txt_parser.py:8`、`src/app.py:18`
- Test: 无(pytest 不属于本任务;冒烟验证)

**Interfaces:**
- Consumes: 用户已确认「直接同步上游」;本地 app.py 未提交修复(图片挂载相对化)将被 reset 丢弃,Step 2 重新施加
- Produces: localhost:8000 提供雷电/微气象/风偏新接口(getWeather_api 等),供 Task 2 的 MCP 服务调用

- [ ] **Step 1: 同步上游**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/mock-lightning"
git fetch origin mcp_version
git reset --hard origin/mcp_version
```

(上游强制重建过历史;本地无需要保留的提交。`.DS_Store`/`__pycache__` 为忽略文件不受影响。)

- [ ] **Step 2: 两处路径相对化**

`src/txt_parser.py:8`:
```python
TXT_DIR = Path(__file__).resolve().parent.parent / "接口"
```

`src/app.py`:顶部 import 区加 `from pathlib import Path`;第 18 行挂载改为:
```python
_IMAGES_DIR = Path(__file__).resolve().parent.parent / "可视化监拍图片"
app.mount("/images", StaticFiles(directory=str(_IMAGES_DIR)), name="images")
```

- [ ] **Step 3: 冒烟验证**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/mock-lightning/src"
/Users/bei/DEVLOPE/3d agent/backend/.venv/bin/python -m uvicorn app:app --port 18000 &
sleep 3
curl -s http://127.0.0.1:18000/docs | head -c 200
curl -s http://127.0.0.1:18000/openapi.json | python3 -c "import json,sys; print('\n'.join(sorted(json.load(sys.stdin)['paths'])))" | head -20
kill %1
```

预期:启动不崩;openapi paths 含天气/风偏相关接口(对比旧版只有雷电)。

- [ ] **Step 4: 提交(mock 仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/mock-lightning"
git add src/txt_parser.py src/app.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "fix: 接口/图片目录路径相对化(脱离原作者机器路径)"
```

---

### Task 2(vendor): 工具层——鸟害禁用 + 微气象/雷电/风偏新 schema + 服务同步

**Files:**
- Modify: `vendor/diagnosis-agent/config/tools/{lightning,wind,weather}.yaml`(取上游版)
- Modify: `vendor/diagnosis-agent/config/tools/bird.yaml`(加 enabled: false)
- Modify: `vendor/diagnosis-agent/src/infrastructure/adapters/registry.py:51-56`(跳过禁用)
- Modify: `vendor/diagnosis-agent/src/core/models.py`(DEFAULT_WEIGHTS 185-190)
- Modify: `vendor/diagnosis-agent/mcp-services/`(整目录取上游版)
- Test: `vendor/diagnosis-agent/tests/unit/test_tool_registry_enabled.py`(新建)

**Interfaces:**
- Consumes: vendor 仓已 fetch origin/mcp_version;上游 mcp-services 与本地无本地定制(仅 .DS_Store 差异,已核实)
- Produces: WeatherDiagnosisTool 注册可用(:8005);BirdDamageDiagnosisTool 不再注册(诊断与前端均不可见);Task 3/4 在此之上改 composer/diagnose

- [ ] **Step 1: 写失败测试**

新建 `vendor/diagnosis-agent/tests/unit/test_tool_registry_enabled.py`:

```python
"""工具注册:enabled:false 跳过注册;微气象工具正常注册。"""
import yaml

from src.infrastructure.adapters.registry import ToolRegistry


def _write_tool(tmp_path, name, enabled=None):
    data = {
        "tool": {
            "name": name,
            "display_name": name,
            "description": "测试工具",
            "category": "test",
            "adapter": {"type": "mcp", "config": {"url": "http://localhost:19999", "timeout": 1}},
            "output_schema": {"type": "structured", "fields": []},
            "report_mapping": {"chapter": "诊断证据", "render_template": "table"},
        }
    }
    if enabled is not None:
        data["tool"]["enabled"] = enabled
    p = tmp_path / f"{name.lower()}.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_disabled_tool_not_registered(tmp_path):
    _write_tool(tmp_path, "BirdDamageDiagnosisTool", enabled=False)
    reg = ToolRegistry()
    reg.load_tools(config_dir=str(tmp_path))
    assert reg.get_config("BirdDamageDiagnosisTool") is None


def test_enabled_default_true(tmp_path):
    _write_tool(tmp_path, "WeatherDiagnosisTool")
    reg = ToolRegistry()
    reg.load_tools(config_dir=str(tmp_path))
    assert reg.get_config("WeatherDiagnosisTool") is not None
```

(若 ToolRegistry 构造/load_tools 签名不同,读 registry.py 对齐;断言语义不变:禁用不注册、缺省注册。)

- [ ] **Step 2: 跑测试确认失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_tool_registry_enabled.py -v
```

预期:test_disabled_tool_not_registered FAIL(未实现 enabled 跳过)。

- [ ] **Step 3: 实现**

① registry.py `_load_from_file`(51-56 区域)`data = yaml.safe_load(f)` 之后插入:

```python
        # enabled: false 的工具跳过注册（诊断与前端均不可见）
        if not data["tool"].get("enabled", True):
            logger.info(f"工具已禁用，跳过注册: {data['tool'].get('name')} ({config_file.name})")
            return
```

② 工具 yaml 与服务目录取上游版:

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/diagnosis-agent"
git checkout origin/mcp_version -- config/tools/lightning.yaml config/tools/wind.yaml config/tools/weather.yaml mcp-services/
```

③ `config/tools/bird.yaml` 第 3 行(display_name 之后)加:

```yaml
  enabled: false
```

④ `src/core/models.py` DEFAULT_WEIGHTS(185-190)改为:

```python
DEFAULT_WEIGHTS: Dict[str, float] = {
    "LightningDiagnosisTool": 1.0,
    "IcingDiagnosisTool": 0.9,
    "WindDiagnosisTool": 1.0,
    "WeatherDiagnosisTool": 1.0,
}
```

- [ ] **Step 4: 测试通过 + 全量回归**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_tool_registry_enabled.py -v
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_diagnose_flow.py
```

预期:新测试 2 条 PASS;全量无回归(注意:若有既有测试断言 Bird 在 DEFAULT_WEIGHTS,按新阵容同步修正该测试,report 中说明)。

- [ ] **Step 5: 提交(vendor 仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/diagnosis-agent"
git add config/tools/ src/infrastructure/adapters/registry.py src/core/models.py mcp-services/ tests/unit/test_tool_registry_enabled.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat: 微气象工具上线+鸟害禁用(上游工具schema/服务同步,registry支持enabled)"
```

---

### Task 3(vendor): 流式报告(compose_stream + report_chunk + sanitizer)

**Files:**
- Create: `vendor/diagnosis-agent/src/domain/report_sanitizer.py`(取上游完整文件)
- Modify: `vendor/diagnosis-agent/src/core/models.py`(EventType 53、Event.report_chunk 261 区域)
- Modify: `vendor/diagnosis-agent/src/domain/report_composer.py`(compose 33-99、_build_prompt 195-206/238-250、_format_response 289-293)
- Modify: `vendor/diagnosis-agent/src/application/commands/diagnose.py`(compose 调用 238-252)
- Test: `vendor/diagnosis-agent/tests/unit/test_compose_stream.py`(新建);`tests/unit/test_report_sanitizer.py`(取上游版)

**Interfaces:**
- Consumes: Task 2 完成;上游 report_sanitizer.py / test_report_sanitizer.py 原样取
- Produces: DiagnoseCommand 产出 EventType.REPORT_CHUNK 事件;web.py SSE 通用序列化自动流出;backend Task 5 消费 report_chunk

- [ ] **Step 1: 取上游文件**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/diagnosis-agent"
git show origin/mcp_version:src/domain/report_sanitizer.py > src/domain/report_sanitizer.py
git show origin/mcp_version:tests/unit/test_report_sanitizer.py > tests/unit/test_report_sanitizer.py
```

- [ ] **Step 2: 写失败测试**

新建 `vendor/diagnosis-agent/tests/unit/test_compose_stream.py`:

```python
"""compose_stream:流式产出增量;finalize_response 与 compose 收尾一致(含 conclusion 剥离+LaTeX清洗)。"""
import pytest

from src.domain.report_composer import ReportComposer
from src.core.models import ToolOutput


class FakeLLM:
    async def chat(self, messages, **kwargs):
        return "# 报告\n\n结论 $a \\times b$\n\n```conclusion\n{\"fault_type\":\"雷击\",\"confidence\":0.9,\"primary_tool\":\"LightningDiagnosisTool\"}\n```"

    async def stream_chat(self, messages, **kwargs):
        for delta in ["# 报告", "\n\n结论 $a \\times b$", "\n\n```conclusion\n{\"fault_type\":\"雷击\",\"confidence\":0.9,\"primary_tool\":\"LightningDiagnosisTool\"}\n```"]:
            yield delta


def _outputs():
    return {"LightningDiagnosisTool": ToolOutput(
        tool_name="LightningDiagnosisTool", raw_text="雷电数据",
        structured_data={"fault_type": "雷击", "confidence": 0.9})}


@pytest.mark.asyncio
async def test_compose_stream_yields_deltas_and_finalizes():
    c = ReportComposer(FakeLLM())
    parts = []
    async for d in c.compose_stream(_outputs(), None, "s1"):
        parts.append(d)
    assert "".join(parts).startswith("# 报告")
    result = c.finalize_response("".join(parts), _outputs())
    assert result["summary"]["fault_type"] == "雷击"
    assert result["summary"]["confidence"] == 0.9
    assert "```conclusion" not in result["report"]   # conclusion 块已剥离
    assert "$" not in result["report"]               # LaTeX 已清洗


@pytest.mark.asyncio
async def test_compose_unchanged_non_stream():
    """compose 保持既有行为(非流式,同收尾逻辑)。"""
    c = ReportComposer(FakeLLM())
    result = await c.compose(_outputs(), None, "s1")
    assert result["summary"]["fault_type"] == "雷击"
    assert "```conclusion" not in result["report"]
```

(pytest-asyncio 配置若既有测试用 asyncio_mode=auto 则同例;否则加 @pytest.mark.asyncio 并确认插件可用——参照 tests/unit/ 既有 async 测试写法。)

- [ ] **Step 3: 跑测试确认失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_compose_stream.py tests/unit/test_report_sanitizer.py -v
```

预期:test_compose_stream 2 条 FAIL(compose_stream/finalize_response 不存在);sanitizer 测试 PASS(文件已取上游)。

- [ ] **Step 4: 实现**

① `src/core/models.py`:
- EventType(53 行 COMPLETE 之前)加 `REPORT_CHUNK = "report_chunk"`
- Event 类 content classmethod(261 区域)之后加:

```python
    @classmethod
    def report_chunk(cls, session_id: str, text: str) -> Event:
        """报告流式增量块（payload.content 与前端累积逻辑约定一致）"""
        return cls(session_id=session_id, event_type=EventType.REPORT_CHUNK, payload={"content": text})
```

② `src/domain/report_composer.py`:

- import 区加 `from src.domain.report_sanitizer import sanitize_report`
- `compose()` 的收尾段(85-99 行,`conclusion, report_text = ...` 到 return)抽为:

```python
        try:
            response = await self.llm.chat(messages)
        except Exception as e:
            logger.error(f"会话 {session_id} 报告生成失败: {e}")
            raise

        return self.finalize_response(response, tool_outputs, fault_context, action_log)

    def finalize_response(
        self,
        response: str,
        tool_outputs: Dict[str, ToolOutput],
        fault_context: Optional[FaultContext] = None,
        action_log: Optional[list[dict]] = None,
    ) -> Dict[str, Any]:
        """报告收尾:conclusion 剥离 + 格式清洗 + 摘要提取(compose/compose_stream 共用)。"""
        conclusion, report_text = self._split_conclusion(response)
        formatted = self._format_response(report_text)
        # 摘要与报告共用 LLM 产出：优先取结论块（已含加权逻辑）；
        # LLM 未按约定输出或解析失败时，回退为纯工具输出 argmax。
        summary = conclusion if conclusion is not None else self._extract_summary(tool_outputs)
        if fault_context:
            summary["line_name"] = fault_context.line_name
            if fault_context.additional_info:
                summary["voltage_level"] = fault_context.additional_info.get("voltage_level", "")
            if fault_context.fault_time:
                summary["fault_time"] = fault_context.fault_time.isoformat()
        if action_log:
            summary["action_log"] = action_log

        return {"summary": summary, "report": formatted}

    async def compose_stream(
        self,
        tool_outputs: Dict[str, ToolOutput],
        template: Optional[Any],
        session_id: str,
        fault_context: Optional[FaultContext] = None,
        action_log: Optional[list[dict]] = None,
        weights: Optional[Dict[str, float]] = None,
        active_template_name: Optional[str] = None,
        active_skill_name: Optional[str] = None,
        data_overrides: Optional[Dict[str, str]] = None,
    ):
        """流式撰写诊断报告,逐块 yield LLM 输出增量。

        与 compose() 使用完全相同的 prompt 构建逻辑(含 data_overrides);
        调用方负责累积全文并调 finalize_response 收尾。
        """
        template_md = self._load_template_md(active_template_name)

        skill_md = ""
        if self.skill_loader and active_skill_name:
            skill_md, _ = self.skill_loader.load(active_skill_name)

        prompt = self._build_prompt(
            tool_outputs, fault_context, action_log, weights, template_md, skill_md,
            data_overrides=data_overrides,
        )

        messages = [
            {"role": "system", "content": "你是输电线路故障诊断报告撰写专家。"},
            {"role": "user", "content": prompt},
        ]

        async for delta in self.llm.stream_chat(messages):
            yield delta
```

- `_build_prompt` 的结构化数据段(200-205)加图片占位(上游逻辑,本地缩进对齐):

```python
            if output.structured_data:
                # base64 图片对文字报告无用，替换为占位说明，避免数万 token 的 prefill 浪费
                # （浅拷贝处理，不影响会话缓存/SSE 事件中的原始数据）
                data = output.structured_data
                details = data.get("details")
                if isinstance(details, dict) and isinstance(details.get("images"), list):
                    data = {
                        **data,
                        "details": {
                            **details,
                            "images": f"<{len(details['images'])} 张图片，文字报告未使用，已省略>",
                        },
                    }
                lines.append(
                    f"结构化数据：\n```json\n"
                    f"{json.dumps(data, ensure_ascii=False, indent=2)}"
                    f"\n```"
                )
```

- 格式要求(238-250)第 6 条之后加第 7 条:

```python
            "7. 数学表达必须使用纯文本符号（×、≤、≥、°、±、%），禁止使用 LaTeX `$...$` 语法",
```

- `_format_response`(289-293)改为:

```python
    def _format_response(self, response: str) -> str:
        stripped = response.strip()
        if not stripped.startswith("# "):
            stripped = f"# 输电线路故障诊断报告\n\n{stripped}"
        # 入库前清洗 LaTeX 公式（$...$ → 纯文本），防止前端渲染乱码
        return sanitize_report(stripped)
```

③ `src/application/commands/diagnose.py` compose 调用段(238-252)改为:

```python
        compose_start = time.perf_counter()
        report_parts: list[str] = []
        async for delta in self.report_composer.compose_stream(
            tool_outputs, None, session.session_id, fault_context, action_log_data,
            weights=session.active_weights,
            active_template_name=session.active_template_name,
            active_skill_name=session.active_skill_name,
            data_overrides=session.data_overrides or None,
        ):
            report_parts.append(delta)
            yield Event.report_chunk(session.session_id, delta)
        compose_end = time.perf_counter()
        if diag_logger:
            diag_logger.record_tool_timing(
                "report_composer", compose_start, compose_end, success=True
            )
        composed = self.report_composer.finalize_response(
            "".join(report_parts), tool_outputs, fault_context, action_log_data
        )
        report = composed["report"]
        summary = composed["summary"]
```

- [ ] **Step 5: 测试通过 + 全量回归**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_compose_stream.py tests/unit/test_report_sanitizer.py -v
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_diagnose_flow.py
```

预期:全部 PASS。注意既有 test_report_composer.py 若断言 _format_response 原样输出,LaTeX 清洗为新增行为,按 sanitize 后结果修正断言并在 report 说明。

- [ ] **Step 6: 提交(vendor 仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/diagnosis-agent"
git add src/domain/report_sanitizer.py src/domain/report_composer.py src/core/models.py src/application/commands/diagnose.py tests/unit/test_compose_stream.py tests/unit/test_report_sanitizer.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat: 报告流式输出(compose_stream+report_chunk事件+LaTeX清洗+图片占位)"
```

---

### Task 4(vendor): 知识库历史关联端点

**Files:**
- Modify: `vendor/diagnosis-agent/src/core/config.py`(KnowledgeBaseConfig,62-82 区域)
- Modify: `vendor/diagnosis-agent/src/interfaces/dependency_injection.py`(tools 合并之后,98-102)
- Modify: `vendor/diagnosis-agent/src/core/models.py`(DiagnosisSession 215 区域)
- Modify: `vendor/diagnosis-agent/src/application/commands/diagnose.py`(213-217 区域)
- Modify: `vendor/diagnosis-agent/src/interfaces/web.py`(imports + /api/sessions/<id> GET 527 之前)
- Modify: `vendor/diagnosis-agent/config/config.yaml`(**仅本地文件**,不提交)
- Test: `vendor/diagnosis-agent/tests/unit/test_history_relation.py`(新建)

**Interfaces:**
- Consumes: Task 3 完成;上游 /api/history-relation 端点代码(origin/mcp_version web.py:465-517)
- Produces: POST /api/history-relation {session_id} → {success, sections:[{title,answer}], cached?};backend Task 5 消费

- [ ] **Step 1: 写失败测试**

新建 `vendor/diagnosis-agent/tests/unit/test_history_relation.py`(fixture 模式与 test_skill_activation.py 同构):

```python
"""POST /api/history-relation:基于会话故障上下文串行查询知识库,会话级缓存,KB 不可用 502。"""
import datetime

import pytest

from src.interfaces.web import create_app
from src.interfaces.dependency_injection import get_container
from src.core.models import FaultContext


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


class FakeResp:
    def __init__(self, answer):
        self._answer = answer

    def raise_for_status(self):
        pass

    def json(self):
        return {"answer": self._answer}


class FakeClient:
    """记录提问序列的 httpx.Client 替身。"""
    calls = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def post(self, url, json=None, **kw):
        FakeClient.calls.append(json["question"])
        return FakeResp(f"回答:{json['question']}")


def _patch_kb(monkeypatch, client_cls=FakeClient):
    import httpx
    FakeClient.calls = []
    monkeypatch.setattr(httpx, "Client", client_cls)


def test_missing_session_id_400(client):
    c, _ = client
    resp = c.post("/api/history-relation", json={})
    assert resp.status_code == 400


def test_unknown_session_404(client):
    c, _ = client
    resp = c.post("/api/history-relation", json={"session_id": "不存在"})
    assert resp.status_code == 404


def test_single_question_without_province_and_cached(client, monkeypatch):
    """无省份/电压:只问线路历年+兜底第二节;第二次调用命中缓存不再问 KB。"""
    c, container = client
    _patch_kb(monkeypatch)
    s = container.session_manager.create("雅湖线")
    r1 = c.post("/api/history-relation", json={"session_id": s.session_id})
    assert r1.status_code == 200
    body = r1.get_json()
    assert body["success"] is True
    assert len(body["sections"]) == 2
    assert "雅湖线历年情况" in FakeClient.calls[0]
    assert "无法生成此查询" in body["sections"][1]["answer"]
    n = len(FakeClient.calls)
    r2 = c.post("/api/history-relation", json={"session_id": s.session_id})
    assert r2.get_json().get("cached") is True
    assert len(FakeClient.calls) == n  # 缓存命中


def test_two_questions_with_fault_context(client, monkeypatch):
    """有省份/电压/故障时间:两问(线路历年 + 区域同期月份窗口)。"""
    c, container = client
    _patch_kb(monkeypatch)
    s = container.session_manager.create("雅湖线")
    s.fault_context = FaultContext(
        line_name="雅湖线",
        fault_time=datetime.datetime(2025, 5, 8, 19, 46),
        additional_info={"province": "江西", "voltage": "500kV"},
    )
    resp = c.post("/api/history-relation", json={"session_id": s.session_id})
    assert resp.status_code == 200
    assert len(FakeClient.calls) == 2
    assert "江西500kV线路2025年4-6月情况" in FakeClient.calls[1]


def test_kb_down_502(client, monkeypatch):
    """KB 不可达:502,不缓存。"""
    class DownClient(FakeClient):
        def post(self, url, json=None, **kw):
            raise ConnectionError("refused")

    c, container = client
    _patch_kb(monkeypatch, DownClient)
    s = container.session_manager.create("雅湖线")
    resp = c.post("/api/history-relation", json={"session_id": s.session_id})
    assert resp.status_code == 502
    assert container.session_manager.get(s.session_id).history_relation_cache is None
```

(FaultContext 必填字段以 src/core/models.py 实际定义为准微调;session_manager.create 签名参照 test_skill_activation.py。)

- [ ] **Step 2: 跑测试确认失败**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_history_relation.py -v
```

预期:全 FAIL(端点/字段不存在)。

- [ ] **Step 3: 实现**

① `src/core/config.py` ToolsConfig(60 行)之后加:

```python
class KnowledgeBaseConfig(BaseSettings):
    """故障知识库配置（历史关联数据源）"""
    model_config = SettingsConfigDict(env_prefix="KB_", extra="ignore")

    base_url: str = "http://localhost:8503"
```

AppConfig `tools` 字段之后加:

```python
    knowledge_base: KnowledgeBaseConfig = Field(default_factory=KnowledgeBaseConfig)
```

② `src/interfaces/dependency_injection.py` tools 合并块之后加:

```python
        # 合并 knowledge_base 配置
        if "knowledge_base" in data:
            for key, value in data["knowledge_base"].items():
                if hasattr(self.config.knowledge_base, key):
                    setattr(self.config.knowledge_base, key, value)
```

③ `src/core/models.py` DiagnosisSession `chat_history` 字段之后加:

```python
    history_relation_cache: Optional[List[Dict[str, str]]] = None
```

④ `src/application/commands/diagnose.py`「新结果存入缓存」循环(213-215)之后加:

```python
        # 从雷电工具输出提取省份/电压存入会话故障上下文（幂等，供历史关联使用）
        lightning_output = tool_outputs.get("LightningDiagnosisTool")
        if lightning_output and session.fault_context is not None:
            details = (lightning_output.structured_data or {}).get("details", {})
            info = session.fault_context.additional_info
            newly_added = False
            if details.get("province"):
                newly_added = newly_added or "province" not in info
                info["province"] = details["province"]
            if details.get("voltage"):
                newly_added = newly_added or "voltage" not in info
                info["voltage"] = details["voltage"]
            # 老会话补齐字段后，此前缓存的兜底历史关联答案需作废重查
            if newly_added:
                session.history_relation_cache = None
```

⑤ `src/interfaces/web.py`:
- import 区加 `import httpx` 与 `from src.core.exceptions import SessionNotFoundError`
- `/api/sessions/<id>` GET(527)之前插入上游端点(原样移植):

```python
    @app.route("/api/history-relation", methods=["POST"])
    def history_relation():
        """历史关联：基于会话故障上下文动态生成两个问题，串行调用故障知识库 API"""
        kb_url = container.config.knowledge_base.base_url.rstrip("/") + "/query"
        body = request.get_json(silent=True) or {}
        session_id = body.get("session_id")
        if not session_id:
            return jsonify({"success": False, "error": "缺少 session_id"}), 400
        try:
            session = container.session_manager.get(session_id)
        except SessionNotFoundError:
            return jsonify({"success": False, "error": f"会话不存在: {session_id}"}), 404

        # 会话级缓存：问题参数来源于会话持久化数据（创建后不变），答案在会话生命周期内确定
        if session.history_relation_cache:
            return jsonify({
                "success": True,
                "sections": session.history_relation_cache,
                "cached": True,
            })

        line = session.line_name
        questions = [(f"一、{line}历年情况", f"{line}历年情况")]

        fault_ctx = session.fault_context
        info = fault_ctx.additional_info if fault_ctx else {}
        province = info.get("province")
        voltage = info.get("voltage")
        fault_time = fault_ctx.fault_time if fault_ctx else None
        if province and voltage and fault_time:
            year, month = fault_time.year, fault_time.month
            a = month - 1 if month > 1 else 1  # 舍弃跨年
            b = month + 1 if month < 12 else 12
            q2 = f"{province}{voltage}线路{year}年{a}-{b}月情况"
            questions.append((f"二、{q2}", q2))

        sections = []
        try:
            with httpx.Client(timeout=300.0) as client:
                for title, question in questions:
                    resp = client.post(kb_url, json={"question": question})
                    resp.raise_for_status()
                    sections.append({"title": title, "answer": resp.json().get("answer", "")})
        except Exception as e:
            logger.error(f"历史关联查询失败: {e}")
            return jsonify({"success": False, "error": f"故障知识库查询失败: {e}"}), 502

        if len(questions) == 1:
            sections.append({
                "title": "二、区域同期故障情况",
                "answer": "该会话诊断时未记录省份/电压信息，无法生成此查询。重新执行一次诊断后可查看。",
            })
        session.history_relation_cache = sections
        container.session_manager._persist()
        return jsonify({"success": True, "sections": sections})
```

(若 `session.line_name` 属性不存在,读 models.py 用实际字段——session.line_name 或 session.fault_context.line_name 或会话存储的线路文本;以代码事实为准并在 report 说明。)

⑥ 本地 `config/config.yaml` 末尾加(**不提交**):

```yaml
knowledge_base:
  base_url: http://localhost:8503
```

- [ ] **Step 4: 测试通过 + 全量回归**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/unit/test_history_relation.py -v
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_diagnose_flow.py
```

- [ ] **Step 5: 提交(vendor 仓,不含 config.yaml)**

```bash
cd "/Users/bei/DEVLOPE/3d agent/vendor/diagnosis-agent"
git add src/core/config.py src/core/models.py src/interfaces/dependency_injection.py src/interfaces/web.py src/application/commands/diagnose.py tests/unit/test_history_relation.py
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat: 知识库历史关联端点(两问串行+会话缓存+省份电压提取,KB不可用502)"
```

---

### Task 5(backend): report_chunk 透传 + history_relation 转发 + 专家阵容

**Files:**
- Modify: `backend/agent_manager.py`(头注释 12、AGENTS 46、TOOL_AGENTS 55、诊断流 475、handle_message 加路由)
- Modify: `backend/pld_client.py`(加 history_relation)
- Modify: `dev.sh`(MCP_SERVICES 去掉 bird)
- Test: `backend/tests/test_report_stream.py`(新建)、`backend/tests/test_history_relation.py`(新建)

**Interfaces:**
- Consumes: vendor Task 3 的 report_chunk 事件、Task 4 的 /api/history-relation
- Produces: 前端消费:report 增量广播(既有形态);WS 路由 `history_relation` → 广播 `history_relation` 事件 {sections} 或 {error};init agents 中 bird→weather

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_report_stream.py`:

```python
"""report_chunk 事件:与 content 同样累积进 report_buf 并广播增量(done:False)。"""
import agent_manager
from tests.test_agent_manager import FakeWS


async def _chunks(events):
    for e in events:
        yield e


async def test_report_chunk_accumulates(monkeypatch):
    events = [
        {"event_type": "start", "payload": {}, "session_id": "s1"},
        {"event_type": "report_chunk", "payload": {"content": "# 报告"}, "session_id": "s1"},
        {"event_type": "report_chunk", "payload": {"content": "\n章节"}, "session_id": "s1"},
        {"event_type": "complete",
         "payload": {"report": "# 报告\n章节", "summary": {"fault_type": "雷击", "confidence": 0.9}},
         "session_id": "s1"},
    ]
    monkeypatch.setattr(agent_manager.pld_client, "chat_stream", lambda *a, **kw: _chunks(events))
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.run_diagnosis(text="雅湖线测试")
    reports = [e for e in ws.events if e["type"] == "report" and not e.get("reset")]
    inc = [e for e in reports if not e["done"]]
    assert any(e["content"] == "# 报告\n章节" for e in inc)  # 增量累积
    final = [e for e in reports if e["done"]][-1]
    assert final["content"] == "# 报告\n章节"                # complete 覆盖
```

(run_diagnosis 的完整依赖——queue 广播/record 创建等——参照 tests/test_agent_manager.py 既有 run_diagnosis 测试的 mock 方式对齐;若既有测试有 helper 直接复用。)

新建 `backend/tests/test_history_relation.py`:

```python
"""history_relation 路由:成功广播 sections;vendor 失败广播 error。"""
import agent_manager
from tests.test_agent_manager import FakeWS


async def areturn(v):
    return v


async def _raise(*a, **kw):
    raise ConnectionError("PLD 8503 不可达")


async def test_history_relation_success(monkeypatch):
    monkeypatch.setattr(agent_manager.pld_client, "history_relation",
                        lambda sid: areturn({"success": True,
                                             "sections": [{"title": "一、雅湖线历年情况", "answer": "……"}]}))
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    ev = [e for e in ws.events if e["type"] == "history_relation"][0]
    assert ev["sections"][0]["title"].startswith("一、")


async def test_history_relation_error(monkeypatch):
    monkeypatch.setattr(agent_manager.pld_client, "history_relation", _raise)
    mgr = agent_manager.AgentManager()
    mgr.session_id = "s1"
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    ev = [e for e in ws.events if e["type"] == "history_relation"][0]
    assert "error" in ev


async def test_history_relation_no_session(monkeypatch):
    mgr = agent_manager.AgentManager()
    mgr.session_id = None
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "history_relation"})
    ev = [e for e in ws.events if e["type"] == "history_relation"][0]
    assert ev["error"] == "无活跃会话"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend
.venv/bin/python -m pytest tests/test_report_stream.py tests/test_history_relation.py -v
```

预期:FAIL(report_chunk 未处理 / 路由不存在)。

- [ ] **Step 3: 实现**

① `backend/agent_manager.py` 诊断流 content 分支(475)改为:

```python
            elif etype in ("content", "report_chunk"):
```

② 头注释 12 行改为 `  weather  微气象诊断   = WeatherDiagnosisTool   (8005)`;AGENTS(46)改为:

```python
    "weather": {"name": "微气象诊断智能体", "role": "WeatherDiagnosisTool :8005"},
```

TOOL_AGENTS(55)改为 `"weather": "WeatherDiagnosisTool",`。

③ handle_message 加路由(放 delete_records 之后):

```python
        elif mtype == "history_relation":
            if not self.session_id:
                await self.broadcast({"type": "history_relation", "error": "无活跃会话"})
            else:
                try:
                    result = await pld_client.history_relation(self.session_id)
                    await self.broadcast({
                        "type": "history_relation",
                        "sections": result.get("sections", []),
                    })
                except Exception as e:
                    await self.broadcast({"type": "history_relation", "error": str(e)})
```

④ `backend/pld_client.py` 末尾加:

```python
async def history_relation(session_id: str) -> dict:
    """调用 PLD /api/history-relation 知识库历史关联(KB 串行两问较慢,超时 310s)。"""
    async with httpx.AsyncClient(timeout=310) as client:
        resp = await client.post(
            f"{PLD_BASE}/api/history-relation", json={"session_id": session_id}
        )
        resp.raise_for_status()
        return resp.json()
```

⑤ `dev.sh`:`MCP_SERVICES="lightning icing wind bird weather"` 改为 `MCP_SERVICES="lightning icing wind weather"`(bird  case 分支保留无害,可一并删除 mcp_port 中 bird 行)。

- [ ] **Step 4: 测试通过 + 全量回归**

```bash
cd backend
.venv/bin/python -m pytest tests/test_report_stream.py tests/test_history_relation.py -v
.venv/bin/python -m pytest tests/ -q
```

预期:全 PASS。注意既有测试若断言 AGENTS 含 bird,按新阵容修正并说明。

- [ ] **Step 5: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add backend/agent_manager.py backend/pld_client.py backend/tests/test_report_stream.py backend/tests/test_history_relation.py dev.sh
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(backend): report_chunk透传+知识库历史关联转发+专家阵容鸟害换微气象"
```

---

### Task 6(frontend): 专家映射 + 历史关联按钮/弹窗

**Files:**
- Modify: `frontend/src/App.vue`(TOOL_CN 37、DEFAULT_WEIGHTS 38、ALL_TOOLS 41、TOOL_AGENTS 78、import/挂载弹窗)
- Modify: `frontend/src/three/CommandRoom.js`(席位 17、状态循环 616)
- Modify: `frontend/src/components/EventStream.vue`(颜色 17)
- Modify: `frontend/src/components/AgentSessionModal.vue`(映射 11)
- Modify: `frontend/src/components/ChatModal.vue`(示例文案 83)
- Modify: `frontend/src/store.js`(加 historyRelation/historyModal)
- Modify: `frontend/src/ws.js`(report_summary 预取、history_relation 事件、run_state 重置、导出 requestHistoryRelation)
- Modify: `frontend/src/components/ReportViewer.vue`(SummaryCard 加按钮)
- Create: `frontend/src/components/HistoryRelationModal.vue`
- Test: 无(构建验证)

**Interfaces:**
- Consumes: backend Task 5 的 init agents(weather)、history_relation 事件
- Produces: 无

- [ ] **Step 1: 专家阵容替换(bird→weather)**

① `App.vue`:
- 37: `const TOOL_CN = { Lightning: '雷电', Icing: '覆冰', Wind: '风偏', Weather: '微气象' }`
- 38: `const DEFAULT_WEIGHTS = { Lightning: 1.0, Icing: 0.9, Wind: 1.0, Weather: 1.0 }`
- 41: `const ALL_TOOLS = ['Lightning', 'Wind', 'Icing', 'Weather']`
- 74-79 TOOL_AGENTS:`bird: 'BirdDamageDiagnosisTool'` → `weather: 'WeatherDiagnosisTool'`

② `CommandRoom.js` 17: `{ id: 'weather', label: '微气象诊断', pos: [11, 0, 2.5], rotY: -Math.PI / 2, kind: 'researcher' },`;616 列表 `'bird'` → `'weather'`。

③ `EventStream.vue` 17: `bird: 'text-orange-300'` → `weather: 'text-orange-300'`。

④ `AgentSessionModal.vue` 11: `BirdDamageDiagnosisTool: 'bird'` → `WeatherDiagnosisTool: 'weather'`。

⑤ `ChatModal.vue` 83 示例文案:「排除鸟害工具」→「排除微气象工具」。

- [ ] **Step 2: store + ws.js**

① `store.js` reportModal 行之后加:

```js
  historyRelation: { status: 'idle', sections: [], error: '' }, // idle|loading|ready|error
  historyModal: false,
```

② `ws.js`:

- report_summary 分支改为:

```js
    case 'report_summary':
      store.summaries[event.kind] = event
      // 报告生成即后台预取历史关联(知识库串行两问较慢,与展示并行;vendor 会话级缓存去重)
      store.historyRelation = { status: 'loading', sections: [], error: '' }
      send({ type: 'history_relation' })
      break
```

- 新事件分支(history_relation,放 replay_compare 之前):

```js
    case 'history_relation':
      store.historyRelation = event.error
        ? { status: 'error', sections: [], error: event.error }
        : { status: 'ready', sections: event.sections || [], error: '' }
      break
```

- run_state 的 realtime 分支内(清空摘要卡处)加:

```js
        store.historyRelation = { status: 'idle', sections: [], error: '' }
```

- [ ] **Step 3: SummaryCard 加「历史关联」按钮**

`ReportViewer.vue` SummaryCard 的 btn 块(87-92)改为双按钮:

```js
      const btn = h('div', { class: 'px-3 pb-2.5 mt-auto flex gap-2' }, [
        h('button', {
          class: `flex-1 text-[11px] font-bold py-1 rounded border ${a.btn}`,
          onClick: openReport,
        }, '查看报告'),
        h('button', {
          class: 'flex-1 text-[11px] font-bold py-1 rounded border bg-violet-500/20 text-violet-200 border-violet-400/50 hover:bg-violet-400/30',
          onClick: () => { store.historyModal = true },
        }, '历史关联'),
      ])
```

- [ ] **Step 4: HistoryRelationModal.vue**

新建 `frontend/src/components/HistoryRelationModal.vue`:

```vue
<script setup>
import { store } from '../store'

function close() {
  store.historyModal = false
}
</script>

<template>
  <div
    v-if="store.historyModal"
    class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center pointer-events-auto"
    @click.self="close"
  >
    <div
      class="glass w-full max-w-2xl max-h-[70vh] rounded-xl flex flex-col overflow-hidden mx-4"
      style="box-shadow: 0 0 50px rgba(167,139,250,.25)"
    >
      <div class="flex items-center justify-between px-4 py-2.5 bg-violet-500/10 border-b border-violet-400/30 shrink-0">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-violet-300 animate-pulse"></span>
          <span class="text-violet-200 text-sm font-bold">历史关联(故障知识库)</span>
        </div>
        <button @click="close" class="text-slate-400 hover:text-red-300 text-lg leading-none px-1">×</button>
      </div>

      <div class="flex-1 overflow-y-auto px-5 py-4 text-[12px] text-slate-200 leading-relaxed">
        <div v-if="store.historyRelation.status === 'loading'" class="text-slate-500 italic text-center py-8">
          知识库查询中,请稍候……
        </div>
        <div v-else-if="store.historyRelation.status === 'error'" class="text-amber-300/90 text-center py-8">
          知识库服务未启动或查询失败。<br/>
          <span class="text-slate-500 text-[11px]">请确认 fault-knowledge-base 已启动(端口 8503);未启动不影响诊断功能。</span>
        </div>
        <div v-else-if="store.historyRelation.status === 'idle'" class="text-slate-500 italic text-center py-8">
          暂无关联数据(报告生成后自动查询)
        </div>
        <template v-else>
          <div v-for="(s, i) in store.historyRelation.sections" :key="i" class="mb-4">
            <div class="text-violet-300 text-xs font-bold mb-1">{{ s.title }}</div>
            <div class="whitespace-pre-wrap text-slate-300">{{ s.answer }}</div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 5: App.vue 挂载弹窗**

import 区加 `import HistoryRelationModal from './components/HistoryRelationModal.vue'`;模板中 `<ReportModal />` 挂载处之后加 `<HistoryRelationModal />`。

- [ ] **Step 6: 构建验证**

```bash
cd frontend
npm run build
```

- [ ] **Step 7: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/src/App.vue frontend/src/three/CommandRoom.js frontend/src/components/EventStream.vue frontend/src/components/AgentSessionModal.vue frontend/src/components/ChatModal.vue frontend/src/store.js frontend/src/ws.js frontend/src/components/ReportViewer.vue frontend/src/components/HistoryRelationModal.vue
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): 微气象专家替换鸟害+摘要卡历史关联按钮与知识库弹窗"
```

---

### Task 7: 全量回归 + 终审 + 实测核对清单

**Files:** 无(纯验证)

**Interfaces:**
- Consumes: Task 1-6 全部完成
- Produces: 无

- [ ] **Step 1: vendor 全量**

```bash
cd vendor/diagnosis-agent
.venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_diagnose_flow.py
```

预期:全部 PASS(372 + 新增)。

- [ ] **Step 2: backend 全量**

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

预期:85 + 新增全 PASS。

- [ ] **Step 3: 前端构建**

```bash
cd frontend && npm run build 2>&1 | tail -3
```

- [ ] **Step 4: 实测核对(记录交用户)**

1. `./dev.sh restart` 后 mock(8000)/微气象 MCP(8005) 起来,鸟害(8004)不再启动
2. 实时诊断:报告区逐字流式;四智能体为雷电/覆冰/风偏/微气象;微气象有真实输出
3. 报告生成后摘要卡出现「历史关联」按钮 → 弹窗(KB 未启动时显示降级提示)
4. 复盘:流程/确认/比对不变,报告同样流式
5. HUD 策略卡权重标签含微气象、无鸟害

---

## Self-Review 记录

- Spec 覆盖:§1 mock→Task 1;§2 工具层→Task 2;§3 流式→Task 3(vendor)+Task 5①(backend 透传;前端零改动已在 Task 6 无 report 渲染改动,符合);§4 知识库→Task 4(vendor)+Task 5③④(backend)+Task 6 Step 2-5(frontend);§5 专家阵容→Task 5②+Task 6 Step 1;dev.sh→Task 5⑤;测试→各 Task+Task 7;「不做的事」→无任务,符合
- 占位符:全部合并代码完整给出;上游原样文件用精确 `git show origin/mcp_version:<path>` 命令(内容确定,非占位);三处标注"以代码事实为准"(ToolRegistry 签名/FaultContext 必填字段/session.line_name)均给出验证方法与兜底语义
- 类型一致:report_chunk payload `{content}` 与 backend content 分支读取 `payload.get("content")` 一致;history_relation 后端广播 {sections}|{error} 与前端 ws.js 消费一致;finalize_response 保留本地 _split_conclusion(上游无此逻辑,未盲抄上游 finalize)
- 既有测试兼容:DEFAULT_WEIGHTS/AGENTS 变更可能影响断言旧阵容的既有测试,已在 Task 2/5 的回归步注明修正原则(按新阵容同步,report 说明)
- 铁律核查:diagnose.py 仅改 compose 调用段与新增省份电压块;复盘(recheck/重跑)共用 DiagnoseCommand 但业务流程未动;报告文本本体不含知识库内容;比对用 complete 清洗后全文
