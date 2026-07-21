#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ensurePhoneConfig, readLauncherPhoneConfigByDevice, signedJsonRequest } from './openclaw-phone-secure.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_POLL_MS = 1800;
const DEFAULT_TIMEOUT_SEC = 600;
const DEFAULT_MAX_ROUNDS = 60;
const HISTORY_PATH = path.join(PROJECT_ROOT, 'data', '.openclaw', 'logs', 'phone-agent-history.jsonl');
const QUEUE_PATH = path.join(PROJECT_ROOT, 'data', '.openclaw', 'launcher', 'phone-agent-queue.json');
const QUEUE_DRAIN_LOCK_PATH = `${QUEUE_PATH}.drain.lock`;
const QUEUE_RW_LOCK_PATH = `${QUEUE_PATH}.rw.lock`;
const DRAIN_LOCK_STALE_MS = 30 * 60 * 1000;
const QUEUE_RW_LOCK_STALE_MS = 5 * 60 * 1000;

function usage() {
  return `
OpenClaw phone Agent CLI

Usage:
  npm run phone:agent -- run --prompt "读取当前手机屏幕并返回摘要"
  npm run phone:agent -- status --task-id <id>
  npm run phone:agent -- cancel --task-id <id>
  npm run phone:agent -- enqueue --prompt "稍后执行这个手机任务"
  npm run phone:agent -- drain
  npm run phone:agent -- history --limit 20

Commands:
  run                         Submit one bounded async APKClaw Agent task and wait for the result
  submit                      Submit an async APKClaw Agent task and print the task id
  enqueue                     Persist one task locally without starting it
  queue                       Print persisted queued/running tasks
  drain                       Continue pending/running queued tasks; safe to rerun after disconnects
  status                      Read one async task status
  cancel                      Cancel one async task
  history                     Print recent launcher-side phone Agent task history

Run options:
  --prompt <text>              Required for run/submit
  --mode <observe|safe|full>   Default: safe
  --timeout-sec <n>            APKClaw-side timeout. Default: 600, phone clamps to its supported range
  --max-rounds <n>              APKClaw Agent round budget. Default: 60
  --max-wait-sec <n>           CLI wait window for run. Default: 615
  --poll-ms <n>                Poll interval. Default: 1800
  --priority <n>               Queue priority. Higher first. Default: 0
  --queue-id <id>              Queue item id for queue/drain targeting
  --limit <n>                  History rows to print. Default: 20
  --json                       Print machine-readable JSON

Debug-only options:
  --device-id <id>             Optional. Select one configured APKClaw device from launcher
  --phone-url <url>            Optional. Defaults to launcher Phone Control config
  --phone-token <token>        Optional. Defaults to launcher Phone Control config
`.trim();
}

function parseArgs(argv) {
  const args = {
    command: '',
    prompt: '',
    taskId: '',
    mode: 'safe',
    timeoutSec: DEFAULT_TIMEOUT_SEC,
    maxRounds: DEFAULT_MAX_ROUNDS,
    maxWaitSec: DEFAULT_TIMEOUT_SEC + 15,
    pollMs: DEFAULT_POLL_MS,
    priority: 0,
    queueId: '',
    limit: 20,
    deviceId: '',
    phoneUrl: '',
    phoneToken: '',
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
      case '--prompt':
        args.prompt = next();
        break;
      case '--task-id':
        args.taskId = next();
        break;
      case '--mode':
        args.mode = next().toLowerCase();
        break;
      case '--timeout-sec':
        args.timeoutSec = nextInt();
        break;
      case '--max-rounds':
        args.maxRounds = nextInt();
        break;
      case '--max-wait-sec':
        args.maxWaitSec = nextInt();
        break;
      case '--poll-ms':
        args.pollMs = nextInt();
        break;
      case '--priority':
        args.priority = nextInt();
        break;
      case '--queue-id':
        args.queueId = next();
        break;
      case '--limit':
        args.limit = nextInt();
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
  args.timeoutSec = Math.max(30, args.timeoutSec);
  args.maxRounds = Math.max(1, args.maxRounds);
  args.maxWaitSec = Math.max(30, args.maxWaitSec);
  args.pollMs = Math.max(500, args.pollMs);
  return args;
}

async function resolveConfig(args) {
  const runtime = await readRuntimeContext();
  const launcherPhone = await readLauncherPhoneConfigByDevice(args.deviceId);
  return {
    ...args,
    phoneUrl: firstNonEmpty(args.phoneUrl, process.env.OPENCLAW_PHONE_BASE_URL, process.env.APKCLAW_BASE_URL, launcherPhone.phoneUrl, runtime?.phone?.baseUrl),
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

function toolPolicy(mode) {
  if (mode === 'observe' || mode === 'observe_only') return 'observe_only';
  if (mode === 'full' || mode === 'full_access') return 'full_access';
  if (mode === 'safe' || mode === 'safe_action') return 'safe_action';
  throw new Error(`Invalid --mode: ${mode}. Use observe, safe, or full.`);
}

function taskBody(config) {
  const policy = toolPolicy(config.mode);
  const prompt = withTaskContracts(config.prompt);
  return {
    prompt: [
      prompt,
      '',
      'OpenClaw wrapper contract:',
      '- Run one bounded task only.',
      `- APKClaw has a hard ${config.maxRounds}-round budget; return partial results instead of looping indefinitely.`,
      '- For shopping/search/list pages, use collect_list_items with a suitable target when available.',
      '- Return structured visible findings, failures, and whether follow-up is needed.',
    ].join('\n'),
    use_template: false,
    force_agent: true,
    learn_template: false,
    read_only: policy === 'observe_only',
    tool_policy: policy,
    template_params: {},
    timeout_sec: config.timeoutSec,
    max_rounds: config.maxRounds,
  };
}

function withTaskContracts(prompt) {
  const base = String(prompt || '').trim();
  if (!shouldAttachAdWatchContract(base)) return base;
  return [
    base,
    '',
    'OpenClaw ad-watch contract:',
    '- Treat ad waiting as a timed state machine, not a blind sleep.',
    '- Record the start time, observe the screen at least every 1-2 seconds, and keep elapsed seconds in your reasoning.',
    '- Before the minimum watch time is reached, do not click skip, close, reward, download, install, open-app, login, payment, or permission buttons.',
    '- After the minimum watch time is reached, only click clearly safe completion controls such as close, x, skip, return, or claim reward.',
    '- If chain prompts appear, follow the task policy for continue watching. When the policy is not explicit, reject extra chain ads.',
    '- Never click download, install, open third-party app, payment, login, authorization, or app-store buttons.',
    '- If the screen leaves the target app, becomes ambiguous, asks for sensitive permission, or shows an unknown overlay, stop and return the visible reason plus screenshot evidence.',
    '- End with one of: completed, no_reward_button, chain_rejected, unsafe_prompt, app_escaped, stuck, or unknown_overlay.',
  ].join('\n');
}

function shouldAttachAdWatchContract(prompt) {
  return /OPENCLAW_AD_WATCH|ad-watch|watch ad|看.{0,8}广告|广告.{0,12}(等待|观看|播放|倒计时|领取奖励|跳过|关闭)|跳过广告|关闭广告|领取奖励|再看一个|继续观看/i.test(prompt);
}

async function submitTask(config) {
  const payload = await signedJsonRequest(config, 'POST', '/api/lumi/agent/tasks', taskBody(config), 60_000);
  const data = payload?.data || payload;
  const taskId = data?.taskId || data?.id;
  if (!taskId) throw new Error('APKClaw did not return a task id.');
  return { payload, taskId };
}

async function getTask(config, taskId) {
  return signedJsonRequest(config, 'GET', `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}`, undefined, 60_000);
}

async function cancelTask(config, taskId) {
  return signedJsonRequest(config, 'POST', `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}/cancel`, {}, 60_000);
}

async function waitForTask(config, taskId) {
  const startedAt = Date.now();
  const maxWaitMs = Math.max(30, config.maxWaitSec) * 1000;
  let lastStatus = null;
  let polls = 0;
  let lastProgressLineAt = 0;
  let consecutivePollErrors = 0;
  const pollErrors = [];
  while (Date.now() - startedAt < maxWaitMs) {
    await new Promise((resolve) => setTimeout(resolve, Math.max(500, config.pollMs)));
    let payload;
    let data;
    try {
      payload = await getTask(config, taskId);
      data = payload?.data || payload;
      consecutivePollErrors = 0;
    } catch (error) {
      consecutivePollErrors += 1;
      const failureClass = classifyFailure({ error: error?.message || String(error) });
      pollErrors.push({
        at: new Date().toISOString(),
        failureClass,
        error: error?.message || String(error),
      });
      if (shouldKeepPollingAfterError(failureClass, consecutivePollErrors)) {
        if (!config.json && consecutivePollErrors === 1) {
          console.error(`poll warning task=${String(taskId).slice(0, 8)} class=${failureClass || 'unknown'} error=${error?.message || error}`);
        }
        continue;
      }
      throw error;
    }
    lastStatus = data;
    polls += 1;
    const now = Date.now();
    if (!config.json && now - lastProgressLineAt > 10_000 && !['success', 'error', 'cancelled'].includes(data?.status)) {
      lastProgressLineAt = now;
      console.error(`still running task=${String(taskId).slice(0, 8)} status=${data?.status || 'pending'} poll=${polls} elapsed=${Math.round((now - startedAt) / 1000)}s${progressSuffix(data)}`);
    }
    if (['success', 'error', 'cancelled'].includes(data?.status)) {
      return { payload, task: data };
    }
  }
  return {
    payload: null,
    task: {
      ...(lastStatus || {}),
      status: 'error',
      error: `Timed out waiting for APKClaw task after ${config.maxWaitSec}s`,
      pollErrors: pollErrors.slice(-8),
    },
  };
}

function shouldKeepPollingAfterError(failureClass, consecutivePollErrors) {
  if (consecutivePollErrors > 5) return false;
  return ['offline', 'timeout', 'apkclaw_crash', 'task_busy'].includes(String(failureClass || ''));
}

function progressSuffix(data) {
  const progress = data?.progress || data?.result?.progress || {};
  const round = data?.round ?? data?.currentRound ?? progress?.round ?? progress?.currentRound;
  const maxRounds = data?.maxRounds ?? progress?.maxRounds ?? progress?.totalRounds;
  const message = data?.message || progress?.message || data?.lastEvent?.message || '';
  const parts = [];
  if (round != null) parts.push(maxRounds != null ? `round=${round}/${maxRounds}` : `round=${round}`);
  if (message) parts.push(`last=${String(message).replace(/\s+/g, ' ').slice(0, 120)}`);
  return parts.length ? ` ${parts.join(' ')}` : '';
}

function summarizeTask(task) {
  const result = task?.result || task?.data || {};
  const answer = result?.answer || task?.answer || '';
  const error = result?.error || task?.error || '';
  const events = Array.isArray(task?.events) ? task.events : Array.isArray(result?.events) ? result.events : [];
  const lastEvent = events.at(-1);
  return [
    `status=${task?.status || 'unknown'}`,
    task?.taskId || task?.id ? `task=${String(task.taskId || task.id).slice(0, 8)}` : '',
    answer ? `answer=${answer}` : '',
    error ? `error=${error}` : '',
    lastEvent?.message ? `last=${lastEvent.message}` : '',
  ].filter(Boolean).join('\n');
}

function classifyFailure(value) {
  const result = value?.result || value?.data || {};
  const parts = [
    value?.status,
    value?.error,
    value?.message,
    result?.error,
    result?.message,
    ...(Array.isArray(value?.events) ? value.events : []),
    ...(Array.isArray(result?.events) ? result.events : []),
  ];
  const text = parts
    .map((item) => (typeof item === 'string' ? item : `${item?.type || ''} ${item?.message || ''} ${item?.error || ''}`))
    .join('\n')
    .toLowerCase();
  if (!text.trim()) return '';
  if (/(401|403|unauthori[sz]ed|forbidden|token|signature|auth)/i.test(text)) return 'unauthorized';
  if (/(accessibility|无障碍|screen.?tree|node tree|permission)/i.test(text)) return 'accessibility_off';
  if (/(timeout|timed out|aborterror|deadline|超时)/i.test(text)) return 'timeout';
  if (/(already running|task is already running|busy|已有任务)/i.test(text)) return 'task_busy';
  if (/(econnrefused|enotfound|network|fetch failed|offline|unreachable|无法连接|离线)/i.test(text)) return 'offline';
  if (/(crash|crashed|崩溃|worker exited|service died|connection reset|socket hang up)/i.test(text)) return 'apkclaw_crash';
  return 'unknown';
}

function promptPreview(prompt) {
  const clean = String(prompt || '').replace(/\s+/g, ' ').trim();
  return clean.length > 160 ? `${clean.slice(0, 160)}...` : clean;
}

function publicDevice(config) {
  return {
    deviceId: config.deviceId || undefined,
    configured: Boolean(config.phoneUrl && config.phoneToken),
  };
}

async function appendHistory(record) {
  try {
    await fs.mkdir(path.dirname(HISTORY_PATH), { recursive: true });
    await fs.appendFile(HISTORY_PATH, `${JSON.stringify({ schema: 'openclaw.phone-agent.history.v1', ...record })}\n`, 'utf8');
  } catch {
    // History must never break a phone task.
  }
}

async function readHistory(limit) {
  try {
    const raw = await fs.readFile(HISTORY_PATH, 'utf8');
    return raw
      .split(/\r?\n/)
      .filter(Boolean)
      .slice(-Math.max(1, Math.min(200, limit || 20)))
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return { raw: line };
        }
      });
  } catch (error) {
    if (error?.code === 'ENOENT') return [];
    throw error;
  }
}

async function readQueue() {
  try {
    const parsed = JSON.parse(await fs.readFile(QUEUE_PATH, 'utf8'));
    return {
      schema: 'openclaw.phone-agent.queue.v1',
      updatedAt: parsed?.updatedAt || null,
      items: Array.isArray(parsed?.items) ? parsed.items : [],
    };
  } catch (error) {
    if (error?.code === 'ENOENT') return { schema: 'openclaw.phone-agent.queue.v1', updatedAt: null, items: [] };
    throw error;
  }
}

async function writeQueue(queue) {
  const release = await acquireQueueRwLock();
  try {
    const current = await readQueue();
    await writeQueueUnlocked(mergeQueue(current, queue));
  } finally {
    await release();
  }
}

async function writeQueueUnlocked(queue) {
  await fs.mkdir(path.dirname(QUEUE_PATH), { recursive: true });
  const payload = { schema: 'openclaw.phone-agent.queue.v1', updatedAt: new Date().toISOString(), items: queue.items || [] };
  const tmpPath = `${QUEUE_PATH}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmpPath, JSON.stringify(payload, null, 2), 'utf8');
  await fs.rename(tmpPath, QUEUE_PATH);
}

function mergeQueue(current, incoming) {
  const merged = new Map();
  for (const item of Array.isArray(current?.items) ? current.items : []) {
    if (item?.id) merged.set(String(item.id), item);
  }
  for (const item of Array.isArray(incoming?.items) ? incoming.items : []) {
    if (item?.id) merged.set(String(item.id), item);
  }
  return {
    schema: 'openclaw.phone-agent.queue.v1',
    updatedAt: new Date().toISOString(),
    items: Array.from(merged.values()),
  };
}

function isProcessAlive(pid) {
  if (!Number.isFinite(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === 'EPERM';
  }
}

async function readDrainLock() {
  try {
    const raw = await fs.readFile(QUEUE_DRAIN_LOCK_PATH, 'utf8');
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

async function removeStaleDrainLock() {
  let stat;
  try {
    stat = await fs.stat(QUEUE_DRAIN_LOCK_PATH);
  } catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error;
  }
  const info = await readDrainLock();
  const pid = Number(info.pid);
  const ageMs = Date.now() - stat.mtimeMs;
  if (isProcessAlive(pid) && ageMs < DRAIN_LOCK_STALE_MS) return false;
  try {
    await fs.unlink(QUEUE_DRAIN_LOCK_PATH);
    return true;
  } catch (error) {
    if (error?.code === 'ENOENT') return true;
    throw error;
  }
}

async function acquireDrainLock() {
  await fs.mkdir(path.dirname(QUEUE_DRAIN_LOCK_PATH), { recursive: true });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const handle = await fs.open(QUEUE_DRAIN_LOCK_PATH, 'wx');
      try {
        await handle.writeFile(JSON.stringify({
          schema: 'openclaw.phone-agent.drain-lock.v1',
          pid: process.pid,
          createdAt: new Date().toISOString(),
        }, null, 2));
      } finally {
        await handle.close();
      }
      return async () => {
        try {
          const info = await readDrainLock();
          if (!info.pid || Number(info.pid) === process.pid) await fs.unlink(QUEUE_DRAIN_LOCK_PATH);
        } catch (error) {
          if (error?.code !== 'ENOENT') throw error;
        }
      };
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      const removed = await removeStaleDrainLock();
      if (!removed) return null;
    }
  }
  return null;
}

async function removeStaleQueueRwLock() {
  let stat;
  try {
    stat = await fs.stat(QUEUE_RW_LOCK_PATH);
  } catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error;
  }
  const ageMs = Date.now() - stat.mtimeMs;
  if (ageMs < QUEUE_RW_LOCK_STALE_MS) return false;
  try {
    await fs.unlink(QUEUE_RW_LOCK_PATH);
    return true;
  } catch (error) {
    if (error?.code === 'ENOENT') return true;
    throw error;
  }
}

async function acquireQueueRwLock() {
  await fs.mkdir(path.dirname(QUEUE_RW_LOCK_PATH), { recursive: true });
  const deadline = Date.now() + 10_000;
  for (;;) {
    try {
      const handle = await fs.open(QUEUE_RW_LOCK_PATH, 'wx');
      try {
        await handle.writeFile(JSON.stringify({
          schema: 'openclaw.phone-agent.queue-rw-lock.v1',
          pid: process.pid,
          createdAt: new Date().toISOString(),
        }, null, 2));
      } finally {
        await handle.close();
      }
      return async () => {
        try {
          await fs.unlink(QUEUE_RW_LOCK_PATH);
        } catch (error) {
          if (error?.code !== 'ENOENT') throw error;
        }
      };
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      const removed = await removeStaleQueueRwLock();
      if (!removed && Date.now() >= deadline) throw new Error('phone queue is busy');
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
}

function createQueueItem(config) {
  const createdAt = new Date().toISOString();
  return {
    id: `phone-task-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    status: 'pending',
    priority: Number(config.priority) || 0,
    createdAt,
    updatedAt: createdAt,
    attempts: 0,
    taskId: '',
    prompt: config.prompt,
    mode: config.mode,
    timeoutSec: config.timeoutSec,
    maxRounds: config.maxRounds,
    maxWaitSec: config.maxWaitSec,
    pollMs: config.pollMs,
    deviceId: config.deviceId,
    phoneUrl: config.phoneUrl,
    phoneToken: config.phoneToken,
    promptPreview: promptPreview(config.prompt),
  };
}

async function queueItemConfig(baseConfig, item) {
  const launcherPhone = item.deviceId ? await readLauncherPhoneConfigByDevice(item.deviceId) : {};
  return {
    ...baseConfig,
    prompt: item.prompt || baseConfig.prompt,
    mode: item.mode || baseConfig.mode,
    timeoutSec: Number(item.timeoutSec) || baseConfig.timeoutSec,
    maxRounds: Number(item.maxRounds) || baseConfig.maxRounds,
    maxWaitSec: Number(item.maxWaitSec) || baseConfig.maxWaitSec,
    pollMs: Number(item.pollMs) || baseConfig.pollMs,
    deviceId: item.deviceId || launcherPhone.id || baseConfig.deviceId,
    phoneUrl: item.phoneUrl || launcherPhone.phoneUrl || baseConfig.phoneUrl,
    phoneToken: item.phoneToken || launcherPhone.phoneToken || baseConfig.phoneToken,
  };
}

function queueSummary(items) {
  if (!items.length) return `No queued phone Agent tasks.\n${QUEUE_PATH}`;
  return items
    .map((item) => `${item.updatedAt || item.createdAt || '-'} ${item.status || 'pending'} priority=${item.priority || 0} ${item.id} ${item.taskId ? `task=${String(item.taskId).slice(0, 8)}` : ''} ${item.promptPreview || ''}`.trim())
    .join('\n');
}

function maxAttempts(item) {
  const value = Number(item.maxAttempts);
  return Number.isFinite(value) && value > 0 ? value : 3;
}

function canDrainItem(item) {
  const status = item.status || 'pending';
  if (['pending', 'running', 'submitted'].includes(status)) return true;
  if (status === 'error') return Number(item.attempts || 0) < maxAttempts(item);
  return false;
}

async function enqueueTask(config) {
  if (!config.prompt.trim()) throw new Error('Missing --prompt');
  const queue = await readQueue();
  const item = createQueueItem(config);
  queue.items.push(item);
  await writeQueue(queue);
  return item;
}

async function drainQueue(config) {
  const releaseDrainLock = await acquireDrainLock();
  if (!releaseDrainLock) {
    const lock = await readDrainLock();
    return { queuePath: QUEUE_PATH, lockPath: QUEUE_DRAIN_LOCK_PATH, lockBusy: true, lock, count: 0, results: [], items: (await readQueue()).items };
  }
  try {
  const queue = await readQueue();
  const candidates = queue.items
    .filter((item) => canDrainItem(item))
    .filter((item) => !config.queueId || item.id === config.queueId)
    .sort((a, b) => (Number(b.priority) || 0) - (Number(a.priority) || 0) || String(a.createdAt || '').localeCompare(String(b.createdAt || '')));
  const results = [];
  for (const item of candidates) {
    const itemConfig = await queueItemConfig(config, item);
    ensurePhoneConfig(itemConfig);
    item.status = 'running';
    item.updatedAt = new Date().toISOString();
    item.attempts = Number(item.attempts || 0) + 1;
    await writeQueue(queue);
    const submittedAt = item.submittedAt || new Date().toISOString();
    item.submittedAt = submittedAt;
    try {
      if (!item.taskId) {
        const submitted = await submitTask(itemConfig);
        item.taskId = submitted.taskId;
        item.status = 'submitted';
        item.updatedAt = new Date().toISOString();
        await writeQueue(queue);
      }
      const finalTask = await waitForTask(itemConfig, item.taskId);
      const ok = finalTask.task?.status === 'success';
      item.status = ok ? 'completed' : item.attempts >= maxAttempts(item) ? 'failed' : finalTask.task?.status || 'error';
      item.finishedAt = new Date().toISOString();
      item.updatedAt = item.finishedAt;
      item.error = ok ? '' : (finalTask.task?.result?.error || finalTask.task?.error || '');
      item.failureClass = ok ? '' : classifyFailure(finalTask.task);
      await appendHistory({
        command: 'drain',
        status: item.status,
        submittedAt,
        finishedAt: item.finishedAt,
        taskId: item.taskId,
        queueId: item.id,
        mode: toolPolicy(itemConfig.mode),
        timeoutSec: itemConfig.timeoutSec,
        maxRounds: itemConfig.maxRounds,
        maxWaitSec: itemConfig.maxWaitSec,
        promptPreview: item.promptPreview,
        failureClass: item.failureClass,
        error: item.error,
        summary: summarizeTask(finalTask.task),
        device: publicDevice(itemConfig),
      });
      results.push({ ok, item, final: finalTask.task });
    } catch (error) {
      item.status = item.attempts >= maxAttempts(item) ? 'failed' : 'error';
      item.error = error?.message || 'queue_item_failed';
      item.updatedAt = new Date().toISOString();
      await appendHistory({
        command: 'drain',
        status: item.status,
        submittedAt,
        finishedAt: item.updatedAt,
        queueId: item.id,
        taskId: item.taskId,
        promptPreview: item.promptPreview,
        failureClass: classifyFailure({ error: item.error }),
        error: item.error,
        device: publicDevice(itemConfig),
      });
      results.push({ ok: false, item, error: item.error });
    }
    await writeQueue(queue);
  }
  return { queuePath: QUEUE_PATH, lockPath: QUEUE_DRAIN_LOCK_PATH, count: candidates.length, results, items: queue.items };
  } finally {
    await releaseDrainLock();
  }
}

function print(config, payload, human) {
  if (config.json) console.log(JSON.stringify(payload, null, 2));
  else console.log(human);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }
  const config = await resolveConfig(args);

  if (config.command === 'history') {
    const rows = await readHistory(config.limit);
    print(
      config,
      { ok: true, historyPath: HISTORY_PATH, count: rows.length, rows },
      rows.length
        ? rows.map((row) => `${row.finishedAt || row.submittedAt || row.createdAt || '-'} ${row.status || row.command || 'unknown'} ${row.taskId ? String(row.taskId).slice(0, 8) : ''} ${row.failureClass || ''} ${row.error || row.summary || ''}`.trim()).join('\n')
        : `No phone Agent history yet.\n${HISTORY_PATH}`,
    );
    return;
  }

  if (config.command === 'queue') {
    const queue = await readQueue();
    const items = config.queueId ? queue.items.filter((item) => item.id === config.queueId) : queue.items;
    print(
      config,
      { ok: true, queuePath: QUEUE_PATH, count: items.length, items },
      queueSummary(items),
    );
    return;
  }

  if (config.command === 'enqueue') {
    const item = await enqueueTask(config);
    print(config, { ok: true, queuePath: QUEUE_PATH, item }, `queued ${item.id} priority=${item.priority || 0}`);
    return;
  }

  if (config.command === 'drain') {
    const result = await drainQueue(config);
    print(config, { ok: result.results.every((item) => item.ok), ...result }, queueSummary(result.items));
    return;
  }

  ensurePhoneConfig(config);

  if (config.command === 'submit' || config.command === 'run') {
    if (!config.prompt.trim()) throw new Error('Missing --prompt');
    const submittedAt = new Date().toISOString();
    const submitted = await submitTask(config);
    await appendHistory({
      command: config.command,
      status: 'submitted',
      submittedAt,
      taskId: submitted.taskId,
      mode: toolPolicy(config.mode),
      timeoutSec: config.timeoutSec,
      maxRounds: config.maxRounds,
      maxWaitSec: config.maxWaitSec,
      promptPreview: promptPreview(config.prompt),
      device: publicDevice(config),
    });
    if (config.command === 'submit') {
      print(config, { ok: true, taskId: submitted.taskId, submitted: submitted.payload }, `submitted task=${submitted.taskId}`);
      return;
    }
    const finalTask = await waitForTask(config, submitted.taskId);
    const ok = finalTask.task?.status === 'success';
    await appendHistory({
      command: config.command,
      status: finalTask.task?.status || 'unknown',
      submittedAt,
      finishedAt: new Date().toISOString(),
      taskId: submitted.taskId,
      mode: toolPolicy(config.mode),
      timeoutSec: config.timeoutSec,
      maxRounds: config.maxRounds,
      maxWaitSec: config.maxWaitSec,
      promptPreview: promptPreview(config.prompt),
      failureClass: ok ? '' : classifyFailure(finalTask.task),
      error: ok ? '' : (finalTask.task?.result?.error || finalTask.task?.error || ''),
      summary: summarizeTask(finalTask.task),
      device: publicDevice(config),
    });
    print(config, { ok, taskId: submitted.taskId, submitted: submitted.payload, final: finalTask.task }, summarizeTask(finalTask.task));
    return;
  }

  if (config.command === 'status') {
    if (!config.taskId.trim()) throw new Error('Missing --task-id');
    const payload = await getTask(config, config.taskId);
    print(config, payload, summarizeTask(payload?.data || payload));
    return;
  }

  if (config.command === 'cancel') {
    if (!config.taskId.trim()) throw new Error('Missing --task-id');
    const payload = await cancelTask(config, config.taskId);
    await appendHistory({
      command: config.command,
      status: 'cancelled',
      finishedAt: new Date().toISOString(),
      taskId: config.taskId,
      device: publicDevice(config),
    });
    print(config, payload, `cancelled task=${config.taskId.slice(0, 8)}`);
    return;
  }

  throw new Error(`Unknown command: ${config.command}`);
}

main().catch((error) => {
  console.error(`ERROR: ${error?.message || error}`);
  process.exitCode = 1;
});
