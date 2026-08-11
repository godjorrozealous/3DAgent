# 输电线路智能诊断全息指挥室

电力线路跳闸诊断多智能体系统：Vue3 + Three.js 3D 指挥室前端，FastAPI 后端编排，对接 PLDiagnosis 诊断平台。

## 架构

```
浏览器 (5173) ──► 前端 Vite dev server
                     │ /ws、/api 代理
                     ▼
              后端 FastAPI (8100) ──► PLDiagnosis Flask 平台 (5000)
                                         │
                                         ├─► LLM（OpenAI 兼容 API）
                                         └─► MCP 诊断服务 ×5
                                             雷电 8001 / 覆冰 8002 / 风偏 8003 / 鸟害 8004 / 气象 8005
```

- **前端** `frontend/`：Vue3 + Three.js + Tailwind，3D 指挥室、实时诊断 HUD、复盘交互、历史结果视图
- **后端** `backend/`：FastAPI + WebSocket，诊断编排、排队、复盘流程、策略生成（skill 构建）、结果持久化（`backend/data/diagnosis_records.json`）
- **PLDiagnosis 平台**：外部依赖，仓库 [Cluade_PLDiagonsis-mcp-version](https://github.com/y1018429125-ship-it/Cluade_PLDiagonsis-mcp-version)（`mcp_version` 分支），需运行在 `http://localhost:5000`

## 端口总览

| 端口 | 服务 | 说明 |
|---|---|---|
| 5173 | 本项目前端 | 用户入口，浏览器访问 |
| 8100 | 本项目后端 | WebSocket `/ws` + `/api` |
| 5000 | PLDiagnosis 平台 | 诊断执行引擎（外部依赖） |
| 8000 | mock 数据平台 | 雷电诊断的数据源（vendor/mock-lightning） |
| 8001–8005 | MCP 诊断服务 | PLDiagnosis 的子服务（雷电/覆冰/风偏/鸟害/气象） |

## 一键启动 / 停止 / 重启（推荐）

项目根目录的 `dev.sh` 统一管理全部 9 个服务（mock 8000、MCP×5 8001–8005、PLD 5000、后端 8100、前端 5173）：

```bash
./dev.sh start     # 启动全部服务
./dev.sh stop      # 停止全部服务
./dev.sh restart   # 一键重启（改了代码用这个）
./dev.sh status    # 查看各服务状态
```

- 浏览器入口：**http://localhost:5173**（重启后若页面已打开，请强刷 Cmd+Shift+R）
- macOS 也可以在 Finder 里**双击 `restart.command`** 一键重启
- 各服务日志：`logs/<服务名>.log`；PID 文件：`logs/pids/`
- `stop` 会同时清理占用端口的残留进程（例如历史上手动启动的旧进程），避免「改了代码但旧进程还在跑」
- 前提：依赖已安装（见下方手动启动各节的 install 步骤）；MCP/PLD 使用 `vendor/diagnosis-agent/.venv`，后端/mock 使用 `backend/.venv`

## 启动顺序（手动，共 3 步）

<details>
<summary>不想用 dev.sh 时，按以下步骤逐个手动启动（点击展开）</summary>

### 第 1 步：启动 PLDiagnosis 平台（端口 5000 + 8001–8005）

```bash
git clone https://github.com/y1018429125-ship-it/Cluade_PLDiagonsis-mcp-version.git
cd Cluade_PLDiagonsis-mcp-version
git checkout mcp_version
```

**配置 LLM（必填，二选一）：**

方式一 —— 环境变量：

```bash
export LLM_BASE_URL="https://api.openai.com/v1"   # 任意 OpenAI 兼容 API
export LLM_MODEL="gpt-4o"
export LLM_API_KEY="your-api-key-here"
```

方式二 —— 编辑 `config/config.yaml` 的 `llm` 节（`base_url` / `model` / `api_key`）。

**启动（二选一）：**

开发模式（本地进程）：

```bash
./start.sh dev
```

脚本会自动：启动 5 个 MCP 服务（8001–8005）→ 安装 Python 依赖（`pip3 install -e .`，要求 Python ≥ 3.10）→ 构建其自带前端 → 启动 Flask 服务于 5000。按 `Ctrl+C` 一并停止全部子服务。

Docker 模式：

```bash
# LLM 配置通过环境变量传入（见上），或写入 .env
./start.sh docker        # 等价于 docker-compose up --build
```

**验证：**

```bash
curl http://localhost:5000/api/health
```

### 第 1.5 步：启动 mock 数据平台（端口 8000，雷电诊断依赖）

雷电诊断工具（lightning-service）会向 `http://localhost:8000/tgyApiservice/*` 请求真实故障数据。本地没有数据平台时，用项目内置的 mock：

```bash
cd vendor/mock-lightning/src
python -m uvicorn app:app --host 0.0.0.0 --port 8000   # 需 fastapi/uvicorn，可复用 backend/.venv
```

**验证：**

```bash
curl -X POST http://localhost:8000/tgyApiservice/userservice/login
```

> mock 仅内置 **2025-05-08** 的跳闸数据（±800kV 雅湖线、1000kV 荆潇Ⅰ线）。测试时线路文本须使用该日期，如「±800kV雅湖线 2025-05-08 19:46:30 跳闸」，否则雷电工具返回参数错误/无数据。

### 第 2 步：启动本项目后端（端口 8100）

```bash
cd backend
pip install -r requirements.txt    # 建议先建虚拟环境：python3 -m venv .venv && source .venv/bin/activate
python main.py                     # uvicorn 带 reload，监听 0.0.0.0:8100
```

**验证：**

```bash
curl http://localhost:8100/api/health
```

### 第 3 步：启动本项目前端（端口 5173）

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 **http://localhost:5173**。

> 前端 `/ws`、`/api` 由 Vite 代理到 8100（见 `frontend/vite.config.js`），后端再转发到 PLDiagnosis 的 5000（见 `backend/pld_client.py` 的 `PLD_BASE`）。如需修改平台地址，改这两处。

</details>

## 生产构建（前端）

```bash
cd frontend
npm run build        # 产物在 frontend/dist/
npm run preview      # 本地预览构建产物
```

## 运行后端测试

```bash
cd backend
python -m pytest tests/ -q
```

（测试通过 conftest 自动隔离 `backend/data/`，不会污染真实诊断记录。）

## 主要功能入口

| 功能 | 位置 |
|---|---|
| 发起诊断 | 顶栏输入线路文本 →「开始诊断」（运行中变为「加入诊断队列」） |
| 复盘 | 实时诊断完成后顶栏「复盘」按钮，逐智能体确认 + 报告异议（报告问题/诊断问题） |
| 历史结果 | 顶栏「🗂 历史结果」切换视图，支持关键字搜索 |
| 保存策略 | 诊断后可保存为完整 skill（权重+排除+异议规则），POST 到 PLD `/api/skills` 并设为全局默认 |

## 常见问题

- **改了代码但没生效**：多半是旧进程没退（后端无 --reload 的手动进程、PLD 是 Flask 需重启）。直接 `./dev.sh restart`，它会连端口残留进程一起清理；然后浏览器强刷 Cmd+Shift+R。
- **诊断无响应 / 工具全部失败**：`./dev.sh status` 检查 PLDiagnosis（5000）与 5 个 MCP 服务（8001–8005）是否都在运行；看 `logs/pld.log` 与 `logs/mcp-*.log`。
- **LLM 报错**：确认 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` 或 `config/config.yaml` 的 `llm` 节配置正确且网络可达（日志见 `logs/pld.log`）。
- **端口冲突**：PLDiagnosis 用 `FLASK_PORT` 环境变量改端口；本项目后端改 `backend/main.py` 末尾的 `port=8100`；前端改 `frontend/vite.config.js` 的 `server.port`，三者需同步改代理指向（用了 dev.sh 也要同步改脚本里的端口）。

## 目录说明

```
backend/
  main.py              FastAPI 入口（/ws WebSocket、/api/health、模板上传代理）
  agent_manager.py     诊断编排核心（实时/复盘/队列/异议/策略保存）
  pld_client.py        PLDiagnosis 平台 HTTP/SSE 客户端
  strategy_builder.py  确定性构建自包含 skill Markdown
  records.py           诊断结果集 JSON 持久化
  skills/              基线 skill（comprehensive_diagnosis.md）
  tests/               pytest 测试
frontend/
  src/three/           Three.js 3D 指挥室
  src/components/      Vue 组件（顶栏、复盘弹窗、历史视图等）
  src/store.js         全局响应式状态
  src/ws.js            WebSocket 客户端
```
