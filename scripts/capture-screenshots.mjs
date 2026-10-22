#!/usr/bin/env node
// 生成 README 与上架用的界面截图：启动演示服务（scripts/demo-server.py），
// 用无头 Chrome 通过 DevTools 协议打开页面并截图。只依赖 Node 18+ 与本机 Chrome。
//
// 用法：node scripts/capture-screenshots.mjs
// 可选环境变量：CHROME_BIN（Chrome 可执行文件路径）、DEMO_PORT（演示服务端口，默认 3869）
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT_DIR = join(ROOT, "docs", "images");
const PORT = Number(process.env.DEMO_PORT || 3869);
const VIEWPORT = { width: 1100, height: 640, deviceScaleFactor: 2 };

// 每张截图：打开页面后执行的脚本（打开弹窗等）
const SHOTS = [
  { file: "autopower-main.png", height: 900, setup: "" },
  { file: "autopower-edit.png", setup: "document.querySelector('#editBtn').click()" },
  { file: "autopower-deploy.png", height: 760, setup: "document.querySelector('#deployBtn').click()" },
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function findChrome() {
  const candidates = [
    process.env.CHROME_BIN,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  const found = candidates.find((path) => existsSync(path));
  if (!found) {
    throw new Error("未找到 Chrome，请设置 CHROME_BIN");
  }
  return found;
}

async function waitFor(check, label, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const value = await check();
      if (value) {
        return value;
      }
    } catch {
      // 服务尚未就绪，继续等待
    }
    await sleep(200);
  }
  throw new Error(`等待超时：${label}`);
}

// 极简 CDP 客户端：按 id 匹配请求与响应
class Cdp {
  constructor(url) {
    this.nextId = 1;
    this.pending = new Map();
    this.socket = new WebSocket(url);
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      const handler = this.pending.get(message.id);
      if (handler) {
        this.pending.delete(message.id);
        if (message.error) {
          handler.reject(new Error(message.error.message));
        } else {
          handler.resolve(message.result);
        }
      }
    });
  }

  open() {
    return new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
}

async function main() {
  const demo = spawn("python3", [join(ROOT, "scripts", "demo-server.py"), "--port", String(PORT)], { stdio: "inherit" });
  const profile = mkdtempSync(join(tmpdir(), "autopower-chrome-"));
  const chrome = spawn(findChrome(), [
    "--headless=new",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });

  try {
    const base = `http://127.0.0.1:${PORT}/`;
    await waitFor(async () => (await fetch(`${base}api/state`)).ok, "演示服务启动");
    const debugPort = await waitFor(() => {
      const file = join(profile, "DevToolsActivePort");
      return existsSync(file) ? readFileSync(file, "utf8").split("\n")[0] : null;
    }, "Chrome 启动");
    const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
    const page = targets.find((target) => target.type === "page");
    const cdp = new Cdp(page.webSocketDebuggerUrl);
    await cdp.open();
    await cdp.send("Page.enable");

    for (const shot of SHOTS) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width: VIEWPORT.width,
        height: shot.height || VIEWPORT.height,
        deviceScaleFactor: VIEWPORT.deviceScaleFactor,
        mobile: false,
      });
      await cdp.send("Page.navigate", { url: base });
      // 等页面渲染出计划列表
      await waitFor(async () => {
        const result = await cdp.send("Runtime.evaluate", {
          expression: "document.querySelectorAll('#scheduleRows tr').length",
          returnByValue: true,
        });
        return result.result.value > 0;
      }, "页面加载");
      if (shot.setup) {
        await cdp.send("Runtime.evaluate", { expression: shot.setup });
      }
      await sleep(400);
      const { data } = await cdp.send("Page.captureScreenshot", { format: "png" });
      const target = join(OUT_DIR, shot.file);
      writeFileSync(target, Buffer.from(data, "base64"));
      console.log(target);
    }
    cdp.socket.close();
  } finally {
    chrome.kill();
    demo.kill();
    await sleep(300);
    rmSync(profile, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
