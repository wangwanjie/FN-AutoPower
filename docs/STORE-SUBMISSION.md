# 飞牛应用中心上架材料

依据：[飞牛开发者文档](https://developer.fnnas.com/docs/)（发布应用、manifest、图标、权限、生命周期、入口配置）。官方没有公开审核细则，以下按文档要求和测试建议整理。

## 提交方式

开发者后台（“我的应用”）尚未开放，目前走人工提交：

1. 在 fnnas.com 右上角“关注飞牛”→ 微信群，加入任意飞牛粉丝群
2. 联系社区管理员，申请加入“应用中心开发者先锋交流群”
3. 按工作人员要求提交 `.fpk`、图标、截图和应用说明

## 提交材料

| 材料 | 位置 |
|---|---|
| 安装包 | `./scripts/build-fpk.sh` 生成的 `dist-fpk/autopower-<version>.fpk` |
| 图标 | `fpk/ICON.PNG`（64×64）、`fpk/ICON_256.PNG`（256×256） |
| 截图 | `docs/images/autopower-main.png`（计划列表）、`docs/images/autopower-edit.png`（编辑计划） |
| 名称 / 简介 / 更新说明 | `fpk/manifest` 的 `display_name`、`desc`、`changelog` |
| 开源地址 | https://github.com/wangwanjie/FN-AutoPower （MIT） |

建议另外在 fnOS 实机上截一张“应用计划”成功后状态栏显示 RTC 闹钟时间的图，证明核心功能可用。

## 应用说明（可直接粘贴）

> 自动开关机：为 NAS 设置定时开机与定时关机计划，支持每天、平日、假日和指定星期。
> 定时开机通过主板 RTC 唤醒实现（需主板支持并在 BIOS 中开启 RTC 唤醒）；定时关机通过系统定时任务实现。
> 关机前会自动写入下一次开机时间，卸载时清除本应用写入的所有定时任务与唤醒闹钟。

## root 权限说明（审核可能会问）

应用以 root 运行，原因：

- 定时关机：写 root crontab，执行 `/sbin/poweroff`
- 定时开机：写 `/sys/class/rtc/rtc0/wakealarm` 或调用 `rtcwake`
- 关机前写入唤醒时间：在 `/etc/systemd/system` 安装 `autopower-rtc-wake.service`

安全措施：

- 后端只监听 `127.0.0.1:3868`，不对外暴露端口
- 唯一入口是 `/cgi/ThirdParty/autopower/index.cgi/`，走飞牛登录鉴权（未设置 `disable_authorization_path`）
- 写接口只接受 `application/json`，阻止跨站表单提交；请求体限制 64KB
- 只改动 crontab 中 `# BEGIN AUTOPOWER` / `# END AUTOPOWER` 之间的内容，不影响用户其他定时任务
- 卸载时（`cmd/uninstall_init`）删除服务、脚本、crontab 托管区并清除 RTC 闹钟

## 上架前实机自查

在每个声明支持的架构（`platform = all`：x86 和 ARM）上执行：

- [ ] 全新安装后能从桌面打开，内网和公网（远程访问）都能加载
- [ ] 新增 / 编辑 / 删除 / 启用 / 停用计划，刷新后数据保持
- [ ] 点“应用计划”成功，`crontab -l` 出现托管区，`cat /proc/driver/rtc` 显示闹钟时间
- [ ] 设一个几分钟后的关机 + 再过几分钟的开机，机器能按时关机并被唤醒
- [ ] 覆盖安装新版本后计划保留，唤醒服务仍然有效（`systemctl status autopower-rtc-wake`）
- [ ] 停止应用后再启动正常；`cmd/main status` 返回值正确
- [ ] 卸载后 crontab 托管区、`/etc/systemd/system/autopower-rtc-wake.service`、`/usr/local/bin/autopower-set-next-wake.sh` 都已删除，`/sys/class/rtc/rtc0/wakealarm` 为空
- [ ] 未登录直接访问 `/cgi/ThirdParty/autopower/index.cgi/api/state` 被拒绝

手动安装测试也可以用命令行：

```bash
appcenter-cli install-fpk autopower-1.1.0.fpk
```
