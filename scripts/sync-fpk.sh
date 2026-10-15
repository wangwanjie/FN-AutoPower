#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT_DIR/fpk/app/AutoPower"
UI_DIR="$ROOT_DIR/fpk/app/ui"

mkdir -p "$APP_DIR/src"
rm -rf "$APP_DIR/web" "$APP_DIR/src/__pycache__"
cp "$ROOT_DIR/src/autopower_core.py" "$APP_DIR/src/autopower_core.py"
cp "$ROOT_DIR/src/autopower_server.py" "$APP_DIR/src/autopower_server.py"

# 同源 CGI 入口直接从 ui 目录返回静态文件（与 wol/xunlei 同款），
# 因此把前端静态文件同步到 ui 目录，并确保 index.cgi 可执行。
cp "$ROOT_DIR/web/index.html" "$UI_DIR/index.html"
cp "$ROOT_DIR/web/styles.css" "$UI_DIR/styles.css"
cp "$ROOT_DIR/web/app.js" "$UI_DIR/app.js"
chmod +x "$UI_DIR/index.cgi"
find "$ROOT_DIR/fpk" \( -name .DS_Store -o -name __pycache__ \) -prune -exec rm -rf {} +

chmod +x "$ROOT_DIR/fpk/cmd/main"
chmod +x "$ROOT_DIR/fpk/cmd/"*

echo "Synced AutoPower app files into fpk/app/AutoPower/src and fpk/app/ui"
