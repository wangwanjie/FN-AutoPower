#!/bin/bash
# 打包前自检：按飞牛开发者文档检查 fpk/ 目录，发现问题时非零退出。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FPK_DIR="$ROOT_DIR/fpk"

python3 - "$FPK_DIR" <<'PY'
import json
import os
import re
import struct
import sys
from pathlib import Path

fpk = Path(sys.argv[1])
errors = []

manifest = {}
for line in (fpk / "manifest").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        manifest[key.strip()] = value.strip()

for key in ("appname", "version", "display_name", "source", "desc", "platform", "maintainer", "changelog"):
    if not manifest.get(key):
        errors.append(f"manifest 缺少 {key}")
if "arch" in manifest:
    errors.append("manifest 的 arch 已废弃，请改用 platform")
if manifest.get("platform") not in (None, "x86", "arm", "all", "loongarch", "risc-v"):
    errors.append(f"manifest platform 取值无效: {manifest.get('platform')}")
appname = manifest.get("appname", "")
if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", appname):
    errors.append(f"appname 格式无效: {appname}")
if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?", manifest.get("version", "")):
    errors.append(f"version 应为 x.y.z 格式: {manifest.get('version')}")


def png_size(path):
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", header[16:24])


icons = {
    fpk / "ICON.PNG": 64,
    fpk / "ICON_256.PNG": 256,
    fpk / "app" / "ui" / "images" / "icon_64.png": 64,
    fpk / "app" / "ui" / "images" / "icon_256.png": 256,
}
for path, size in icons.items():
    if not path.exists():
        errors.append(f"缺少图标 {path.relative_to(fpk)}")
    elif png_size(path) != (size, size):
        errors.append(f"图标尺寸应为 {size}x{size}: {path.relative_to(fpk)}")
    elif path.stat().st_size > 1024 * 1024:
        errors.append(f"图标超过 1MB: {path.relative_to(fpk)}")

json_files = [fpk / "config" / "privilege", fpk / "config" / "resource", fpk / "app" / "ui" / "config"]
json_files += sorted((fpk / "wizard").glob("*")) if (fpk / "wizard").is_dir() else []
for path in json_files:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"JSON 无效 {path.relative_to(fpk)}: {exc}")
        continue
    if path.name == "config" and path.parent.name == "ui":
        for entry_id in data.get(".url", {}):
            if not entry_id.startswith(appname):
                errors.append(f"入口 ID 必须以 appname 开头: {entry_id}")
        if manifest.get("desktop_applaunchname") not in data.get(".url", {}):
            errors.append("desktop_applaunchname 在 ui/config 中不存在")

documented = {"main", "install_init", "install_callback", "upgrade_init", "upgrade_callback",
              "uninstall_init", "uninstall_callback", "config_init", "config_callback"}
for script in sorted((fpk / "cmd").iterdir()):
    if script.name not in documented:
        errors.append(f"cmd/{script.name} 不在飞牛生命周期脚本列表中，不会被调用")
    if not os.access(script, os.X_OK):
        errors.append(f"cmd/{script.name} 不可执行")
if not os.access(fpk / "app" / "ui" / "index.cgi", os.X_OK):
    errors.append("app/ui/index.cgi 不可执行")

for junk in list(fpk.rglob("__pycache__")) + list(fpk.rglob(".DS_Store")) + list(fpk.rglob("*.pyc")):
    errors.append(f"包内不应包含 {junk.relative_to(fpk)}")

if errors:
    print("FPK 自检失败：", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    sys.exit(1)
print(f"FPK 自检通过：{appname} {manifest['version']}")
PY

# 包内代码必须与 src/、web/ 一致：直接改了包模板或忘记同步都会在这里发现
sync_pairs=(
  "src/autopower_core.py:fpk/app/AutoPower/src/autopower_core.py"
  "src/autopower_server.py:fpk/app/AutoPower/src/autopower_server.py"
  "src/autopower_executor.py:fpk/app/AutoPower/src/autopower_executor.py"
  "web/index.html:fpk/app/ui/index.html"
  "web/styles.css:fpk/app/ui/styles.css"
  "web/app.js:fpk/app/ui/app.js"
)
for pair in "${sync_pairs[@]}"; do
  source_file="$ROOT_DIR/${pair%%:*}"
  packaged_file="$ROOT_DIR/${pair#*:}"
  if ! cmp -s "$source_file" "$packaged_file"; then
    echo "${pair#*:} 与 ${pair%%:*} 不一致，请先运行 ./scripts/sync-fpk.sh" >&2
    exit 1
  fi
done

for script in "$FPK_DIR"/cmd/* "$FPK_DIR/app/ui/index.cgi"; do
  bash -n "$script"
done
if command -v node >/dev/null 2>&1; then
  node --check "$FPK_DIR/app/ui/app.js"
fi
(cd "$ROOT_DIR" && python3 -m unittest discover -s tests >/dev/null 2>&1) || {
  echo "单元测试失败：python3 -m unittest discover -s tests -v" >&2
  exit 1
}
