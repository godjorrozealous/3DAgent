#!/usr/bin/env bash
# 一键启动：PLD 诊断平台(6000) + 本项目后端(8100，同时托管前端)
# MCP 诊断服务(8001-8005)与数据平台(8000)由外部环境提供，本脚本只做连通性检查。
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

[ -f config.env ] && . ./config.env
FLASK_PORT="${FLASK_PORT:-6000}"
PLD_BASE="${PLD_BASE:-http://localhost:$FLASK_PORT}"
BACKEND_PORT="${BACKEND_PORT:-8100}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
PLD_ACTIVE_SKILL="${PLD_ACTIVE_SKILL:-comprehensive_diagnosis}"
CHECK_PORTS="${CHECK_PORTS:-8000 8001 8002 8003 8004 8005}"
export FLASK_PORT PLD_BASE PLD_ACTIVE_SKILL

LOG_DIR="$ROOT/logs"; PID_DIR="$LOG_DIR/pids"
mkdir -p "$PID_DIR" "$ROOT/backend/data"

red()   { printf "\033[31m%b\033[0m" "$1"; }
green() { printf "\033[32m%b\033[0m" "$1"; }
yellow(){ printf "\033[33m%b\033[0m" "$1"; }

port_free() { ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

wait_port() {  # $1=port $2=name $3=timeout
    local i=0
    while [ "$i" -lt "$3" ]; do
        if ! port_free "$1"; then return 0; fi
        sleep 1; i=$((i+1))
    done
    yellow "警告：$2 端口 $1 ${3}s 内未就绪，详见 logs/$2.log\n"
    return 1
}

start_svc() {  # $1=name $2=port $3=workdir $4...=cmd
    local name="$1" port="$2" workdir="$3"; shift 3
    local pidfile="$PID_DIR/$name.pid"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        echo "  $(green '✓') $name 已在运行 (pid $(cat "$pidfile"))"
        return 0
    fi
    if ! port_free "$port"; then
        yellow "  ! 端口 $port 被占用（非本脚本管理的进程），跳过 $name。先 ./stop.sh 或手动释放端口。\n"
        return 1
    fi
    ( cd "$workdir" && exec nohup "$@" > "$LOG_DIR/$name.log" 2>&1 ) &
    local pid=$!
    echo "$pid" > "$pidfile"
    echo "  启动 $name (pid $pid) → logs/$name.log"
}

# ---- 前置检查 ----
if [ ! -x "$ROOT/venvs/pld/bin/python" ] || [ ! -x "$ROOT/venvs/backend/bin/python" ]; then
    red "尚未安装依赖，请先执行 ./install.sh\n"
    exit 1
fi

echo "== 外部服务连通性检查（MCP/数据平台，需同机已启动）=="
check_tcp() { (exec 3<>"/dev/tcp/127.0.0.1/$1" && exec 3>&- 3<&-) 2>/dev/null; }
for p in $CHECK_PORTS; do
    if check_tcp "$p"; then
        echo "  $(green '✓') 127.0.0.1:$p 可达"
    else
        yellow "  ! 127.0.0.1:$p 不可达 —— 对应诊断工具将调用失败（仅警告，不阻断启动）\n"
    fi
done

echo "== 1/2 PLD 诊断平台 ($FLASK_PORT) =="
start_svc pld "$FLASK_PORT" "$ROOT/pld" "$ROOT/venvs/pld/bin/python" web_app.py
wait_port "$FLASK_PORT" pld 20

echo "== 2/2 本项目后端+前端 ($BACKEND_PORT) =="
start_svc backend "$BACKEND_PORT" "$ROOT/backend" \
    "$ROOT/venvs/backend/bin/python" -m uvicorn main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT"
wait_port "$BACKEND_PORT" backend 20

echo ""
green "启动完成。浏览器入口：http://<服务器IP>:$BACKEND_PORT\n"
echo "日志：logs/pld.log、logs/backend.log；停止：./stop.sh；状态：./status.sh"
