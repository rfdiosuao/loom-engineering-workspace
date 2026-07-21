#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ensurePhoneConfig, readLauncherPhoneConfigByDevice, signedJsonRequest } from './openclaw-phone-secure.mjs';
import {
  buildGameModeAgentPrompt,
  inspectVisionActionPlan,
  minimalActionForPhone,
  visionSafetyPolicy,
} from './lib/vision-safety.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_OUT_DIR = path.join(PROJECT_ROOT, 'data', 'phone-frames');

function usage() {
  return `
OpenClaw game/vision loop CLI

Usage:
  npm run phone:game -- run --goal "inspect this game screen"
  npm run phone:game -- run --goal "open repair tools" --plan-body "{\\"action\\":\\"tap\\",\\"gridCell\\":\\"F3\\",\\"targetLabel\\":\\"settings wrench\\",\\"reason\\":\\"open safe repair/settings panel\\"}"
  npm run phone:game -- act --plan-body "{\\"action\\":\\"tap\\",\\"gridCell\\":\\"F3\\",\\"targetLabel\\":\\"settings wrench\\",\\"reason\\":\\"open safe repair/settings panel\\"}"

Commands:
  run                         Probe APKClaw Agent, capture a vision frame, and optionally execute one guarded visual plan
  capture                     Capture a game-mode vision frame and sidecar JSON
  act                         Execute one guarded visual plan through APKClaw Agent by default

Options:
  --goal <text>                User goal for this game-mode step
  --plan-body <json>           OpenClaw visual plan. Must include action plus targetLabel/reason for mutating actions
  --direct-action              Debug/fallback: call /api/lumi/vision/action directly instead of APKClaw Agent
  --force-direct               Required together with --direct-action
  --allow-unknown-target       Debug only. Allow missing targetLabel/reason metadata. Blacklisted labels still block
  --out <path>                 Frame path. Default: data/phone-frames/game-frame-<time>.jpg
  --format <jpeg|png>          Default: jpeg
  --quality <n>                Default: 82
  --max-long-side <n>          Default: 1600
  --grid-columns <n>           Default: 6
  --grid-rows <n>              Default: 12
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
    goal: '',
    planBody: '',
    directAction: false,
    forceDirect: false,
    allowUnknownTarget: false,
    phoneUrl: '',
    phoneToken: '',
    out: '',
    format: 'jpeg',
    quality: 82,
    maxLongSide: 1600,
    gridColumns: 6,
    gridRows: 12,
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
      case '--goal':
        args.goal = next();
        break;
      case '--plan-body':
        args.planBody = next();
        break;
      case '--direct-action':
        args.directAction = true;
        break;
      case '--force-direct':
        args.forceDirect = true;
        break;
      case '--allow-unknown-target':
        args.allowUnknownTarget = true;
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

  if (!args.command) args.command = 'run';
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
    overlayGrid: 'true',
  });
  return `/api/lumi/vision/frame?${query.toString()}`;
}

async function captureFrame(config, tag = 'game-frame') {
  const payload = await signedJsonRequest(config, 'GET', frameEndpoint(config), undefined, 60_000);
  const image = payload?.data?.image;
  if (!image?.base64) throw new Error('Vision frame did not include image.base64');
  const mime = image.mime || 'image/jpeg';
  const extension = mime.includes('png') ? 'png' : 'jpg';
  const out = config.out || path.join(DEFAULT_OUT_DIR, `${tag}-${timestamp()}.${extension}`);
  await fs.mkdir(path.dirname(out), { recursive: true });
  await fs.writeFile(out, Buffer.from(image.base64, 'base64'));

  const frame = { ...payload.data };
  if (frame.image) frame.image = { ...frame.image, base64: undefined, dataUrl: undefined };
  const sidecar = `${out}.json`;
  await fs.writeFile(sidecar, JSON.stringify({
    schema: 'openclaw.game.frame.v1',
    imagePath: out,
    sidecarPath: sidecar,
    frame,
    safety: visionSafetyPolicy(),
    requestedPlanSchema: {
      action: 'tap | long_press | swipe | drag | wait | finish',
      targetLabel: 'short visible label, required for mutating actions',
      reason: 'why this is safe and useful',
      gridCell: 'optional A1-style cell',
      x: 'optional screen x',
      y: 'optional screen y',
      start: 'for swipe/drag',
      end: 'for swipe/drag',
    },
  }, null, 2), 'utf8');

  return { imagePath: out, sidecarPath: sidecar, frame: payload.data };
}

async function runProbe(config) {
  const goal = config.goal || 'inspect the current game/canvas screen safely';
  const prompt = [
    'OpenClaw game-mode probe.',
    `Goal: ${goal}.`,
    'First call get_screen_info.',
    'If accessibility nodes are empty, low-confidence, or the screen is game/canvas/image-heavy, do not loop and do not guess.',
    'A single APKClaw Agent task can run at most 60 rounds; finish early with needs_vision or needs_followup instead of burning rounds.',
    'Do not tap login, authorization, payment, purchase, recharge, account binding, delete, clear-cache, upload-log, log-out, or exit-game targets.',
    'If visual help is needed, call finish with a concise "needs_vision:" summary.',
  ].join('\n');

  const payload = await signedJsonRequest(config, 'POST', '/api/lumi/agent/execute_task', {
    prompt,
    use_template: false,
    force_agent: true,
    learn_template: false,
    read_only: false,
    tool_policy: 'safe_action',
    template_params: {},
    timeout_sec: 600,
  }, 615_000);
  return payload?.data || payload;
}

async function executePlan(config, plan, frame) {
  const safety = inspectVisionActionPlan(plan, { strict: !config.allowUnknownTarget });
  if (!safety.allowed) {
    throw new Error(`Vision safety guard blocked action: ${safety.reason}`);
  }

  if (config.directAction) {
    if (!config.forceDirect) {
      throw new Error('Refusing direct vision action without --force-direct. Default game mode commands APKClaw Agent first.');
    }
    const payload = await signedJsonRequest(config, 'POST', '/api/lumi/vision/action', minimalActionForPhone(plan), 60_000);
    return { mode: 'direct_action', safety, result: payload?.data || payload };
  }

  const prompt = buildGameModeAgentPrompt(config.goal, plan, frame);
  const payload = await signedJsonRequest(config, 'POST', '/api/lumi/agent/execute_task', {
    prompt,
    use_template: false,
    force_agent: true,
    learn_template: false,
    read_only: false,
    tool_policy: 'safe_action',
    template_params: {},
    timeout_sec: 600,
  }, 615_000);
  return { mode: 'agent_guided', safety, result: payload?.data || payload };
}

function parsePlanBody(value) {
  if (!value) return null;
  const plan = JSON.parse(value);
  if (!plan || typeof plan !== 'object' || Array.isArray(plan)) {
    throw new Error('--plan-body must be a JSON object');
  }
  return plan;
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

  if (config.command === 'capture') {
    const captured = await captureFrame(config);
    print(config, captured, `Captured game frame: ${captured.imagePath}\nSidecar: ${captured.sidecarPath}`);
    return;
  }

  if (config.command === 'act') {
    const plan = parsePlanBody(config.planBody);
    if (!plan) throw new Error('Missing --plan-body');
    const earlySafety = inspectVisionActionPlan(plan, { strict: !config.allowUnknownTarget });
    if (!earlySafety.allowed) {
      throw new Error(`Vision safety guard blocked action: ${earlySafety.reason}`);
    }
    const status = await signedJsonRequest(config, 'GET', '/api/lumi/vision/status?_lumi=1', undefined, 30_000);
    const executed = await executePlan(config, plan, status?.data || {});
    const after = await captureFrame({ ...config, out: '' }, 'game-after-action');
    const result = { ok: true, executed, after };
    print(config, result, `Executed ${executed.mode}; after frame: ${after.imagePath}; safety=${executed.safety.category}`);
    return;
  }

  if (config.command === 'run') {
    const probe = await runProbe(config);
    const frame = await captureFrame(config);
    const plan = parsePlanBody(config.planBody);
    if (!plan) {
      const result = {
        ok: true,
        needsOpenClawVisionPlan: true,
        probe,
        frame,
        safety: visionSafetyPolicy(),
      };
      print(
        config,
        result,
        [
          `Probe answer: ${probe?.answer || probe?.error || 'ok'}`,
          `Captured game frame: ${frame.imagePath}`,
          `Sidecar: ${frame.sidecarPath}`,
          'Next: inspect the image and rerun with --plan-body containing action, targetLabel, and reason.',
        ].join('\n')
      );
      return;
    }
    const executed = await executePlan(config, plan, frame.frame || {});
    const after = await captureFrame({ ...config, out: '' }, 'game-after-action');
    const result = { ok: true, probe, before: frame, executed, after };
    print(config, result, `Probe + ${executed.mode} done; after frame: ${after.imagePath}; safety=${executed.safety.category}`);
    return;
  }

  throw new Error(`Unknown command: ${config.command}`);
}

main().catch((error) => {
  console.error(`ERROR: ${error?.message || error}`);
  process.exitCode = 1;
});
