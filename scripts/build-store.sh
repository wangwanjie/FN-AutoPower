#!/bin/bash
# 汇总飞牛应用中心上架材料到 store/：安装包、图标、截图、提交说明。
# 用法：./scripts/build-store.sh   （会先执行 build-fpk.sh 构建当前 manifest 版本的各平台安装包）
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STORE_DIR="$ROOT_DIR/store"
MANIFEST="$ROOT_DIR/fpk/manifest"

# 从 manifest 读取字段，去掉键名和等号两侧空白
manifest_value() {
  awk -v key="$1" '
    {
      split($0, parts, "=")
      name = parts[1]
      gsub(/[[:space:]]/, "", name)
      if (name == key) {
        sub(/^[^=]*=[[:space:]]*/, "")
        print
        exit
      }
    }
  ' "$MANIFEST"
}

VERSION="$(manifest_value version)"
FPKS=()
while IFS= read -r line; do
  FPKS+=("$line")
done < <("$ROOT_DIR/scripts/build-fpk.sh")
if [ "${#FPKS[@]}" -eq 0 ]; then
  echo "构建失败，未生成安装包" >&2
  exit 1
fi

rm -rf "$STORE_DIR"
mkdir -p "$STORE_DIR/icons" "$STORE_DIR/screenshots"
PACKAGE_ROWS=""
for fpk in "${FPKS[@]}"; do
  if [ ! -f "$fpk" ]; then
    echo "构建失败，未找到安装包：$fpk" >&2
    exit 1
  fi
  cp "$fpk" "$STORE_DIR/"
  name="$(basename "$fpk")"
  platform="${name%.fpk}"
  platform="${platform##*-}"
  sha="$(shasum -a 256 "$fpk" | awk '{print $1}')"
  size_kb="$(( $(wc -c < "$fpk") / 1024 ))"
  PACKAGE_ROWS="${PACKAGE_ROWS}| ${platform} | ${name}（${size_kb} KB） | \`${sha}\` |
"
done
cp "$ROOT_DIR/fpk/ICON.PNG" "$STORE_DIR/icons/ICON_64.png"
cp "$ROOT_DIR/fpk/ICON_256.PNG" "$STORE_DIR/icons/ICON_256.png"
cp "$ROOT_DIR/docs/images/autopower-main.png" "$STORE_DIR/screenshots/1-计划列表.png"
cp "$ROOT_DIR/docs/images/autopower-edit.png" "$STORE_DIR/screenshots/2-编辑计划.png"
cp "$ROOT_DIR/docs/images/autopower-deploy.png" "$STORE_DIR/screenshots/3-执行器部署.png"

cat > "$STORE_DIR/提交说明.md" <<EOF
# 自动开关机 ${VERSION} — 飞牛应用中心上架申请

## 基本信息

| 项目 | 内容 |
|---|---|
| 应用名称 | $(manifest_value display_name) |
| 应用标识（appname） | $(manifest_value appname) |
| 版本 | ${VERSION} |
| 分类 | 系统工具 |
| 开发者 | $(manifest_value maintainer) |
| 开源地址 | $(manifest_value maintainer_url)（MIT 协议） |

## 安装包

各平台安装包内容相同（纯 Python + Bash），只有 manifest 的 platform 字段不同。

| 平台 | 文件 | SHA-256 |
|---|---|---|
${PACKAGE_ROWS}
## 应用简介

$(manifest_value desc)

## 功能

- 新增、编辑、删除、启用、停用开机或关机计划，计划可加备注
- 日期支持每天、平日（周一至周五）、假日（周六、周日）和指定星期
- 首页显示下一次执行时间和未来 7 天的执行预览，同一时间既开机又关机等冲突会提示
- 关机（包括手动关机）前自动把下一次开机时间写入主板 RTC；主板时钟与系统时间存在时区差时自动补偿
- 卸载应用后执行器自动停止关机并清除 RTC 闹钟

## 本版更新

$(manifest_value changelog)

## 使用前提

定时开机依赖主板 RTC 唤醒：需要主板支持，并在 BIOS/UEFI 中开启 RTC 唤醒（部分主板叫 “Resume by RTC Alarm” / “Wake on RTC”）。定时关机不依赖硬件。

## 权限说明

应用本身以普通包用户运行（\`config/privilege\` 为 \`run-as: package\`），只负责编辑计划文件。
关机与写 RTC 闹钟需要 root，由管理员通过 SSH 一次性部署的执行器完成：

- \`/etc/cron.d/autopower\`：每分钟以 root 运行执行器，命中关机计划时执行 \`/sbin/poweroff\`，并同步 RTC 唤醒闹钟
- \`/etc/systemd/system/autopower-rtc-wake.service\`：关机前写入下一次开机时间
- 执行器代码复制到 root 所有的 \`/usr/local/lib/autopower\`，cron 不运行应用目录里可被包用户修改的代码

安全措施：

- 执行器只做关机和写 RTC 两件事，不执行任何来自配置的命令；计划文件按白名单逐条校验，拒绝符号链接、限制大小
- 后端只监听 \`127.0.0.1:3868\`，不对外开放端口
- 唯一入口 \`/cgi/ThirdParty/autopower/index.cgi/\`，需要飞牛登录（未设置 \`disable_authorization_path\`）
- 写接口只接受 \`application/json\`，阻止跨站表单提交；请求体限制 64KB
- 不访问外网，不收集任何数据

## 测试情况

x86 版已在两台 x86 fnOS 设备上实机验证：全新安装、计划增删改、定时关机与 RTC 定时开机、网页端覆盖升级后计划保留、内网与远程访问。ARM 版与 x86 版代码完全相同，尚未在 ARM 实机上验证。

## 附件

- \`autopower-${VERSION}-<平台>.fpk\`：各平台安装包
- \`icons/\`：64×64、256×256 图标
- \`screenshots/\`：计划列表、编辑计划、执行器部署界面截图
EOF

echo "上架材料已生成：$STORE_DIR"
ls -R "$STORE_DIR"
