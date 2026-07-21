#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ensurePhoneConfig, readLauncherPhoneConfigByDevice, signedFetch, signedJsonRequest } from './openclaw-phone-secure.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_OUT_DIR = path.join(PROJECT_ROOT, 'data', 'phone-videos');
const REQUEST_TIMEOUT_MS = 120_000;

function usage() {
  return `
OpenClaw phone video CLI

Usage:
  npm run phone:video -- status
  npm run phone:video -- start --max-seconds 60 --filename demo.mp4
  npm run phone:video -- stop
  npm run phone:video -- list
  npm run phone:video -- download --latest --out-dir ./data/phone-videos

Commands:
  status                      Read screen recording state
  start                       Ask the phone to start screen recording
  stop                        Stop the current recording
  list                        List videos recorded by APKClaw
  download                    Download a recording from phone to PC

Options:
  --device-id <id>             Optional. Select one configured APKClaw device from launcher
  --phone-url <url>            Optional. Defaults to launcher Phone Control config, then env
  --phone-token <token>        Optional. Defaults to launcher Phone Control config, then env
  --id <filename>              Recording id/filename for download
  --latest                     Download the newest recording
  --out-dir <path>             Download directory. Default: data/phone-videos
  --filename <name>            Filename to create on phone when recording starts
  --max-seconds <n>            Max recording seconds. Default phone-side cap: 180, max: 600
  --fps <n>                    Recording FPS. Phone clamps to 10-60
  --bit-rate <n>               Recording bit rate. Phone clamps to 800000-20000000
  --width <n>                  Optional output width
  --height <n>                 Optional output height
  --json                       Print machine-readable JSON
  -h, --help                   Show help

Notes:
  Android screen recording requires a one-time consent prompt on the phone for each start request.
`.trim();
}

function parseArgs(argv) {
  const args = {
    command: '',
    deviceId: '',
    phoneUrl: '',
    phoneToken: '',
    id: '',
    latest: false,
    outDir: DEFAULT_OUT_DIR,
    filename: '',
    maxSeconds: undefined,
    fps: undefined,
    bitRate: undefined,
    width: undefined,
    height: undefined,
    json: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (!value || value.startsWith('--')) {
        throw new Error(`Missing value for ${arg}`);
      }
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
      case '--id':
        args.id = next();
        break;
      case '--latest':
        args.latest = true;
        break;
      case '--out-dir':
        args.outDir = path.resolve(next());
        break;
      case '--filename':
        args.filename = next();
        break;
      case '--max-seconds':
        args.maxSeconds = nextInt();
        break;
      case '--fps':
        args.fps = nextInt();
        break;
      case '--bit-rate':
      case '--bitrate':
        args.bitRate = nextInt();
        break;
      case '--width':
        args.width = nextInt();
        break;
      case '--height':
        args.height = nextInt();
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
    phoneUrl: firstNonEmpty(
      args.phoneUrl,
      process.env.OPENCLAW_PHONE_BASE_URL,
      process.env.APKCLAW_BASE_URL,
      runtime?.phone?.baseUrl,
      launcherPhone.phoneUrl
    ),
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

async function requestJson(config, method, endpoint, body) {
  ensurePhoneConfig(config);
  return signedJsonRequest(config, method, endpoint, body, REQUEST_TIMEOUT_MS);
}

function startBody(config) {
  const body = {};
  if (config.filename) body.filename = config.filename;
  if (Number.isFinite(config.maxSeconds)) body.maxSeconds = config.maxSeconds;
  if (Number.isFinite(config.fps)) body.fps = config.fps;
  if (Number.isFinite(config.bitRate)) body.bitRate = config.bitRate;
  if (Number.isFinite(config.width)) body.width = config.width;
  if (Number.isFinite(config.height)) body.height = config.height;
  return body;
}

async function listVideos(config) {
  const payload = await requestJson(config, 'GET', '/api/lumi/media/videos?_lumi=1');
  return payload?.data?.recordings || payload?.recordings || [];
}

async function downloadVideo(config) {
  let id = config.id;
  if (!id && config.latest) {
    const videos = await listVideos(config);
    id = videos?.[0]?.id || videos?.[0]?.filename || '';
  }
  if (!id) throw new Error('Missing video id. Use --id <filename> or --latest.');

  ensurePhoneConfig(config);
  const response = await signedFetch(config, 'GET', `/api/lumi/media/video?id=${encodeURIComponent(id)}`, 300_000);
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`Video download failed: HTTP ${response.status}${text ? ` ${text.slice(0, 160)}` : ''}`);
  }

  await fs.mkdir(config.outDir, { recursive: true });
  const filename = sanitizeFilename(id);
  const filePath = path.join(config.outDir, filename);
  const buffer = Buffer.from(await response.arrayBuffer());
  await fs.writeFile(filePath, buffer);
  return {
    ok: true,
    id,
    filePath,
    sizeBytes: buffer.length,
  };
}

function sanitizeFilename(value) {
  return String(value || '')
    .split(/[\\/]/)
    .pop()
    .replace(/[\\/:*?"<>|\p{C}]/gu, '_')
    .replace(/_+/g, '_')
    .replace(/^[_\s.]+|[_\s.]+$/g, '')
    || `apkclaw-video-${timestamp()}.mp4`;
}

function timestamp() {
  return new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '').replace('T', '-');
}

function print(config, payload, human) {
  if (config.json) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    console.log(human);
  }
}

async function main() {
  const parsed = parseArgs(process.argv.slice(2));
  if (parsed.help) {
    console.log(usage());
    return;
  }

  const config = await resolveConfig(parsed);
  switch (config.command) {
    case 'status': {
      const payload = await requestJson(config, 'GET', '/api/lumi/media/record/status?_lumi=1');
      print(config, payload, `state=${payload?.data?.state || 'unknown'} recording=${Boolean(payload?.data?.recording)}`);
      break;
    }
    case 'start': {
      const payload = await requestJson(config, 'POST', '/api/lumi/media/record/start', startBody(config));
      const reason = payload?.data?.reason || 'start_requested';
      print(config, payload, `start accepted=${Boolean(payload?.data?.accepted)} reason=${reason}`);
      break;
    }
    case 'stop': {
      const payload = await requestJson(config, 'POST', '/api/lumi/media/record/stop');
      const latest = payload?.data?.latest?.id ? ` latest=${payload.data.latest.id}` : '';
      print(config, payload, `stop accepted=${Boolean(payload?.data?.accepted)}${latest}`);
      break;
    }
    case 'list': {
      const videos = await listVideos(config);
      print(config, { ok: true, videos }, videos.length ? videos.map((item) => `${item.id || item.filename} ${item.sizeBytes || 0} bytes`).join('\n') : 'No APKClaw recordings found.');
      break;
    }
    case 'download': {
      const result = await downloadVideo(config);
      print(config, result, `Downloaded: ${result.filePath} (${result.sizeBytes} bytes)`);
      break;
    }
    default:
      throw new Error(`Unknown command: ${config.command}`);
  }
}

main().catch((error) => {
  console.error(`ERROR: ${error?.message || error}`);
  process.exitCode = 1;
});
