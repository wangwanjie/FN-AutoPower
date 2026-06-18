#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT_DIR/fpk/app/AutoPower"

mkdir -p "$APP_DIR/src" "$APP_DIR/web"
cp "$ROOT_DIR/src/autopower_core.py" "$APP_DIR/src/autopower_core.py"
cp "$ROOT_DIR/src/autopower_server.py" "$APP_DIR/src/autopower_server.py"
cp "$ROOT_DIR/web/index.html" "$APP_DIR/web/index.html"
cp "$ROOT_DIR/web/styles.css" "$APP_DIR/web/styles.css"
cp "$ROOT_DIR/web/app.js" "$APP_DIR/web/app.js"
python3 "$ROOT_DIR/scripts/create-icons.py"
chmod +x "$ROOT_DIR/fpk/cmd/main"
chmod +x "$ROOT_DIR/fpk/cmd/"*

echo "Synced AutoPower app files into fpk/app/AutoPower"
