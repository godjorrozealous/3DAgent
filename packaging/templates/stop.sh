#!/usr/bin/env bash
# 停止 PLD 平台与本项目后端（不会动 8000-8005 的外部服务）
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[ -f config.env ] && . ./config.env
FLASK_PORT="${FLASK_PORT:-6000}"
BACKEND_PORT="${BACKEND_PORT:-8100}"
PID_DIR="$ROOT/logs/pids"

port_free() { ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

kill_port() {  # 清理占用端口的残留进程
    local port="$1" pids=""
    if command -v lsof >/dev/null 2>&1; then
        pids="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    elif command -v fuser >/dev/null 2>&1; then
        pids="$(fuser "$port"/tcp 2>/dev/null || true)"
    fi
    if [ -n "$pids" ]; then
        echo $pids | xargs kill 2>/dev/null
        sleep 1
        echo $pids | xargs kill -9 2>/dev/null
        echo "  清理端口 $port 残留进程"
    fi
}

stop_svc() {  # $1=name $2=port
    local name="$1" port="$2" pidfile="$PID_DIR/$1.pid"
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
    port_free "$port" || kill_port "$port"
}

echo "== 停止服务 =="
stop_svc backend "$BACKEND_PORT"
stop_svc pld "$FLASK_PORT"
echo "已停止（8000-8005 外部服务不受影响）。"
