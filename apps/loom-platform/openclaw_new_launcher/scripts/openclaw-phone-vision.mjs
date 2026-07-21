#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  authHeaders,
  ensurePhoneConfig,
  fetchWithTimeout,
  normalizePhoneUrl,
  PhoneBridgeError,
  phoneBridgeErrorPayload,
  readLauncherPhoneConfigByDevice,
  signedJsonRequest,
} from './openclaw-phone-secure.mjs';
import { compactReadSelectors, inspectVisionActionPlan, minimalActionForPhone, visionActionEndpointForBody } from './lib/vision-safety.mjs';
import {
  phoneFrameCachePath,
  phoneFrameMetadataPath,
  phoneFrameOutputPath,
} from './lib/phone-frame-paths.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_OUT_DIR = path.join(PROJECT_ROOT, 'data', 'phone-frames');
const DEFAULT_FRAME_TIMEOUT_MS = 40_000;
let lastArgs = { json: process.argv.includes('--json'), command: '' };
let lastConfig = null;

function usage() {
  return `
OpenClaw phone vision/game-mode CLI

Usage:
  npm run phone:vision -- status
  npm run phone:vision -- read --prompt "读取当前页面"
  npm run phone:vision -- frame --out ./data/phone-frames/frame.jpg
  npm run phone:vision -- action --force-action --action-body "{\\"action\\":\\"tap\\",\\"gridCell\\":\\"C7\\",\\"targetLabel\\":\\"settings button\\",\\"reason\\":\\"open safe settings panel\\"}"

Commands:
  status                      Read game/vision mode status and current hints
  read                        Read screen tree/profile directly without starting APKClaw Agent
  frame                       Capture a signed vision frame with grid and coordinate mapping
  action                      Execute a visual coordinate action. Debug/fallback only; requires --force-action

Frame options:
  --out <path>                 Save returned image. Default: data/phone-frames/vision-frame-<time>.jpg
  --format <jpeg|png>          Default: jpeg
  --quality <n>                JPEG quality, phone clamps to 45-95. Default: 82
  --max-long-side <n>          Phone-side image long edge. Default: 1600
  --frame-timeout-ms <n>       Screenshot request budget. Default: 40000
  --cache-ttl-ms <n>           Reuse the last fast frame if it is still fresh
  --grid-columns <n>           Default: 6
  --grid-rows <n>              Default: 12
  --no-grid                    Disable grid overlay

Action options:
  --action-body <json>         Raw action JSON. Text/node actions use action_fast; coordinate actions use vision/action
  --action-body-file <path>    Read action JSON from file. Recommended for PowerShell
  --action-body-stdin          Read action JSON from stdin
  --force-action               Required for action. Use only after APKClaw Agent fails, for debugging, or for explicit coordinate tasks
  --allow-unknown-target        Debug only. Permit an action plan without targetLabel/reason metadata. Blacklisted labels still block.

PowerShell action example:
  $body = @{ action = 'tap'; gridCell = 'C7'; targetLabel = 'settings button'; reason = 'open settings' } | ConvertTo-Json -Compress
  Set-Content -Encoding UTF8 .\\action.json $body
  node scripts\\openclaw-phone-vision.mjs action --force-action --action-body-file .\\action.json --json

Common options:
  --fast-path <name>           For read, try APKClaw fast read first. Default: observe_fast
  --known-hash <hash>          For read, pass the previous screenHash for incremental observe_fast responses
  --device-id <id>             Optional. Select one configured APKClaw device from launcher
  --phone-url <url>            Optional. Defaults to launcher Phone Control config, then env
  --phone-token <token>        Optional. Defaults to launcher Phone Control config, then env
  --json                       Print machine-readable JSON
  -h, --help                   Show help
`.trim();
}

function parseArgs(argv) {
  const args = {
    command: '',
    prompt: '',
    deviceId: '',
    phoneUrl: '',
    phoneToken: '',
    out: '',
    format: 'jpeg',
    quality: 82,
    maxLongSide: 1600,
    frameTimeoutMs: DEFAULT_FRAME_TIMEOUT_MS,
    cacheTtlMs: 0,
    gridColumns: 6,
    gridRows: 12,
    overlayGrid: true,
    actionBody: '',
    actionBodyFile: '',
    actionBodyStdin: false,
    forceAction: false,
    allowUnknownTarget: false,
    fastPath: 'observe_fast',
    knownHash: '',
    json: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (!value || value.startsWith('--')) throw new Error(`Missing value for ${arg}`);
      i += 1;
      return value;
    };
    const nextInt = () => {
      const value = Number.parseInt(next(), 10);
      if (!Number.isFinite(value)) throw new Error(`Invalid number for ${arg}`);
      return value;
    };

    switch (arg) {
      case '-h':
      case '--help':
        args.help = true;
        break;
      case '--phone-url':
        args.phoneUrl = next();
        break;
      case '--device-id':
        args.deviceId = next();
        break;
      case '--phone-token':
        args.phoneToken = next();
        break;
      case '--prompt':
        args.prompt = next();
        break;
      case '--out':
        args.out = path.resolve(next());
        break;
      case '--format':
        args.format = next().toLowerCase();
        break;
      case '--quality':
        args.quality = nextInt();
        break;
      case '--max-long-side':
        args.maxLongSide = nextInt();
        break;
      case '--frame-timeout-ms':
        args.frameTimeoutMs = Math.max(250, Math.min(nextInt(), 120_000));
        break;
      case '--cache-ttl-ms':
        args.cacheTtlMs = Math.max(0, nextInt());
        break;
      case '--grid-columns':
        args.gridColumns = nextInt();
        break;
      case '--grid-rows':
        args.gridRows = nextInt();
        break;
      case '--no-grid':
        args.overlayGrid = false;
        break;
      case '--action-body':
        args.actionBody = next();
        break;
      case '--action-body-file':
        args.actionBodyFile = path.resolve(next());
        break;
      case '--action-body-stdin':
        args.actionBodyStdin = true;
        break;
      case '--force-action':
        args.forceAction = true;
        break;
      case '--allow-unknown-target':
        args.allowUnknownTarget = true;
        break;
      case '--fast-path':
        args.fastPath = next().toLowerCase();
        break;
      case '--known-hash':
      case '--screen-hash':
        args.knownHash = next();
        break;
      case '--json':
        args.json = true;
        break;
      default:
        if (!arg.startsWith('-') && !args.command) {
          args.command = arg;
        } else {
          throw new Error(`Unknown option: ${arg}`);
        }
    }
  }

  if (!args.command) args.command = 'status';
  args.command = args.command.toLowerCase();
  return args;
}

async function resolveConfig(args) {
  const runtime = await readRuntimeContext();
  const launcherPhone = await readLauncherPhoneConfigByDevice(args.deviceId);
  return {
    ...args,
    phoneUrl: firstNonEmpty(args.phoneUrl, process.env.OPENCLAW_PHONE_BASE_URL, process.env.APKCLAW_BASE_URL, runtime?.phone?.baseUrl, launcherPhone.phoneUrl),
    phoneToken: firstNonEmpty(args.phoneToken, process.env.OPENCLAW_PHONE_TOKEN, process.env.APKCLAW_TOKEN, launcherPhone.phoneToken),
    deviceId: args.deviceId || launcherPhone.id || runtime?.phone?.defaultDeviceId || '',
    lumiLauncherId: firstNonEmpty(args.lumiLauncherId, process.env.LUMI_LAUNCHER_ID, launcherPhone.lumiLauncherId),
    lumiLauncherSecret: firstNonEmpty(args.lumiLauncherSecret, process.env.LUMI_LAUNCHER_SECRET, launcherPhone.lumiLauncherSecret),
    source: launcherPhone.source,
  };
}

async function readRuntimeContext() {
  const candidates = [
    path.join(PROJECT_ROOT, 'data', '.openclaw', 'workspace', 'runtime-context.json'),
    path.join(PROJECT_ROOT, 'openclaw-workspace', 'runtime-context.json'),
  ];
  for (const filePath of candidates) {
    try {
      return JSON.parse(await fs.readFile(filePath, 'utf8'));
    } catch (error) {
      if (error?.code !== 'ENOENT') return {};
    }
  }
  return {};
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function frameEndpoint(config) {
  const query = new URLSearchParams({
    _lumi: '1',
    format: config.format || 'jpeg',
    quality: String(config.quality || 82),
    maxLongSide: String(config.maxLongSide || 1600),
    gridColumns: String(config.gridColumns || 6),
    gridRows: String(config.gridRows || 12),
    overlayGrid: String(config.overlayGrid !== false),
  });
  return `/api/lumi/vision/frame?${query.toString()}`;
}

async function saveFrame(config, payload) {
  const image = payload?.data?.image;
  if (!image?.base64) throw new Error('Vision frame did not include image.base64');
  const mime = image.mime || 'image/jpeg';
  const extension = mime.includes('png') ? 'png' : 'jpg';
  const cachePath = phoneFrameCachePath(DEFAULT_OUT_DIR, config);
  const out = config.out || phoneFrameOutputPath(DEFAULT_OUT_DIR, config, extension);
  await fs.mkdir(path.dirname(out), { recursive: true });
  await fs.writeFile(out, Buffer.from(image.base64, 'base64'));
  if (config.cacheTtlMs > 0 && path.resolve(out) !== path.resolve(cachePath)) {
    try {
      await fs.copyFile(out, cachePath);
      const frame = payload?.data && typeof payload.data === 'object' ? payload.data : {};
      await fs.writeFile(phoneFrameMetadataPath(cachePath), JSON.stringify({
        capturedAt: frame.capturedAt || frame.timestamp || new Date().toISOString(),
        screenHash: frame.screenHash || '',
        width: Number(frame.width || image.width || 0),
        height: Number(frame.height || image.height || 0),
        currentScreen: frame.currentScreen || undefined,
        mime,
      }), 'utf8');
    } catch {
      // Screenshot cache is a speed hint, not required for correctness.
    }
  }
  return out;
}

async function cachedFrame(config) {
  if (!config.cacheTtlMs || config.out) return null;
  const cachePath = phoneFrameCachePath(DEFAULT_OUT_DIR, config);
  try {
    const stat = await fs.stat(cachePath);
    if (Date.now() - stat.mtimeMs > config.cacheTtlMs) return null;
    const metadata = JSON.parse(await fs.readFile(phoneFrameMetadataPath(cachePath), 'utf8'));
    if (Number(metadata?.width || 0) < 1 || Number(metadata?.height || 0) < 1) return null;
    return {
      ok: true,
      cached: true,
      filePath: cachePath,
      frame: {
        ...metadata,
        cached: true,
        imageOmitted: true,
        image: { mime: metadata.mime || 'image/jpeg' },
      },
    };
  } catch {
    return null;
  }
}

async function requestPhoneJson(config, endpoint, timeoutMs = 20_000) {
  ensurePhoneConfig(config);
  const response = await fetchWithTimeout(`${normalizePhoneUrl(config.phoneUrl)}${endpoint}`, {
    headers: {
      ...authHeaders(config),
      Accept: 'application/json',
    },
  }, timeoutMs);
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`Phone returned non-JSON response: HTTP ${response.status}`);
  }
  if (!response.ok || payload?.success === false) {
    throw new Error(payload?.error || payload?.message || `Phone request failed: HTTP ${response.status}`);
  }
  return payload;
}

async function readScreenDirect(config) {
  const screenTree = await readScreenPayload(config);
  const data = screenTree?.data || screenTree;
  const texts = collectVisibleTexts(data).slice(0, 80);
  const selectors = compactReadSelectors(data?.selectors || screenTree?.selectors || data?.keyNodes || screenTree?.keyNodes);
  const unchanged = Boolean(data?.unchanged || screenTree?.unchanged);
  const cacheHit = Boolean(data?.cacheHit || data?.metrics?.cacheHit || screenTree?.cacheHit || screenTree?.metrics?.cacheHit);
  const backendSummary = data?.summary || screenTree?.summary || '';
  return {
    ok: true,
    mode: data?.mode || screenTree?.mode || (screenTree?.fastPath === 'observe_fast' ? 'observe_fast' : 'direct_read'),
    metrics: data?.metrics || screenTree?.metrics || undefined,
    screenHash: data?.screenHash || screenTree?.screenHash || undefined,
    currentPackage: data?.currentPackage || data?.screen?.currentPackage || undefined,
    unchanged,
    cacheHit,
    backendSummary: backendSummary || undefined,
    fastPath: screenTree?.fastPath || undefined,
    promptPreview: promptPreview(config.prompt),
    textCount: texts.length,
    texts,
    selectorCount: selectors.length,
    selectors,
    summary: texts.length
      ? `读取完成：${texts.slice(0, 12).join(' / ')}`
      : '读取完成：当前页面没有返回可见文本',
  };
}

async function readScreenPayload(config) {
  if (!config.fastPath || config.fastPath === 'observe_fast') {
    try {
      const knownHash = config.knownHash ? `&knownHash=${encodeURIComponent(config.knownHash)}` : '';
      const payload = await signedJsonRequest(config, 'GET', `/api/lumi/agent/observe_fast?_lumi=1${knownHash}`, undefined, 12_000);
      return { ...payload, fastPath: 'observe_fast' };
    } catch (error) {
      // Only endpoint absence identifies an older APKClaw build. Runtime and
      // accessibility failures must remain visible to callers.
      if (!(error instanceof PhoneBridgeError) || error.errorCode !== 'phone_endpoint_not_found') {
        throw error;
      }
    }
  }
  try {
    return await requestPhoneJson(config, '/api/tool/screen_tree', 12_000);
  } catch (firstError) {
    try {
      return await signedJsonRequest(config, 'GET', '/api/lumi/device/profile?includeApps=false&appLimit=0', undefined, 12_000);
    } catch {
      throw firstError;
    }
  }
}

function collectVisibleTexts(value) {
  const texts = [];
  const seen = new Set();
  const visit = (item, key = '') => {
    if (item == null || texts.length >= 120) return;
    if (typeof item === 'string' || typeof item === 'number') {
      const normalized = String(item).replace(/\s+/g, ' ').trim();
      const lowerKey = String(key || '').toLowerCase();
      if (
        normalized &&
        normalized.length <= 120 &&
        ['text', 'label', 'contentdescription', 'description', 'title', 'name'].some((token) => lowerKey.includes(token)) &&
        !seen.has(normalized)
      ) {
        seen.add(normalized);
        texts.push(normalized);
      }
      return;
    }
    if (Array.isArray(item)) {
      for (const child of item) visit(child, key);
      return;
    }
    if (typeof item === 'object') {
      for (const [childKey, childValue] of Object.entries(item)) {
        visit(childValue, childKey);
      }
    }
  };
  visit(value);
  return texts;
}

function promptPreview(prompt) {
  const clean = String(prompt || '').replace(/\s+/g, ' ').trim();
  return clean.length > 160 ? `${clean.slice(0, 160)}...` : clean;
}

async function readActionBodyText(config) {
  if (config.actionBodyFile) {
    return fs.readFile(config.actionBodyFile, 'utf8');
  }
  if (config.actionBodyStdin || config.actionBody === '-') {
    return readStdinText();
  }
  return String(config.actionBody || '');
}

function readStdinText() {
  return new Promise((resolve, reject) => {
    let text = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      text += chunk;
    });
    process.stdin.on('end', () => resolve(text));
    process.stdin.on('error', reject);
  });
}

async function parseActionBody(config) {
  const text = (await readActionBodyText(config)).trim();
  if (!text) {
    throw new PhoneBridgeError(
      'missing_action_body_json',
      '缺少动作 JSON。PowerShell 请优先使用 --action-body-file 或 --action-body-stdin。',
      { retryable: false, currentStep: 'parse_action_body' },
    );
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new PhoneBridgeError(
      'invalid_action_body_json',
      '动作 JSON 格式不正确。PowerShell 会改写命令行引号，请使用 --action-body-file 或 --action-body-stdin。',
      { retryable: false, currentStep: 'parse_action_body', details: { reason: error?.message || String(error) } },
    );
  }
}

function print(config, payload, human) {
  if (config.json) {
    console.log(JSON.stringify({ ...payload, configSource: payload?.configSource || config.source || '' }, null, 2));
  } else {
    console.log(human);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  lastArgs = args;
  if (args.help) {
    console.log(usage());
    return;
  }
  const config = await resolveConfig(args);
  lastConfig = config;
  ensurePhoneConfig(config);

  if (config.command === 'status') {
    const payload = await signedJsonRequest(config, 'GET', '/api/lumi/vision/status?_lumi=1', undefined, 30_000);
    print(config, payload, `vision=${payload?.data?.vision?.mode || 'unknown'} reason=${payload?.data?.vision?.reason || 'unknown'}`);
    return;
  }

  if (config.command === 'read') {
    const result = await readScreenDirect(config);
    print(config, result, result.summary);
    return;
  }

  if (config.command === 'frame') {
    const cached = await cachedFrame(config);
    if (cached) {
      print(config, cached, `Using cached vision frame: ${cached.filePath}`);
      return;
    }
    const payload = await signedJsonRequest(config, 'GET', frameEndpoint(config), undefined, config.frameTimeoutMs);
    const filePath = await saveFrame(config, payload);
    const result = { ok: true, filePath, frame: payload.data };
    print(config, result, `Saved vision frame: ${filePath}`);
    return;
  }

  if (config.command === 'action') {
    if (!config.forceAction) {
      throw new Error('Refusing direct vision action without --force-action. Default flow: send a better natural-language task to APKClaw Agent; use direct visual actions only for debugging or fallback after repeated APKClaw failure.');
    }
    const body = await parseActionBody(config);
    const safety = inspectVisionActionPlan(body, { strict: !config.allowUnknownTarget });
    if (!safety.allowed) {
      throw new Error(`Vision safety guard blocked action: ${safety.reason}`);
    }
    const actionBody = minimalActionForPhone(body);
    const endpoint = visionActionEndpointForBody(actionBody, config.fastPath);
    const payload = await signedJsonRequest(config, 'POST', endpoint, actionBody, Math.min(25_000, config.actionTimeoutMs || 25_000));
    print(config, payload, `action=${payload?.data?.action || body.action} success=${payload?.success !== false} safety=${safety.category}`);
    return;
  }

  throw new Error(`Unknown command: ${config.command}`);
}

main().catch((error) => {
  const config = lastConfig || lastArgs || {};
  const payload = phoneBridgeErrorPayload(error, config, config.command || 'vision');
  if (config.json || process.argv.includes('--json')) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    console.error(`ERROR: ${payload.message}`);
  }
  process.exitCode = 1;
});
