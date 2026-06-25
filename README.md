# AutoPower

AutoPower 是一个飞牛 fnOS FPK 应用，用来管理 NAS 自动开机和自动关机计划。界面参考 `design/fnos-power-schedule-flows.html` 的 fnOS 风格，底层使用 RTC wakealarm、systemd shutdown hook 和 root crontab 实现。

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

## 目录结构

```text
src/                    后端服务与调度核心
web/                    前端页面
tests/                  单元测试
fpk/                    fnOS FPK 包模板
docs/images/            README 截图
scripts/sync-fpk.sh     同步 src/web 到 fpk/app/AutoPower
scripts/build-fpk.sh    构建 .fpk
scripts/create-icons.py 生成 FPK 图标
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

本地运行时不要点击“应用计划”或“测试开机计划”来验证真实系统写入，因为 macOS 没有 fnOS 的 `/sys/class/rtc/rtc0/wakealarm`、systemd 和 root crontab 环境。页面会显示失败原因，这是预期行为。

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

构建当前版本：

```bash
./scripts/build-fpk.sh
```

指定版本：

```bash
FPK_VERSION=1.0.4 ./scripts/build-fpk.sh
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

当前入口配置使用 `iframe` 窗口模式：

```json
{
  "type": "iframe",
  "protocol": "https",
  "port": "3868",
  "url": "/",
  "allUsers": true
}
```

入口协议必须用 `https`：fnOS 会在应用端口前做 TLS 终止，桌面图标地址按 `${协议}://${当前主机}:${端口}/` 拼接。写成 `http` 时，内网（http 桌面）能开，但公网（https 桌面）会因混合内容被浏览器拦截而打不开。改用 `https` 后内外网都正常，无需额外反代。详见 [docs/REMOTE-ACCESS.md](docs/REMOTE-ACCESS.md)。

## 系统写入行为

应用计划时会：

- 生成 root crontab 托管区，用于关机计划
- 写入 `/sys/class/rtc/rtc0/wakealarm`，用于下一次开机
- 安装 `autopower-rtc-wake.service`，在关机前刷新下一次 RTC 唤醒

卸载脚本会移除 systemd service、唤醒脚本和 crontab 托管区。
