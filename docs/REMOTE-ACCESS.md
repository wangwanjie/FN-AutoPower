# 公网访问修复说明

本文说明 AutoPower 在内网正常、但通过公网域名访问「无反应 / 拒绝连接」的**真正**根本原因和修复方法。

> 订正：早期版本（1.0.5）曾把问题判为「混合内容（Mixed Content）」并把入口协议从 `http` 改成 `https`。
> 经对照飞牛自带应用（`wol`、`xunlei`）的真实配置后确认，那个判断是**错的**。真正原因见下。

## 现象

- 内网正常：`http://192.168.18.28:5000/` 桌面里打开 AutoPower 正常。
- 公网无反应：`https://nas.remote.vanjay.cn:4433/` 里打开 AutoPower 空白 / 拒绝连接。
- 对比：其他飞牛应用在内网和公网都能正常打开，且**无需任何额外端口/域名/反代配置**。

## 根本原因（一句话）

AutoPower 原来是「**固定端口式**」入口，桌面会去打开 `http(s)://<域名>:3868/`，
而公网链路只转发了 `:4433`，`:3868` 根本不对外 → 拒绝连接。

### 飞牛应用是怎么开的

点击桌面图标时，窗口地址按 `{protocol}://{当前主机}:{port}{url}` 拼接。`protocol`/`port`/`url` 取自 `app/ui/config`。

- **其他第三方应用（如 wol、xunlei）走「同源路径」**：它们的 `ui/config` 里 **不写 `port`**，`protocol` 写 `http`，`url` 是一个相对路径：

  ```json
  "type": "iframe",
  "protocol": "http",
  "url": "/cgi/ThirdParty/wol/index.cgi/"
  ```

  这个路径由**飞牛自带的 nginx**（`/usr/trim/nginx`）以 CGI 方式执行应用 `ui/` 目录下的 `index.cgi`。
  因为是「当前站点同源的相对路径」，所以无论你从内网 `:5000` 还是公网 `:4433` 访问，
  它都跟着用同一个 host/port/protocol —— **永远不需要对外暴露应用自己的端口**，也就「什么都不用配」。

- **AutoPower 原来走「端口式」**：`ui/config` 写死了 `protocol`+`port: 3868`、`url: "/"`，
  于是桌面去打开绝对地址 `…://<域名>:3868/`：
  - 内网：`http://192.168.18.28:3868/` —— 局域网能直连 3868，正常。
  - 公网：`https://nas.remote.vanjay.cn:3868/` —— 公网只转发了 4433，3868 不可达 → **拒绝连接**。

## 修复（改为与 wol/xunlei 同款的「同源 CGI」接入）

1. 新增 `fpk/app/ui/index.cgi`（bash CGI）：从 `ui/` 目录返回前端静态文件，并把 `/api/*` 反代到本机 `127.0.0.1:<service_port>` 的 AutoPower 服务。
2. `fpk/app/ui/config` 改为：`protocol: http`、**去掉 `port`**、`url: /cgi/ThirdParty/autopower/index.cgi/`。
3. `fpk/manifest` 去掉 `disable_authorization_path = true`（见下方安全说明），保留 `service_port = 3868`。
4. 后端只监听 `127.0.0.1`（`fpk/cmd/main` 里 `--host 127.0.0.1`），不再对外暴露任何端口。
5. 前端接口请求走相对路径（`apiUrl()` 基于 `document.baseURI`），静态资源相对引用 —— 在 `…/index.cgi/` 子路径下也能正常请求。

改后内网/公网都用同源路径打开，和其他飞牛应用一致，**不需要 Lucky/haproxy/nginx 做任何针对 AutoPower 的配置**。

### 安全说明（重要）

原 `disable_authorization_path = true` 会让 `/cgi/ThirdParty/autopower/…` 这个路径**绕过飞牛登录鉴权**——
对一个以 root 运行、能改 RTC/关机/定时任务的应用来说很危险（公网任何人都能调）。
`wol`/`xunlei` 都没有设这个字段，其路径需要登录后才能访问。本次修复已移除它，**恢复为需要登录**。

## 生效方法

安装 `dist-fpk/autopower-1.0.6.fpk`（覆盖安装）。若桌面入口没刷新：

```bash
systemctl restart trim_app_center.service
```

## 验证清单

1. 公网 `https://nas.remote.vanjay.cn:4433/` 桌面打开 AutoPower，iframe 正常加载，F12 控制台无报错，地址形如 `…/cgi/ThirdParty/autopower/index.cgi/`。
2. 内网 `http://192.168.18.28:5000/` 桌面打开仍正常。
3. 新增/编辑/删除/启用计划、「应用计划」「测试开机计划」均可用（后者依赖真实 RTC/systemd/root，只能在 fnOS 实机验证）。

## 工作原理小结

```
浏览器(公网 :4433 / 内网 :5000)
   │  GET /cgi/ThirdParty/autopower/index.cgi/...
   ▼
飞牛自带 nginx (/usr/trim/nginx)  ── 登录鉴权 ──► 执行 ui/index.cgi (CGI)
   │ 静态: 直接读 ui/ 下文件
   │ /api/*: curl 反代到 ──► 127.0.0.1:3868  (AutoPower 服务, 仅本机, root)
```
