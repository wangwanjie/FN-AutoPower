# 飞牛应用中心上架材料

依据：[飞牛开发者文档](https://developer.fnnas.com/docs/)（发布应用、manifest、图标、权限、生命周期、入口配置）。官方没有公开审核细则，以下按文档要求和测试建议整理。

## 提交方式

开发者后台（“我的应用”）尚未开放，目前走人工提交：

1. 在 fnnas.com 右上角“关注飞牛”→ 微信群，加入任意飞牛粉丝群
2. 联系社区管理员，申请加入“应用中心开发者先锋交流群”
3. 按工作人员要求提交 `.fpk`、图标、截图和应用说明

## 提交材料

运行 `./scripts/build-store.sh` 会把下表材料汇总到 `store/` 目录。

| 材料 | 位置 |
|---|---|
| 安装包 | `./scripts/build-fpk.sh` 生成的 `dist-fpk/autopower-<version>-x86.fpk`、`dist-fpk/autopower-<version>-arm.fpk` |
| 图标 | `fpk/ICON.PNG`（64×64）、`fpk/ICON_256.PNG`（256×256） |
| 截图 | `docs/images/autopower-main.png`（计划列表）、`docs/images/autopower-edit.png`（编辑计划）、`docs/images/autopower-deploy.png`（执行器部署）；用 `node scripts/capture-screenshots.mjs` 重新生成 |
| 名称 / 简介 / 更新说明 | `fpk/manifest` 的 `display_name`、`desc`、`changelog` |
| 开源地址 | https://github.com/wangwanjie/FN-AutoPower （MIT） |

建议另外在 fnOS 实机上截一张执行器部署后“运行正常”、显示 RTC 闹钟时间的图，证明核心功能可用。

## 应用说明（可直接粘贴）

> 自动开关机：为 NAS 设置定时开机、定时关机与定时重启计划，支持每天、平日、假日和指定星期。
> 定时开机通过主板 RTC 唤醒实现（需主板支持并在 BIOS 中开启 RTC 唤醒）；定时关机与重启通过系统定时任务实现。
> 应用以普通权限运行，关机、重启与写 RTC 由管理员通过 SSH 一次性部署的执行器完成；关机前会自动写入下一次开机时间。

## 权限说明（审核可能会问）

应用以普通包用户运行（`config/privilege` 为 `run-as: package`），只读写自己的数据目录。需要 root 的操作由执行器完成，管理员在应用内复制命令、通过 SSH 部署一次：

- `/etc/cron.d/autopower`：每分钟以 root 运行执行器，命中关机计划时执行 `/sbin/poweroff`、命中重启计划时执行 `/sbin/reboot`，并同步 `/sys/class/rtc/rtc0/wakealarm`
- `/etc/systemd/system/autopower-rtc-wake.service`：关机前写入下一次开机时间
- 执行器代码复制到 root 所有的 `/usr/local/lib/autopower`，cron 不运行应用目录中可被包用户修改的代码

安全措施：

- 执行器只做关机、重启和写 RTC，不执行任何来自配置的命令；计划文件按白名单校验，拒绝符号链接、限制大小
- 后端只监听 `127.0.0.1:3868`，不对外暴露端口
- 唯一入口是 `/cgi/ThirdParty/autopower/index.cgi/`，走飞牛登录鉴权（未设置 `disable_authorization_path`）
- 写接口只接受 `application/json`，阻止跨站表单提交；请求体限制 64KB
- 卸载应用后执行器发现数据目录被删除，会自动停止关机并清除 RTC 闹钟；`--uninstall` 删除执行器的全部文件

## 上架前实机自查

在每个声明支持的架构（x86、arm 各自的安装包）上执行：

- [ ] 全新安装后能从桌面打开，内网和公网（远程访问）都能加载
- [ ] 新增 / 编辑 / 删除 / 启用 / 停用计划，刷新后数据保持
- [ ] 按应用内命令部署执行器后状态显示“运行正常”，`cat /etc/cron.d/autopower` 存在，`cat /proc/driver/rtc` 显示闹钟时间
- [ ] 设一个几分钟后的关机 + 再过几分钟的开机，机器能按时关机并被唤醒
- [ ] 覆盖安装新版本后计划保留，唤醒服务仍然有效（`systemctl status autopower-rtc-wake`）；执行器版本变化时界面提示重新部署
- [ ] 停止应用后再启动正常；`cmd/main status` 返回值正确
- [ ] 执行 `--uninstall` 后 `/etc/cron.d/autopower`、`/etc/systemd/system/autopower-rtc-wake.service`、`/usr/local/lib/autopower` 都已删除，`/sys/class/rtc/rtc0/wakealarm` 为空
- [ ] 未登录直接访问 `/cgi/ThirdParty/autopower/index.cgi/api/state` 被拒绝

安装方式：

- **升级已安装的版本**：只能在网页端「应用中心 → 手动安装」上传 `.fpk`。实测 `appcenter-cli install-fpk` 遇到已安装的应用会提示 “is installed” 并跳过，`appcenter-cli uninstall` 也会要求去网页端操作
- **全新安装**（机器上没有该应用）可以用命令行，`-v 1` 指定安装卷（CLI 默认卷未设置时不带会报 “Volume is unavailable”）：

```bash
appcenter-cli install-fpk autopower-<version>-x86.fpk -v 1
```

不要用 `appcenter-cli install-local` 升级：它会先删掉旧版本，安装失败时应用直接消失。
