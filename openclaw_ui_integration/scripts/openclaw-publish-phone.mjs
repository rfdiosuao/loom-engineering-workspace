#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  readLauncherPhoneConfigByDevice,
  signedJsonRequest,
  uploadImageBuffer,
  uploadVideoBuffer,
} from './openclaw-phone-secure.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_TIMEOUT_SEC = 600;
const DEFAULT_MAX_WAIT_SEC = DEFAULT_TIMEOUT_SEC + 15;
const DEFAULT_POLL_MS = 1800;
const DEFAULT_RELAY_WAIT_SEC = 300;
const DEFAULT_RELAY_POLL_MS = 2000;
const DEFAULT_ALBUM = 'OpenClaw Publish';

const PLATFORM_META = {
  x: {
    label: 'X / Twitter',
    appName: 'X',
    hint: '先进入 X 的发帖入口，再填正文、附件和可见性设置，最后提交发布。',
  },
  xiaohongshu: {
    label: '小红书',
    appName: '小红书',
    hint: '优先确认标题、正文、话题和封面，再检查预览和发布按钮。',
  },
  douyin: {
    label: '抖音',
    appName: '抖音',
    hint: '优先使用视频发布入口，确认封面、标题、描述和发布状态。',
  },
  wechat: {
    label: '微信朋友圈',
    appName: '微信',
    hint: '进入朋友圈发布入口，检查可见性、定位和草稿状态后再提交。',
  },
  custom: {
    label: '自定义平台',
    appName: '目标应用',
    hint: '按照目标应用的发布入口执行，先确认发布草稿页，再处理素材和说明。',
  },
};

function usage() {
  return `
OpenClaw platform publish CLI

Usage:
  npm run phone:publish -- --platform xiaohongshu --title "..." --body "..." --image ./a.png --video ./b.mp4
  npm run phone:publish -- --transport reverse --platform douyin --packet-out .\\publish-packet.json
  npm run phone:publish -- --transport reverse --platform douyin --relay-url https://relay.example.com/api/lumi/publish/packet --relay-token ... --channel-id publish-channel-01 --wait-relay

Options:
  --platform <x|xiaohongshu|douyin|wechat|custom>  Default: xiaohongshu
  --transport <direct|reverse>                    Default: direct
  --title <text>                                  Post title / video title
  --body <text>                                   Main caption / body
  --hashtags <tag1,tag2>                          Comma, space or newline separated hashtags
  --notes <text>                                  Extra operator notes for the Agent prompt
  --album <name>                                  Default phone album. Default: OpenClaw Publish
  --relay-url <url>                               Optional reverse relay / phone publish endpoint
  --relay-token <token>                           Optional reverse relay auth token. Env: OPENCLAW_PUBLISH_RELAY_TOKEN
  --channel-id <id>                               Optional reverse publish channel
  --channel <id>                                  Alias for --channel-id
  --wait-relay                                    Wait for relay packet status done/failed in reverse mode
  --relay-wait-sec <n>                            Relay wait window. Default: ${DEFAULT_RELAY_WAIT_SEC}
  --relay-poll-ms <n>                             Relay status poll interval. Default: ${DEFAULT_RELAY_POLL_MS}
  --device-id <id>                                Optional launcher device id
  --phone-url <url>                               Optional phone Agent base URL
  --phone-token <token>                           Optional phone Agent token
  --image <path>                                  Repeatable image file path
  --video <path>                                  Repeatable video file path
  --file <path>                                   Repeatable generic media file path
  --packet-out <path>                             Write reverse packet to file
  --timeout-sec <n>                               APKClaw-side timeout. Default: 600
  --max-wait-sec <n>                              CLI wait window for direct mode. Default: 615
  --poll-ms <n>                                   Poll interval. Default: 1800
  --json                                          Print machine-readable JSON
  -h, --help                                      Show help
`.trim();
}

function parseArgs(argv) {
  const args = {
    platform: 'xiaohongshu',
    transport: 'direct',
    title: '',
    body: '',
    hashtags: '',
    notes: '',
    album: DEFAULT_ALBUM,
    deviceId: '',
    phoneUrl: '',
    phoneToken: '',
    relayUrl: '',
    relayToken: '',
    channelId: '',
    waitRelay: false,
    relayWaitSec: DEFAULT_RELAY_WAIT_SEC,
    relayPollMs: DEFAULT_RELAY_POLL_MS,
    imagePaths: [],
    videoPaths: [],
    filePaths: [],
    packetOut: '',
    timeoutSec: DEFAULT_TIMEOUT_SEC,
    maxWaitSec: DEFAULT_MAX_WAIT_SEC,
    pollMs: DEFAULT_POLL_MS,
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
      case '--platform':
        args.platform = next().toLowerCase();
        break;
      case '--transport':
        args.transport = next().toLowerCase();
        break;
      case '--title':
        args.title = next();
        break;
      case '--body':
        args.body = next();
        break;
      case '--hashtags':
        args.hashtags = next();
        break;
      case '--notes':
        args.notes = next();
        break;
      case '--album':
        args.album = next();
        break;
      case '--device-id':
        args.deviceId = next();
        break;
      case '--phone-url':
        args.phoneUrl = next();
        break;
      case '--phone-token':
        args.phoneToken = next();
        break;
      case '--relay-url':
        args.relayUrl = next();
        break;
      case '--relay-token':
        args.relayToken = next();
        break;
      case '--channel-id':
      case '--channel':
        args.channelId = next();
        break;
      case '--wait-relay':
        args.waitRelay = true;
        break;
      case '--relay-wait-sec':
        args.relayWaitSec = nextInt();
        break;
      case '--relay-poll-ms':
        args.relayPollMs = nextInt();
        break;
      case '--image':
        args.imagePaths.push(next());
        break;
      case '--video':
        args.videoPaths.push(next());
        break;
      case '--file':
        args.filePaths.push(next());
        break;
      case '--packet-out':
        args.packetOut = next();
        break;
      case '--timeout-sec':
        args.timeoutSec = nextInt();
        break;
      case '--max-wait-sec':
        args.maxWaitSec = nextInt();
        break;
      case '--poll-ms':
        args.pollMs = nextInt();
        break;
      case '--json':
        args.json = true;
        break;
      default:
        if (!arg.startsWith('-')) {
          if (!args.platform) {
            args.platform = arg;
          } else {
            throw new Error(`Unknown positional argument: ${arg}`);
          }
        } else {
          throw new Error(`Unknown option: ${arg}`);
        }
    }
  }

  args.platform = normalizePlatform(args.platform);
  args.transport = args.transport === 'reverse' ? 'reverse' : 'direct';
  args.timeoutSec = Math.max(30, args.timeoutSec);
  args.maxWaitSec = Math.max(30, args.maxWaitSec);
  args.pollMs = Math.max(500, args.pollMs);
  args.relayWaitSec = Math.max(5, args.relayWaitSec);
  args.relayPollMs = Math.max(500, args.relayPollMs);
  return args;
}

function normalizePlatform(value) {
  const text = String(value || '').trim().toLowerCase();
  if (text === 'x' || text === 'xiaohongshu' || text === 'douyin' || text === 'wechat' || text === 'custom') {
    return text;
  }
  return 'xiaohongshu';
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function splitHashtags(value) {
  return String(value || '')
    .split(/[\n,，\s]+/)
    .map((item) => item.trim().replace(/^#+/, ''))
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index)
    .slice(0, 12);
}

function normalizeMediaPath(filePath) {
  return path.resolve(filePath);
}

function inferMime(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.png') return 'image/png';
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.webp') return 'image/webp';
  if (ext === '.mp4') return 'video/mp4';
  if (ext === '.webm') return 'video/webm';
  if (ext === '.mov' || ext === '.qt') return 'video/quicktime';
  if (ext === '.mkv') return 'video/x-matroska';
  return '';
}

function inferKind(filePath, mime) {
  if (mime.startsWith('video/') || /\.(mp4|webm|mov|mkv)$/i.test(filePath)) return 'video';
  return 'image';
}

async function readRuntimeContext() {
  const candidates = [
    path.join(PROJECT_ROOT, 'data', '.openclaw', 'workspace', 'runtime-context.json'),
    path.join(PROJECT_ROOT, 'OpenClawFiles', 'data', '.openclaw', 'workspace', 'runtime-context.json'),
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

async function resolveConfig(args) {
  const runtime = await readRuntimeContext();
  const launcherPhone = await readLauncherPhoneConfigByDevice(args.deviceId);
  return {
    ...args,
    phoneUrl: firstNonEmpty(args.phoneUrl, process.env.OPENCLAW_PHONE_BASE_URL, process.env.APKCLAW_BASE_URL, runtime?.phone?.baseUrl, launcherPhone.phoneUrl),
    phoneToken: firstNonEmpty(args.phoneToken, process.env.OPENCLAW_PHONE_TOKEN, process.env.APKCLAW_TOKEN, launcherPhone.phoneToken),
    deviceId: args.deviceId || launcherPhone.id || runtime?.phone?.defaultDeviceId || '',
    album: firstNonEmpty(args.album, launcherPhone.album, DEFAULT_ALBUM),
    relayUrl: args.relayUrl.trim(),
    relayToken: firstNonEmpty(args.relayToken, process.env.OPENCLAW_PUBLISH_RELAY_TOKEN),
    channelId: args.channelId.trim(),
  };
}

async function readMediaEntries(args) {
  const paths = [
    ...args.imagePaths.map((filePath) => ({ filePath, forcedKind: 'image' })),
    ...args.videoPaths.map((filePath) => ({ filePath, forcedKind: 'video' })),
    ...args.filePaths.map((filePath) => ({ filePath, forcedKind: '' })),
  ];
  const entries = [];
  for (const item of paths) {
    const filePath = normalizeMediaPath(item.filePath);
    const bytes = await fs.readFile(filePath);
    const mime = inferMime(filePath) || (item.forcedKind === 'video' ? 'video/mp4' : 'image/png');
    const kind = item.forcedKind || inferKind(filePath, mime);
    entries.push({
      filePath,
      bytes,
      mime,
      kind,
      name: path.basename(filePath),
      size: bytes.length,
    });
  }
  return entries;
}

function buildPrompt(config, uploadedMediaRefs = []) {
  const meta = PLATFORM_META[config.platform] || PLATFORM_META.custom;
  const hashtags = splitHashtags(config.hashtags);
  const mediaBlock = uploadedMediaRefs.length
    ? uploadedMediaRefs.map((item, index) => `${index + 1}. ${item.kind} / ${item.name} / ${item.uploadedRelativePath || item.uploadedPath || item.sourcePath || '未上传'}`).join('\n')
    : '- 无素材';

  return [
    '你现在执行的是 OpenClaw 平台发布任务。',
    '不要重新生成图片或视频，只使用已经准备好的标题、正文和素材。',
    `目标平台: ${meta.label}`,
    `发布入口: ${meta.appName}`,
    `传输模式: ${config.transport === 'reverse' ? '反向任务包' : '直连手机'}`,
    `内容类型: ${uploadedMediaRefs.some((item) => item.kind === 'video') ? '视频' : uploadedMediaRefs.some((item) => item.kind === 'image') ? '图文' : '纯文本'}`,
    config.title.trim() ? `标题: ${config.title.trim()}` : '标题: 无',
    config.body.trim() ? `正文: ${config.body.trim()}` : '正文: 无',
    hashtags.length ? `话题: ${hashtags.map((tag) => `#${tag}`).join(' ')}` : '话题: 无',
    config.notes.trim() ? `补充要求: ${config.notes.trim()}` : '',
    '已准备素材:',
    mediaBlock,
    '',
    '执行要求:',
    meta.hint,
    '- 先进入应用的发帖/创作入口，再检查当前页面标题。',
    '- 媒体有顺序时必须按顺序添加，封面需要时先确认封面。',
    '- 发布前检查预览、可见性、@、定位、草稿状态和平台提示。',
    '- 只在确认内容正确后才提交发布。',
    '- 完成后返回当前页面、是否提交成功、草稿状态和失败原因。',
  ].filter(Boolean).join('\n');
}

function buildReversePacket(config, mediaRefs = []) {
  const meta = PLATFORM_META[config.platform] || PLATFORM_META.custom;
  return {
    schema: 'openclaw.publish.packet.v1',
    createdAt: new Date().toISOString(),
    platformId: config.platform,
    platformLabel: meta.label,
    contentType: config.transport === 'reverse' && mediaRefs.some((item) => item.kind === 'video') ? 'video' : mediaRefs.some((item) => item.kind === 'image') ? 'image' : 'text',
    title: config.title.trim(),
    body: config.body.trim(),
    hashtags: splitHashtags(config.hashtags),
    notes: config.notes.trim(),
    transport: config.transport,
    relayUrl: config.relayUrl.trim(),
    channelId: config.channelId.trim(),
    album: config.album || DEFAULT_ALBUM,
    media: mediaRefs.map((item) => ({
      kind: item.kind,
      name: item.name,
      mime: item.mime,
      size: item.size,
      sourcePath: item.sourcePath,
      uploadedPath: item.uploadedPath,
      uploadedRelativePath: item.uploadedRelativePath,
      album: item.album,
    })),
  };
}

function taskBody(config, prompt) {
  return {
    prompt,
    use_template: false,
    force_agent: true,
    learn_template: false,
    read_only: false,
    tool_policy: 'safe_action',
    template_params: {},
    timeout_sec: config.timeoutSec,
    max_rounds: 60,
  };
}

async function submitTask(config, prompt) {
  const payload = await signedJsonRequest(config, 'POST', '/api/lumi/agent/tasks', taskBody(config, prompt), 60_000);
  const data = payload?.data || payload;
  const taskId = data?.taskId || data?.id;
  if (!taskId) throw new Error('APKClaw did not return a task id.');
  return { payload, taskId };
}

async function getTask(config, taskId) {
  return signedJsonRequest(config, 'GET', `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}`, undefined, 60_000);
}

async function waitForTask(config, taskId) {
  const startedAt = Date.now();
  const maxWaitMs = Math.max(30, config.maxWaitSec) * 1000;
  let lastStatus = null;
  while (Date.now() - startedAt < maxWaitMs) {
    await new Promise((resolve) => setTimeout(resolve, Math.max(500, config.pollMs)));
    const payload = await getTask(config, taskId);
    const data = payload?.data || payload;
    lastStatus = data;
    if (['success', 'error', 'cancelled'].includes(data?.status)) {
      return { payload, task: data };
    }
  }
  return {
    payload: null,
    task: { ...(lastStatus || {}), status: 'error', error: `Timed out waiting for APKClaw task after ${config.maxWaitSec}s` },
  };
}

async function writePacketIfRequested(packet, targetPath) {
  if (!targetPath) return;
  await fs.mkdir(path.dirname(targetPath), { recursive: true });
  await fs.writeFile(targetPath, `${JSON.stringify(packet, null, 2)}\n`, 'utf8');
}

function relayAuthHeaders(relayToken, headers = {}) {
  if (!relayToken) return headers;
  return {
    ...headers,
    Authorization: `Bearer ${relayToken}`,
    'X-OpenClaw-Relay-Token': relayToken,
  };
}

async function readJsonResponse(response) {
  const text = await response.text();
  if (!text.trim()) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

async function postPacketToRelay(relayUrl, packet, relayToken) {
  if (!relayUrl) return { response: null, body: null };
  const headers = { 'Content-Type': 'application/json' };
  const response = await fetch(relayUrl, {
    method: 'POST',
    headers: relayAuthHeaders(relayToken, headers),
    body: JSON.stringify(packet),
  });
  const body = await readJsonResponse(response);
  if (!response.ok) {
    const detail = body?.error || body?.raw || '';
    throw new Error(`Relay rejected packet: ${response.status}${detail ? ` ${String(detail).slice(0, 300)}` : ''}`);
  }
  return { response, body };
}

function relayRecordData(payload) {
  return payload?.data || payload || null;
}

function relayStatusUrl(relayUrl, relayPayload) {
  const data = relayRecordData(relayPayload);
  const packetId = data?.packetId || data?.id;
  if (data?.statusUrl) {
    return new URL(data.statusUrl, relayUrl).toString();
  }
  if (!packetId) {
    throw new Error('Relay did not return a packetId; cannot wait for status.');
  }
  const url = new URL('/api/lumi/relay/status', relayUrl);
  url.searchParams.set('id', packetId);
  return url.toString();
}

async function getRelayStatus(statusUrl, relayToken) {
  const response = await fetch(statusUrl, {
    headers: relayAuthHeaders(relayToken, { Accept: 'application/json' }),
  });
  const body = await readJsonResponse(response);
  if (!response.ok) {
    const detail = body?.error || body?.raw || '';
    throw new Error(`Relay status failed: ${response.status}${detail ? ` ${String(detail).slice(0, 300)}` : ''}`);
  }
  return body;
}

async function waitForRelayCompletion(relayUrl, relayPayload, relayToken, waitSec, pollMs) {
  const statusUrl = relayStatusUrl(relayUrl, relayPayload);
  const deadline = Date.now() + waitSec * 1000;
  let lastRecord = null;

  while (Date.now() <= deadline) {
    const payload = await getRelayStatus(statusUrl, relayToken);
    const record = relayRecordData(payload);
    lastRecord = record;
    if (record?.status === 'done') {
      return { statusUrl, payload, record };
    }
    if (record?.status === 'failed') {
      throw new Error(`Relay packet failed: ${record.lastError || 'unknown error'}`);
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }

  throw new Error(`Timed out waiting for relay packet after ${waitSec}s; last status=${lastRecord?.status || 'unknown'}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(`${usage()}\n`);
    process.exit(0);
  }

  const resolved = await resolveConfig(args);
  const mediaEntries = await readMediaEntries(resolved);

  if (resolved.transport === 'reverse') {
    const packet = buildReversePacket(resolved, mediaEntries.map((item) => ({
      kind: item.kind,
      name: item.name,
      mime: item.mime,
      size: item.size,
      sourcePath: item.filePath,
    })));
    await writePacketIfRequested(packet, resolved.packetOut);
    let relayResult = null;
    let relayCompletion = null;
    if (resolved.relayUrl) {
      relayResult = await postPacketToRelay(resolved.relayUrl, packet, resolved.relayToken);
      if (resolved.waitRelay) {
        relayCompletion = await waitForRelayCompletion(
          resolved.relayUrl,
          relayResult.body,
          resolved.relayToken,
          resolved.relayWaitSec,
          resolved.relayPollMs,
        );
      }
    }
    if (resolved.json) {
      process.stdout.write(`${JSON.stringify({
        ...packet,
        relayedTo: resolved.relayUrl || null,
        relay: relayResult?.body || null,
        relayStatus: relayCompletion?.record || null,
        relayStatusUrl: relayCompletion?.statusUrl || null,
      }, null, 2)}\n`);
    } else {
      process.stdout.write(`Reverse packet created for ${packet.platformLabel}\n`);
      if (resolved.relayUrl) {
        process.stdout.write(`Relayed to ${resolved.relayUrl}\n`);
        const relayData = relayRecordData(relayResult?.body);
        if (relayData?.packetId) {
          process.stdout.write(`Relay packet id: ${relayData.packetId}\n`);
        }
        if (relayCompletion?.record) {
          process.stdout.write(`Relay status: ${relayCompletion.record.status}\n`);
        }
      }
      if (resolved.packetOut) {
        process.stdout.write(`Wrote ${resolved.packetOut}\n`);
      } else {
        process.stdout.write(`${JSON.stringify(packet, null, 2)}\n`);
      }
    }
    return;
  }

  if (!resolved.phoneUrl || !resolved.phoneToken) {
    throw new Error('Missing phone URL or token. Configure the launcher Phone Control page first, or use --phone-url / --phone-token.');
  }

  const uploadedMediaRefs = [];
  for (const entry of mediaEntries) {
    const fileConfig = {
      phoneUrl: resolved.phoneUrl,
      phoneToken: resolved.phoneToken,
      album: resolved.album || DEFAULT_ALBUM,
      lumiLauncherId: '',
      lumiLauncherSecret: '',
    };
    const upload = entry.kind === 'video'
      ? await uploadVideoBuffer(fileConfig, entry.bytes, entry.name, entry.mime)
      : await uploadImageBuffer(fileConfig, entry.bytes, entry.name, entry.mime);
    uploadedMediaRefs.push({
      kind: entry.kind,
      name: entry.name,
      mime: entry.mime,
      size: entry.size,
      sourcePath: entry.filePath,
      uploadedPath: upload?.path || upload?.uri || '',
      uploadedRelativePath: upload?.relativePath || upload?.path || '',
      album: upload?.album || resolved.album || DEFAULT_ALBUM,
    });
  }

  const prompt = buildPrompt(resolved, uploadedMediaRefs);
  const { taskId } = await submitTask(resolved, prompt);
  const result = await waitForTask(resolved, taskId);
  const task = result.task || {};
  const answer = task?.result?.answer || task?.answer || '';
  const error = task?.result?.error || task?.error || '';
  const output = {
    taskId,
    status: task.status || 'unknown',
    platform: resolved.platform,
    transport: resolved.transport,
    answer,
    error,
    uploadedMediaRefs,
  };
  if (resolved.json) {
    process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
  } else {
    process.stdout.write(`status=${output.status}\n`);
    process.stdout.write(`task=${taskId}\n`);
    if (answer) process.stdout.write(`answer=${answer}\n`);
    if (error) process.stdout.write(`error=${error}\n`);
  }
}

main().catch((error) => {
  console.error(error?.message || error);
  process.exit(1);
});
