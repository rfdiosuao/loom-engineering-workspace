#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ensurePhoneConfig, readLauncherPhoneConfigByDevice, signedJsonRequest } from './openclaw-phone-secure.mjs';
import { inspectVisionActionPlan, minimalActionForPhone } from './lib/vision-safety.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_OUT_DIR = path.join(PROJECT_ROOT, 'data', 'phone-frames');

function usage() {
  return `
OpenClaw phone vision/game-mode CLI

Usage:
  npm run phone:vision -- status
  npm run phone:vision -- frame --out ./data/phone-frames/frame.jpg
  npm run phone:vision -- action --force-action --action-body "{\\"action\\":\\"tap\\",\\"gridCell\\":\\"C7\\",\\"targetLabel\\":\\"settings button\\",\\"reason\\":\\"open safe settings panel\\"}"

Commands:
  status                      Read game/vision mode status and current hints
  frame                       Capture a signed vision frame with grid and coordinate mapping
  action                      Execute a visual coordinate action. Debug/fallback only; requires --force-action

Frame options:
  --out <path>                 Save returned image. Default: data/phone-frames/vision-frame-<time>.jpg
  --format <jpeg|png>          Default: jpeg
  --quality <n>                JPEG quality, phone clamps to 45-95. Default: 82
  --max-long-side <n>          Phone-side image long edge. Default: 1600
  --grid-columns <n>           Default: 6
  --grid-rows <n>              Default: 12
  --no-grid                    Disable grid overlay

Action options:
  --action-body <json>         Raw body for /api/lumi/vision/action
  --force-action               Required for action. Use only after APKClaw Agent fails, for debugging, or for explicit coordinate tasks
  --allow-unknown-target        Debug only. Permit an action plan without targetLabel/reason metadata. Blacklisted labels still block.

Common options:
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
    deviceId: '',
    phoneUrl: '',
    phoneToken: '',
    out: '',
    format: 'jpeg',
    quality: 82,
    maxLongSide: 1600,
    gridColumns: 6,
    gridRows: 12,
    overlayGrid: true,
    actionBody: '',
    forceAction: false,
    allowUnknownTarget: false,
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
      case '--force-action':
        args.forceAction = true;
        break;
      case '--allow-unknown-target':
        args.allowUnknownTarget = true;
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
      if (error?.code !== 'ENOENT') throw new Error(`Failed to read ${filePath}: ${error.message}`);
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

function timestamp() {
  return new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '').replace('T', '-');
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
  const out = config.out || path.join(DEFAULT_OUT_DIR, `vision-frame-${timestamp()}.${extension}`);
  await fs.mkdir(path.dirname(out), { recursive: true });
  await fs.writeFile(out, Buffer.from(image.base64, 'base64'));
  return out;
}

function print(config, payload, human) {
  if (config.json) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    console.log(human);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }
  const config = await resolveConfig(args);
  ensurePhoneConfig(config);

  if (config.command === 'status') {
    const payload = await signedJsonRequest(config, 'GET', '/api/lumi/vision/status?_lumi=1', undefined, 30_000);
    print(config, payload, `vision=${payload?.data?.vision?.mode || 'unknown'} reason=${payload?.data?.vision?.reason || 'unknown'}`);
    return;
  }

  if (config.command === 'frame') {
    const payload = await signedJsonRequest(config, 'GET', frameEndpoint(config), undefined, 60_000);
    const filePath = await saveFrame(config, payload);
    const result = { ok: true, filePath, frame: payload.data };
    print(config, result, `Saved vision frame: ${filePath}`);
    return;
  }

  if (config.command === 'action') {
    if (!config.forceAction) {
      throw new Error('Refusing direct vision action without --force-action. Default flow: send a better natural-language task to APKClaw Agent; use direct visual actions only for debugging or fallback after repeated APKClaw failure.');
    }
    if (!config.actionBody) throw new Error('Missing --action-body JSON');
    const body = JSON.parse(config.actionBody);
    const safety = inspectVisionActionPlan(body, { strict: !config.allowUnknownTarget });
    if (!safety.allowed) {
      throw new Error(`Vision safety guard blocked action: ${safety.reason}`);
    }
    const payload = await signedJsonRequest(config, 'POST', '/api/lumi/vision/action', minimalActionForPhone(body), 60_000);
    print(config, payload, `action=${payload?.data?.action || body.action} success=${payload?.success !== false} safety=${safety.category}`);
    return;
  }

  throw new Error(`Unknown command: ${config.command}`);
}

main().catch((error) => {
  console.error(`ERROR: ${error?.message || error}`);
  process.exitCode = 1;
});
