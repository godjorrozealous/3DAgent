# 输电线路智能诊断全息指挥室 — 内网部署包

一键部署：PLD 诊断平台（6000）+ 本项目后端（8100，同时托管前端页面）。
Python 依赖已内置离线 wheel（Linux x86_64 / Python 3.10），安装过程无需联网。

## 前置条件

| 条件 | 说明 |
|---|---|
| 操作系统 | Linux x86_64 |
| Python | 3.10（`python3.10` 或 `python3` 指向 3.10；Ubuntu/Debian 需 `python3.10-venv`） |
| 外部服务 | 以下服务已在本机运行（本包不启动它们，只做连通性检查）：<br>8000 数据平台(tgyApiservice)、8001 雷电、8002 覆冰、8003 风偏、8004 鸟害、8005 微气象 |

## 依赖关系说明（为什么同机即可）

整条链路全部走 `localhost`，只要服务在同一台服务器上启动即可，无需任何额外配置：

```
浏览器 ──► 8100 本项目后端(托管前端) ──► 6000 PLD 平台（PLD_BASE，见 config.env）
                                            │
                                            ├─► LLM（pld/config/config.yaml 的 llm 节）
                                            └─► MCP 服务 localhost:8001-8005
                                                （pld/config/tools/*.yaml 中的 url）
                                                   雷电服务内部再取数 localhost:8000
                                            （pld/mcp-services/lightning-service/config.py 的 BASE_URL）
```

- 若某个 MCP 服务不在本机，编辑 `pld/config/tools/<服务>.yaml` 里的 `url` 为实际地址即可；
- 若数据平台(8000)不在本机，编辑 `pld/mcp-services/lightning-service/config.py` 的 `BASE_URL`；
- 若 PLD 平台不在本机，改 `config.env` 的 `PLD_BASE`。

## 安装与启动

```bash
tar xzf pld-command-center-*.tar.gz
cd pld-command-center
./install.sh        # 创建虚拟环境 + 离线安装依赖（约 1-2 分钟）
./start.sh          # 启动 PLD(6000) + 后端(8100)
```

浏览器访问：**http://&lt;服务器IP&gt;:8100**

其他命令：`./status.sh` 查看状态；`./stop.sh` 停止（不影响 8000-8005 外部服务）。

## LLM 配置（必填）

编辑 `pld/config/config.yaml` 的 `llm` 节：

```yaml
llm:
  provider: openai
  model: <模型名>
  api_key: <密钥>
  base_url: <OpenAI 兼容 API 地址>
```

## 端口总览

| 端口 | 服务 | 由谁启动 |
|---|---|---|
| 8100 | 本项目后端 + 前端页面（用户入口） | 本包 |
| 6000 | PLD 诊断平台（避开内网 5000 占用） | 本包 |
| 8000 | 数据平台 tgyApiservice | 外部环境 |
| 8001–8005 | MCP 诊断服务 | 外部环境 |

## 日志与数据

- 日志：`logs/pld.log`、`logs/backend.log`
- 诊断记录：`backend/data/diagnosis_records.json`
- PLD 会话/策略数据：`pld/data/`、`pld/skills/`

## 常见问题

- **install.sh 报 Python 版本错误**：离线 wheel 按 CPython 3.10 构建，请安装 3.10 后重试。
- **诊断工具全部失败**：`./status.sh` 查看 8000-8005 是否可达；看 `logs/pld.log`。
- **8100/6000 被占用**：改 `config.env` 的 `BACKEND_PORT` / `FLASK_PORT`（两者联动，PLD_BASE 默认跟随 FLASK_PORT），然后 `./stop.sh && ./start.sh`。
