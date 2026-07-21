import { maskSecret, toBool, toNumber, toText } from '../lib/format';

type AnyRecord = Record<string, any>;

const STORAGE_KEY = 'ui-redesign-preview.mock-state';

function nowIso(): string {
  return new Date().toISOString();
}

function svgDataUrl(title: string, subtitle: string, accent = '#c7a66a'): string {
  const safeTitle = title.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const safeSubtitle = subtitle.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="0 0 1280 800">
      <rect width="1280" height="800" fill="#0b0f14"/>
      <rect x="48" y="48" width="1184" height="704" rx="24" fill="#111820" stroke="rgba(255,255,255,0.12)"/>
      <rect x="92" y="92" width="324" height="16" rx="8" fill="${accent}" opacity="0.9"/>
      <text x="92" y="176" fill="#f3efe6" font-size="48" font-family="Georgia, serif" font-weight="700">${safeTitle}</text>
      <text x="92" y="228" fill="#afbac6" font-size="24" font-family="Avenir Next, Arial, sans-serif">${safeSubtitle}</text>
      <g fill="none" stroke="rgba(255,255,255,0.08)">
        <path d="M92 310H1188M92 390H1188M92 470H1188M92 550H1188M92 630H1188"/>
        <path d="M470 300V660M820 300V660"/>
      </g>
      <rect x="92" y="310" width="290" height="350" rx="18" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.08)"/>
      <rect x="410" y="310" width="360" height="350" rx="18" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.08)"/>
      <rect x="800" y="310" width="388" height="350" rx="18" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.08)"/>
      <circle cx="238" cy="490" r="90" fill="rgba(199,166,106,0.14)" stroke="${accent}" stroke-width="4"/>
      <text x="222" y="503" fill="${accent}" font-size="42" font-family="Consolas, monospace" font-weight="700">LIVE</text>
    </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function buildLicense() {
  return {};
}

function buildMember() {
  return {
    memberId: 'member-001',
    leaseId: 'lease-001',
    token: 'member-token-mock',
    status: 'active',
    usage: { llm: 8200, image: 4, video: 1, month: 1 },
    quota: { llm: 120000, image: 120, video: 60, month: 1 },
    expiresAt: '2026-06-20T08:30:00.000Z',
    renewAt: '2026-06-10T08:30:00.000Z',
    gatewayBaseUrl: 'https://api.heang.top/v1',
    gatewayToken: 'mock-gateway-token',
  };
}

function buildTheme() {
  return {
    theme: {
      name: '星航玻璃',
      colors: {},
      fonts: {},
      brand: {
        name: 'OpenClaw',
        subtitle: '预览控制台',
        app_user_model_id: 'OpenClaw.Preview',
        terminal_header: '预览控制台',
      },
    },
    isCustom: false,
    merchantId: null,
    themes: [
      { id: 'obsidian', name: '星航玻璃' },
      { id: 'paper', name: '档案索引' },
    ],
  };
}

function buildSkills() {
  return {
    skills: [
      {
        id: 'image-staging',
        name: '图像暂存',
        version: '1.4.0',
        description: '把生图结果送往发布链路，并保留草稿。',
        category: 'media',
        runtime: 'node',
        icon: 'IMG',
        source: 'uploaded',
        sourceLabel: '启动器上传',
        path: 'data/.openclaw/workspace/skills/image-staging',
        installed: true,
        enabled: true,
        writable: true,
        hasReadme: true,
      },
      {
        id: 'phone-runbook',
        name: '手机任务手册',
        version: '2.0.1',
        description: '标准化手机任务步骤和视觉检查。',
        category: 'automation',
        runtime: 'python',
        icon: 'PH',
        source: 'openclaw',
        sourceLabel: 'OpenClaw Scan',
        path: 'skills/phone-runbook',
        installed: true,
        enabled: false,
        writable: false,
        hasReadme: true,
      },
      {
        id: 'desktop-fix',
        name: '桌面修复',
        version: '0.8.2',
        description: '桌面 Agent 修复与环境回收脚本。',
        category: 'maintenance',
        runtime: 'node',
        icon: 'PC',
        source: 'openclaw',
        sourceLabel: 'OpenClaw Scan',
        path: 'skills/desktop-fix',
        installed: true,
        enabled: true,
        writable: false,
        hasReadme: false,
      },
    ],
    directories: [
      { key: 'user', label: '用户 Skills', path: 'data/.openclaw/workspace/skills', writable: true },
      { key: 'bundle', label: '内置 Skills', path: 'openclaw-workspace/skills', writable: false },
    ],
    sites: [
      { name: 'OpenClaw 文档', url: 'https://heang.top/docs.html' },
      { name: 'Skill 市场', url: 'https://heang.top/skills' },
    ],
    statePath: 'D:/Axiangmu/AUSTART/openclaw_new_launcher/data/.openclaw/launcher/skills-state.json',
  };
}

function buildComponents() {
  return {
    manifest: {
      schemaVersion: 1,
      product: 'OpenClaw',
      channel: 'stable',
      version: '2.2.0',
      publishedAt: '2026-06-28T00:00:00+08:00',
      minLauncherVersion: '2.1.15',
    },
    components: [
      {
        id: 'codex-desktop',
        name: 'Codex',
        version: '26.602.71036',
        installedVersion: '26.602.71036',
        previousVersion: null,
        status: 'ready',
        platform: 'windows',
        arch: 'x64',
        type: 'installer',
        size: 120000000,
        entry: 'Codex-Installer.exe',
        installPath: 'OpenClawFiles/agents/codex',
        category: 'agent',
        officialUrl: 'https://get.microsoft.com/installer/download/9PLM9XGG6VKS',
        description: 'OpenAI coding agent desktop installer.',
        urls: ['https://download.heang.top/openclaw/v2.2.0/agents/codex-desktop-windows-x64.exe'],
        updatedAt: nowIso(),
      },
      {
        id: 'claude-code',
        name: 'Claude Code',
        version: '2.1.169',
        installedVersion: null,
        previousVersion: null,
        status: 'not_installed',
        platform: 'windows',
        arch: 'x64',
        type: 'tgz',
        size: 80000000,
        entry: 'claude-code-2.1.169.tgz',
        installPath: 'OpenClawFiles/agents/claude-code',
        category: 'agent',
        officialUrl: 'https://registry.npmjs.org/@anthropic-ai/claude-code/-/claude-code-2.1.169.tgz',
        description: 'Anthropic command-line coding agent package.',
        urls: ['https://download.heang.top/openclaw/v2.2.0/agents/claude-code-2.1.169.tgz'],
        updatedAt: null,
      },
      {
        id: 'opencode',
        name: 'opencode',
        version: '2026.6.28',
        installedVersion: null,
        previousVersion: null,
        status: 'not_installed',
        platform: 'windows',
        arch: 'x64',
        type: 'zip',
        size: 60000000,
        entry: 'opencode.exe',
        installPath: 'OpenClawFiles/agents/opencode',
        category: 'agent',
        officialUrl: 'https://github.com/sst/opencode/releases',
        description: 'Terminal-first AI coding agent.',
        urls: ['https://download.heang.top/openclaw/v2.2.0/agents/opencode-windows-x64.zip'],
        updatedAt: null,
      },
      {
        id: 'openclaw-companion',
        name: 'OpenClaw',
        version: '2026.6.1',
        installedVersion: null,
        previousVersion: null,
        status: 'not_installed',
        platform: 'windows',
        arch: 'x64',
        type: 'installer',
        size: 180000000,
        entry: 'OpenClawCompanion-Setup-x64.exe',
        installPath: 'OpenClawFiles/agents/openclaw',
        category: 'agent',
        officialUrl: 'https://github.com/openclaw/openclaw/releases/download/v2026.6.1/OpenClawCompanion-Setup-x64.exe',
        description: 'OpenClaw companion installer.',
        urls: ['https://download.heang.top/openclaw/v2.2.0/agents/openclaw-companion-setup-x64.exe'],
        updatedAt: null,
      },
      {
        id: 'hermes',
        name: 'Hermes',
        version: '0.16.0',
        installedVersion: null,
        previousVersion: null,
        status: 'not_installed',
        platform: 'windows',
        arch: 'x64',
        type: 'installer',
        size: 150000000,
        entry: 'Hermes-Setup.exe',
        installPath: 'OpenClawFiles/agents/hermes',
        category: 'agent',
        officialUrl: 'https://hermes-assets.nousresearch.com/Hermes-Setup.exe?build=8d71c3891970',
        description: 'Hermes desktop agent installer.',
        urls: ['https://download.heang.top/openclaw/v2.2.0/agents/hermes-setup-windows-x64.exe'],
        updatedAt: null,
      },
    ],
    error: null,
  };
}

function buildDiagnostics() {
  return {
    report: {
      basePath: 'D:/Axiangmu/AUSTART/openclaw_new_launcher',
      serviceRunning: false,
      servicePid: null,
      startupState: 'idle',
      startupElapsedSec: 0,
      startupTimeoutSec: 420,
      startupError: '',
      startupDurationMs: null,
      startupStage: null,
      startupSnapshotPath: '',
      checks: [
        { id: 'python', label: 'Python 运行时', status: 'ok', message: 'Python 运行时可用', detail: 'python 3.10.11', repairable: false },
        { id: 'bridge', label: '桥接服务', status: 'warn', message: '桥接服务空闲', detail: '启动器可以按需启动', repairable: true },
      ],
      summary: { status: 'warn', ok: 1, warnings: 1, failed: 0, total: 2 },
      repairAvailable: true,
    },
  };
}

function buildDesktop() {
  return {
    configured: true,
    present: true,
    running: false,
    pid: null,
    apiReady: false,
    health: { ok: true, message: '预览健康检查正常', ready: false },
    command: ['python', 'desktop-agent.py'],
    config: {
      enabled: true,
      agentDir: 'D:/Axiangmu/AUSTART/sightflow-desktop-agent',
      port: 13240,
      tokenAvailable: true,
      tokenPreview: '****9A1B',
      appType: 'weixin',
      autoStartHttpApi: true,
      policy: {
        allowScreenshot: true,
        allowClick: true,
        allowType: true,
        allowWechatSend: true,
        requireConfirmForClick: true,
        requireConfirmForType: true,
        requireConfirmForSend: true,
        blockedWindowKeywords: ['密码', '支付', '授权'],
      },
      capture: { format: 'jpeg', quality: 82, maxWidth: 1600 },
      action: { clickDelayMs: 120, typeDelayMs: 80, timeoutMs: 5000 },
      wechat: { sendMode: 'api', detectUnreadMode: 'ocr' },
    },
  };
}

function buildPhoneDevices() {
  return {
    selectedDeviceId: 'pixel-8',
    devices: [
      {
        id: 'pixel-8',
        name: 'Pixel 8',
        baseUrl: 'http://192.168.1.100:9527',
        token: 'phone-token-1',
        relayBaseUrl: 'http://192.168.1.12:8848',
        relayChannelId: 'channel-alpha',
        relayToken: 'relay-token-1',
        enabled: true,
        tags: ['primary', 'wechat'],
        online: true,
        active: true,
      },
      {
        id: 'redmi-note',
        name: 'Redmi Note',
        baseUrl: 'http://192.168.1.101:9527',
        token: 'phone-token-2',
        relayBaseUrl: '',
        relayChannelId: '',
        relayToken: '',
        enabled: true,
        tags: ['backup'],
        online: false,
        active: false,
      },
    ],
    statusById: {
      'pixel-8': {
        online: true,
        taskRunning: false,
        agentInitialized: true,
        llmConfigured: true,
        accessibilityRunning: true,
        screenshotSupported: true,
        screenInfoSupported: true,
        overlayPermission: true,
        cursorOverlayEnabled: true,
        cursorPreviewSupported: true,
        screenOn: true,
        interactive: true,
        keyguardLocked: false,
        deviceLocked: false,
        version: '6.26',
        versionCode: 626,
        versionInfo: 'OpenClaw Phone 6.26',
        serverPort: 9527,
      },
      'redmi-note': {
        online: false,
        taskRunning: false,
        agentInitialized: false,
        llmConfigured: false,
        accessibilityRunning: false,
        screenshotSupported: false,
        screenInfoSupported: false,
        overlayPermission: false,
        cursorOverlayEnabled: false,
        cursorPreviewSupported: false,
        screenOn: false,
        interactive: false,
        keyguardLocked: true,
        deviceLocked: true,
        version: '6.11',
        versionCode: 611,
        versionInfo: 'OpenClaw Phone 6.11',
        serverPort: 9527,
      },
    },
    screenshotById: {
      'pixel-8': svgDataUrl('Pixel 8', '预览手机截图', '#c7a66a'),
      'redmi-note': svgDataUrl('Redmi Note', '离线设备', '#5cc8ff'),
    },
    screenTreeById: {
      'pixel-8': {
        screen: { width: 1080, height: 2400, orientation: 'portrait' },
        nodes: [
          { id: '1', parentId: null, depth: 0, className: 'android.widget.FrameLayout', text: null, description: null, resourceId: 'root', clickable: false, bounds: { left: 0, top: 0, right: 1080, bottom: 2400, width: 1080, height: 2400, centerX: 540, centerY: 1200 } },
          { id: '2', parentId: '1', depth: 1, className: 'android.widget.TextView', text: 'OpenClaw', description: '标题', resourceId: 'title', clickable: false, bounds: { left: 48, top: 96, right: 420, bottom: 144, width: 372, height: 48, centerX: 234, centerY: 120 } },
          { id: '3', parentId: '1', depth: 1, className: 'android.widget.Button', text: '发送', description: '发送按钮', resourceId: 'send', clickable: true, bounds: { left: 840, top: 2200, right: 1020, bottom: 2300, width: 180, height: 100, centerX: 930, centerY: 2250 } },
        ],
      },
    },
    deviceProfiles: {
      'pixel-8': {
        profileVersion: 2,
        capturedAt: Date.now(),
        device: { manufacturer: 'Google', model: 'Pixel 8', androidVersion: '14' },
        capabilities: { screenshot: true, accessibility: true, vision: true },
        memory: { total: '8 GB', available: '4.9 GB' },
        storage: { total: '256 GB', available: '193 GB' },
        battery: { level: 86, charging: true },
        apps: [
          { label: 'WeChat', packageName: 'com.tencent.mm', launchable: true },
          { label: 'Browser', packageName: 'mark.via', launchable: true },
        ],
        privacyNote: '仅预览数据',
      },
    },
    visionFrames: {
      'pixel-8': {
        mode: 'frame',
        capturedAt: nowIso(),
        currentScreen: { title: 'OpenClaw', page: 'home' },
        vision: { summary: 'Dashboard layout', focus: 'top-left' },
        input: { points: 3, state: 'ready' },
        safety: { blocked: false },
        image: {
          mime: 'image/svg+xml',
          base64: btoa('<svg xmlns="http://www.w3.org/2000/svg"/>'),
          dataUrl: svgDataUrl('Pixel 8', '视觉帧', '#67c7bd'),
          width: 1080,
          height: 2400,
          originalWidth: 1080,
          originalHeight: 2400,
          orientation: 'portrait',
          format: 'svg',
          quality: 100,
          overlayGrid: true,
          maxLongSide: 2400,
        },
        coordinateSpace: {
          screenWidth: 1080,
          screenHeight: 2400,
          imageWidth: 1080,
          imageHeight: 2400,
          actionCoordinates: 'screen',
          grid: { columns: 6, rows: 12, cellFormat: 'A1', firstCell: 'A1', lastCell: 'F12' },
        },
      },
    },
    recordings: {
      'pixel-8': [
        {
          exists: true,
          id: 'record-001',
          filename: 'screen-20260525-001.mp4',
          path: 'mock://phone/pixel-8/screen-20260525-001.mp4',
          sizeBytes: 8_782_124,
          modifiedAt: '2026-05-25T10:04:00.000Z',
          downloadUrl: 'mock://phone/pixel-8/screen-20260525-001.mp4',
          mimeType: 'video/mp4',
        },
      ],
    },
    agentTask: null as AnyRecord | null,
  };
}

function createDefaultState() {
  return {
    process: {
      running: false,
      processAlive: false,
      starting: false,
      startupState: 'idle',
      startupElapsedSec: 0,
      startupTimeoutSec: 420,
      startupError: '',
      startupStage: 'idle',
      pid: null,
      portReady: false,
      status: 'idle',
    },
    logs: [
      '[预览] 控制台已启动。',
      '[预览] 可以启动核心服务，或查看各页面快照。',
      '[预览] 未配置真实桥接时，数据来自预览适配器。',
    ].join('\n'),
    license: buildLicense(),
    member: buildMember(),
    clientConfig: {
      cardSite: {
        enabled: true,
        label: '打开发卡站',
        url: 'https://license.heang.top',
      },
    },
    account: {
      loggedIn: false,
      source: '',
      account: '',
      memberId: '',
      plan: '',
      status: 'inactive',
      baseUrl: 'https://api.heang.top',
      gatewayBaseUrl: 'https://api.heang.top/v1',
      tokenMasked: '',
      models: {
        text: [],
        image: [],
        video: [],
      },
      usage: {},
      lastOnlineAt: '',
      graceExpiresAt: '',
    },
    update: {
      current: '2.0.6',
      latest: '2.1.0',
      hasUpdate: true,
      log: ['Checking current package', 'Latest build available'],
    },
    system: {
      node_path: 'D:/Axiangmu/AUSTART/openclaw_new_launcher/node.exe',
      base_path: 'D:/Axiangmu/AUSTART/openclaw_new_launcher',
      openclaw_version: '2.0.6',
    },
    theme: buildTheme(),
    authProfiles: {
      models: {
        providers: {
          heang: {
            baseUrl: 'https://api.heang.top/v1',
            apiKey: 'mock-gateway-token',
            model: 'gpt-4o',
          },
        },
      },
    },
    configFiles: {
      'data/.openclaw/agents/main/agent/auth-profiles.json': {
        models: { providers: { heang: { baseUrl: 'https://api.heang.top/v1', apiKey: 'mock-gateway-token' } } },
      },
      'imgapi_config.json': { gatewayMode: 'member', baseUrl: 'https://api.heang.top/v1', apiKey: 'mock-image-token' },
      'videoapi_config.json': { gatewayMode: 'member', providerId: 'dashscope', apiBase: 'https://dashscope.aliyuncs.com/api/v1', apiKey: 'mock-video-token', model: 'happyhorse-1.0-t2v' },
      'data/.openclaw/openclaw.json': { ui: 'preview', version: '0.1.0' },
    } as Record<string, unknown>,
    skills: buildSkills(),
    components: buildComponents(),
    diagnostics: buildDiagnostics(),
    desktop: buildDesktop(),
    phone: buildPhoneDevices(),
    studio: {
      imageHistory: [] as AnyRecord[],
      videoHistory: [] as AnyRecord[],
    },
  };
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return createDefaultState();
    const parsed = JSON.parse(raw);
    const state = { ...createDefaultState(), ...parsed };
    const license = state.license || {};
    if (license.signature === 'mock-signature') {
      state.license = buildLicense();
    }
    return state;
  } catch {
    return createDefaultState();
  }
}

function saveState(state: AnyRecord) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function mutateState<T>(updater: (state: AnyRecord) => T): T {
  const state = loadState();
  const result = updater(state);
  saveState(state);
  return result;
}

function selectedPhoneDevice(state: AnyRecord): AnyRecord {
  const selectedId = state.phone?.selectedDeviceId || state.phone?.devices?.[0]?.id || null;
  return state.phone?.devices?.find((device: AnyRecord) => device.id === selectedId) || state.phone?.devices?.[0] || null;
}

function advanceAgentTask(state: AnyRecord) {
  const task = state.phone?.agentTask;
  if (!task || task.status !== 'running') return;
  const startedAt = toNumber(task.startedAt, Date.now());
  if (Date.now() - startedAt < 1200) return;
  task.status = 'success';
  task.finishedAt = Date.now();
  task.result = {
    success: true,
    mode: 'template',
    readOnly: false,
    toolPolicy: 'safe_action',
    answer: '预览手机任务已完成。',
    rounds: 3,
    tokens: 882,
    stepsExecuted: 3,
    stepsTotal: 3,
    executionTimeMs: 1450,
    events: [
      { type: 'observe', round: 1, toolName: 'vision', success: true, message: '已采集屏幕' },
      { type: 'plan', round: 2, toolName: 'planner', success: true, message: '已选择目标元素' },
      { type: 'tap', round: 3, toolName: 'tap', success: true, message: '动作已执行' },
    ],
  };
}

function toBridgeLicense(state: AnyRecord) {
  const license = state.license;
  const member = state.member;
  const gatewayProfile = {
    baseUrl: license.gatewayBaseUrl,
    imageBaseUrl: license.gatewayImageBaseUrl,
    videoBaseUrl: license.gatewayVideoBaseUrl,
    apiKey: license.gatewayAccessToken,
    imageApiKey: license.gatewayImageAccessToken,
    videoApiKey: license.gatewayVideoAccessToken,
    defaultModel: license.gatewayDefaultModel,
    imageModel: license.gatewayImageModel,
    videoModel: license.gatewayVideoModel,
  };
  return { license, gatewayProfile, member };
}

function toBridgeMember(state: AnyRecord) {
  return { member: state.member, lease: state.member, usage: state.member.usage };
}

function toBridgeUpdate(state: AnyRecord) {
  return { current: state.update.current, latest: state.update.latest, hasUpdate: state.update.hasUpdate };
}

function toBridgeSystem(state: AnyRecord) {
  return { node_path: state.system.node_path, base_path: state.system.base_path, openclaw_version: state.system.openclaw_version };
}

function toBridgeTheme(state: AnyRecord) {
  return { theme: state.theme.theme, isCustom: state.theme.isCustom, merchantId: state.theme.merchantId };
}

function toBridgeLog(state: AnyRecord, offset = 0) {
  const text = String(state.logs || '');
  const reset = offset > text.length;
  const safeOffset = reset ? 0 : Math.max(0, offset);
  return { log: text.slice(safeOffset), offset: text.length, total: text.length, reset };
}

function generateMockImage(label: string, accent = '#c7a66a') {
  return svgDataUrl('OpenClaw 预览', label, accent);
}

function makeImageResult(prompt: string, _size: string, count = 1) {
  const previewUrls = Array.from({ length: count }, (_, index) => generateMockImage(`图像 ${index + 1}: ${prompt.slice(0, 24)}`, index % 2 === 0 ? '#c7a66a' : '#67c7bd'));
  return {
    images: previewUrls.map((url) => url.split(',')[1] || ''),
    files: previewUrls.map((_, index) => ({
      path: `mock://generated/openclaw-image-${Date.now()}-${index + 1}.png`,
      directory: 'mock://generated',
      filename: `openclaw-image-${Date.now()}-${index + 1}.png`,
      size: 248_000 + index * 19_000,
      mime: 'image/svg+xml',
    })),
    count,
    previewUrls,
  };
}

function makeVideoResult(prompt: string, mode: string, resolution: string, duration: number, ratio: string) {
  return {
    video: generateMockImage(`视频 ${resolution} ${duration}s`, '#67c7bd'),
    mime: 'image/svg+xml',
    size: 1_280_000,
    path: `mock://generated/openclaw-video-${Date.now()}.mp4`,
    directory: 'mock://generated',
    filename: `openclaw-video-${Date.now()}.mp4`,
    prompt,
    mode,
    resolution,
    ratio,
    duration,
  };
}

function readConfigFile(state: AnyRecord, path: string, fallback: any) {
  return clone(state.configFiles?.[path] ?? fallback);
}

export function getMockPhoneInventory() {
  const state = loadState();
  return {
    selectedDeviceId: state.phone?.selectedDeviceId || null,
    devices: clone(state.phone?.devices || []),
  };
}

export function setMockPhoneSelection(deviceId: string | null) {
  mutateState((state) => {
    state.phone.selectedDeviceId = deviceId;
    return state.phone.selectedDeviceId;
  });
}

export function upsertMockPhoneDevice(device: AnyRecord) {
  mutateState((state) => {
    const devices = Array.isArray(state.phone.devices) ? state.phone.devices : [];
    const index = devices.findIndex((item: AnyRecord) => item.id === device.id);
    if (index >= 0) devices[index] = { ...devices[index], ...device };
    else devices.unshift(device);
    state.phone.devices = devices;
    return device;
  });
}

export function removeMockPhoneDevice(deviceId: string) {
  mutateState((state) => {
    state.phone.devices = (state.phone.devices || []).filter((item: AnyRecord) => item.id !== deviceId);
    if (state.phone.selectedDeviceId === deviceId) {
      state.phone.selectedDeviceId = state.phone.devices[0]?.id || null;
    }
    return deviceId;
  });
}

export async function mockBridgeRequest(path: string, method = 'GET', body?: Record<string, unknown>): Promise<any> {
  const state = loadState();
  const url = new URL(path, 'http://mock.local');
  const route = url.pathname;

  if (route === '/api/process/status') return clone(state.process);

  if (route === '/api/process/start') {
    state.process = {
      ...state.process,
      running: true,
      processAlive: true,
      starting: false,
      startupState: 'running',
      startupElapsedSec: 32,
      startupStage: 'bridge ready',
      pid: 18840,
      portReady: true,
      status: 'running',
    };
    state.logs = `${state.logs}\n[预览] 服务已启动，桥接已就绪。`;
    saveState(state);
    return clone(state.process);
  }

  if (route === '/api/process/stop') {
    state.process = { ...state.process, running: false, processAlive: false, starting: false, startupState: 'idle', startupStage: 'stopped', pid: null, portReady: false, status: 'stopped' };
    state.logs = `${state.logs}\n[预览] 服务已停止。`;
    saveState(state);
    return { status: 'stopped', message: '预览服务已停止' };
  }

  if (route === '/api/log/get') return toBridgeLog(state, toNumber(url.searchParams.get('offset'), 0));
  if (route === '/api/log/clear') {
    state.logs = '';
    saveState(state);
    return { status: 'cleared' };
  }

  if (route === '/api/license/current') return toBridgeLicense(state);
  if (route === '/api/license/client-config') return clone(state.clientConfig);
  if (route === '/api/license/authorized') return { authorized: true };
  if (route === '/api/license/activate') {
    const code = toText(body?.code, '');
    if (!code.trim()) return { error: '授权码不能为空' };
    state.license = { ...state.license, activationCodeLabel: code.slice(-8).toUpperCase(), codeLabel: code.slice(-8).toUpperCase() };
    state.process.running = true;
    state.process.processAlive = true;
    state.logs = `${state.logs}\n[预览] 授权码 ${code} 已激活。`;
    saveState(state);
    return toBridgeLicense(state);
  }

  if (route === '/api/member/current') return toBridgeMember(state);
  if (route === '/api/member/activate') {
    const code = toText(body?.code, '');
    if (!code.trim()) return { error: '会员码不能为空' };
    state.member.status = 'active';
    state.member.leaseId = `lease-${code.slice(-4).toLowerCase()}`;
    state.logs = `${state.logs}\n[预览] 成员已激活。`;
    saveState(state);
    return toBridgeMember(state);
  }
  if (route === '/api/member/refresh') return toBridgeMember(state);
  if (route === '/api/member/usage') return toBridgeMember(state);

  if (route === '/api/account/current') return { account: clone(state.account) };
  if (route === '/api/account/login') {
    const username = toText(body?.username || body?.email, '').trim();
    const password = toText(body?.password, '').trim();
    const baseUrl = toText(body?.baseUrl, 'https://api.heang.top').replace(/\/+$/, '');
    if (!username || !password) return { account: clone(state.account), error: '账号和密码不能为空' };
    state.account = {
      loggedIn: true,
      source: 'newapi_account',
      account: username,
      memberId: `user-${username.replace(/[^a-z0-9]+/gi, '-').toLowerCase().slice(0, 18) || 'mock'}`,
      plan: 'default',
      status: 'active',
      baseUrl,
      gatewayBaseUrl: `${baseUrl}/v1`,
      tokenMasked: 'sk-****MOCK',
      models: {
        text: ['gpt-4o-mini', 'doubao-seed-1-6'],
        image: ['gpt-image-1'],
        video: ['agnes-video-v2.0'],
      },
      usage: { quota: 100000, used: 1200 },
      lastOnlineAt: nowIso(),
      graceExpiresAt: new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString(),
    };
    state.member = {
      ...state.member,
      status: 'active',
      memberId: state.account.memberId,
      gatewayBaseUrl: state.account.gatewayBaseUrl,
      gatewayToken: 'mock-newapi-token',
    };
    state.configFiles['data/.openclaw/agents/main/agent/auth-profiles.json'] = {
      models: {
        primary: 'member_gateway',
        providers: {
          member_gateway: {
            title: 'Heang API',
            type: 'openai-compatible',
            baseUrl: state.account.gatewayBaseUrl,
            apiKey: 'mock-newapi-token',
            models: state.account.models.text.map((id: string) => ({ id })),
            managedBy: 'newapi_account',
          },
        },
      },
    };
    state.configFiles['imgapi_config.json'] = {
      gatewayMode: 'member',
      baseUrl: state.account.gatewayBaseUrl,
      apiKey: 'mock-newapi-token',
      model: state.account.models.image[0],
      managedBy: 'newapi_account',
    };
    state.logs = `${state.logs}\n[预览] 中转站账号 ${username} 已登录并同步模型。`;
    saveState(state);
    return { account: clone(state.account), member: clone(state.member) };
  }
  if (route === '/api/account/bind-ticket') {
    const ticket = toText(body?.ticket || body?.code, '').trim();
    const baseUrl = toText(body?.baseUrl, 'https://api.heang.top').replace(/\/+$/, '');
    if (!ticket) return { account: clone(state.account), error: '网站绑定码不能为空' };
    state.account = {
      loggedIn: true,
      source: 'newapi_account',
      account: 'website-user@example.com',
      memberId: 'user-website-bind',
      plan: 'default',
      status: 'active',
      baseUrl,
      gatewayBaseUrl: `${baseUrl}/v1`,
      tokenMasked: 'sk-****BIND',
      models: {
        text: ['qwen3.7-plus', 'agnes-2.0-flash'],
        image: ['gpt-image-1'],
        video: ['agnes-video-v2.0'],
      },
      usage: { quota: 100000, used: 1200 },
      lastOnlineAt: nowIso(),
      graceExpiresAt: new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString(),
    };
    state.member = {
      ...state.member,
      status: 'active',
      memberId: state.account.memberId,
      gatewayBaseUrl: state.account.gatewayBaseUrl,
      gatewayToken: 'mock-bound-token',
    };
    state.configFiles['data/.openclaw/agents/main/agent/auth-profiles.json'] = {
      models: {
        primary: 'member_gateway',
        providers: {
          member_gateway: {
            title: 'Heang API',
            type: 'openai-compatible',
            baseUrl: state.account.gatewayBaseUrl,
            apiKey: 'mock-bound-token',
            models: state.account.models.text.map((id: string) => ({ id })),
            managedBy: 'newapi_account',
          },
        },
      },
    };
    state.configFiles['imgapi_config.json'] = {
      gatewayMode: 'member',
      baseUrl: state.account.gatewayBaseUrl,
      apiKey: 'mock-bound-token',
      model: state.account.models.image[0],
      managedBy: 'newapi_account',
    };
    state.logs = `${state.logs}\n[预览] 网站账号已绑定并同步模型。`;
    saveState(state);
    return { account: clone(state.account), member: clone(state.member) };
  }
  if (route === '/api/account/sync') {
    if (!state.account?.loggedIn) return { account: clone(state.account), error: '未登录' };
    state.account.lastOnlineAt = nowIso();
    state.logs = `${state.logs}\n[预览] 中转站账号模型已同步。`;
    saveState(state);
    return { account: clone(state.account), member: clone(state.member) };
  }
  if (route === '/api/account/logout') {
    state.account = {
      loggedIn: false,
      source: '',
      account: '',
      memberId: '',
      plan: '',
      status: 'inactive',
      baseUrl: 'https://api.heang.top',
      gatewayBaseUrl: 'https://api.heang.top/v1',
      tokenMasked: '',
      models: { text: [], image: [], video: [] },
      usage: {},
      lastOnlineAt: '',
      graceExpiresAt: '',
    };
    state.logs = `${state.logs}\n[预览] 中转站账号已退出。`;
    saveState(state);
    return { account: clone(state.account) };
  }

  if (route === '/api/update/check') return toBridgeUpdate(state);
  if (route === '/api/update/do') {
    state.update.current = state.update.latest;
    state.update.hasUpdate = false;
    state.update.log.push('已更新到最新预览版本');
    state.logs = `${state.logs}\n[预览] 更新完成。`;
    saveState(state);
    return { success: true, current_version: state.update.current, log: clone(state.update.log) };
  }

  if (route === '/api/system/info') return toBridgeSystem(state);

  if (route === '/api/theme/current') return toBridgeTheme(state);
  if (route === '/api/theme/list') return { themes: clone(state.theme.themes || []) };
  if (route === '/api/theme/by_merchant') return { theme: state.theme.theme };

  if (route === '/api/config/read') {
    const configPath = toText(body?.path, '');
    return { data: readConfigFile(state, configPath, body?.default ?? {}) };
  }
  if (route === '/api/config/write') {
    const configPath = toText(body?.path, '');
    state.configFiles[configPath] = clone(body?.data);
    saveState(state);
    return { status: 'ok' };
  }
  if (route === '/api/auth/profiles') {
    if (method === 'PUT') {
      state.authProfiles = { ...(state.authProfiles || {}), ...(body || {}) };
      state.configFiles['data/.openclaw/agents/main/agent/auth-profiles.json'] = clone(state.authProfiles);
      saveState(state);
      return { status: 'ok' };
    }
    return { profiles: clone(state.authProfiles) };
  }

  if (route === '/api/skills/list') return clone(state.skills);
  if (route === '/api/skills/paths') return { directories: clone(state.skills.directories), sites: clone(state.skills.sites) };
  if (route === '/api/skills/install_zip') {
    const filename = toText(body?.filename, 'skill.zip');
    const skill = {
      id: filename.replace(/\.zip$/i, '').replace(/[^a-z0-9]+/gi, '-').toLowerCase() || `skill-${Date.now()}`,
      name: filename.replace(/\.zip$/i, ''),
      version: '1.0.0',
      description: 'Installed from mock archive.',
      category: 'custom',
      runtime: 'node',
      icon: 'SK',
      source: 'uploaded',
      sourceLabel: '启动器上传',
      path: `data/.openclaw/workspace/skills/${filename.replace(/\.zip$/i, '')}`,
      installed: true,
      enabled: true,
      writable: true,
      hasReadme: true,
    };
    state.skills.skills.unshift(skill);
    saveState(state);
    return { skill: clone(skill) };
  }
  if (route === '/api/skills/enable') {
    const id = toText(body?.id, '');
    const enabled = toBool(body?.enabled);
    const skill = state.skills.skills.find((item: AnyRecord) => item.id === id);
    if (skill) skill.enabled = enabled;
    saveState(state);
    return { skill: clone(skill || { id, enabled }) };
  }
  if (route === '/api/skills/uninstall') {
    const id = toText(body?.id, '');
    state.skills.skills = state.skills.skills.filter((item: AnyRecord) => item.id !== id);
    saveState(state);
    return { status: 'removed', id };
  }
  if (route === '/api/skills/readme') {
    const id = toText(body?.id, '');
    const skill = state.skills.skills.find((item: AnyRecord) => item.id === id);
    return {
      id,
      path: skill?.path || `skills/${id}/README.md`,
      content: `# ${skill?.name || id}\n\n这是预览 README。\n\n- 来源: ${skill?.sourceLabel || '预览'}\n- 运行时: ${skill?.runtime || 'node'}`,
    };
  }

  if (route === '/api/components/status') return clone(state.components);
  if (route === '/api/components/install') {
    const id = toText(body?.componentId || body?.id, '');
    const component = state.components.components.find((item: AnyRecord) => item.id === id);
    if (!component) return { error: `Unknown component: ${id}` };
    component.status = 'ready';
    component.installedVersion = component.version;
    component.updatedAt = nowIso();
    saveState(state);
    return { state: clone(component), catalog: clone(state.components) };
  }
  if (route === '/api/components/rollback') {
    const id = toText(body?.componentId || body?.id, '');
    const component = state.components.components.find((item: AnyRecord) => item.id === id);
    if (!component) return { error: `Unknown component: ${id}` };
    component.status = 'ready';
    component.installedVersion = component.previousVersion || component.installedVersion;
    component.previousVersion = null;
    component.updatedAt = nowIso();
    saveState(state);
    return { state: clone(component), catalog: clone(state.components) };
  }

  if (route === '/api/diagnostics/run') return clone(state.diagnostics.report);
  if (route === '/api/diagnostics/repair') {
    const report = clone(state.diagnostics.report);
    report.summary = { status: 'ok', ok: report.summary.total, warnings: 0, failed: 0, total: report.summary.total };
    report.checks = report.checks.map((check: AnyRecord) => ({ ...check, status: 'ok', message: `Repaired: ${check.label}` }));
    state.diagnostics.report = report;
    saveState(state);
    return {
      actions: [
        { label: '恢复桥接运行时', status: 'ok', message: '预览运行时已健康', count: 1 },
        { label: '重建配置缓存', status: 'ok', message: '配置缓存已刷新', count: 1 },
      ],
      diagnostics: clone(report),
    };
  }
  if (route === '/api/diagnostics/export') {
    return {
      path: `mock://diagnostics/openclaw-diagnostics-${Date.now()}.zip`,
      directory: 'mock://diagnostics',
      filename: `openclaw-diagnostics-${Date.now()}.zip`,
      size: 18_420,
    };
  }

  if (route === '/api/desktop-agent/status') return clone(state.desktop);
  if (route === '/api/desktop-agent/config') {
    state.desktop.config = { ...state.desktop.config, ...(body || {}) };
    saveState(state);
    return { config: clone(state.desktop.config) };
  }
  if (route === '/api/desktop-agent/start') {
    state.desktop.running = true;
    state.desktop.pid = 9124;
    state.desktop.apiReady = true;
    saveState(state);
    return clone(state.desktop);
  }
  if (route === '/api/desktop-agent/stop') {
    state.desktop.running = false;
    state.desktop.pid = null;
    state.desktop.apiReady = false;
    saveState(state);
    return clone(state.desktop);
  }
  if (route === '/api/desktop-agent/health') return clone(state.desktop.health);
  if (route === '/api/desktop-agent/screenshot') return { success: true, screenshot: generateMockImage('桌面截图', '#67c7bd') };
  if (route === '/api/desktop-agent/click') return { ok: true, success: true, x: body?.x, y: body?.y, confirmed: body?.confirmed ?? false };
  if (route === '/api/desktop-agent/type') return { ok: true, success: true, text: body?.text, confirmed: body?.confirmed ?? false };
  if (route === '/api/desktop-agent/wechat/send') return { ok: true, success: true, text: body?.text, confirmed: body?.confirmed ?? false };
  if (route === '/api/desktop-agent/wechat/unread') return { ok: true, success: true, unread: 7, channel: 'mock' };

  if (route === '/api/image/generate') {
    const prompt = toText(body?.prompt, '');
    const size = toText(body?.size, '1024x1024');
    const count = Math.max(1, toNumber(body?.count, 1));
    const result = makeImageResult(prompt, size, count);
    state.studio.imageHistory.unshift({
      prompt,
      size,
      count,
      previewUrls: clone(result.previewUrls),
      files: clone(result.files),
      source: 'mock',
    });
    state.studio.imageHistory = state.studio.imageHistory.slice(0, 8);
    saveState(state);
    return result;
  }
  if (route === '/api/video/generate') {
    const prompt = toText(body?.prompt, '');
    const mode = toText(body?.mode, 't2v');
    const resolution = toText(body?.resolution, '720P');
    const duration = toNumber(body?.duration, 5);
    const ratio = toText(body?.ratio, '16:9');
    const result = makeVideoResult(prompt, mode, resolution, duration, ratio);
    state.studio.videoHistory.unshift({ ...result, source: 'mock' });
    state.studio.videoHistory = state.studio.videoHistory.slice(0, 8);
    saveState(state);
    return result;
  }

  return { ok: true, route, method, body: clone(body || {}) };
}

export async function mockPhoneRequest(
  baseUrl: string,
  token: string,
  path: string,
  method = 'GET',
  body?: Record<string, unknown>
): Promise<any> {
  const state = loadState();
  const device = selectedPhoneDevice(state);
  const deviceId = device?.id || 'phone';
  const url = new URL(path, 'http://mock.phone');
  const route = url.pathname;
  advanceAgentTask(state);

  if (route === '/api/device/status') {
    return clone(state.phone.statusById?.[deviceId] || { online: false, taskRunning: false, agentInitialized: false });
  }
  if (route === '/api/device/wake') {
    const status = state.phone.statusById?.[deviceId] || {};
    status.screenOn = true;
    status.interactive = true;
    status.keyguardLocked = false;
    status.deviceLocked = false;
    state.phone.statusById[deviceId] = status;
    saveState(state);
    return {
      wakeAttempted: true,
      wakeRequested: true,
      message: '预览设备已唤醒',
      before: { screenOn: false, interactive: false, keyguardLocked: true, deviceLocked: true },
      after: { screenOn: true, interactive: true, keyguardLocked: false, deviceLocked: false },
    };
  }
  if (route === '/api/tool/screenshot') {
    return {
      mime: 'image/svg+xml',
      base64: btoa('mock'),
      dataUrl: state.phone.screenshotById?.[deviceId] || generateMockImage(`Phone ${deviceId}`, '#c7a66a'),
      capturedAt: nowIso(),
      width: 1080,
      height: 2400,
      orientation: 'portrait',
    };
  }
  if (route === '/api/tool/screen_tree') return clone(state.phone.screenTreeById?.[deviceId] || { screen: { width: 1080, height: 2400 }, nodes: [] });
  if (route === '/api/lumi/device/profile') {
    const profile = clone(state.phone.deviceProfiles?.[deviceId] || { profileVersion: 1, capturedAt: Date.now(), apps: [], privacyNote: 'Mock' });
    if (!profile.capturedAt) profile.capturedAt = nowIso();
    if (!profile.battery || profile.battery.level == null) profile.battery = { level: 86, charging: true };
    if (!Array.isArray(profile.apps) || profile.apps.length === 0) {
      profile.apps = [
        { label: 'WeChat', packageName: 'com.tencent.mm', launchable: true },
        { label: 'Browser', packageName: 'mark.via', launchable: true },
      ];
    }
    return profile;
  }
  if (route === '/api/lumi/vision/status' || route === '/api/lumi/vision/frame') return clone(state.phone.visionFrames?.[deviceId] || {});
  if (route === '/api/lumi/vision/action') {
    return {
      action: body?.action || 'tap',
      blocked: false,
      point: { x: body?.x, y: body?.y },
      start: body?.start,
      end: body?.end,
      durationMs: body?.durationMs,
      holdMs: body?.holdMs,
      traceId: body?.traceId || `trace-${Date.now()}`,
      visualize: body?.visualize ?? false,
      executedAt: nowIso(),
      message: 'Mock vision action executed',
    };
  }
  if (route === '/api/lumi/agent/tasks' && method === 'POST') {
    const taskId = `task-${Date.now()}`;
    state.phone.agentTask = {
      taskId,
      status: 'running',
      prompt: toText(body?.prompt, ''),
      createdAt: Date.now(),
      startedAt: Date.now(),
      events: [],
    };
    saveState(state);
    return { taskId, status: 'running', prompt: toText(body?.prompt, '') };
  }
  if (route.match(/^\/api\/lumi\/agent\/tasks\/[^/]+$/)) {
    const task = state.phone.agentTask;
    if (!task) return { taskId: 'task-none', status: 'cancelled', error: 'no_task' };
    advanceAgentTask(state);
    saveState(state);
    return clone(task);
  }
  if (route.match(/^\/api\/lumi\/agent\/tasks\/[^/]+\/events$/)) {
    const task = state.phone.agentTask;
    return { taskId: task?.taskId || 'task-none', status: task?.status || 'idle', events: task?.result?.events || task?.events || [] };
  }
  if (route.match(/^\/api\/lumi\/agent\/tasks\/[^/]+\/cancel$/)) {
    if (state.phone.agentTask) state.phone.agentTask.status = 'cancelled';
    saveState(state);
    return clone(state.phone.agentTask || { status: 'cancelled' });
  }
  if (route === '/api/lumi/agent/execute_task') {
    return {
      success: true,
      mode: 'template',
      readOnly: false,
      toolPolicy: body?.tool_policy || 'safe_action',
      answer: '预览同步任务已完成。',
      rounds: 2,
      tokens: 654,
      events: [{ type: 'result', round: 2, success: true, message: 'done' }],
    };
  }
  if (route === '/api/lumi/media/record/status') return { state: 'idle', recording: false, accepted: true, current: null, latest: state.phone.recordings?.[deviceId]?.[0] || null };
  if (route === '/api/lumi/media/record/start') return { state: 'recording', recording: true, accepted: true, startedAt: nowIso(), current: { exists: true, id: 'record-002', filename: 'screen-mock.mp4', path: 'mock://phone/recording.mp4', sizeBytes: 0, modifiedAt: nowIso(), downloadUrl: 'mock://phone/recording.mp4', mimeType: 'video/mp4' } };
  if (route === '/api/lumi/media/record/stop') return { state: 'idle', recording: false, accepted: true, latest: { exists: true, id: 'record-002', filename: 'screen-mock.mp4', path: 'mock://phone/recording.mp4', sizeBytes: 9_421_000, modifiedAt: nowIso(), downloadUrl: 'mock://phone/recording.mp4', mimeType: 'video/mp4' } };
  if (route === '/api/lumi/media/videos') return { recordings: clone(state.phone.recordings?.[deviceId] || []) };
  if (route === '/api/lumi/media/import_image' || route === '/api/lumi/media/import_video') {
    return {
      path: `mock://phone/gallery/${Date.now()}-${route.includes('image') ? 'image.png' : 'video.mp4'}`,
      relativePath: `OpenClaw/${Date.now()}`,
      filename: body?.filename || (route.includes('image') ? 'openclaw-image.png' : 'openclaw-video.mp4'),
      mime: route.includes('image') ? 'image/png' : 'video/mp4',
      size: 2048,
      message: '已导入预览相册',
    };
  }
  if (route === '/api/tool/tap' || route === '/api/tool/long_press' || route === '/api/tool/swipe' || route === '/api/tool/drag') {
    return { ...clone(body || {}), executedAt: nowIso(), message: '预览手势已执行' };
  }
  if (route === '/api/overlay/cursor/preview') {
    return { x: toNumber(body?.x, 0), y: toNumber(body?.y, 0), action: toText(body?.action, 'tap'), durationMs: toNumber(body?.durationMs, 2600), traceId: toText(body?.traceId, `trace-${Date.now()}`), enabled: true };
  }

  return { ok: true, baseUrl, token: maskSecret(token), route };
}

