#!/usr/bin/env bash
# 输电线路智能诊断全息指挥室 — 一键启动/停止/重启（macOS）
#
# 用法：
#   ./dev.sh start     启动全部服务
#   ./dev.sh stop      停止全部服务
#   ./dev.sh restart   一键重启全部服务（改代码后用这个）
#   ./dev.sh status    查看各服务运行状态
#
# 服务与端口：
#   mock 数据平台   8000   vendor/mock-lightning（雷电诊断数据源）
#   MCP 诊断服务×5  8001-8005  vendor/diagnosis-agent/mcp-services（含默认激活）
#   PLD 诊断平台    5000   vendor/diagnosis-agent（Flask）
#   本项目后端      8100   backend（FastAPI + WebSocket，--reload）
#   本项目前端      5173   frontend（Vite，用户入口 http://localhost:5173）
#
# 日志：logs/<服务名>.log    PID：logs/pids/<服务名>.pid

set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

LOG_DIR="$ROOT/logs"
PID_DIR="$LOG_DIR/pids"
mkdir -p "$PID_DIR"

BACKEND_PY="$ROOT/backend/.venv/bin/python"
PLD_DIR="$ROOT/vendor/diagnosis-agent"
PLD_PY="$PLD_DIR/.venv/bin/python"
MCP_SERVICES="lightning icing wind bird weather"

mcp_port() {  # lightning→8001 … weather→8005
    case "$1" in
        lightning) echo 8001 ;; icing) echo 8002 ;; wind) echo 8003 ;;
        bird)      echo 8004 ;; weather) echo 8005 ;;
    esac
}

# MCP 服务与 PLD 共用一个解释器：vendor venv 内 fastapi/uvicorn 依赖齐全
# （系统 /usr/bin/python3 是 3.9、homebrew python3.11 未装 fastapi，均不可用）
PY3="$PLD_PY"

# 默认激活：session 固化权重时前端提示需手动激活的策略名（对应 active_weights.json）
export PLD_ACTIVE_SKILL="${PLD_ACTIVE_SKILL:-comprehensive_diagnosis}"

red()   { printf "\033[31m%b\033[0m" "$1"; }
green() { printf "\033[32m%b\033[0m" "$1"; }
yellow(){ printf "\033[33m%b\033[0m" "$1"; }

is_running() {  # $1=name
    local pidfile="$PID_DIR/$1.pid"
    [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

port_free() {  # $1=port
    ! lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_port() {  # $1=port $2=name $3=timeout(秒)
    local i=0
    while [ "$i" -lt "$3" ]; do
        if ! port_free "$1"; then return 0; fi
        sleep 1; i=$((i+1))
    done
    yellow "警告：$2 端口 $1 ${3}s 内未就绪，详见 logs/$2.log\n"
    return 1
}

start_svc() {  # $1=name $2=port $3=工作目录 $4...=命令
    local name="$1" port="$2" workdir="$3"; shift 3
    if is_running "$name"; then
        echo "  $(green '✓') $name 已在运行 (pid $(cat "$PID_DIR/$name.pid"))"
        return 0
    fi
    if [ "$port" != "-" ] && ! port_free "$port"; then
        yellow "  ! 端口 $port 被占用（非本脚本管理的进程），跳过 $name。先 ./dev.sh stop 或手动释放端口。\n"
        return 1
    fi
    ( cd "$workdir" && exec nohup "$@" > "$LOG_DIR/$name.log" 2>&1 ) &
    local pid=$!
    echo "$pid" > "$PID_DIR/$name.pid"
    disown "$pid" 2>/dev/null
    echo "  启动 $name (pid $pid) → logs/$name.log"
}

stop_svc() {  # $1=name $2=端口（用于清理脚本外的残留进程，"-" 表示不按端口清理）
    local name="$1" port="${2:-}"
    local pidfile="$PID_DIR/$name.pid"
    if [ -f "$pidfile" ]; then
        local pid; pid="$(cat "$pidfile")"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            for _ in 1 2 3 4 5; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
            kill -9 "$pid" 2>/dev/null
        fi
        rm -f "$pidfile"
        echo "  停止 $name"
    fi
    # 清理占用端口的残留进程（如历史上手动启动、无 --reload 的旧进程）
    if [ -n "$port" ] && [ "$port" != "-" ] && ! port_free "$port"; then
        local pids; pids="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
        if [ -n "$pids" ]; then
            echo "$pids" | xargs kill 2>/dev/null
            sleep 1
            echo "$pids" | xargs kill -9 2>/dev/null
            echo "  清理端口 $port 残留进程 ($name)"
        fi
    fi
}

do_start() {
    echo "== 1/5 mock 数据平台 (8000) =="
    start_svc mock-lightning 8000 "$ROOT/vendor/mock-lightning/src" \
        "$BACKEND_PY" -m uvicorn app:app --host 0.0.0.0 --port 8000
    wait_port 8000 mock-lightning 15

    echo "== 2/5 MCP 诊断服务 (8001-8005) =="
    for svc in $MCP_SERVICES; do
        start_svc "mcp-$svc" "$(mcp_port "$svc")" "$PLD_DIR" "$PY3" "mcp-services/$svc-service/main.py"
    done
    sleep 2

    echo "== 3/5 PLD 诊断平台 (5000) =="
    start_svc pld 5000 "$PLD_DIR" "$PLD_PY" web_app.py
    wait_port 5000 pld 20

    echo "== 4/5 本项目后端 (8100) =="
    start_svc backend 8100 "$ROOT/backend" "$BACKEND_PY" main.py
    wait_port 8100 backend 20

    echo "== 5/5 本项目前端 (5173) =="
    start_svc frontend 5173 "$ROOT/frontend" npm run dev
    wait_port 5173 frontend 30

    echo ""
    green "全部启动完成。入口：http://localhost:5173\n"
    yellow "提示：前端是 dev server，若页面已打开请强刷（Cmd+Shift+R）。\n"
}

do_stop() {
    echo "== 停止全部服务 =="
    stop_svc frontend 5173
    stop_svc backend 8100
    stop_svc pld 5000
    for svc in $MCP_SERVICES; do stop_svc "mcp-$svc" "$(mcp_port "$svc")"; done
    stop_svc mock-lightning 8000
    green "已停止。\n"
}

do_status() {
    printf "%-16s %-8s %s\n" "服务" "端口" "状态"
    status_line() {  # $1=name $2=port
        local st
        if is_running "$1"; then st="$(green '运行中') (pid $(cat "$PID_DIR/$1.pid"))"
        elif [ "$2" != "-" ] && ! port_free "$2"; then st="$(yellow '端口被占用（非本脚本启动）')"
        else st="$(red '未启动')"; fi
        printf "%-16s %-8s %b\n" "$1" "$2" "$st"
    }
    status_line mock-lightning 8000
    for svc in $MCP_SERVICES; do status_line "mcp-$svc" "$(mcp_port "$svc")"; done
    status_line pld 5000
    status_line backend 8100
    status_line frontend 5173
}

case "${1:-}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; echo ""; do_start ;;
    status)  do_status ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
