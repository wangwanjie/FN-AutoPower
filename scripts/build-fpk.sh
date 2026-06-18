#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${FPK_OUT_DIR:-$ROOT_DIR/dist-fpk}"
VERSION="${FPK_VERSION:-1.0.0}"

"$ROOT_DIR/scripts/sync-fpk.sh"
mkdir -p "$OUT_DIR"

if [ -n "${FNPACK_BIN:-}" ]; then
  FNPACK="$FNPACK_BIN"
elif command -v fnpack >/dev/null 2>&1; then
  FNPACK="$(command -v fnpack)"
else
  FNPACK="$(find "$ROOT_DIR" -maxdepth 1 -type f -name 'fnpack*' -perm +111 2>/dev/null | head -n 1 || true)"
fi

if [ -z "$FNPACK" ]; then
  echo "fnpack not found. Put fnpack in project root or set FNPACK_BIN=/abs/path/to/fnpack." >&2
  exit 1
fi

sed -i.bak "s/^version[[:space:]]*=.*/version               = $VERSION/" "$ROOT_DIR/fpk/manifest"
rm -f "$ROOT_DIR/fpk/manifest.bak"

before_list="$(mktemp)"
after_list="$(mktemp)"
find "$ROOT_DIR" -maxdepth 3 -name '*.fpk' -print | sort > "$before_list"

"$FNPACK" build -d "$ROOT_DIR/fpk"

find "$ROOT_DIR" -maxdepth 4 -name '*.fpk' -print | sort > "$after_list"
new_fpk="$(comm -13 "$before_list" "$after_list" | head -n 1)"
rm -f "$before_list" "$after_list"

if [ -z "$new_fpk" ]; then
  new_fpk="$(find "$ROOT_DIR/fpk" "$ROOT_DIR" -maxdepth 3 -name '*.fpk' -print | sort -r | head -n 1)"
fi

if [ -z "$new_fpk" ]; then
  echo "fnpack finished but no .fpk file was found." >&2
  exit 1
fi

target="$OUT_DIR/autopower-$VERSION.fpk"
mv "$new_fpk" "$target"
echo "$target"
