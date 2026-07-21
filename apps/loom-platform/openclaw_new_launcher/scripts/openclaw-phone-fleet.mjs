#!/usr/bin/env node

import {
  authHeaders,
  ensurePhoneConfig,
  fetchWithTimeout,
  normalizePhoneUrl,
  phoneBridgeErrorPayload,
  readLauncherPhoneConfigByDevice,
  readLauncherPhoneStore,
  signedJsonRequest,
} from './openclaw-phone-secure.mjs';

const DEFAULT_TIMEOUT_SEC = 600;
const DEFAULT_MAX_WAIT_SEC = DEFAULT_TIMEOUT_SEC + 15;
const DEFAULT_POLL_MS = 1800;

function usage() {
  return `
OpenClaw APKClaw fleet CLI

Usage:
  npm run phone:fleet -- list
  npm run phone:fleet -- status --target all
  npm run phone:fleet -- run --target redmi-k70,pixel-01 --prompt "inspect the current screen" --mode observe

Commands:
  list                        Print configured APKClaw devices without exposing tokens
  status                      Probe /api/device/status for one or more devices
  run                         Submit one bounded Agent task to one or more devices and wait for results

Options:
  --target <id|id,id|all>      Device target. Default: current selected device
  --prompt <text>              Required for run
  --mode <observe|safe|full>   Default: safe
  --timeout-sec <n>            APKClaw-side timeout. Default: 600
  --max-wait-sec <n>           CLI wait window for run. Default: 615
  --poll-ms <n>                Poll interval. Default: 1800
  --concurrency <n>            Device concurrency. Default: 1, max: 8
  --json                       Print machine-readable JSON
  -h, --help                   Show help
`.trim();
}

function parseArgs(argv) {
  const args = {
    command: '',
    target: '',
    prompt: '',
    mode: 'safe',
    timeoutSec: DEFAULT_TIMEOUT_SEC,
    maxWaitSec: DEFAULT_MAX_WAIT_SEC,
    pollMs: DEFAULT_POLL_MS,
    concurrency: 1,
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
      case '--target':
      case '--devices':
        args.target = next();
        break;
      case '--prompt':
        args.prompt = next();
        break;
      case '--mode':
        args.mode = next().toLowerCase();
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
      case '--concurrency':
        args.concurrency = nextInt();
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

  args.command = (args.command || 'list').toLowerCase();
  args.concurrency = Math.max(1, Math.min(8, args.concurrency || 1));
  return args;
}

function toolPolicy(mode) {
  if (mode === 'observe' || mode === 'observe_only') return 'observe_only';
  if (mode === 'full' || mode === 'full_access') return 'full_access';
  if (mode === 'safe' || mode === 'safe_action') return 'safe_action';
  throw new Error(`Invalid --mode: ${mode}. Use observe, safe, or full.`);
}

function publicDevice(device, selectedDeviceId = '') {
  return {
    id: device.id || '',
    name: device.name || device.id || 'Android Phone',
    selected: Boolean(device.id && device.id === selectedDeviceId),
    configured: Boolean(device.phoneUrl && device.phoneToken),
    tokenAvailable: Boolean(device.phoneToken),
    source: device.source || '',
  };
}

async function loadDevices() {
  const store = await readLauncherPhoneStore();
  if (store.devices.length) {
    return {
      selectedDeviceId: store.selectedDeviceId || store.devices[0]?.id || '',
      devices: store.devices,
      source: store.source,
    };
  }
  const single = await readLauncherPhoneConfigByDevice();
  return {
    selectedDeviceId: single.id || '',
    devices: single.phoneUrl || single.phoneToken || single.id ? [single] : [],
    source: single.source || '',
  };
}

async function resolveTargets(args) {
  const store = await loadDevices();
  if (!store.devices.length) throw new Error('No APKClaw devices are configured in launcher.');
  const target = String(args.target || '').trim();
  const requestedIds =
    target && target.toLowerCase() !== 'current'
      ? target.toLowerCase() === 'all'
        ? store.devices.map((device) => device.id).filter(Boolean)
        : target.split(',').map((item) => item.trim()).filter(Boolean)
      : [store.selectedDeviceId || store.devices[0]?.id].filter(Boolean);

  if (!requestedIds.length) throw new Error('No target device selected.');

  const targets = [];
  const missing = [];
  for (const id of requestedIds) {
    const device = store.devices.find((item) => item.id === id);
    if (!device) {
      missing.push(id);
      continue;
    }
    targets.push({ ...device, selected: device.id === store.selectedDeviceId });
  }
  if (missing.length) throw new Error(`Unknown device id(s): ${missing.join(', ')}`);
  return { ...store, targets };
}

function taskBody(args) {
  const policy = toolPolicy(args.mode);
  return {
    prompt: [
      args.prompt,
      '',
      'OpenClaw fleet wrapper contract:',
      '- Run one bounded task on this target device only.',
      '- APKClaw has a hard 60-round budget; return partial results instead of looping indefinitely.',
      '- Include the visible result, failures, and whether follow-up is needed.',
    ].join('\n'),
    use_template: false,
    force_agent: true,
    learn_template: false,
    read_only: policy === 'observe_only',
    tool_policy: policy,
    template_params: {},
    timeout_sec: args.timeoutSec,
  };
}

async function probeStatus(device) {
  ensurePhoneConfig(device);
  const response = await fetchWithTimeout(`${normalizePhoneUrl(device.phoneUrl)}/api/device/status`, {
    headers: {
      ...authHeaders(device),
      Accept: 'application/json',
    },
  }, 30_000);
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { raw: text };
  }
  if (!response.ok) {
    throw new Error(payload?.error || payload?.message || `HTTP ${response.status}`);
  }
  const data = payload?.data && typeof payload.data === 'object' ? payload.data : payload;
  return {
    online: true,
    version: data?.version ?? null,
    versionCode: data?.versionCode ?? null,
    taskRunning: Boolean(data?.taskRunning),
    agentInitialized: Boolean(data?.agentInitialized),
    accessibilityRunning: Boolean(data?.accessibilityRunning),
    screenOn: data?.screenOn ?? null,
    deviceLocked: data?.deviceLocked ?? null,
  };
}

async function submitTask(device, args) {
  const payload = await signedJsonRequest(device, 'POST', '/api/lumi/agent/tasks', taskBody(args), 60_000);
  const data = payload?.data || payload;
  const taskId = data?.taskId || data?.id;
  if (!taskId) throw new Error('APKClaw did not return a task id.');
  return { payload, taskId };
}

async function getTask(device, taskId) {
  return signedJsonRequest(device, 'GET', `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}`, undefined, 60_000);
}

async function waitForTask(device, taskId, args) {
  const startedAt = Date.now();
  const maxWaitMs = Math.max(30, args.maxWaitSec) * 1000;
  let lastStatus = null;
  while (Date.now() - startedAt < maxWaitMs) {
    await new Promise((resolve) => setTimeout(resolve, Math.max(500, args.pollMs)));
    const payload = await getTask(device, taskId);
    const data = payload?.data || payload;
    lastStatus = data;
    if (['success', 'error', 'cancelled'].includes(data?.status)) {
      return data;
    }
  }
  return { ...(lastStatus || {}), status: 'error', error: `Timed out waiting for APKClaw task after ${args.maxWaitSec}s` };
}

async function runOnDevice(device, args) {
  const startedAt = new Date().toISOString();
  try {
    ensurePhoneConfig(device);
    if (args.command === 'status') {
      return { ok: true, device: publicDevice(device), status: await probeStatus(device), startedAt, finishedAt: new Date().toISOString() };
    }
    const submitted = await submitTask(device, args);
    const final = await waitForTask(device, submitted.taskId, args);
    return {
      ok: final?.status === 'success',
      device: publicDevice(device),
      taskId: submitted.taskId,
      final,
      startedAt,
      finishedAt: new Date().toISOString(),
    };
  } catch (error) {
    const failure = phoneBridgeErrorPayload(error, device, 'phone.status');
    return {
      ...failure,
      device: publicDevice(device),
      startedAt,
      finishedAt: new Date().toISOString(),
    };
  }
}

async function runWithConcurrency(items, limit, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await worker(items[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}

function summarize(results) {
  return results
    .map((result) => {
      const label = result.device?.name || result.device?.id || 'device';
      if (!result.ok) return `[${label}] error=${result.message || result.error || result.final?.error || result.final?.status || 'failed'}`;
      if (result.status) return `[${label}] online version=${result.status.version || 'unknown'} taskRunning=${result.status.taskRunning}`;
      const answer = result.final?.result?.answer || result.final?.answer || '';
      return `[${label}] status=${result.final?.status || 'unknown'}${answer ? ` answer=${answer}` : ''}`;
    })
    .join('\n');
}

function print(args, payload, human) {
  if (args.json) console.log(JSON.stringify(payload, null, 2));
  else console.log(human);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }

  if (args.command === 'list') {
    const store = await loadDevices();
    const devices = store.devices.map((device) => publicDevice(device, store.selectedDeviceId));
    print(args, { ok: true, selectedDeviceId: store.selectedDeviceId || null, devices }, devices.map((device) => `${device.selected ? '*' : '-'} ${device.id || '(no-id)'} ${device.name} configured=${device.configured}`).join('\n'));
    return;
  }

  if (args.command !== 'status' && args.command !== 'run') {
    throw new Error(`Unknown command: ${args.command}`);
  }
  if (args.command === 'run' && !args.prompt.trim()) {
    throw new Error('Missing --prompt');
  }

  const { targets, selectedDeviceId } = await resolveTargets(args);
  const results = await runWithConcurrency(targets, args.concurrency, (device) => runOnDevice(device, args));
  print(args, { ok: results.every((item) => item.ok), selectedDeviceId: selectedDeviceId || null, count: results.length, results }, summarize(results));
}

main().catch((error) => {
  console.error(error?.message || String(error));
  process.exit(1);
});
