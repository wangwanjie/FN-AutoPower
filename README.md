# AutoPower

AutoPower（自动开关机）是一个飞牛 fnOS FPK 应用，用来管理 NAS 自动开机和自动关机计划。界面参考 `design/fnos-power-schedule-flows.html` 的 fnOS 风格，底层使用 RTC wakealarm、systemd shutdown hook 和 root crontab 实现。

- 支持平台：fnOS x86（纯 Python + Bash，依赖系统自带的 `python3` 与 `curl`；ARM 未实机验证）
- 开源协议：[MIT](LICENSE)
- 更新日志：[CHANGELOG.md](CHANGELOG.md)

## 技术栈

- 后端：Python 3 标准库 HTTP server，不依赖第三方包
- 前端：原生 HTML/CSS/JavaScript
- 调度核心：纯 Python 计划校验、下次唤醒计算、crontab 渲染
- 打包：fnOS `fnpack`
- 测试：Python `unittest`

## 界面参考

OpenDesign 参考稿来自 `design/fnos-power-schedule-flows.html`：

![OpenDesign 参考界面](docs/images/fnos-power-schedule-flows.png)

当前实现的主界面：

![AutoPower 主界面](docs/images/autopower-main.png)

![编辑计划](docs/images/autopower-edit.png)

## 目录结构

```text
src/                    后端服务与调度核心
web/                    前端页面
tests/                  单元测试
fpk/                    fnOS FPK 包模板
docs/images/            README 与上架截图
docs/STORE-SUBMISSION.md 飞牛应用中心上架材料与自查清单
scripts/sync-fpk.sh     同步 src 到 fpk/app/AutoPower/src，web 到 fpk/app/ui
scripts/check-fpk.sh    打包前自检（manifest、图标、JSON、生命周期脚本、单元测试）
scripts/build-fpk.sh    自检并构建 .fpk
scripts/build-store.sh  汇总上架材料到 store/（构建产物，不提交）
scripts/create-icons.py 重新生成图标（需要 Pillow，仅改图标设计时运行）
design/                 OpenDesign 参考稿
```

## 本地运行

```bash
python3 src/autopower_server.py \
  --host 127.0.0.1 \
  --port 3868 \
  --data-dir /tmp/autopower-dev \
  --web-dir web
```

打开：

```text
http://127.0.0.1:3868/
```

非 Linux 系统（如 macOS）上，后端会跳过所有系统写入（crontab、RTC、systemd），增删计划只保存到 `--data-dir`，“应用计划”会提示当前环境不允许写入，这是预期行为。在 Linux 上调试且不想改动本机时，设置 `AUTOPOWER_DRY_RUN=1`。

## 修改页面

主要改这三个文件：

```text
web/index.html
web/styles.css
web/app.js
```

修改后运行：

```bash
node --check web/app.js
python3 -m unittest discover -s tests -v
```

如果要让修改进入 FPK 包模板：

```bash
./scripts/sync-fpk.sh
```

## 修改后端或调度逻辑

主要文件：

```text
src/autopower_core.py
src/autopower_server.py
```

验证：

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/autopower_core.py src/autopower_server.py scripts/create-icons.py
```

## 打包

确认 `fnpack` 已在 PATH 中：

```bash
fnpack --help
```

构建 manifest 中的当前版本（会先执行 `scripts/check-fpk.sh` 自检）：

```bash
./scripts/build-fpk.sh
```

指定版本（会同时改写 `fpk/manifest` 的 version，记得同步更新 `changelog` 字段和 `CHANGELOG.md`）：

```bash
FPK_VERSION=1.1.1 ./scripts/build-fpk.sh
```

产物输出到：

```text
dist-fpk/autopower-<version>.fpk
```

`dist-fpk/` 是构建产物，不提交到 git。

## fnOS 安装与刷新

在飞牛应用中心手动安装生成的 `.fpk`。如果覆盖安装后桌面入口没有刷新，可以在 fnOS 上执行：

```bash
systemctl restart trim_app_center.service
```

入口使用与飞牛自带应用相同的同源 CGI 方式：

```json
{
  "type": "iframe",
  "protocol": "http",
  "url": "/cgi/ThirdParty/autopower/index.cgi/",
  "allUsers": true
}
```

飞牛自带 nginx 执行 `ui/index.cgi`：静态文件直接从 `ui/` 返回，`/api/*` 转发到只监听 `127.0.0.1:3868` 的后端。路径走飞牛登录鉴权，内网和公网访问都无需额外端口或反代。详见 [docs/REMOTE-ACCESS.md](docs/REMOTE-ACCESS.md)。

## 系统写入行为

应用计划时会：

- 生成 root crontab 托管区，用于关机计划
- 写入 `/sys/class/rtc/rtc0/wakealarm`，用于下一次开机
- 安装 `autopower-rtc-wake.service`，在关机前刷新下一次 RTC 唤醒

卸载时（`cmd/uninstall_init`）会移除 systemd service、唤醒脚本和 crontab 托管区，并清除 RTC 唤醒闹钟。

## 为什么需要 root

`config/privilege` 声明 `run-as: root`，因为核心功能都需要 root：写 root crontab 执行 `/sbin/poweroff`、写 `/sys/class/rtc/rtc0/wakealarm`（或调用 `rtcwake`）、在 `/etc/systemd/system` 安装关机前设置唤醒的服务。后端只监听 `127.0.0.1`，只能经过飞牛登录鉴权的 CGI 入口访问；写接口只接受 `application/json`，防止跨站表单提交。
