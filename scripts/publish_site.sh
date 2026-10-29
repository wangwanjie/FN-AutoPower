#!/usr/bin/env bash
# 把已提交的 site/ 目录作为单个提交强推到 GitHub 的 gh-pages 分支（GitHub Pages）。
#
# 用法：scripts/publish_site.sh
# 可选环境变量：
#   REMOTE   推送的远端，默认 origin（GitHub：wangwanjie/FN-AutoPower）
#   BRANCH   目标分支，默认 gh-pages
#   DRY_RUN  设为 1 时只生成提交并打印，不推送
#
# 说明：发布的是 HEAD 中 site/ 的内容，未提交的改动不会发布。
# 主页经 hk_main 反代到 https://autopower.vanjay.cn ，因此不写 CNAME 文件。
set -euo pipefail

REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-gh-pages}"
ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
cd "$ROOT"

# site/ 有未提交改动时提示，避免以为发布了最新内容
if [ -n "$(git status --porcelain -- site)" ]; then
  echo "site/ 有未提交的改动，只会发布 HEAD 中的版本：" >&2
  git status --short -- site >&2
  read -r -p "继续发布？[y/N] " answer
  if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
    exit 1
  fi
fi

# 取 HEAD 中 site/ 对应的 tree 对象，直接生成一个无父提交，不需要切换分支或临时工作区
TREE="$(git rev-parse "HEAD:site")"
SRC="$(git rev-parse --short HEAD)"
if ! git cat-file -e "$TREE:index.html" 2>/dev/null; then
  echo "HEAD 的 site/ 中没有 index.html，已中止" >&2
  exit 1
fi
if ! git cat-file -e "$TREE:.nojekyll" 2>/dev/null; then
  echo "HEAD 的 site/ 中没有 .nojekyll，已中止" >&2
  exit 1
fi

COMMIT="$(git commit-tree "$TREE" -m "发布主页（来自 $SRC）")"
echo "已生成提交 $COMMIT（site/ 来自 $SRC）"

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY_RUN=1，未推送。可用 git ls-tree -r $COMMIT 查看内容。"
  exit 0
fi

git push --force "$REMOTE" "$COMMIT:refs/heads/$BRANCH"
echo "已推送到 $REMOTE/$BRANCH"
echo "首次发布后在仓库 Settings → Pages 选择分支 $BRANCH、目录 / (root)"
