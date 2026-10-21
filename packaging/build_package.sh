#!/usr/bin/env bash
# 构建内网一键安装包：pld-command-center-<日期>.tar.gz
# 内容：backend(源码) + frontend/dist(预构建) + pld(PLD平台源码) + wheels(离线依赖) + 安装/启停脚本
# 用法：packaging/build_package.sh          完整构建（含前端构建与 wheel 下载）
#       SKIP_WHEELS=1 packaging/build_package.sh   跳过 wheel 下载（复用已有 wheels）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUT="$ROOT/dist-packages"
PKG="$OUT/pld-command-center"
DATE="$(date +%Y%m%d)"
TARBALL="$OUT/pld-command-center-$DATE.tar.gz"

echo "== 1/5 构建前端 =="
( cd frontend && npm run build )

echo "== 2/5 组装目录 =="
rm -rf "$PKG"
mkdir -p "$PKG/backend/data" "$PKG/wheels/backend" "$PKG/wheels/pld"

# 后端源码（不含 venv/测试/运行数据）
rsync -a \
    --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
    --exclude 'tests' --exclude 'data' --exclude '.DS_Store' \
    backend/ "$PKG/backend/"
mkdir -p "$PKG/backend/data"

# 前端构建产物
mkdir -p "$PKG/frontend"
rsync -a frontend/dist "$PKG/frontend/"

# PLD 平台源码（不含 venv/日志/其自带前端与文档）
rsync -a \
    --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
    --exclude '.git' --exclude '.github' --exclude '.superpowers' \
    --exclude '.coverage' --exclude '.dockerignore' --exclude '.env*' \
    --exclude 'logs' --exclude 'logs_*.log' --exclude 'server.log' --exclude 'server.pid' \
    --exclude '*.egg-info' --exclude 'node_modules' \
    --exclude 'web' --exclude 'landing-page' --exclude 'docs' --exclude 'tests' \
    --exclude 'EOF' --exclude 'temp_*' --exclude 'task.md' --exclude '修改.md' \
    --exclude 'requirements.md' --exclude 'generate_doc.js' --exclude 'package.json' \
    --exclude 'Dockerfile' --exclude 'docker-compose.yml' --exclude 'start.sh' \
    --exclude '.DS_Store' --exclude '/PLDiagnosis_*.docx' \
    --exclude 'config/config_*.yaml' --exclude 'config/config-*.yaml' --exclude 'config/config1.yaml' \
    vendor/diagnosis-agent/ "$PKG/pld/"

# 安装/启停脚本与说明
cp packaging/templates/install.sh packaging/templates/start.sh \
   packaging/templates/stop.sh packaging/templates/status.sh \
   packaging/templates/config.env packaging/templates/README.md \
   packaging/templates/部署说明.md "$PKG/"
chmod +x "$PKG"/*.sh

echo "== 2.5/5 内置 LibreOffice 便携版（Word/WPS 预览用，解压即用免 root）=="
LO_TAR="$(ls "$OUT/libreoffice-cache"/LibreOffice_*_Linux_x86-64_deb.tar.gz 2>/dev/null | head -1)"
if [ -z "$LO_TAR" ]; then
    yellow() { printf "\033[33m%b\033[0m" "$1"; }
    yellow "  ! 未找到 dist-packages/libreoffice-cache/LibreOffice_*_deb.tar.gz，跳过（Word/WPS 预览将依赖服务器系统安装）\n"
else
    LO_TMP="$OUT/.lo-extract"
    rm -rf "$LO_TMP"; mkdir -p "$LO_TMP" "$PKG/libreoffice"
    tar xzf "$LO_TAR" -C "$LO_TMP"
    for deb in "$LO_TMP"/*/DEBS/*.deb; do
        # .deb = ar 归档(data.tar.* 为内容)；逐层解包成便携目录树
        d="$LO_TMP/work"; rm -rf "$d"; mkdir -p "$d"
        ( cd "$d" && ar x "$deb" )
        data="$(ls "$d"/data.tar.* 2>/dev/null | head -1)"
        [ -n "$data" ] && tar xf "$data" -C "$PKG/libreoffice"
    done
    rm -rf "$LO_TMP"
    chmod +x "$PKG"/libreoffice/opt/libreoffice*/program/soffice 2>/dev/null || true
    echo "  内置完成：$(ls -d "$PKG"/libreoffice/opt/libreoffice*/ 2>/dev/null | head -1)"
fi

echo "== 3/5 下载离线 wheel（Linux x86_64 / CPython 3.10）=="
CACHE="$OUT/wheels-cache"
PLATFORMS=( --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 )
mkdir -p "$CACHE/backend" "$CACHE/pld"
if [ "${SKIP_WHEELS:-0}" = "1" ] && [ -n "$(ls -A "$CACHE/backend" 2>/dev/null)" ]; then
    echo "  SKIP_WHEELS=1，复用缓存 $CACHE"
else
    PIP=( "$ROOT/backend/.venv/bin/python" -m pip )
    "${PIP[@]}" download -r backend/requirements.txt -d "$CACHE/backend" \
        --only-binary=:all: "${PLATFORMS[@]}" --python-version 3.10 --quiet
    "${PIP[@]}" download -r "$PKG/pld/requirements.txt" -d "$CACHE/pld" \
        --only-binary=:all: "${PLATFORMS[@]}" --python-version 3.10 --quiet
fi

# 补全环境标记依赖：pip download 按本机 Python(3.11) 评估 marker，会漏掉
# python_version<"3.11" 的条件依赖（如 anyio→exceptiongroup），此处按目标环境补全
echo "== 3.5/5 校验并补全依赖闭包 =="
for app in backend pld; do
    "$ROOT/backend/.venv/bin/python" "$ROOT/packaging/fill_wheelhouse.py" "$CACHE/$app" \
        --only-binary=:all: "${PLATFORMS[@]}" --python-version 3.10
done
rsync -a "$CACHE/backend/" "$PKG/wheels/backend/"
rsync -a "$CACHE/pld/" "$PKG/wheels/pld/"
echo "  backend wheels: $(ls "$PKG/wheels/backend" | wc -l | tr -d ' ') 个"
echo "  pld wheels:     $(ls "$PKG/wheels/pld" | wc -l | tr -d ' ') 个"

echo "== 4/5 打包 =="
mkdir -p "$OUT"
rm -f "$TARBALL"
( cd "$OUT" && tar czf "$TARBALL" pld-command-center )

echo "== 5/5 校验 =="
ls -lh "$TARBALL"
shasum -a 256 "$TARBALL" | awk '{print "sha256: "$1}'
echo ""
echo "完成：$TARBALL"
