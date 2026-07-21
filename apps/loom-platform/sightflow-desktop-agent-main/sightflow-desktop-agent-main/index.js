"use strict";
const electron = require("electron");
const path = require("path");
const utils = require("@electron-toolkit/utils");
const permission = require("./chunks/permission-BwwSmAFW.js");
const Store = require("electron-store");
const http = require("http");
const promises = require("node:fs/promises");
const node_module = require("node:module");
const path$1 = require("node:path");
const node_url = require("node:url");
require("jimp");
require("active-win");
require("pixelmatch");
require("pngjs");
function _interopNamespaceDefault(e) {
  const n = Object.create(null, { [Symbol.toStringTag]: { value: "Module" } });
  if (e) {
    for (const k in e) {
      if (k !== "default") {
        const d = Object.getOwnPropertyDescriptor(e, k);
        Object.defineProperty(n, k, d.get ? d : {
          enumerable: true,
          get: () => e[k]
        });
      }
    }
  }
  n.default = e;
  return Object.freeze(n);
}
const http__namespace = /* @__PURE__ */ _interopNamespaceDefault(http);
const icon = path.join(__dirname, "../../resources/icon.png");
class HttpApiServer {
  constructor(config) {
    this.config = config;
  }
  config;
  server = null;
  device = null;
  attachDevice(device) {
    this.device = device;
  }
  getPort() {
    return this.config.port;
  }
  getToken() {
    return this.config.token || "";
  }
  start() {
    return new Promise((resolve, reject) => {
      this.server = http.createServer(async (req, res) => {
        const origin = String(req.headers.origin || "");
        if (this.isAllowedOrigin(origin)) {
          res.setHeader("Access-Control-Allow-Origin", origin);
        }
        res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
        res.setHeader(
          "Access-Control-Allow-Headers",
          "Content-Type, Authorization, X-Desktop-Agent-Token"
        );
        if (req.method === "OPTIONS") {
          res.writeHead(204);
          res.end();
          return;
        }
        if (!this.isAuthorized(req)) {
          res.writeHead(401, { "Content-Type": "application/json; charset=utf-8" });
          res.end(JSON.stringify({ success: false, error: "unauthorized" }));
          return;
        }
        try {
          const body = await this.readBody(req);
          const result = await this.handleRequest(req.url || "/", req.method || "GET", body);
          res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
          res.end(JSON.stringify(result));
        } catch (err) {
          res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
          res.end(
            JSON.stringify({
              success: false,
              error: err instanceof Error ? err.message : String(err)
            })
          );
        }
      });
      const host = this.config.host || "127.0.0.1";
      this.server.listen(this.config.port, host, () => {
        console.log(`[HttpApiServer] Listening on http://${host}:${this.config.port}`);
        resolve();
      });
      this.server.on("error", (err) => {
        console.error("[HttpApiServer] Server error:", err);
        reject(err);
      });
    });
  }
  stop() {
    if (this.server) {
      this.server.close();
      this.server = null;
      console.log("[HttpApiServer] Stopped");
    }
  }
  async handleRequest(url, _method, body) {
    const path2 = url.split("?")[0];
    switch (path2) {
      // ── 健康检查 ──
      case "/health":
      case "/":
        return {
          success: true,
          status: "running",
          engine: false,
          device: !!this.device,
          tools: [
            "screenshot",
            "click",
            "type",
            "vlm_detect",
            "wechat_send",
            "wechat_unread",
            "measure_layout"
          ]
        };
      // ── 截屏 ──
      case "/screenshot":
        return await this.handleScreenshot(body);
      // ── 鼠标点击 ──
      case "/click":
        return await this.handleClick(body);
      // ── 键盘输入 ──
      case "/type":
        return await this.handleType(body);
      // ── 发送微信消息（高级：自动定位输入框 + 粘贴 + 回车） ──
      case "/wechat/send":
        return await this.handleWechatSend(body);
      // ── 未读检测 ──
      case "/wechat/unread":
        return await this.handleWechatUnread(body);
      // ── 联系人未读细检测 ──
      case "/wechat/contact_unread":
        return await this.handleContactUnread();
      // ── 布局测量 ──
      case "/measure_layout":
        return await this.handleMeasureLayout();
      // ── 聊天区域 diff ──
      case "/wechat/chat_diff":
        return await this.handleChatDiff();
      // ── 引擎状态 ──
      case "/engine/status":
        return {
          success: true,
          running: false
        };
      default:
        return { success: false, error: `Unknown endpoint: ${path2}` };
    }
  }
  // ── 工具实现 ──
  async handleScreenshot(_body) {
    this.requireDevice();
    const screenshot = await this.device.screenshot();
    return {
      success: true,
      // 返回 base64 截图（含 data:image/png;base64, 前缀）
      screenshot,
      timestamp: Date.now()
    };
  }
  async handleClick(body) {
    this.requireDevice();
    const { x, y, coordinates } = body || {};
    let clickX, clickY;
    if (coordinates && Array.isArray(coordinates)) {
      clickX = coordinates[0];
      clickY = coordinates[1];
    } else if (typeof x === "number" && typeof y === "number") {
      clickX = x;
      clickY = y;
    } else {
      return {
        success: false,
        error: "Missing coordinates. Provide {x, y} or {coordinates: [x, y]}"
      };
    }
    await this.device.clickAt(clickX, clickY);
    return { success: true, clicked: { x: clickX, y: clickY } };
  }
  async handleType(body) {
    this.requireDevice();
    const { text } = body || {};
    if (!text) {
      return { success: false, error: 'Missing "text" field' };
    }
    await this.device.sendMessage(String(text));
    return { success: true, typed: text };
  }
  async handleWechatSend(body) {
    this.requireDevice();
    const { text } = body || {};
    if (!text) {
      return { success: false, error: 'Missing "text" field' };
    }
    await this.device.sendMessage(String(text));
    return { success: true, sent: text };
  }
  async handleWechatUnread(_body) {
    this.requireDevice();
    const result = await this.device.hasUnreadMessage();
    return {
      success: true,
      hasUnread: result.hasUnread,
      chatEntranceArea: result.chatEntranceArea || null
    };
  }
  async handleContactUnread() {
    this.requireDevice();
    const result = await this.device.isChatContactUnread();
    return {
      success: true,
      isUnread: result.isUnread,
      firstContactCoords: result.firstContactCoords || null
    };
  }
  async handleMeasureLayout() {
    this.requireDevice();
    const result = await this.device.measureLayout();
    return {
      success: true,
      measured: result.success,
      error: result.error || null
    };
  }
  async handleChatDiff() {
    this.requireDevice();
    const result = await this.device.hasChatAreaChanged();
    return {
      success: true,
      hasDiff: result.hasDiff,
      hasBaseline: result.hasBaseline
    };
  }
  // ── 辅助 ──
  requireDevice() {
    if (!this.device) {
      throw new Error("Device not attached. Start the engine first.");
    }
  }
  isAuthorized(req) {
    const expectedToken = this.config.token?.trim();
    if (!expectedToken) return this.config.allowUnauthenticated === true;
    const authHeader = String(req.headers.authorization || "");
    if (authHeader === `Bearer ${expectedToken}`) return true;
    const tokenHeader = req.headers["x-desktop-agent-token"];
    if (Array.isArray(tokenHeader)) {
      return tokenHeader.includes(expectedToken);
    }
    return tokenHeader === expectedToken;
  }
  isAllowedOrigin(origin) {
    if (!origin) return false;
    try {
      const parsed = new URL(origin);
      return parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1" || parsed.hostname === "[::1]";
    } catch {
      return false;
    }
  }
  readBody(req) {
    return new Promise((resolve) => {
      if (req.method === "GET") {
        resolve({});
        return;
      }
      let data = "";
      req.on("data", (chunk) => {
        data += chunk;
      });
      req.on("end", () => {
        if (!data) {
          resolve({});
          return;
        }
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve({});
        }
      });
    });
  }
}
function rectCenter(rect) {
  return [rect.x + rect.width / 2, rect.y + rect.height / 2];
}
class BoxSelectDevice {
  appType = "generic";
  regions;
  chatBaseline = null;
  constructor(regions = null) {
    this.regions = regions;
  }
  setAppType(appType) {
    this.appType = appType;
  }
  // BoxSelectDevice 不需要视觉密钥；保留 no-op 以满足接口（engine:updateConfig 会调）。
  setApiKey(apiKey, _config) {
  }
  setRegions(regions) {
    this.regions = regions;
  }
  getRegions() {
    return this.regions;
  }
  // ── 生命周期 ──
  onSessionStop() {
    permission.clearLayoutCache(this.appType);
    this.chatBaseline = null;
  }
  // ── 感知层 ──
  async measureLayout() {
    if (!this.regions) {
      return { success: false, error: "尚未保存框选区域，请先完成框选向导" };
    }
    const required = [
      ["contactList", this.regions.contactList],
      ["chatMain", this.regions.chatMain],
      ["inputBox", this.regions.inputBox]
    ];
    for (const [name, rect] of required) {
      if (!rect || rect.width <= 0 || rect.height <= 0) {
        return { success: false, error: `框选区域 ${name} 无效，请重新框选` };
      }
    }
    const chatMainCenter = rectCenter(this.regions.chatMain);
    const inputBoxCenter = rectCenter(this.regions.inputBox);
    const layout = {
      chatEntranceArea: null,
      firstContact: null,
      searchInputBox: null,
      headerArea: null,
      chatMainArea: {
        rect: this.regions.chatMain,
        coordinates: chatMainCenter,
        source: "box-select"
      },
      messageInputArea: {
        rect: this.regions.inputBox,
        coordinates: inputBoxCenter,
        source: "box-select"
      },
      timestamp: Date.now(),
      appType: this.appType
    };
    permission.setLayoutCache(this.appType, layout);
    return { success: true };
  }
  // 把 chatMain 区域截图作为"会话上下文"返回给 provider VLM 分析。
  // 比起 RPADevice 整窗截图，这里更聚焦于聊天内容，省 token 且与目标 app 无关。
  async screenshot() {
    const image = await permission.captureChatMainArea(this.appType);
    if (!image) {
      throw new Error("chatMain 截图失败");
    }
    return image.toDataURL();
  }
  // 单会话模式：BoxSelectDevice 只关心"当前已经打开的对话窗口里有没有新内容"，
  // 不去扫 contactList 红点 / 点击切换会话。原因：第三方 IM（飞书 / 钉钉 / Slack 等）
  // 联系人列表布局差异太大，「激活联系人 → 回到输入框」的来回点击经常打偏，
  // 失败的代价很大（点错地方、误发到别的会话）。
  //
  // hasUnreadMessage 永远返回 false，让 GenericChannelSession 退化到 wait_retry
  // 循环，下一轮 check_unread 时只走 hasChatAreaChanged（chatMain pixel diff）。
  // 用户只要把目标对话窗口保持打开，新消息进来 → diff 命中 → 触发 observe_chat。
  async hasUnreadMessage() {
    return { hasUnread: false };
  }
  // 单会话模式下不会被调用到（hasUnreadMessage 已返回 false）；保留实现以满足接口。
  async isChatContactUnread() {
    return { isUnread: false };
  }
  // box-select 没有 VLM 缓存可清；no-op。
  clearUnreadCache() {
  }
  // ── chatMainArea Diff ──
  async setChatBaseline() {
    const image = await permission.captureChatMainArea(this.appType);
    if (!image) {
      console.warn("[BoxSelectDevice] baseline 设置失败: chatMain 截图为空");
      return false;
    }
    this.chatBaseline = image.toPNG();
    return true;
  }
  async hasChatAreaChanged() {
    if (!this.chatBaseline) return { hasDiff: false, hasBaseline: false };
    const image = await permission.captureChatMainArea(this.appType);
    if (!image) {
      return { hasDiff: false, hasBaseline: true };
    }
    const current = image.toPNG();
    const cmp = permission.comparePngBuffers(this.chatBaseline, current, {
      threshold: 0.1,
      changeThreshold: 0.5
    });
    return { hasDiff: cmp.hasChanged && !cmp.identical, hasBaseline: true };
  }
  clearChatBaseline() {
    this.chatBaseline = null;
  }
  // ── 动作层 ──
  async sendMessage(text) {
    const inputArea = permission.getInputAreaFromCache(this.appType);
    if (!inputArea) throw new Error("尚未测量输入框区域");
    const [x, y] = inputArea.coordinates;
    const submitMode = permission.defaultSubmitMode(this.appType);
    const ok = await permission.sendReplyByCoordsAction(x, y, text, {
      submitMode: submitMode === "mouse" && inputArea.rect ? "mouse" : "keyboard",
      submitTarget: inputArea.rect
    });
    if (!ok) throw new Error("发送消息失败");
  }
  // 通用 IM 一般单击就能切换会话，统一走 defaultClickPolicy(appType)，
  // wechat 双击的特例由 RPADevice 自己负责。
  async activeUnreadByClick(coordinates) {
    await permission.activeUnreadByClickAction(coordinates, this.appType, permission.defaultClickPolicy(this.appType));
  }
  async clickUnreadContact(coordinates) {
    await permission.clickUnreadContactAction(coordinates);
  }
  async clickAt(x, y) {
    await permission.clickUnreadContactAction([x, y]);
  }
}
class RuntimeHost {
  constructor(options) {
    this.options = options;
    this.context = {
      appType: options.appType,
      state: options.initialState,
      host: this.createControls()
    };
  }
  options;
  running = false;
  stopping = false;
  processingQueue = false;
  queue = [];
  timers = /* @__PURE__ */ new Set();
  context;
  async startSession() {
    if (this.running) return;
    this.running = true;
    this.stopping = false;
    this.log("reply", "引擎已启动");
    try {
      await this.options.channel.onStart(this.context);
    } catch (error) {
      this.log("error", error?.message || String(error));
      await this.stopSession("start_failed");
      throw error;
    }
  }
  async stopSession(_reason) {
    if (!this.running || this.stopping) return;
    this.stopping = true;
    this.running = false;
    for (const timer of this.timers) {
      clearTimeout(timer);
    }
    this.timers.clear();
    this.queue.length = 0;
    try {
      await this.options.channel.onStop(this.context);
    } finally {
      this.processingQueue = false;
      this.stopping = false;
      this.log("skip", "引擎已停止");
    }
  }
  isRunning() {
    return this.running;
  }
  updateAppType(appType) {
    this.context.appType = appType;
  }
  createControls() {
    return {
      enqueue: (event) => this.enqueue(event),
      schedule: (event, delayMs) => this.schedule(event, delayMs),
      runProvider: (input) => this.options.provider.run(input),
      log: (type, content) => this.log(type, content),
      isRunning: () => this.running,
      stopSession: async (reason) => this.stopSession(reason)
    };
  }
  enqueue(event) {
    if (!this.running) return;
    this.queue.push(event);
    void this.drainQueue();
  }
  schedule(event, delayMs) {
    if (!this.running) return;
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      this.enqueue(event);
    }, delayMs);
    this.timers.add(timer);
  }
  async drainQueue() {
    if (this.processingQueue || !this.running) return;
    this.processingQueue = true;
    try {
      while (this.queue.length > 0 && this.running) {
        const event = this.queue.shift();
        if (!event) continue;
        await this.options.channel.onEvent(event, this.context);
      }
    } catch (error) {
      this.log("error", error?.message || String(error));
      await this.stopSession("runtime_error");
    } finally {
      this.processingQueue = false;
    }
  }
  log(type, content) {
    if (this.options.onLog) {
      this.options.onLog(type, content);
    } else {
      console.log(`[RuntimeHost] [${type}] ${content}`);
    }
  }
}
function createInitialGenericChannelState() {
  return {
    measuredAt: null,
    latestChatBaseline: null
  };
}
class GenericChannelSession {
  constructor(device) {
    this.device = device;
  }
  device;
  retryDelayMs = 5e3;
  consecutiveUnreadFailures = 0;
  async onStart(ctx) {
    this.device.setAppType(ctx.appType);
    this.device.clearChatBaseline();
    this.consecutiveUnreadFailures = 0;
    this.resetState(ctx.state);
    await this.device.onSessionStart?.();
    ctx.host.enqueue({ type: "bootstrap" });
  }
  async onStop(ctx) {
    this.device.clearChatBaseline();
    this.consecutiveUnreadFailures = 0;
    await this.device.onSessionStop?.();
    this.resetState(ctx.state);
  }
  async onEvent(event, ctx) {
    this.device.setAppType(ctx.appType);
    switch (event.type) {
      case "bootstrap": {
        ctx.host.log("thinking", "正在识别聊天窗口布局...");
        const result = await this.device.measureLayout();
        if (!result.success) {
          ctx.host.log("error", `${result.error || "界面识别失败"}，引擎无法启动`);
          await ctx.host.stopSession("bootstrap_failed");
          return;
        }
        ctx.state.measuredAt = Date.now();
        ctx.host.log("thinking", "聊天窗口识别完成");
        ctx.host.enqueue({ type: "observe_chat" });
        break;
      }
      case "observe_chat": {
        const screenshot = await this.device.screenshot();
        void this.forwardProviderEvents(screenshot, ctx);
        break;
      }
      case "provider.thinking":
        ctx.host.log("thinking", event.content);
        break;
      case "provider.reply_text":
        await this.device.sendMessage(event.content);
        ctx.host.log("reply", event.content);
        await this.device.setChatBaseline();
        ctx.state.latestChatBaseline = Date.now();
        ctx.host.enqueue({ type: "check_unread" });
        break;
      case "provider.skip":
        ctx.host.log("skip", "本轮无需回复");
        await this.device.setChatBaseline();
        ctx.state.latestChatBaseline = Date.now();
        ctx.host.enqueue({ type: "check_unread" });
        break;
      case "provider.error":
        ctx.host.log("error", `回复服务异常：${event.error}`);
        ctx.host.enqueue({
          type: "wait_retry",
          reason: "provider_error",
          delayMs: this.retryDelayMs
        });
        break;
      case "check_unread": {
        const diffResult = await this.device.hasChatAreaChanged();
        if (diffResult.hasDiff) {
          ctx.host.log("thinking", "检测到当前对话有新消息");
          ctx.host.enqueue({ type: "observe_chat" });
          break;
        }
        const unreadResult = await this.device.hasUnreadMessage();
        if (!unreadResult.hasUnread) {
          ctx.host.enqueue({
            type: "wait_retry",
            reason: "no_unread",
            delayMs: this.retryDelayMs
          });
          break;
        }
        const chatEntranceCoords = unreadResult.chatEntranceArea?.coordinates;
        if (!chatEntranceCoords) {
          ctx.host.log("error", "检测到未读消息，但未找到聊天入口位置");
          ctx.host.enqueue({
            type: "wait_retry",
            reason: "missing_chat_entrance",
            delayMs: this.retryDelayMs
          });
          break;
        }
        ctx.host.log("thinking", "检测到未读消息，正在尝试打开会话");
        await this.device.activeUnreadByClick(chatEntranceCoords);
        await this.sleep(150 + Math.random() * 100);
        const openResult = await this.tryOpenUnreadConversation(ctx);
        if (openResult === "opened") {
          ctx.host.enqueue({ type: "observe_chat" });
          break;
        }
        ctx.host.enqueue({
          type: "wait_retry",
          reason: openResult,
          delayMs: this.retryDelayMs
        });
        break;
      }
      case "wait_retry":
        ctx.host.log("skip", "等待下一轮未读检测");
        ctx.host.schedule(
          event.reason === "provider_error" ? { type: "observe_chat" } : { type: "check_unread" },
          event.delayMs ?? this.retryDelayMs
        );
        break;
    }
  }
  async forwardProviderEvents(screenshot, ctx) {
    try {
      for await (const event of ctx.host.runProvider({
        screenshot,
        appType: ctx.appType
      })) {
        if (!ctx.host.isRunning()) break;
        const sessionEvent = this.mapProviderEvent(event);
        if (sessionEvent) {
          ctx.host.enqueue(sessionEvent);
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      ctx.host.enqueue({ type: "provider.error", error: message });
    }
  }
  mapProviderEvent(event) {
    switch (event.type) {
      case "thinking":
        return { type: "provider.thinking", content: event.content };
      case "reply_text":
        return { type: "provider.reply_text", content: event.content };
      case "skip":
        return { type: "provider.skip" };
      case "error":
        return { type: "provider.error", error: event.error };
      default:
        return null;
    }
  }
  resetState(state) {
    state.measuredAt = null;
    state.latestChatBaseline = null;
  }
  async tryOpenUnreadConversation(ctx) {
    let contactResult = await this.device.isChatContactUnread();
    if (!contactResult.isUnread) {
      ctx.host.log("thinking", "当前会话没有新消息，正在重新检测...");
      await this.sleep(1e3);
      const recheckResult = await this.device.hasUnreadMessage();
      const recheckCoords = recheckResult.chatEntranceArea?.coordinates;
      if (!recheckResult.hasUnread || !recheckCoords) {
        ctx.host.log("skip", "重新检测后无未读消息，等待下一轮");
        return "contact_not_ready";
      }
      ctx.host.log("thinking", "仍检测到未读消息，正在再次尝试打开会话");
      await this.device.activeUnreadByClick(recheckCoords);
      await this.sleep(500);
      contactResult = await this.device.isChatContactUnread();
    }
    if (!contactResult.isUnread) {
      this.consecutiveUnreadFailures += 1;
      if (this.consecutiveUnreadFailures >= 3) {
        ctx.host.log(
          "thinking",
          `连续 ${this.consecutiveUnreadFailures} 次检测失败，正在重置未读识别状态`
        );
        this.device.clearUnreadCache();
        this.consecutiveUnreadFailures = 0;
        await this.sleep(500);
        contactResult = await this.device.isChatContactUnread();
        if (!contactResult.isUnread) {
          ctx.host.log("thinking", "重置后仍未成功，正在再次尝试打开会话");
          const retryUnread = await this.device.hasUnreadMessage();
          const retryCoords = retryUnread.chatEntranceArea?.coordinates;
          if (!retryUnread.hasUnread || !retryCoords) {
            ctx.host.log("skip", "重置后仍未找到可用会话入口，等待下一轮");
            return "contact_not_ready";
          }
          await this.device.activeUnreadByClick(retryCoords);
          await this.sleep(500);
          contactResult = await this.device.isChatContactUnread();
          if (!contactResult.isUnread) {
            ctx.host.log("skip", "最终检测仍失败，放弃当前轮未读切换");
            return "contact_not_ready";
          }
        }
      } else {
        ctx.host.log(
          "skip",
          `会话切换检测失败（第 ${this.consecutiveUnreadFailures} 次），等待下一轮`
        );
        return "contact_not_ready";
      }
    }
    this.consecutiveUnreadFailures = 0;
    if (!contactResult.firstContactCoords) {
      ctx.host.log("skip", "未找到联系人位置，等待下一轮");
      return "contact_not_ready";
    }
    ctx.host.log("thinking", "正在打开未读会话");
    await this.device.clickUnreadContact(contactResult.firstContactCoords);
    await this.sleep(500 + Math.random() * 300);
    this.device.clearChatBaseline();
    ctx.state.latestChatBaseline = null;
    return "opened";
  }
  sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
function isWechatLike(appType) {
  return appType === "wechat" || appType === "wework";
}
let active = null;
let listenersBound = false;
let nextId = 1;
function genWizardId() {
  return `wizard-${Date.now()}-${nextId++}`;
}
function pickWizardDisplay() {
  const cursor = electron.screen.getCursorScreenPoint();
  return electron.screen.getDisplayNearestPoint(cursor);
}
function bindIpcOnce() {
  if (listenersBound) return;
  listenersBound = true;
  electron.ipcMain.on("overlay-wizard:complete", (_evt, payload) => {
    if (!active || active.finished || active.id !== payload?.id) return;
    active.finished = true;
    active.resolve({ ok: true, regions: payload.regions });
    closeActive();
  });
  electron.ipcMain.on("overlay-wizard:cancel", (_evt, payload) => {
    if (!active || active.finished || active.id !== payload?.id) return;
    active.finished = true;
    active.resolve({ ok: false, reason: "cancelled" });
    closeActive();
  });
}
function closeActive() {
  if (!active) return;
  try {
    if (!active.window.isDestroyed()) active.window.destroy();
  } catch {
  }
  active = null;
}
async function runBoxSelectWizard(opts) {
  if (active && !active.finished) {
    return { ok: false, reason: "error" };
  }
  bindIpcOnce();
  const display = pickWizardDisplay();
  const wizardId = genWizardId();
  const win = new electron.BrowserWindow({
    x: display.bounds.x,
    y: display.bounds.y,
    width: display.bounds.width,
    height: display.bounds.height,
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    movable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    fullscreenable: false,
    focusable: true,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      sandbox: false,
      contextIsolation: true
    }
  });
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  const sendInit = () => {
    if (win.isDestroyed()) return;
    const cb = win.getContentBounds();
    win.webContents.send("overlay-wizard:init", {
      id: wizardId,
      appType: opts.appType,
      steps: opts.steps ?? ["contactList", "chatMain", "inputBox"],
      prefill: opts.prefill ?? null,
      display: {
        id: display.id,
        bounds: display.bounds,
        scaleFactor: display.scaleFactor
      },
      contentOriginAbs: { x: cb.x, y: cb.y }
    });
  };
  win.webContents.once("did-finish-load", sendInit);
  electron.ipcMain.once(`overlay-wizard:request-init:${wizardId}`, sendInit);
  const overlayHtml = "overlay.html";
  if (utils.is.dev && process.env["ELECTRON_RENDERER_URL"]) {
    win.loadURL(`${process.env["ELECTRON_RENDERER_URL"]}/${overlayHtml}`);
  } else {
    win.loadFile(path.join(__dirname, "../renderer", overlayHtml));
  }
  return await new Promise((resolve) => {
    active = { id: wizardId, window: win, resolve, finished: false };
    win.on("closed", () => {
      if (active?.id === wizardId && !active.finished) {
        active.finished = true;
        resolve({ ok: false, reason: "closed" });
        active = null;
      }
    });
  });
}
const BUILTIN_DOUBAO_PROVIDER_ID = "volcengine-ark";
function getBuiltinProviderDir(id) {
  const root = electron.app.isPackaged ? path$1.join(process.resourcesPath, "app.asar.unpacked") : electron.app.getAppPath();
  return path$1.join(root, "resources", "providers", id);
}
class BundleProviderAdapter {
  constructor(instance, manifest) {
    this.instance = instance;
    this.manifest = manifest;
  }
  instance;
  manifest;
  async *run(input) {
    for await (const event of this.instance.run(input)) {
      if (this.isProviderEvent(event)) {
        yield event;
      } else {
        yield {
          type: "error",
          error: `Invalid provider event from ${this.manifest.id}`
        };
        return;
      }
    }
  }
  isProviderEvent(event) {
    if (!event || typeof event !== "object" || typeof event.type !== "string") return false;
    switch (event.type) {
      case "thinking":
      case "reply_text":
        return typeof event.content === "string";
      case "skip":
        return true;
      case "error":
        return typeof event.error === "string";
      default:
        return false;
    }
  }
}
async function installProviderFromUrl(manifestUrl) {
  const normalizedUrl = manifestUrl.trim();
  if (!normalizedUrl) {
    throw new Error("配置清单地址不能为空");
  }
  const manifestContent = await readUrlText(normalizedUrl);
  const manifest = validateManifest(JSON.parse(manifestContent));
  const entryUrl = new URL(manifest.entry, normalizedUrl).toString();
  const entryContent = await readUrlText(entryUrl);
  const installDir = getProviderInstallDir(manifest.id, manifest.version);
  const manifestFile = path$1.join(installDir, "manifest.json");
  const entryFile = path$1.join(installDir, path$1.basename(manifest.entry));
  await promises.mkdir(installDir, { recursive: true });
  await promises.writeFile(manifestFile, `${JSON.stringify(manifest, null, 2)}
`, "utf8");
  await promises.writeFile(entryFile, entryContent, "utf8");
  return {
    installed: {
      id: manifest.id,
      name: manifest.name,
      version: manifest.version,
      entryFile,
      installedAt: (/* @__PURE__ */ new Date()).toISOString()
    },
    manifest
  };
}
async function getInstalledProviderManifest(installed) {
  if (!installed?.entryFile) return null;
  const manifestFile = path$1.join(path$1.dirname(installed.entryFile), "manifest.json");
  try {
    const content = await promises.readFile(manifestFile, "utf8");
    return validateManifest(JSON.parse(content));
  } catch {
    return null;
  }
}
async function getBuiltinDoubaoManifestRaw() {
  const dir = getBuiltinProviderDir(BUILTIN_DOUBAO_PROVIDER_ID);
  const manifestFile = path$1.join(dir, "manifest.json");
  try {
    const content = await promises.readFile(manifestFile, "utf8");
    return validateManifest(JSON.parse(content));
  } catch {
    return null;
  }
}
async function getBuiltinDoubaoManifestForUi() {
  const raw = await getBuiltinDoubaoManifestRaw();
  if (!raw) return null;
  const properties = {};
  for (const [key, field] of Object.entries(raw.configSchema.properties)) {
    if (key === "apiKey") continue;
    properties[key] = field;
  }
  const required = (raw.configSchema.required || []).filter((k) => k !== "apiKey");
  return {
    ...raw,
    configSchema: {
      type: "object",
      properties,
      required
    }
  };
}
async function getBuiltinDoubaoInstalledInfo() {
  const raw = await getBuiltinDoubaoManifestRaw();
  if (!raw) return null;
  const dir = getBuiltinProviderDir(BUILTIN_DOUBAO_PROVIDER_ID);
  return {
    id: raw.id,
    name: raw.name,
    version: raw.version,
    entryFile: path$1.join(dir, raw.entry),
    installedAt: "0"
  };
}
async function loadBuiltinDoubaoProvider(providerConfig) {
  const installed = await getBuiltinDoubaoInstalledInfo();
  if (!installed) {
    throw new Error("内置 doubao provider 资源缺失");
  }
  return loadInstalledProvider(installed, providerConfig);
}
function validateProviderConfig(manifest, config) {
  const required = manifest.configSchema.required || [];
  for (const key of required) {
    const value = config[key];
    if (value === void 0 || value === null || value === "") {
      return { valid: false, error: `缺少必填项: ${key}` };
    }
  }
  for (const [key, field] of Object.entries(manifest.configSchema.properties || {})) {
    const value = config[key];
    if (value === void 0 || value === null || value === "") continue;
    switch (field.type) {
      case "string":
      case "password":
        if (typeof value !== "string") {
          return { valid: false, error: `${key} 必须是字符串` };
        }
        break;
      case "boolean":
        if (typeof value !== "boolean") {
          return { valid: false, error: `${key} 必须是布尔值` };
        }
        break;
      case "select":
        if (typeof value !== "string" || !field.enum.includes(value)) {
          return { valid: false, error: `${key} 必须是有效选项` };
        }
        break;
    }
  }
  return { valid: true };
}
async function loadInstalledProvider(installed, providerConfig) {
  const manifest = await getInstalledProviderManifest(installed);
  if (!manifest) {
    throw new Error("未找到已安装服务的配置清单");
  }
  const validation = validateProviderConfig(manifest, providerConfig);
  if (!validation.valid) {
    throw new Error(validation.error || "聊天服务配置无效");
  }
  const loaded = await loadProviderBundleModule(installed.entryFile, manifest);
  const createProvider = resolveCreateProvider(loaded);
  if (typeof createProvider !== "function") {
    throw new Error(`服务包 ${manifest.id} 未导出 createProvider`);
  }
  const instance = createProvider({
    providerConfig,
    host: {
      log: (message) => console.log(`[ProviderBundle:${manifest.id}] ${message}`),
      platform: process.platform,
      appVersion: electron.app.getVersion()
    }
  });
  if (!instance || typeof instance.run !== "function") {
    throw new Error(`服务包 ${manifest.id} 的 createProvider 返回值无效`);
  }
  return {
    provider: new BundleProviderAdapter(instance, manifest),
    manifest
  };
}
async function loadProviderBundleModule(entryFile, manifest) {
  if (shouldUseEsmLoader(manifest, entryFile)) {
    const entryUrl = node_url.pathToFileURL(entryFile);
    entryUrl.searchParams.set("ts", String(Date.now()));
    return await import(
      /* @vite-ignore */
      entryUrl.href
    );
  }
  const runtimeRequire = node_module.createRequire(__filename);
  const resolvedEntry = runtimeRequire.resolve(entryFile);
  delete runtimeRequire.cache[resolvedEntry];
  return runtimeRequire(resolvedEntry);
}
function resolveCreateProvider(loaded) {
  if (typeof loaded.createProvider === "function") {
    return loaded.createProvider;
  }
  if (loaded.default && typeof loaded.default === "object" && typeof loaded.default.createProvider === "function") {
    return loaded.default.createProvider;
  }
  if (typeof loaded.default === "function") {
    return loaded.default;
  }
  return void 0;
}
function shouldUseEsmLoader(manifest, entryFile) {
  if (manifest.moduleType === "module") {
    return true;
  }
  if (manifest.moduleType === "commonjs") {
    return false;
  }
  return isLegacyEsmEntry(entryFile);
}
function isLegacyEsmEntry(entryFile) {
  const extension = path$1.extname(entryFile).toLowerCase();
  return extension === ".mjs" || extension === ".mts";
}
function validateManifest(input) {
  if (!input || typeof input !== "object") {
    throw new Error("Manifest 格式无效");
  }
  if (input.apiVersion !== 1) {
    throw new Error("仅支持 apiVersion = 1 的 provider manifest");
  }
  if (typeof input.id !== "string" || !input.id.trim()) {
    throw new Error("Manifest 缺少有效 id");
  }
  if (typeof input.name !== "string" || !input.name.trim()) {
    throw new Error("Manifest 缺少有效 name");
  }
  if (typeof input.version !== "string" || !input.version.trim()) {
    throw new Error("Manifest 缺少有效 version");
  }
  if (typeof input.entry !== "string" || !input.entry.trim()) {
    throw new Error("Manifest 缺少有效 entry");
  }
  if (input.moduleType !== void 0 && input.moduleType !== "module" && input.moduleType !== "commonjs") {
    throw new Error('Manifest moduleType 仅支持 "module" 或 "commonjs"');
  }
  if (!Array.isArray(input.capabilities) || input.capabilities.length !== 1 || input.capabilities[0] !== "chat") {
    throw new Error('Manifest capabilities 仅支持 ["chat"]');
  }
  const configSchema = input.configSchema;
  if (!configSchema || configSchema.type !== "object" || typeof configSchema.properties !== "object") {
    throw new Error("Manifest 缺少有效 configSchema");
  }
  for (const [key, field] of Object.entries(configSchema.properties)) {
    if (!field || typeof field !== "object") {
      throw new Error(`configSchema.properties.${key} 无效`);
    }
    if (!["string", "password", "select", "boolean"].includes(field.type)) {
      throw new Error(`字段 ${key} 的类型 ${field.type} 不受支持`);
    }
    if (typeof field.title !== "string" || !field.title.trim()) {
      throw new Error(`字段 ${key} 缺少 title`);
    }
    if (field.type === "select") {
      if (!Array.isArray(field.enum) || field.enum.some((value) => typeof value !== "string")) {
        throw new Error(`字段 ${key} 的 enum 无效`);
      }
    }
  }
  const required = Array.isArray(configSchema.required) ? configSchema.required.filter((key) => typeof key === "string") : [];
  return {
    apiVersion: 1,
    id: input.id,
    name: input.name,
    version: input.version,
    entry: input.entry,
    moduleType: input.moduleType,
    capabilities: ["chat"],
    configSchema: {
      type: "object",
      properties: configSchema.properties,
      required
    }
  };
}
function getProviderInstallDir(id, version) {
  return path$1.join(electron.app.getPath("userData"), "providers", id, version);
}
async function readUrlText(targetUrl) {
  const url = new URL(targetUrl);
  if (url.protocol === "file:") {
    return await promises.readFile(node_url.fileURLToPath(url), "utf8");
  }
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error(`不支持的 provider URL 协议: ${url.protocol}`);
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`下载失败: ${response.status} ${response.statusText}`);
  }
  return await response.text();
}
const PRIMARY_PORT = 12680;
const FALLBACK_PORT = 12681;
let server = null;
let controller = null;
let skillOperationLock = false;
function jsonResponse(res, statusCode, body) {
  res.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*"
  });
  res.end(JSON.stringify(body));
}
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > 1024) {
        req.destroy();
        reject(new Error("body_too_large"));
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    req.on("error", reject);
  });
}
const START_STATUS_MAP = {
  already_running: 409,
  no_vision_key: 400,
  no_provider: 400,
  missing_required_field: 400,
  engine_failed: 500,
  wizard_cancelled: 409
};
const PAUSE_STATUS_MAP = {
  not_running: 409,
  pause_failed: 500
};
async function handleStart(res) {
  if (!controller) {
    jsonResponse(res, 503, { ok: false, error: "controller_unavailable" });
    return;
  }
  if (skillOperationLock) {
    jsonResponse(res, 409, { ok: false, error: "operation_in_progress" });
    return;
  }
  if (controller.isRunning()) {
    jsonResponse(res, 409, { ok: false, error: "already_running" });
    return;
  }
  skillOperationLock = true;
  try {
    const result = await controller.start();
    if (result.ok) {
      jsonResponse(res, 200, { ok: true });
    } else {
      const reason = result.reason || "engine_failed";
      const status = START_STATUS_MAP[reason] ?? 500;
      jsonResponse(res, status, {
        ok: false,
        error: reason,
        message: result.message
      });
    }
  } catch (error) {
    console.error("[Skill Server] start error:", error);
    jsonResponse(res, 500, { ok: false, error: "engine_failed" });
  } finally {
    skillOperationLock = false;
  }
}
async function handlePause(res) {
  if (!controller) {
    jsonResponse(res, 503, { ok: false, error: "controller_unavailable" });
    return;
  }
  if (skillOperationLock) {
    jsonResponse(res, 409, { ok: false, error: "operation_in_progress" });
    return;
  }
  if (!controller.isRunning()) {
    jsonResponse(res, 409, { ok: false, error: "not_running" });
    return;
  }
  skillOperationLock = true;
  try {
    const result = await controller.pause();
    if (result.ok) {
      jsonResponse(res, 200, { ok: true });
    } else {
      const reason = result.reason || "pause_failed";
      const status = PAUSE_STATUS_MAP[reason] ?? 500;
      jsonResponse(res, status, {
        ok: false,
        error: reason,
        message: result.message
      });
    }
  } catch (error) {
    console.error("[Skill Server] pause error:", error);
    jsonResponse(res, 500, { ok: false, error: "pause_failed" });
  } finally {
    skillOperationLock = false;
  }
}
function handleStatus(res) {
  if (!controller) {
    jsonResponse(res, 503, { ok: false, error: "controller_unavailable" });
    return;
  }
  jsonResponse(res, 200, {
    ok: true,
    status: controller.isRunning() ? "running" : "stopped"
  });
}
async function requestHandler(req, res) {
  const { method, url } = req;
  if (method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type"
    });
    res.end();
    return;
  }
  try {
    if (url === "/skill/start" && method === "POST") {
      await readBody(req);
      await handleStart(res);
    } else if (url === "/skill/pause" && method === "POST") {
      await readBody(req);
      await handlePause(res);
    } else if (url === "/skill/status" && method === "GET") {
      handleStatus(res);
    } else {
      jsonResponse(res, 404, { ok: false, error: "not_found" });
    }
  } catch (error) {
    console.error("[Skill Server] 请求处理异常:", error);
    jsonResponse(res, 500, { ok: false, error: "internal_error" });
  }
}
function startSkillServer(engineController) {
  if (server) {
    console.warn("[Skill Server] already started, skip");
    return;
  }
  controller = engineController;
  server = http__namespace.createServer((req, res) => {
    requestHandler(req, res).catch((error) => {
      console.error("[Skill Server] Unhandled error:", error);
      try {
        jsonResponse(res, 500, { ok: false, error: "internal_error" });
      } catch {
      }
    });
  });
  server.on("error", (err) => {
    if (err.code === "EADDRINUSE" && server) {
      console.warn(
        `[Skill Server] 端口 ${PRIMARY_PORT} 被占用，尝试 fallback 端口 ${FALLBACK_PORT}`
      );
      server.listen(FALLBACK_PORT, "127.0.0.1", () => {
        console.log(`[Skill Server] 已启动，监听 http://127.0.0.1:${FALLBACK_PORT}`);
      });
    } else {
      console.error("[Skill Server] 启动失败:", err);
    }
  });
  server.listen(PRIMARY_PORT, "127.0.0.1", () => {
    console.log(`[Skill Server] 已启动，监听 http://127.0.0.1:${PRIMARY_PORT}`);
  });
}
function stopSkillServer() {
  if (server) {
    server.close(() => {
      console.log("[Skill Server] 已关闭");
    });
    server = null;
  }
  controller = null;
  skillOperationLock = false;
}
const StoreClass = typeof Store === "function" ? Store : Store.default;
const FIXED_ARK_MODEL = "doubao-seed-2-0-lite-260215";
const FIXED_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3";
function cleanRuntimeString(value) {
  return typeof value === "string" ? value.trim() : "";
}
function normalizeArkBaseURL(value) {
  return (cleanRuntimeString(value) || FIXED_ARK_BASE_URL).replace(/\/+$/, "");
}
function resolveArkRuntimeConfig(settings, overrides = {}) {
  const providerConfig = settings.chatProvider?.config && typeof settings.chatProvider.config === "object" ? settings.chatProvider.config : {};
  const merged = { ...providerConfig, ...overrides };
  return {
    apiKey: cleanRuntimeString(overrides.apiKey) || cleanRuntimeString(settings.vision?.apiKey) || cleanRuntimeString(providerConfig.apiKey),
    model: cleanRuntimeString(merged.model) || FIXED_ARK_MODEL,
    baseURL: normalizeArkBaseURL(merged.baseURL)
  };
}
const DEFAULT_PROVIDER_HUB_URL = process.env.LUMINODE_PROVIDER_HUB_URL || process.env.SIGHTFLOW_PROVIDER_HUB_URL || "";
const PROVIDER_HUB_CACHE_KEY = "providerHubCache";
const settingsStore = new StoreClass({
  name: "settings",
  defaults: {
    locale: "zh",
    appType: "wechat",
    vision: { apiKey: "" },
    chatProvider: {
      manifestUrl: "",
      installed: null,
      config: {}
    },
    defaultCaptureStrategy: "auto",
    capture: {}
  }
});
let runtime = null;
let runtimeDevice = null;
let settingsWindow = null;
let httpApiServer = null;
let standaloneHttpApiDevice = null;
function getArgValue(name) {
  const prefix = `${name}=`;
  const exactIndex = process.argv.indexOf(name);
  if (exactIndex >= 0 && process.argv[exactIndex + 1]) return process.argv[exactIndex + 1];
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : "";
}
function hasArg(name) {
  return process.argv.includes(name) || process.argv.some((arg) => arg.startsWith(`${name}=`));
}
function normalizeLauncherAppType(raw) {
  const v = (raw || "").toLowerCase();
  if (v === "weixin" || v === "wechat" || v === "") return "wechat";
  const allowed = ["wechat", "wework", "dingtalk", "lark", "slack", "telegram", "generic"];
  return allowed.includes(v) ? v : "wechat";
}
function maybeStartLauncherSidecar() {
  if (httpApiServer) return;
  const autostart = process.env.LUMINODE_HTTP_API_AUTOSTART || process.env.SIGHTFLOW_HTTP_API_AUTOSTART || "";
  if (autostart !== "1" && !hasArg("--luminode-sidecar")) return;
  const apiPort = Number(getArgValue("--port") || process.env.LUMINODE_HTTP_API_PORT || process.env.SIGHTFLOW_HTTP_API_PORT || "21900") || 21900;
  const token = getArgValue("--token") || process.env.LUMINODE_AGENT_TOKEN || process.env.SIGHTFLOW_AGENT_TOKEN || "";
  const appType = normalizeLauncherAppType(
    getArgValue("--app-type") || process.env.LUMINODE_APP_TYPE || process.env.SIGHTFLOW_APP_TYPE || ""
  );
  const apiKey = getArgValue("--api-key") || process.env.LUMINODE_API_KEY || process.env.SIGHTFLOW_API_KEY || "";
  const baseURL = getArgValue("--base-url") || process.env.LUMINODE_BASE_URL || process.env.SIGHTFLOW_BASE_URL || "";
  const model = getArgValue("--model") || process.env.LUMINODE_MODEL || process.env.SIGHTFLOW_MODEL || "";
  httpApiServer = new HttpApiServer({ port: apiPort, host: "127.0.0.1", token });
  standaloneHttpApiDevice = new permission.RPADevice();
  standaloneHttpApiDevice.setAppType(appType);
  if (apiKey) {
    standaloneHttpApiDevice.setApiKey(apiKey, { baseURL, model });
  }
  httpApiServer.attachDevice(standaloneHttpApiDevice);
  httpApiServer.start().catch((err) => {
    console.error("[Main] Launcher sidecar HTTP API start error:", err);
    httpApiServer = null;
  });
}
function createWindow() {
  const mainWindow = new electron.BrowserWindow({
    width: 420,
    height: 700,
    minWidth: 360,
    minHeight: 500,
    show: false,
    autoHideMenuBar: true,
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 12, y: 12 },
    backgroundColor: "#0a0b10",
    ...process.platform === "linux" ? { icon } : {},
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      sandbox: false
    }
  });
  mainWindow.on("ready-to-show", () => {
    mainWindow.show();
  });
  mainWindow.webContents.setWindowOpenHandler((details) => {
    electron.shell.openExternal(details.url);
    return { action: "deny" };
  });
  if (utils.is.dev && process.env["ELECTRON_RENDERER_URL"]) {
    mainWindow.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }
}
function createSettingsWindow() {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.show();
    settingsWindow.focus();
    return;
  }
  settingsWindow = new electron.BrowserWindow({
    width: 900,
    height: 720,
    minWidth: 860,
    minHeight: 640,
    show: false,
    autoHideMenuBar: true,
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 14, y: 14 },
    backgroundColor: "#0a0b10",
    ...process.platform === "linux" ? { icon } : {},
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      sandbox: false
    }
  });
  settingsWindow.on("ready-to-show", () => {
    settingsWindow?.show();
  });
  settingsWindow.on("closed", () => {
    settingsWindow = null;
  });
  settingsWindow.webContents.setWindowOpenHandler((details) => {
    electron.shell.openExternal(details.url);
    return { action: "deny" };
  });
  if (utils.is.dev && process.env["ELECTRON_RENDERER_URL"]) {
    settingsWindow.loadURL(`${process.env["ELECTRON_RENDERER_URL"]}?window=settings`);
  } else {
    settingsWindow.loadFile(path.join(__dirname, "../renderer/index.html"), {
      query: { window: "settings" }
    });
  }
}
function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function normalizeFieldType(value, format) {
  if (value === "password" || value === "url" || value === "select" || value === "textarea") {
    return value;
  }
  if (format === "password") return "password";
  if (format === "uri" || format === "url") return "url";
  return "text";
}
function normalizeOptions(value) {
  if (!Array.isArray(value)) return void 0;
  const options = value.map((item) => {
    if (typeof item === "string") return { label: item, value: item };
    if (!isRecord(item)) return null;
    const label = typeof item.label === "string" ? item.label : String(item.value || "");
    const optionValue = typeof item.value === "string" ? item.value : "";
    return optionValue ? { label, value: optionValue } : null;
  }).filter(Boolean);
  return options.length ? options : void 0;
}
function normalizeManifestConfigFields(configSchema) {
  if (!isRecord(configSchema)) return [];
  const required = Array.isArray(configSchema.required) ? configSchema.required.filter((key) => typeof key === "string") : [];
  if (Array.isArray(configSchema.fields)) {
    return configSchema.fields.map((field) => {
      if (!isRecord(field) || typeof field.key !== "string") return null;
      return {
        key: field.key,
        label: typeof field.label === "string" ? field.label : field.key,
        type: normalizeFieldType(field.type),
        required: field.required === true || required.includes(field.key),
        readonly: field.readonly === true,
        placeholder: typeof field.placeholder === "string" ? field.placeholder : void 0,
        hint: typeof field.hint === "string" ? field.hint : void 0,
        defaultValue: typeof field.defaultValue === "string" ? field.defaultValue : void 0,
        options: normalizeOptions(field.options)
      };
    }).filter(Boolean);
  }
  if (!isRecord(configSchema.properties)) return [];
  return Object.entries(configSchema.properties).map(([key, property]) => {
    const schema = isRecord(property) ? property : {};
    const title = typeof schema.title === "string" ? schema.title : key;
    return {
      key,
      label: title,
      type: normalizeFieldType(schema.type, schema.format),
      required: required.includes(key),
      readonly: schema.readonly === true || schema.readOnly === true,
      placeholder: typeof schema.placeholder === "string" ? schema.placeholder : void 0,
      hint: typeof schema.description === "string" ? schema.description : void 0,
      defaultValue: typeof schema.default === "string" ? schema.default : void 0,
      options: normalizeOptions(schema.enum)
    };
  });
}
async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`);
  }
  return response.json();
}
function getCachedProviderHub() {
  const cached = settingsStore.get(PROVIDER_HUB_CACHE_KEY);
  if (!isRecord(cached) || !Array.isArray(cached.providers)) return null;
  return cached;
}
async function fetchProviderHub(url = DEFAULT_PROVIDER_HUB_URL) {
  if (!url) {
    return { sourceUrl: "", fetchedAt: (/* @__PURE__ */ new Date()).toISOString(), providers: [] };
  }
  const hub = await fetchJson(url);
  if (!isRecord(hub) || !Array.isArray(hub.providers)) {
    throw new Error("Provider hub JSON must contain a providers array");
  }
  const providers = await Promise.all(
    hub.providers.filter((entry) => entry?.enabled !== false && typeof entry?.manifestUrl === "string").map(async (entry) => {
      const manifestUrl = entry.manifestUrl;
      const manifest = await fetchJson(manifestUrl);
      const id = typeof manifest.id === "string" ? manifest.id : typeof entry.id === "string" ? entry.id : manifestUrl;
      const name = typeof manifest.name === "string" ? manifest.name : id;
      const version = typeof manifest.version === "string" ? manifest.version : "0.0.0";
      const capabilities = Array.isArray(manifest.capabilities) ? manifest.capabilities.filter((item) => typeof item === "string") : void 0;
      const description = typeof manifest.description === "string" ? manifest.description : void 0;
      return {
        id,
        name,
        description,
        version,
        manifestUrl,
        capabilities,
        configSchema: {
          fields: normalizeManifestConfigFields(manifest.configSchema)
        }
      };
    })
  );
  const cache = {
    sourceUrl: url,
    fetchedAt: (/* @__PURE__ */ new Date()).toISOString(),
    providers
  };
  settingsStore.set(PROVIDER_HUB_CACHE_KEY, cache);
  return cache;
}
electron.app.whenReady().then(async () => {
  utils.electronApp.setAppUserModelId("com.electron");
  await permission.checkAndRequestPermissions();
  electron.app.on("browser-window-created", (_, window) => {
    utils.optimizer.watchWindowShortcuts(window);
  });
  electron.ipcMain.on("ping", () => console.log("pong"));
  electron.ipcMain.handle("settings:getAll", async () => {
    return normalizeSettings(settingsStore.store);
  });
  electron.ipcMain.handle("settings:get", async (_event, key) => {
    const settings = normalizeSettings(settingsStore.store);
    return settings[key];
  });
  electron.ipcMain.handle("settings:set", async (_event, data) => {
    const current = normalizeSettings(settingsStore.store);
    const next = {
      ...current,
      ...data,
      vision: {
        ...current.vision,
        ...data.vision || {}
      },
      chatProvider: {
        ...current.chatProvider,
        ...data.chatProvider || {},
        config: {
          ...current.chatProvider.config,
          ...data.chatProvider?.config || {}
        }
      },
      capture: {
        ...current.capture,
        ...data.capture || {}
      }
    };
    settingsStore.set(next);
    return { success: true };
  });
  electron.ipcMain.handle("provider:installFromUrl", async (_event, manifestUrl) => {
    try {
      const result = await installProviderFromUrl(manifestUrl);
      const current = normalizeSettings(settingsStore.store);
      settingsStore.set({
        ...current,
        chatProvider: {
          ...current.chatProvider,
          manifestUrl,
          installed: result.installed,
          config: withSchemaDefaults(result.manifest.configSchema, current.chatProvider.config)
        }
      });
      return {
        success: true,
        installed: result.installed,
        manifest: result.manifest
      };
    } catch (error) {
      return { success: false, error: error?.message || String(error) };
    }
  });
  electron.ipcMain.handle("provider:getInstalled", async () => {
    const settings = normalizeSettings(settingsStore.store);
    if (settings.chatProvider.installed) {
      const manifest2 = await getInstalledProviderManifest(settings.chatProvider.installed);
      return {
        installed: settings.chatProvider.installed,
        manifest: manifest2,
        isBuiltinDefault: false
      };
    }
    const installed = await getBuiltinDoubaoInstalledInfo();
    const manifest = await getBuiltinDoubaoManifestForUi();
    return {
      installed,
      manifest,
      isBuiltinDefault: true
    };
  });
  electron.ipcMain.handle("providerHub:getCatalog", async () => {
    const cached = getCachedProviderHub();
    if (cached) return { success: true, catalog: cached };
    try {
      const catalog = await fetchProviderHub();
      return { success: true, catalog };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { success: false, error: message, catalog: null };
    }
  });
  electron.ipcMain.handle("providerHub:update", async () => {
    try {
      const catalog = await fetchProviderHub();
      return { success: true, catalog };
    } catch (error) {
      const cached = getCachedProviderHub();
      const message = error instanceof Error ? error.message : String(error);
      return { success: false, error: message, catalog: cached };
    }
  });
  electron.ipcMain.handle("settings:open", async () => {
    createSettingsWindow();
    return { success: true };
  });
  electron.ipcMain.handle("engine:start", async (_event, config) => {
    const result = await startEngineCore(config);
    if (result.ok) return { success: true };
    return { success: false, error: result.message || result.reason };
  });
  electron.ipcMain.handle("engine:stop", async (_event, reason) => {
    const result = await stopEngineCore(reason || "ipc_stop");
    if (result.ok) return { success: true };
    return { success: false, error: result.message || result.reason };
  });
  electron.ipcMain.handle("engine:status", async () => {
    return { running: runtime?.isRunning() ?? false };
  });
  electron.ipcMain.handle("engine:updateConfig", async (_event, config) => {
    const settings = normalizeSettings(config || settingsStore.store);
    if (runtimeDevice) {
      const arkConfig = resolveArkRuntimeConfig(settings);
      runtimeDevice.setApiKey(arkConfig.apiKey, {
        baseURL: arkConfig.baseURL,
        model: arkConfig.model
      });
      runtimeDevice.setAppType(settings.appType);
    }
    if (runtime) {
      runtime.updateAppType(settings.appType);
    }
    return { success: true };
  });
  electron.ipcMain.handle("engine:testConnection", async (_event, config) => {
    const settings = normalizeSettings(settingsStore.store);
    const arkConfig = resolveArkRuntimeConfig(settings, config || {});
    const client = new permission.AIClient({
      apiKey: arkConfig.apiKey,
      model: arkConfig.model,
      baseURL: arkConfig.baseURL
    });
    return client.testConnection();
  });
  electron.ipcMain.handle(
    "capture:openSetupWizard",
    async (_event, args) => {
      const settings = normalizeSettings(settingsStore.store);
      const appType = coerceAppType(args?.appType);
      const prefill = settings.capture[appType]?.regions ?? null;
      const result = await runBoxSelectWizard({ appType, steps: args?.steps, prefill });
      if (!result.ok || !result.regions) {
        return { success: false, reason: result.reason || "cancelled" };
      }
      const current = normalizeSettings(settingsStore.store);
      const next = {
        ...current,
        capture: {
          ...current.capture,
          [appType]: {
            strategy: current.capture[appType]?.strategy ?? "auto",
            regions: result.regions
          }
        }
      };
      settingsStore.set(next);
      notifyCaptureRegionsUpdated(appType, result.regions);
      return { success: true, regions: result.regions };
    }
  );
  electron.ipcMain.handle("capture:getRegions", async (_event, appType) => {
    const settings = normalizeSettings(settingsStore.store);
    return settings.capture[coerceAppType(appType)]?.regions ?? null;
  });
  electron.ipcMain.handle("capture:resetRegions", async (_event, appType) => {
    const current = normalizeSettings(settingsStore.store);
    const key = coerceAppType(appType);
    const next = {
      ...current,
      capture: {
        ...current.capture,
        [key]: { strategy: current.capture[key]?.strategy ?? "auto", regions: null }
      }
    };
    settingsStore.set(next);
    notifyCaptureRegionsUpdated(key, null);
    return { success: true };
  });
  electron.ipcMain.on("ping", () => console.log("pong"));
  electron.ipcMain.handle("capture-screen", async () => {
    try {
      const sources = await electron.desktopCapturer.getSources({
        types: ["screen"],
        thumbnailSize: { width: 1920, height: 1080 }
      });
      if (sources && sources.length > 0) {
        return sources[0].thumbnail.toDataURL();
      }
      return null;
    } catch (error) {
      console.error("Screen capture failed:", error);
      return null;
    }
  });
  electron.ipcMain.handle("test:vlm-parallel", async () => {
    const apiKey = normalizeSettings(settingsStore.store).vision.apiKey;
    if (!apiKey) return { error: "请先在设置中填写视觉接口密钥" };
    const { runVlmParallelTest } = await Promise.resolve().then(() => require("./chunks/test-vlm-parallel-CDZ_pWrH.js"));
    return await runVlmParallelTest(apiKey, "wechat");
  });
  startSkillServer(skillEngineController);
  maybeStartLauncherSidecar();
  createWindow();
  electron.app.on("activate", function() {
    if (electron.BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});
electron.app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    electron.app.quit();
  }
});
electron.app.on("before-quit", () => {
  stopSkillServer();
  if (httpApiServer) {
    httpApiServer.stop();
    httpApiServer = null;
  }
});
async function startEngineCore(rawConfig) {
  if (runtime?.isRunning()) {
    return { ok: false, reason: "already_running", message: "引擎已在运行中" };
  }
  try {
    const settings = normalizeSettings(rawConfig || settingsStore.store);
    const appType = settings.appType || "wechat";
    const startupStrategy = resolveSettingsStrategy(appType, settings);
    const providerNeedsVisionKey = !settings.chatProvider.installed || settings.chatProvider.installed.id === BUILTIN_DOUBAO_PROVIDER_ID;
    const needsVisionKey = startupStrategy === "vlm" || providerNeedsVisionKey;
    if (needsVisionKey && !settings.vision.apiKey) {
      return { ok: false, reason: "no_vision_key", message: "请先填写视觉接口密钥" };
    }
    let provider;
    if (!settings.chatProvider.installed) {
      const loaded = await loadBuiltinDoubaoProvider({
        ...settings.chatProvider.config,
        apiKey: settings.vision.apiKey
      });
      provider = loaded.provider;
    } else {
      const installedManifest = await getInstalledProviderManifest(settings.chatProvider.installed);
      const isDoubao = settings.chatProvider.installed.id === BUILTIN_DOUBAO_PROVIDER_ID;
      const required = (installedManifest?.configSchema?.required || []).filter(
        (key) => !(isDoubao && key === "apiKey")
      );
      const missing = required.find((key) => {
        const value = settings.chatProvider.config?.[key];
        return value === void 0 || value === null || value === "";
      });
      if (missing) {
        return {
          ok: false,
          reason: "missing_required_field",
          message: `缺少必填配置: ${missing}`
        };
      }
      const effectiveConfig = isDoubao ? { ...settings.chatProvider.config, apiKey: settings.vision.apiKey } : settings.chatProvider.config;
      const loaded = await loadInstalledProvider(settings.chatProvider.installed, effectiveConfig);
      provider = loaded.provider;
    }
    const mainWindow = electron.BrowserWindow.getAllWindows().find((w) => !w.isDestroyed()) ?? null;
    const log = (type, content) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("engine:log", { type, content });
      }
    };
    let device;
    let strategy;
    try {
      const built = await buildDevice(appType, settings, settings.vision.apiKey, log);
      device = built.device;
      strategy = built.strategy;
    } catch (err) {
      const message = err?.message || String(err);
      if (message === "user_cancelled_box_select_wizard") {
        return { ok: false, reason: "wizard_cancelled", message: "已取消框选，引擎未启动" };
      }
      throw err;
    }
    log("thinking", `已选用抓取策略：${strategy}`);
    runtimeDevice = device;
    const channel = new GenericChannelSession(device);
    runtime = new RuntimeHost({
      appType,
      channel,
      provider,
      initialState: createInitialGenericChannelState(),
      onLog: log
    });
    runtime.startSession().catch((err) => {
      console.error("[Main] Runtime session error:", err);
    });
    notifyEngineStateChanged("running");
    return { ok: true };
  } catch (error) {
    return {
      ok: false,
      reason: "engine_failed",
      message: error?.message || String(error)
    };
  }
}
async function stopEngineCore(stopReason) {
  if (!runtime?.isRunning()) {
    return { ok: false, reason: "not_running", message: "引擎未运行" };
  }
  try {
    await runtime.stopSession(stopReason);
    notifyEngineStateChanged("idle");
    return { ok: true };
  } catch (error) {
    return {
      ok: false,
      reason: "pause_failed",
      message: error?.message || String(error)
    };
  }
}
function notifyEngineStateChanged(status) {
  for (const win of electron.BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send("engine:state", { status });
    }
  }
}
function notifyCaptureRegionsUpdated(appType, regions) {
  for (const win of electron.BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send("capture:regions-updated", { appType, regions });
    }
  }
}
function resolveEffectiveStrategy(appType, perAppStrategy, defaultStrategy) {
  const effective = perAppStrategy === "auto" ? defaultStrategy : perAppStrategy;
  if (effective === "auto") {
    return isWechatLike(appType) ? "vlm" : "box-select";
  }
  return effective;
}
function resolveSettingsStrategy(appType, settings) {
  const perApp = settings.capture[appType] ?? { strategy: "auto" };
  return resolveEffectiveStrategy(appType, perApp.strategy, settings.defaultCaptureStrategy);
}
async function buildDevice(appType, settings, apiKey, log) {
  const perApp = settings.capture[appType] ?? { strategy: "auto", regions: null };
  const effective = resolveSettingsStrategy(appType, settings);
  if (effective === "vlm") {
    const rpa = new permission.RPADevice();
    const arkConfig = resolveArkRuntimeConfig(settings, { apiKey });
    rpa.setAppType(appType);
    rpa.setApiKey(arkConfig.apiKey, {
      baseURL: arkConfig.baseURL,
      model: arkConfig.model
    });
    return { device: rpa, strategy: "vlm" };
  }
  let regions = perApp.regions;
  if (!regions) {
    log("thinking", `首次配置 ${appType}：请框选 3 个关键区域`);
    const wizardResult = await runBoxSelectWizard({ appType, prefill: null });
    if (!wizardResult.ok || !wizardResult.regions) {
      throw new Error("user_cancelled_box_select_wizard");
    }
    regions = wizardResult.regions;
    persistRegionsAndStickyStrategy(appType, regions, perApp.strategy);
  }
  return { device: new BoxSelectDevice(regions), strategy: "box-select" };
}
function persistRegionsAndStickyStrategy(appType, regions, strategy) {
  const current = normalizeSettings(settingsStore.store);
  const next = {
    ...current,
    capture: {
      ...current.capture,
      [appType]: { strategy, regions }
    }
  };
  settingsStore.set(next);
  notifyCaptureRegionsUpdated(appType, regions);
}
const skillEngineController = {
  start: () => startEngineCore(),
  pause: () => stopEngineCore("skill_pause"),
  isRunning: () => runtime?.isRunning() ?? false
};
const VALID_APP_TYPES = [
  "wechat",
  "wework",
  "dingtalk",
  "lark",
  "slack",
  "telegram",
  "generic"
];
const VALID_CAPTURE_STRATEGIES = ["auto", "vlm", "box-select"];
function coerceAppType(raw) {
  return typeof raw === "string" && VALID_APP_TYPES.includes(raw) ? raw : "wechat";
}
function coerceStrategy(raw, fallback = "auto") {
  return typeof raw === "string" && VALID_CAPTURE_STRATEGIES.includes(raw) ? raw : fallback;
}
function coerceRect(raw) {
  if (!raw || typeof raw !== "object") return null;
  const r = raw;
  const x = Number(r.x), y = Number(r.y), w = Number(r.width), h = Number(r.height);
  if (![x, y, w, h].every((n) => Number.isFinite(n))) return null;
  return { x, y, width: w, height: h };
}
function coerceRegions(raw) {
  if (!raw || typeof raw !== "object") return null;
  const r = raw;
  const contactList = coerceRect(r.contactList);
  const chatMain = coerceRect(r.chatMain);
  const inputBox = coerceRect(r.inputBox);
  if (!contactList || !chatMain || !inputBox) return null;
  return {
    contactList,
    chatMain,
    inputBox,
    unreadIndicator: coerceRect(r.unreadIndicator),
    displayId: typeof r.displayId === "number" ? r.displayId : void 0,
    scaleFactor: typeof r.scaleFactor === "number" ? r.scaleFactor : void 0,
    capturedAt: typeof r.capturedAt === "number" ? r.capturedAt : Date.now()
  };
}
function normalizeCapture(raw) {
  const out = {};
  if (!raw || typeof raw !== "object") return out;
  for (const key of VALID_APP_TYPES) {
    const value = raw[key];
    if (!value || typeof value !== "object") continue;
    const v = value;
    out[key] = {
      strategy: coerceStrategy(v.strategy),
      regions: coerceRegions(v.regions)
    };
  }
  return out;
}
function normalizeSettings(raw) {
  const oldApiKey = typeof raw?.apiKey === "string" ? raw.apiKey : "";
  const oldModel = typeof raw?.model === "string" && raw.model ? raw.model : FIXED_ARK_MODEL;
  const oldBaseURL = typeof raw?.baseURL === "string" && raw.baseURL ? raw.baseURL : FIXED_ARK_BASE_URL;
  const oldSystemPrompt = typeof raw?.systemPrompt === "string" ? raw.systemPrompt : "";
  const rawProviderConfig = raw?.chatProvider?.config && typeof raw.chatProvider.config === "object" ? { ...raw.chatProvider.config } : {};
  if (rawProviderConfig.apiKey === void 0 && oldApiKey) {
    rawProviderConfig.apiKey = oldApiKey;
  }
  if (rawProviderConfig.model === void 0 && oldModel) {
    rawProviderConfig.model = oldModel;
  }
  if (rawProviderConfig.baseURL === void 0 && oldBaseURL) {
    rawProviderConfig.baseURL = oldBaseURL;
  }
  if (rawProviderConfig.systemPrompt === void 0 && oldSystemPrompt) {
    rawProviderConfig.systemPrompt = oldSystemPrompt;
  }
  return {
    locale: raw?.locale === "en" ? "en" : "zh",
    appType: coerceAppType(raw?.appType),
    vision: {
      apiKey: raw?.vision?.apiKey || oldApiKey || ""
    },
    chatProvider: {
      manifestUrl: raw?.chatProvider?.manifestUrl || raw?.providerManifestUrl || "",
      installed: raw?.chatProvider?.installed || null,
      config: rawProviderConfig
    },
    defaultCaptureStrategy: coerceStrategy(raw?.defaultCaptureStrategy, "auto"),
    capture: normalizeCapture(raw?.capture)
  };
}
function withSchemaDefaults(schema, current) {
  const next = { ...current };
  for (const [key, field] of Object.entries(schema.properties || {})) {
    if (next[key] === void 0 && field.default !== void 0) {
      next[key] = field.default;
    }
  }
  return next;
}
