#!/bin/bash
# 构建 fnOS 安装包：同一份代码按平台分别打包（manifest 的 platform 字段不同），
# 用户按 NAS 架构下载对应的包。纯 Python + Bash 实现，各平台包内容一致。
#
# 用法：
#   ./scripts/build-fpk.sh                       构建 manifest 当前版本的 x86 与 arm 包
#   FPK_VERSION=1.3.0 ./scripts/build-fpk.sh     指定版本（同时改写 manifest 的 version）
#   FPK_PLATFORMS=x86 ./scripts/build-fpk.sh     只构建指定平台，多个平台用空格分隔
#
# 产物：dist-fpk/autopower-<version>-<platform>.fpk 和 dist-fpk/autopower-<version>-SHA256SUMS.txt
# 标准输出最后几行是生成的安装包路径，每行一个。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${FPK_OUT_DIR:-$ROOT_DIR/dist-fpk}"
MANIFEST="$ROOT_DIR/fpk/manifest"
MANIFEST_VERSION="$(awk -F '=' '/^version[[:space:]]*=/{gsub(/[[:space:]]/, "", $2); print $2}' "$MANIFEST")"
VERSION="${FPK_VERSION:-$MANIFEST_VERSION}"
PLATFORMS="${FPK_PLATFORMS:-x86 arm}"

for platform in $PLATFORMS; do
  case "$platform" in
    x86|arm|loongarch|risc-v|all)
      ;;
    *)
      echo "不支持的平台：$platform（可选 x86、arm、loongarch、risc-v、all）" >&2
      exit 1
      ;;
  esac
done

if [ -n "${FNPACK_BIN:-}" ]; then
  FNPACK="$FNPACK_BIN"
elif command -v fnpack >/dev/null 2>&1; then
  FNPACK="$(command -v fnpack)"
else
  # 项目根目录下的 fnpack 可执行文件；-perm -u+x 在 GNU 与 BSD find 上都可用
  FNPACK="$(find "$ROOT_DIR" -maxdepth 1 -type f -name 'fnpack*' -perm -u+x 2>/dev/null | head -n 1 || true)"
fi
if [ -z "$FNPACK" ]; then
  echo "fnpack not found. Put fnpack in project root or set FNPACK_BIN=/abs/path/to/fnpack." >&2
  exit 1
fi

"$ROOT_DIR/scripts/sync-fpk.sh" >&2

set_manifest() {
  local key="$1"
  local value="$2"
  # key 左对齐到 22 列，与 manifest 现有格式一致
  local padded
  padded="$(printf '%-22s' "$key")"
  sed -i.bak "s/^${key}[[:space:]]*=.*/${padded}= ${value}/" "$MANIFEST"
  rm -f "$MANIFEST.bak"
}

set_manifest version "$VERSION"
"$ROOT_DIR/scripts/check-fpk.sh" >&2

# 打包过程中临时改写 platform，结束（包括失败）时恢复原值，避免把临时值提交进仓库
ORIGINAL_PLATFORM="$(awk -F '=' '/^platform[[:space:]]*=/{gsub(/[[:space:]]/, "", $2); print $2}' "$MANIFEST")"
trap 'set_manifest platform "$ORIGINAL_PLATFORM"' EXIT

mkdir -p "$OUT_DIR"
BUILD_DIR="$(mktemp -d)"
trap 'set_manifest platform "$ORIGINAL_PLATFORM"; rm -rf "$BUILD_DIR"' EXIT

outputs=()
for platform in $PLATFORMS; do
  set_manifest platform "$platform"
  # 在临时目录中构建，fnpack 产物只会出现在这里，不会和仓库里的其他 .fpk 混淆
  (cd "$BUILD_DIR" && "$FNPACK" build -d "$ROOT_DIR/fpk" >&2)
  built="$(find "$BUILD_DIR" "$ROOT_DIR/fpk" -maxdepth 1 -name '*.fpk' -print | head -n 1)"
  if [ -z "$built" ]; then
    echo "fnpack 完成但没有找到 $platform 平台的 .fpk 文件" >&2
    exit 1
  fi
  target="$OUT_DIR/autopower-$VERSION-$platform.fpk"
  mv "$built" "$target"
  outputs+=("$target")
done

(
  cd "$OUT_DIR"
  names=()
  for path in "${outputs[@]}"; do
    names+=("$(basename "$path")")
  done
  # macOS 自带 shasum，Linux 发行版通常只有 sha256sum
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${names[@]}" > "autopower-$VERSION-SHA256SUMS.txt"
  else
    shasum -a 256 "${names[@]}" > "autopower-$VERSION-SHA256SUMS.txt"
  fi
)

for path in "${outputs[@]}"; do
  echo "$path"
done
