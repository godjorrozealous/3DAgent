#!/usr/bin/env bash
# 一键安装：创建虚拟环境并离线安装 Python 依赖（wheels 已内置，无需联网）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "== 1/4 检查 Python 3.10 =="
PY="$(command -v python3.10 || true)"
if [ -z "$PY" ]; then
    PY="$(command -v python3 || true)"
    if [ -z "$PY" ]; then
        echo "错误：未找到 python3.10。请先安装 Python 3.10（PLD 平台要求 >= 3.10，离线 wheel 按 3.10 构建）。"
        exit 1
    fi
    if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 10) else 1)'; then
        echo "错误：$PY 版本为 $("$PY" -V 2>&1)，离线依赖包要求 Python 3.10。"
        echo "请安装 Python 3.10，或让 python3.10 命令可用后重试。"
        exit 1
    fi
fi
echo "  使用 $PY ($("$PY" -V 2>&1))"

echo "== 2/4 创建虚拟环境并离线安装依赖 =="
for app in backend pld; do
    if [ ! -x "venvs/$app/bin/python" ]; then
        echo "  创建 venvs/$app"
        if ! "$PY" -m venv "venvs/$app"; then
            echo "错误：创建虚拟环境失败。Ubuntu/Debian 请先安装 python3.10-venv：apt install python3.10-venv"
            exit 1
        fi
    fi
    echo "  安装 $app 依赖（离线，wheels/$app）"
    "venvs/$app/bin/pip" install --no-index --find-links="wheels/$app" -r "$app/requirements.txt"
done

echo "== 3/4 初始化运行目录 =="
mkdir -p logs backend/data
chmod +x start.sh stop.sh status.sh 2>/dev/null || true

echo "== 4/4 校验安装完整性 =="
# 防「异常中断导致包写了一半但记录显示已装」：pip check 核依赖，import 核文件本身
FAILED=0
for app in backend pld; do
    if ! "venvs/$app/bin/pip" check --quiet; then
        echo "  ✗ $app 依赖完整性校验未通过"
        FAILED=1
    fi
done
if ! "venvs/backend/bin/python" -c \
    "import fastapi, uvicorn, httpx, starlette, pydantic, anyio, exceptiongroup, multipart" 2>/dev/null; then
    echo "  ✗ backend 关键模块导入失败"
    FAILED=1
fi
if ! "venvs/pld/bin/python" -c \
    "import flask, pydantic, yaml, jinja2, docx, httpx, openai, anyio, exceptiongroup, lxml.etree, jiter, markupsafe" 2>/dev/null; then
    echo "  ✗ pld 关键模块导入失败"
    FAILED=1
fi
if [ "$FAILED" = "1" ]; then
    echo ""
    echo "安装未通过校验。请执行以下命令彻底重建环境后重试："
    echo "  rm -rf venvs && ./install.sh"
    exit 1
fi
echo "  ✓ 依赖完整、关键模块均可正常导入"

# Word/WPS 在线预览依赖 LibreOffice：安装包已内置便携版，此处仅提示状态
if ls libreoffice/opt/libreoffice*/program/soffice >/dev/null 2>&1; then
    echo "  ✓ 内置 LibreOffice 便携版就绪（Word/WPS 可在线预览）"
elif command -v soffice >/dev/null 2>&1; then
    echo "  ✓ 检测到系统 LibreOffice（Word/WPS 可在线预览）"
else
    echo ""
    echo "提示：未检测到 LibreOffice。Word/WPS 文件将无法在线预览（PDF 与诊断功能不受影响）。"
fi

echo ""
echo "安装完成。后续步骤："
echo "  1. 按需编辑 config.env（端口一般无需改动）"
echo "  2. 配置 LLM：编辑 pld/config/config.yaml 的 llm 节（base_url / model / api_key）"
echo "  3. 确认 MCP 服务已在本机运行：8000(数据平台) 8001(雷电) 8002(覆冰) 8003(风偏) 8004(鸟害) 8005(微气象)"
echo "  4. 启动：./start.sh，浏览器访问 http://<服务器IP>:8100"
