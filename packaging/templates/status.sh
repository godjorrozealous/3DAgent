#!/usr/bin/env bash
# 查看各服务状态
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[ -f config.env ] && . ./config.env
FLASK_PORT="${FLASK_PORT:-6000}"
BACKEND_PORT="${BACKEND_PORT:-8100}"
CHECK_PORTS="${CHECK_PORTS:-8000 8001 8002 8003 8004 8005}"
PID_DIR="$ROOT/logs/pids"

red()   { printf "\033[31m%b\033[0m" "$1"; }
green() { printf "\033[32m%b\033[0m" "$1"; }
yellow(){ printf "\033[33m%b\033[0m" "$1"; }

port_free() { ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

line() {  # $1=name $2=port
    local st
    if [ -f "$PID_DIR/$1.pid" ] && kill -0 "$(cat "$PID_DIR/$1.pid")" 2>/dev/null; then
        st="$(green '运行中') (pid $(cat "$PID_DIR/$1.pid"))"
    elif ! port_free "$2"; then
        st="$(yellow '端口被占用（非本脚本启动）')"
    else
        st="$(red '未启动')"
    fi
    printf "%-14s %-8s %b\n" "$1" "$2" "$st"
}

printf "%-14s %-8s %s\n" "服务" "端口" "状态"
line pld "$FLASK_PORT"
line backend "$BACKEND_PORT"
echo "---- 外部服务（应已运行）----"
for p in $CHECK_PORTS; do
    if port_free "$p"; then
        printf "%-14s %-8s %b\n" "外部服务" "$p" "$(red '不可达')"
    else
        printf "%-14s %-8s %b\n" "外部服务" "$p" "$(green '可达')"
    fi
done
