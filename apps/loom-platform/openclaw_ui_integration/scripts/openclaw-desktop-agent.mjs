#!/usr/bin/env node

import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const defaultRoot = path.resolve(scriptDir, '..');

function usage() {
  return `
OpenClaw desktop Agent CLI

Usage:
  npm run desktop:agent -- status
  npm run desktop:agent -- start
  npm run desktop:agent -- screenshot --out .\\data\\desktop.png
  npm run desktop:agent -- wechat unread
  npm run desktop:agent -- wechat send --text "message" --confirmed
  npm run desktop:reply -- observe
  npm run desktop:reply -- once --text "reply text" --confirmed

Commands:
  status                    Read launcher Desktop Agent status
  health                    Probe Luminode sidecar health
  config                    Read or update launcher Desktop Agent config
  start                     Start Luminode through the launcher Bridge
  stop                      Stop Luminode through the launcher Bridge
  screenshot                Capture a desktop screenshot through the Bridge
  click                     Click coordinates after explicit confirmation
  type                      Type text after explicit confirmation
  wechat unread             Inspect unread WeChat state
  wechat send               Send one explicit WeChat message
  reply observe             Read status, health, unread state, and screenshot summary
  reply once                Send one explicit reply text after confirmation

Options:
  --root <path>             Launcher or OpenClawFiles root. Default: auto-detect
  --python <path>           Python executable. Default: bundled runtime or python
  --bridge-timeout-sec <n>  Bridge startup wait. Default: 20
  --wait-sec <n>            start: wait for sidecar health. Default: 15
  --timeout-ms <n>          HTTP request timeout. Default: 45000
  --text <text>             Text for type/wechat send/reply once
  --x <n> --y <n>           Coordinates for click
  --out <path>              Save screenshot image if the sidecar returns one
  --agent-dir <path>        config: set Luminode agent directory
  --port <n>                config: set Luminode HTTP API port
  --app-type <name>         config: set app type, e.g. wechat, dingtalk, lark
  --enabled | --disabled    config: toggle desktop agent enable flag
  --allow-click <true|false>
  --allow-type <true|false>
  --allow-wechat-send <true|false>
  --send-mode <mode>        config: draft_only or auto_enter
  --confirmed, --yes        Required for mutating desktop actions
  --no-screenshot           reply observe: skip screenshot
  --json                    Print machine-readable JSON
  -h, --help                Show help
`.trim();
}

function parseArgs(argv) {
  const args = {
    command: '',
    subcommand: '',
    root: '',
    python: process.env.OPENCLAW_PYTHON || '',
    bridgeTimeoutSec: 20,
    waitSec: 15,
    timeoutMs: 45_000,
    text: '',
    x: null,
    y: null,
    out: '',
    agentDir: '',
    port: null,
    appType: '',
    enabled: null,
    allowClick: null,
    allowType: null,
    allowWechatSend: null,
    sendMode: '',
    confirmed: false,
    noScreenshot: false,
    json: false,
    help: false,
  };
  const positional = [];

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (value === undefined || value.startsWith('--')) throw new Error(`Missing value for ${arg}`);
      i += 1;
      return value;
    };
    const nextInt = () => {
      const value = Number.parseInt(next(), 10);
      if (!Number.isFinite(value)) throw new Error(`Invalid number for ${arg}`);
      return value;
    };
    const nextBool = () => {
      const value = next().toLowerCase();
      if (['true', '1', 'yes', 'on'].includes(value)) return true;
      if (['false', '0', 'no', 'off'].includes(value)) return false;
      throw new Error(`Invalid boolean for ${arg}: ${value}`);
    };

    switch (arg) {
      case '-h':
      case '--help':
        args.help = true;
        break;
      case '--root':
        args.root = next();
        break;
      case '--python':
        args.python = next();
        break;
      case '--bridge-timeout-sec':
        args.bridgeTimeoutSec = nextInt();
        break;
      case '--wait-sec':
        args.waitSec = nextInt();
        break;
      case '--timeout-ms':
        args.timeoutMs = nextInt();
        break;
      case '--text':
        args.text = next();
        break;
      case '--x':
        args.x = nextInt();
        break;
      case '--y':
        args.y = nextInt();
        break;
      case '--out':
        args.out = next();
        break;
      case '--agent-dir':
        args.agentDir = next();
        break;
      case '--port':
        args.port = nextInt();
        break;
      case '--app-type':
        args.appType = next();
        break;
      case '--enabled':
        args.enabled = true;
        break;
      case '--disabled':
        args.enabled = false;
        break;
      case '--allow-click':
        args.allowClick = nextBool();
        break;
      case '--allow-type':
        args.allowType = nextBool();
        break;
      case '--allow-wechat-send':
        args.allowWechatSend = nextBool();
        break;
      case '--send-mode':
        args.sendMode = next();
        break;
      case '--confirmed':
      case '--yes':
        args.confirmed = true;
        break;
      case '--no-screenshot':
        args.noScreenshot = true;
        break;
      case '--json':
        args.json = true;
        break;
      default:
        if (arg.startsWith('-')) throw new Error(`Unknown option: ${arg}`);
        positional.push(arg.toLowerCase());
    }
  }

  args.command = positional[0] || 'status';
  args.subcommand = positional[1] || '';
  args.bridgeTimeoutSec = Math.max(3, args.bridgeTimeoutSec);
  args.waitSec = Math.max(0, args.waitSec);
  args.timeoutMs = Math.max(1000, args.timeoutMs);
  return args;
}

async function pathExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function firstExisting(candidates) {
  for (const candidate of candidates) {
    if (candidate && await pathExists(candidate)) return candidate;
  }
  return candidates.find(Boolean) || '';
}

async function resolveRoot(inputRoot) {
  if (inputRoot) return path.resolve(inputRoot);
  const cwd = process.cwd();
  const candidates = [
    cwd,
    path.join(cwd, 'openclaw_new_launcher'),
    path.join(cwd, 'openclaw_ui_integration'),
    defaultRoot,
  ];
  for (const candidate of candidates) {
    if (await pathExists(path.join(candidate, 'python', 'bridge.py')) || await pathExists(path.join(candidate, '_up_', 'python', 'bridge.py'))) {
      return path.resolve(candidate);
    }
  }
  return defaultRoot;
}

async function resolveBridgePath(root) {
  const bridgePath = await firstExisting([
    path.join(root, 'python', 'bridge.py'),
    path.join(root, '_up_', 'python', 'bridge.py'),
    path.join(root, 'OpenClawFiles', '_up_', 'python', 'bridge.py'),
    path.join(root, 'OpenClawFiles', 'python', 'bridge.py'),
  ]);
  if (!bridgePath || !await pathExists(bridgePath)) {
    throw new Error(`Bridge script not found under ${root}`);
  }
  return bridgePath;
}

async function resolvePython(root, requested) {
  if (requested) return requested;
  const candidates = [
    path.join(root, '_up_', 'python-runtime', process.platform === 'win32' ? 'python.exe' : 'bin/python3'),
    path.join(root, 'python-runtime', process.platform === 'win32' ? 'python.exe' : 'bin/python3'),
    path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python3'),
  ];
  for (const candidate of candidates) {
    if (await pathExists(candidate)) return candidate;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

function bridgeEnv(root, bridgePath) {
  const env = {
    ...process.env,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    PYTHONDONTWRITEBYTECODE: '1',
  };
  const bundledPython = path.join(root, '_up_', 'python');
  if (bridgePath.includes(`${path.sep}_up_${path.sep}python${path.sep}`)) {
    env.PYTHONPATH = bundledPython + (env.PYTHONPATH ? `${path.delimiter}${env.PYTHONPATH}` : '');
  }
  return env;
}

async function startBridge(config) {
  config.bridgeLock = await acquireBridgeLock(config.root, Math.max(config.bridgeTimeoutSec * 1000, 10_000));
  const bridgePath = await resolveBridgePath(config.root);
  const python = await resolvePython(config.root, config.python);
  const child = spawn(python, [bridgePath], {
    cwd: config.root,
    env: bridgeEnv(config.root, bridgePath),
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  let stdout = '';
  let stderr = '';
  let port = '';
  let token = '';
  let impl = '';

  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    stdout += chunk;
    for (const line of stdout.split(/\r?\n/)) {
      if (!port && line.startsWith('BRIDGE_PORT=')) port = line.slice('BRIDGE_PORT='.length).trim();
      if (!token && line.startsWith('BRIDGE_TOKEN=')) token = line.slice('BRIDGE_TOKEN='.length).trim();
      if (!impl && line.startsWith('BRIDGE_IMPL=')) impl = line.slice('BRIDGE_IMPL='.length).trim();
    }
  });
  child.stderr.on('data', (chunk) => {
    stderr += chunk;
  });

  const deadline = Date.now() + config.bridgeTimeoutSec * 1000;
  while (Date.now() < deadline) {
    if (port && token) {
      await waitForTcp(Number.parseInt(port, 10), 5000);
      return {
        child,
        port: Number.parseInt(port, 10),
        token,
        impl,
        baseUrl: `http://127.0.0.1:${port}`,
      };
    }
    if (child.exitCode !== null) {
      throw new Error(`Bridge exited before ready. stdout=${stdout.trim()} stderr=${stderr.trim()}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }

  stopBridge(child);
  throw new Error(`Bridge did not become ready within ${config.bridgeTimeoutSec}s. stdout=${stdout.trim()} stderr=${stderr.trim()}`);
}

async function waitForTcp(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await canConnect(port)) return;
    await new Promise((resolve) => setTimeout(resolve, 80));
  }
  throw new Error(`Bridge port ${port} did not accept TCP connections within ${timeoutMs}ms.`);
}

function canConnect(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: '127.0.0.1', port });
    const done = (ok) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(300);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
  });
}

function stopBridge(child) {
  if (!child || child.exitCode !== null) return;
  try {
    child.kill();
  } catch {
    // best effort
  }
}

async function acquireBridgeLock(root, timeoutMs) {
  const lockPath = path.join(root, 'data', '.openclaw', 'launcher', 'desktop-cli-bridge.lock');
  await fs.mkdir(path.dirname(lockPath), { recursive: true });
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const handle = await fs.open(lockPath, 'wx');
      await handle.writeFile(JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() }));
      return { path: lockPath, handle };
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      if (await removeStaleLock(lockPath)) continue;
      await new Promise((resolve) => setTimeout(resolve, 120));
    }
  }
  throw new Error(`Timed out waiting for desktop CLI bridge lock: ${lockPath}`);
}

async function removeStaleLock(lockPath) {
  try {
    const stat = await fs.stat(lockPath);
    if (Date.now() - stat.mtimeMs < 60_000) return false;
    await fs.rm(lockPath, { force: true });
    return true;
  } catch {
    return true;
  }
}

async function releaseBridgeLock(lock) {
  if (!lock) return;
  try {
    await lock.handle?.close();
  } catch {
    // best effort
  }
  try {
    await fs.rm(lock.path, { force: true });
  } catch {
    // best effort
  }
}

async function bridgeRequest(bridge, config, method, endpoint, body = undefined) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);
  try {
    const response = await fetch(`${bridge.baseUrl}${endpoint}`, {
      method,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        'X-Bridge-Token': bridge.token,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json; charset=utf-8' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    const payload = parseJson(text);
    if (!response.ok) {
      const errorText = payload?.error || payload?._meta?.error?.message || text || `HTTP ${response.status}`;
      const error = new Error(`[${response.status}] ${errorText}`);
      error.payload = payload;
      error.statusCode = response.status;
      throw error;
    }
    return payload;
  } finally {
    clearTimeout(timer);
  }
}

function parseJson(text) {
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { text };
  }
}

function requireConfirmed(args, label) {
  if (!args.confirmed) {
    throw new Error(`${label} requires --confirmed after explicit user approval.`);
  }
}

function configPatch(args) {
  const patch = {};
  const policy = {};
  const wechat = {};
  if (args.agentDir) patch.agentDir = args.agentDir;
  if (args.port !== null) patch.port = args.port;
  if (args.appType) patch.appType = args.appType;
  if (args.enabled !== null) patch.enabled = args.enabled;
  if (args.allowClick !== null) policy.allowClick = args.allowClick;
  if (args.allowType !== null) policy.allowType = args.allowType;
  if (args.allowWechatSend !== null) policy.allowWechatSend = args.allowWechatSend;
  if (args.sendMode) wechat.sendMode = args.sendMode;
  if (Object.keys(policy).length) patch.policy = policy;
  if (Object.keys(wechat).length) patch.wechat = wechat;
  return patch;
}

function configPatchRequiresConfirmation(patch) {
  return Boolean(
    patch?.policy?.allowClick === true ||
    patch?.policy?.allowType === true ||
    patch?.policy?.allowWechatSend === true ||
    patch?.wechat?.sendMode === 'auto_enter'
  );
}

function summarizeScreenshot(payload) {
  const image = findImageValue(payload);
  return {
    ok: Boolean(payload?.ok ?? payload?.success ?? image),
    imageAvailable: Boolean(image),
    imageBytesApprox: image ? Math.round(image.length * 0.75) : 0,
    keys: payload && typeof payload === 'object' ? Object.keys(payload).slice(0, 12) : [],
  };
}

function findImageValue(value) {
  if (!value || typeof value !== 'object') return '';
  const directKeys = ['screenshot', 'dataUrl', 'image', 'imageData', 'base64'];
  for (const key of directKeys) {
    const item = value[key];
    if (typeof item === 'string' && (item.startsWith('data:image/') || item.length > 1000)) return item;
  }
  for (const item of Object.values(value)) {
    if (item && typeof item === 'object') {
      const found = findImageValue(item);
      if (found) return found;
    }
  }
  return '';
}

async function saveImageIfRequested(payload, outPath, root) {
  if (!outPath) return null;
  const image = findImageValue(payload);
  if (!image) throw new Error('Screenshot response did not include image data.');
  const absoluteOut = path.resolve(root, outPath);
  const match = image.match(/^data:image\/[a-z0-9.+-]+;base64,(.+)$/i);
  const bytes = Buffer.from(match ? match[1] : image, 'base64');
  await fs.mkdir(path.dirname(absoluteOut), { recursive: true });
  await fs.writeFile(absoluteOut, bytes);
  return absoluteOut;
}

function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (!value || typeof value !== 'object') return value;
  const output = {};
  for (const [key, item] of Object.entries(value)) {
    const lowered = key.toLowerCase();
    if (lowered.includes('token') || lowered.includes('secret') || lowered.includes('authorization') || lowered.includes('apikey')) {
      output[key] = item ? '[redacted]' : item;
    } else if (typeof item === 'string' && (item.startsWith('data:image/') || item.length > 2000)) {
      output[key] = `[omitted string length=${item.length}]`;
    } else {
      output[key] = redact(item);
    }
  }
  return output;
}

async function runCommand(bridge, args) {
  const command = args.command;
  const sub = args.subcommand;

  if (command === 'status') return bridgeRequest(bridge, args, 'GET', '/api/desktop-agent/status');
  if (command === 'health') return bridgeRequest(bridge, args, 'GET', '/api/desktop-agent/health');
  if (command === 'start') {
    const started = await bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/start', {});
    const health = await waitForHealth(bridge, args);
    return { started, health };
  }
  if (command === 'stop') return bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/stop', {});

  if (command === 'config') {
    const patch = configPatch(args);
    if (!Object.keys(patch).length) {
      const status = await bridgeRequest(bridge, args, 'GET', '/api/desktop-agent/status');
      return status?.config || status;
    }
    if (configPatchRequiresConfirmation(patch)) requireConfirmed(args, 'Opening desktop mutation policy');
    return bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/config', patch);
  }

  if (command === 'screenshot') {
    const payload = await bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/screenshot', {});
    const saved = await saveImageIfRequested(payload, args.out, args.root);
    return { ...summarizeScreenshot(payload), saved };
  }

  if (command === 'click') {
    requireConfirmed(args, 'Desktop click');
    if (args.x === null || args.y === null) throw new Error('click requires --x and --y.');
    return bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/click', { x: args.x, y: args.y, confirmed: true });
  }

  if (command === 'type') {
    requireConfirmed(args, 'Desktop type');
    if (!args.text) throw new Error('type requires --text.');
    return bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/type', { text: args.text, confirmed: true });
  }

  if (command === 'wechat') {
    if (sub === 'unread' || !sub) return bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/wechat/unread', {});
    if (sub === 'send') {
      requireConfirmed(args, 'WeChat send');
      if (!args.text) throw new Error('wechat send requires --text.');
      return bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/wechat/send', { text: args.text, confirmed: true });
    }
    throw new Error(`Unknown wechat command: ${sub}`);
  }

  if (command === 'reply') {
    const mode = sub || 'observe';
    if (mode === 'observe') {
      const status = await safeCall(() => bridgeRequest(bridge, args, 'GET', '/api/desktop-agent/status'));
      const health = await safeCall(() => bridgeRequest(bridge, args, 'GET', '/api/desktop-agent/health'));
      const unread = await safeCall(() => bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/wechat/unread', {}));
      const screenshot = args.noScreenshot
        ? { skipped: true }
        : await safeCall(async () => {
            const payload = await bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/screenshot', {});
            const saved = await saveImageIfRequested(payload, args.out, args.root);
            return { ...summarizeScreenshot(payload), saved };
          });
      return { status, health, unread, screenshot };
    }
    if (mode === 'once') {
      requireConfirmed(args, 'Reply once');
      if (!args.text) throw new Error('reply once requires --text.');
      const unread = await safeCall(() => bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/wechat/unread', {}));
      const send = await bridgeRequest(bridge, args, 'POST', '/api/desktop-agent/wechat/send', { text: args.text, confirmed: true });
      return { unread, send };
    }
    if (mode === 'auto') {
      throw new Error('reply auto is not exposed by the Luminode sidecar yet. Use reply observe plus reply once, or add a one-shot auto-reply endpoint to Luminode.');
    }
    throw new Error(`Unknown reply command: ${mode}`);
  }

  throw new Error(`Unknown command: ${command}`);
}

async function waitForHealth(bridge, args) {
  const deadline = Date.now() + args.waitSec * 1000;
  let last = null;
  while (Date.now() <= deadline) {
    last = await safeCall(() => bridgeRequest(bridge, args, 'GET', '/api/desktop-agent/health'));
    if (last?.ok || last?.success) return last;
    if (args.waitSec <= 0) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return last;
}

async function safeCall(fn) {
  try {
    return await fn();
  } catch (error) {
    return {
      ok: false,
      success: false,
      error: error?.message || String(error),
      statusCode: error?.statusCode ?? null,
      payload: error?.payload ? redact(error.payload) : undefined,
    };
  }
}

function printResult(result, args) {
  const payload = redact(result);
  if (args.json) {
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
    return;
  }
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  args.root = await resolveRoot(args.root);
  let bridge = null;
  try {
    bridge = await startBridge(args);
    const result = await runCommand(bridge, args);
    printResult(result, args);
  } finally {
    if (bridge) stopBridge(bridge.child);
    await releaseBridgeLock(args.bridgeLock);
  }
}

main().catch((error) => {
  console.error(error?.message || error);
  process.exit(1);
});
