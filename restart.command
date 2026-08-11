#!/usr/bin/env bash
# macOS Finder 双击入口：一键重启全部服务
cd "$(dirname "$0")"
./dev.sh restart
echo ""
read -r -p "按回车关闭窗口…"
