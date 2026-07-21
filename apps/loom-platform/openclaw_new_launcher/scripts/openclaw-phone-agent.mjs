#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  authHeaders,
  ensurePhoneConfig,
  fetchWithTimeout,
  normalizePhoneUrl,
  phoneBridgeErrorPayload,
  readLauncherPhoneConfigByDevice,
  readLauncherPhoneLlmConfig,
  signedJsonRequest,
} from './openclaw-phone-secure.mjs';
import {
  tryGetMetricsViaDaemon,
  tryRunViaDaemon,
  trySyncEventsViaDaemon,
} from './lib/phone-daemon/client.mjs';
import {
  getPhoneMetrics,
  runPhoneCommand,
  syncPhoneEvents,
} from './lib/phone-command-core.mjs';
import { normalizeProgressLog } from './lib/phone-progress-log.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_POLL_MS = 1200;
const DEFAULT_TIMEOUT_SEC = 600;
const DEFAULT_STEP_TIMEOUT_SEC = 12;
const DEFAULT_MAX_ROUNDS_BY_MODE = {
  observe: 1,
  safe: 12,
  full: 30,
};
const HISTORY_PATH = path.join(PROJECT_ROOT, 'data', '.openclaw', 'logs', 'phone-agent-history.jsonl');
const READ_SCREEN_TEMPLATES = new Set(['read-screen', 'screen-summary', 'observe', 'observe-fast', 'observe_fast']);
const SCREENSHOT_TEMPLATES = new Set(['screenshot', 'take-screenshot', 'take_screenshot', 'screen-shot']);
const BACK_TEMPLATES = new Set(['back', 'press-back', 'press_back', 'system-back', 'system_back']);
const HOME_TEMPLATES = new Set(['home', 'press-home', 'press_home', 'system-home', 'system_home']);
const OPEN_SETTINGS_TEMPLATES = new Set(['open-settings', 'open_settings', 'settings', 'android-settings', 'android_settings']);
let lastArgs = { json: process.argv.includes('--json'), command: '' };
let lastConfig = null;

function usage() {
  return `
OpenClaw phone Agent CLI

Usage:
  npm run phone:agent -- run --prompt "读取当前手机屏幕并返回摘要"
  npm run phone:agent -- status --task-id <id>
  npm run phone:agent -- events --task-id <id>
  npm run phone:agent -- cancel --task-id <id>
  npm run phone:agent -- metrics --json
  npm run phone:agent -- wechat-reply --reply "你好，我稍后回复你" --json
  npm run phone:agent -- history --limit 20

Commands:
  config-sync                 Push the launcher phone model config into APKClaw
  run                         Submit one bounded async APKClaw Agent task and wait for the result
  submit                      Submit an async APKClaw Agent task and print the task id
  status                      Read one async task status
  events                      Read lightweight events for one async task
  cancel                      Cancel one async task
  metrics                     Read APKClaw phone runtime speed/queue metrics
  events-sync                 Keep a signed SSE connection to APKClaw and print phone events
  wechat-reply                Draft or send a reply in the current WeChat chat screen
  history                     Print recent launcher-side phone Agent task history

Run options:
  --prompt <text>              Required for run/submit
  --mode <observe|safe|full>   Default: safe
  --timeout-sec <n>            APKClaw-side timeout. Default: 600, phone clamps to its supported range
  --max-rounds <n>              APKClaw Agent round budget. Default: observe=1, safe=12, full=30
  --max-wait-sec <n>           CLI wait window for run. Default: 615
  --max-sec <n>                Event sync window. Default: 3600
  --max-events <n>             Event sync frame cap. Default: 0 (until max-sec)
  --poll-ms <n>                Adaptive poll cap. Default: 1200, schedule: immediate, 500ms, 800ms, 1200ms
  --execution-layer <template|agent>
                               Default: agent. Template mode asks APKClaw to try a solidified template first
  --template <name>             Optional solidified template id/name
  --daemon <auto|off|require>   Default: auto. Reuse local phone-agent daemon when possible.
  --step-timeout-sec <n>        Small timeout for each submit/status HTTP step. Default: 12
  --cancel-file <path>          Internal cooperative cancellation signal used by LOOM
  --campaign-id <id>           Canonical Matrix campaign id
  --assignment-id <id>         Canonical Matrix assignment id
  --assignment-template-id <id> Canonical Matrix template id
  --input-json <json>           Canonical Matrix assignment input object
  --retry-budget <n>            Canonical Matrix retry budget
  --limit <n>                  History rows to print. Default: 20
  --reply <text>               Reply text for wechat-reply
  --contact <name>             Optional contact override for whitelist matching
  --whitelist <a,b>            Contacts allowed for --auto-send
  --auto-send                  Actually tap WeChat Send after drafting; requires whitelist
  --allow-group-chat           Allow group chat auto-send when the group is whitelisted
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
    maxRounds: undefined,
    maxWaitSec: DEFAULT_TIMEOUT_SEC + 15,
    maxSec: 3600,
    maxEvents: 0,
    pollMs: DEFAULT_POLL_MS,
    executionLayer: 'agent',
    daemon: normalizedDaemonMode(process.env.OPENCLAW_PHONE_DAEMON || 'auto'),
    templateName: '',
    stepTimeoutSec: DEFAULT_STEP_TIMEOUT_SEC,
    cancelFile: '',
    campaignId: '',
    assignmentId: '',
    assignmentTemplateId: '',
    assignmentInput: null,
    retryBudget: 0,
    canonicalTimeoutProvided: false,
    canonicalRetryBudgetProvided: false,
    limit: 20,
    deviceId: '',
    phoneUrl: '',
    phoneToken: '',
    replyText: '',
    contact: '',
    whitelist: [],
    autoSend: false,
    allowGroupChat: false,
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
        args.canonicalTimeoutProvided = true;
        break;
      case '--max-rounds':
        args.maxRounds = nextInt();
        break;
      case '--max-wait-sec':
        args.maxWaitSec = nextInt();
        break;
      case '--max-sec':
        args.maxSec = nextInt();
        break;
      case '--max-events':
        args.maxEvents = nextInt();
        break;
      case '--poll-ms':
        args.pollMs = nextInt();
        break;
      case '--execution-layer':
        args.executionLayer = next().toLowerCase();
        break;
      case '--template':
        args.templateName = next();
        if (!args.executionLayer || args.executionLayer === 'agent') args.executionLayer = 'template';
        break;
      case '--daemon':
        args.daemon = normalizedDaemonMode(next());
        if (!['auto', 'off', 'require'].includes(args.daemon)) throw new Error('Invalid --daemon, expected auto|off|require');
        break;
      case '--step-timeout-sec':
        args.stepTimeoutSec = nextInt();
        break;
      case '--cancel-file':
        args.cancelFile = next();
        break;
      case '--campaign-id':
        args.campaignId = next();
        break;
      case '--assignment-id':
        args.assignmentId = next();
        break;
      case '--assignment-template-id':
        args.assignmentTemplateId = next();
        break;
      case '--input-json': {
        let value;
        try {
          value = JSON.parse(next());
        } catch {
          throw new Error('Invalid JSON for --input-json');
        }
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
          throw new Error('--input-json must be a JSON object');
        }
        args.assignmentInput = value;
        break;
      }
      case '--retry-budget':
        args.retryBudget = nextInt();
        args.canonicalRetryBudgetProvided = true;
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
      case '--reply':
      case '--reply-text':
        args.replyText = next();
        break;
      case '--contact':
        args.contact = next();
        break;
      case '--whitelist':
      case '--allow-contacts':
        args.whitelist = splitList(next());
        break;
      case '--auto-send':
        args.autoSend = true;
        break;
      case '--allow-group-chat':
        args.allowGroupChat = true;
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
  const canonicalAssignment = Boolean(
    args.campaignId
    || args.assignmentId
    || args.assignmentTemplateId
    || args.assignmentInput
    || args.canonicalRetryBudgetProvided
  );
  if (canonicalAssignment) {
    if (!args.campaignId || !args.assignmentId || !args.deviceId) {
      throw new Error('Canonical Matrix execution requires --campaign-id, --assignment-id, and --device-id');
    }
    if (!args.assignmentInput || !args.canonicalTimeoutProvided || !args.canonicalRetryBudgetProvided) {
      throw new Error('Canonical Matrix execution requires --input-json, --timeout-sec, and --retry-budget');
    }
    if (args.timeoutSec < 30 || args.timeoutSec > 1200) {
      throw new Error('Canonical Matrix --timeout-sec must be between 30 and 1200');
    }
    if (args.retryBudget < 0 || args.retryBudget > 10) {
      throw new Error('Canonical Matrix --retry-budget must be between 0 and 10');
    }
  }
  args.timeoutSec = Math.max(30, args.timeoutSec);
  args.maxRounds = Math.max(1, args.maxRounds || defaultMaxRoundsForMode(args.mode));
  args.maxWaitSec = Math.max(1, args.maxWaitSec);
  args.maxSec = Math.max(1, Math.min(86_400, args.maxSec));
  args.maxEvents = Math.max(0, Math.min(100_000, args.maxEvents));
  args.pollMs = Math.max(500, Math.min(1200, args.pollMs));
  if (!['template', 'agent'].includes(args.executionLayer)) {
    throw new Error('Invalid --execution-layer. Use template or agent.');
  }
  if (!['auto', 'off', 'require'].includes(args.daemon)) {
    throw new Error('Invalid --daemon, expected auto|off|require');
  }
  args.stepTimeoutSec = Math.max(5, Math.min(30, args.stepTimeoutSec));
  return args;
}

function normalizedDaemonMode(value) {
  const mode = String(value || '').trim().toLowerCase();
  if (!mode || mode === '1' || mode === 'true' || mode === 'on') return 'auto';
  if (mode === '0' || mode === 'false' || mode === 'disabled') return 'off';
  return mode;
}

function splitList(value) {
  return String(value || '')
    .split(/[,;\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function resolveConfig(args) {
  const runtime = await readRuntimeContext();
  const launcherPhone = args.deviceId && args.phoneUrl
    ? { id: args.deviceId, phoneUrl: args.phoneUrl, phoneToken: args.phoneToken, source: 'explicit' }
    : await readLauncherPhoneConfigByDevice(args.deviceId);
  const phoneLlm = await readLauncherPhoneLlmConfig();
  return {
    ...args,
    phoneUrl: firstNonEmpty(args.phoneUrl, process.env.OPENCLAW_PHONE_BASE_URL, process.env.APKCLAW_BASE_URL, runtime?.phone?.baseUrl, launcherPhone.phoneUrl),
    phoneToken: firstNonEmpty(args.phoneToken, process.env.OPENCLAW_PHONE_TOKEN, process.env.APKCLAW_TOKEN, launcherPhone.phoneToken),
    deviceId: args.deviceId || launcherPhone.id || runtime?.phone?.defaultDeviceId || '',
    lumiLauncherId: firstNonEmpty(args.lumiLauncherId, process.env.LUMI_LAUNCHER_ID, launcherPhone.lumiLauncherId),
    lumiLauncherSecret: firstNonEmpty(args.lumiLauncherSecret, process.env.LUMI_LAUNCHER_SECRET, launcherPhone.lumiLauncherSecret),
    source: launcherPhone.source,
    phoneLlm,
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

function toolPolicy(mode) {
  if (mode === 'observe' || mode === 'observe_only') return 'observe_only';
  if (mode === 'full' || mode === 'full_access') return 'full_access';
  if (mode === 'safe' || mode === 'safe_action') return 'safe_action';
  throw new Error(`Invalid --mode: ${mode}. Use observe, safe, or full.`);
}

function defaultMaxRoundsForMode(mode) {
  const normalized = String(mode || '').toLowerCase();
  if (normalized === 'observe' || normalized === 'observe_only') return DEFAULT_MAX_ROUNDS_BY_MODE.observe;
  if (normalized === 'full' || normalized === 'full_access') return DEFAULT_MAX_ROUNDS_BY_MODE.full;
  return DEFAULT_MAX_ROUNDS_BY_MODE.safe;
}

function taskBody(config) {
  const policy = toolPolicy(config.mode);
  const canonicalAssignment = Boolean(config.assignmentId);
  return {
    prompt: canonicalAssignment ? config.prompt : [
      config.prompt,
      '',
      'OpenClaw wrapper contract:',
      '- Run one bounded task only.',
      `- APKClaw has a hard ${config.maxRounds}-round budget; return partial results instead of looping indefinitely.`,
      '- For visible list, menu, Settings category, shopping/search/product/job/comment collection, call collect_list_items first with target=generic/job/product as appropriate instead of manual get_screen_info + swipe loops.',
      '- When the user asks for read-only collection with scrolling, infer max_swipes from the prompt and finish after one collect_list_items result unless a safety issue is detected.',
      '- Return structured visible findings, failures, and whether follow-up is needed.',
    ].join('\n'),
    use_template: config.executionLayer === 'template',
    force_agent: config.executionLayer === 'agent',
    learn_template: config.executionLayer === 'agent',
    read_only: policy === 'observe_only',
    tool_policy: policy,
    template_name: config.templateName || undefined,
    template_id: config.templateName || undefined,
    template_params: canonicalAssignment ? {
      source: 'loom',
      execution_layer: config.executionLayer,
      campaign_id: config.campaignId,
      assignment_id: config.assignmentId,
      assignment_template_id: config.assignmentTemplateId || '',
      device_id: config.deviceId,
      input: config.assignmentInput,
      retry_budget: config.retryBudget,
    } : { source: 'loom', execution_layer: config.executionLayer },
    direct_first: config.executionLayer !== 'agent',
    step_timeout_sec: config.stepTimeoutSec,
    timeout_sec: config.timeoutSec,
    max_rounds: config.maxRounds,
    ...(canonicalAssignment ? {
      campaign_id: config.campaignId,
      assignment_id: config.assignmentId,
      assignment_template_id: config.assignmentTemplateId || '',
      device_id: config.deviceId,
      input: config.assignmentInput,
      retry_budget: config.retryBudget,
    } : {}),
  };
}

async function probeDeviceStatus(config) {
  ensurePhoneConfig(config);
  const response = await fetchWithTimeout(`${normalizePhoneUrl(config.phoneUrl)}/api/device/status`, {
    headers: {
      ...authHeaders(config),
      Accept: 'application/json',
    },
}, Math.min(8_000, config.stepTimeoutSec * 1000));
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`device_status_non_json: HTTP ${response.status}`);
  }
  if (!response.ok || payload?.success === false) {
    throw new Error(payload?.error || payload?.message || `device_status_failed: HTTP ${response.status}`);
  }
  return payload?.data || payload;
}

async function assertReadyForAgent(config) {
  let status;
  try {
    status = await probeDeviceStatus(config);
  } catch (error) {
    throw new Error(`device_offline: 无法连接手机端 APKClaw，请确认手机和电脑在同一网络，且 APKClaw 已启动。${error?.message || error}`);
  }
  let stop = earlyStopReason(status);
  let importResult = null;
  if (stop?.code === 'model_not_configured') {
    importResult = await importPhoneLlmConfig(config);
    if (importResult.ok) {
      status = await probeDeviceStatus(config);
      stop = earlyStopReason(status);
    }
    if (stop?.code === 'model_not_configured') {
      const exported = await exportPhoneLlmConfig(config);
      if (phoneHasUsableLlmConfig(exported)) {
        status = {
          ...status,
          agentInitialized: true,
          llmConfigured: true,
          modelConfigured: true,
          modelReady: true,
          phoneLlmExport: publicPhoneLlmExport(exported),
        };
        stop = earlyStopReason(status);
      }
    }
  }
  if (stop) {
    const extra = importResult?.error ? `; auto_config_failed=${importResult.error}` : '';
    throw new Error(`${stop.code}: ${stop.message}${extra}`);
  }
  return status;
}

function hasPhoneLlmConfig(config) {
  const llm = config.phoneLlm || {};
  return Boolean(llm.baseUrl && llm.apiKey && llm.model);
}

function publicPhoneLlmConfig(config) {
  const llm = config.phoneLlm || {};
  return {
    configured: hasPhoneLlmConfig(config),
    baseUrlConfigured: Boolean(llm.baseUrl),
    apiKeyConfigured: Boolean(llm.apiKey),
    model: llm.model || '',
    source: llm.source || '',
  };
}

async function importPhoneLlmConfig(config) {
  if (!hasPhoneLlmConfig(config)) {
    return { ok: false, error: 'missing_local_phone_model_config' };
  }
  try {
    const llm = config.phoneLlm;
    const payload = await signedJsonRequest(config, 'POST', '/api/lumi/config/llm/import', {
      baseUrl: llm.baseUrl,
      apiKey: llm.apiKey,
      model: llm.model,
    }, config.stepTimeoutSec * 1000);
    const data = payload?.data || payload;
    return {
      ok: payload?.success !== false,
      model: llm.model,
      phone: {
        llmConfigured: data?.llmConfigured,
        modelConfigured: data?.modelConfigured,
        modelReady: data?.modelReady,
        model: data?.model || data?.modelName || llm.model,
      },
    };
  } catch (error) {
    return { ok: false, error: error?.message || String(error) };
  }
}

async function exportPhoneLlmConfig(config) {
  try {
    const payload = await signedJsonRequest(config, 'GET', '/api/lumi/config/llm/export', undefined, config.stepTimeoutSec * 1000);
    const data = payload?.data || payload;
    return { ok: payload?.success !== false, ...data };
  } catch (error) {
    return { ok: false, error: error?.message || String(error) };
  }
}

function phoneHasUsableLlmConfig(summary) {
  if (!summary || summary.ok === false) return false;
  const apiKeySet = summary.apiKeySet === true || summary.apiKeyConfigured === true || summary.hasApiKey === true;
  return Boolean(apiKeySet && firstNonEmpty(summary.baseUrl, summary.base_url) && firstNonEmpty(summary.model, summary.modelName));
}

function publicPhoneLlmExport(summary) {
  return {
    configured: phoneHasUsableLlmConfig(summary),
    baseUrlConfigured: Boolean(firstNonEmpty(summary?.baseUrl, summary?.base_url)),
    apiKeyConfigured: summary?.apiKeySet === true || summary?.apiKeyConfigured === true || summary?.hasApiKey === true,
    model: firstNonEmpty(summary?.model, summary?.modelName),
  };
}

function normalizedAccessibilityState(status) {
  return String(status?.accessibilityState || '').trim().toLowerCase();
}

function accessibilityLooksHealthy(status) {
  const state = normalizedAccessibilityState(status);
  return (
    state === 'healthy'
    || status?.accessibilityHealthy === true
    || status?.accessibilityBound === true
    || status?.accessibilityRunning === true
  );
}

function accessibilityLooksStale(status) {
  const state = normalizedAccessibilityState(status);
  return state === 'stale_enabled_not_bound' || status?.accessibilityStale === true;
}

function accessibilityClearlyOff(status) {
  if (accessibilityLooksHealthy(status) || accessibilityLooksStale(status)) return false;
  return (
    status?.accessibilityEnabledInSettings === false
    || status?.accessibilityListedInSettings === false
    || status?.accessibilityMasterEnabled === false
    || status?.accessibilityRunning === false
    || status?.accessibilityEnabled === false
  );
}

function phoneAgentRuntimeLooksReady(status) {
  if (!status || typeof status !== 'object') return false;
  if (status.agentInitialized !== false) return true;
  return (
    accessibilityLooksHealthy(status)
    || status.agentServiceReady === true
    || status.agentServiceRunning === true
    || status.taskQueueReady === true
    || status.queueSupported === true
  );
}

function earlyStopReason(status, options = {}) {
  const requireModel = options.requireModel !== false;
  const queueSupported = status?.queueSupported === true;
  if (!queueSupported && (status?.taskRunning === true || status?.agentBusy === true || status?.busy === true)) {
    return { code: 'task_busy', message: 'APKClaw 正在执行其他任务，请稍后重试。' };
  }
  if (status?.screenOn === false || status?.interactive === false || status?.deviceLocked === true || status?.locked === true) {
    return { code: 'phone_locked', message: '手机处于锁屏或熄屏状态，请先解锁并保持亮屏。' };
  }
  if (accessibilityLooksStale(status)) {
    return { code: 'accessibility_stale', message: '手机无障碍开关已开启，但 APKClaw 服务未重新绑定。请打开 APKClaw 到前台，必要时重新开关一次无障碍。' };
  }
  if (accessibilityClearlyOff(status)) {
    return { code: 'accessibility_off', message: '手机无障碍服务未开启，请在手机端开启 APKClaw 无障碍。' };
  }
  if (status?.agentInitialized === false && !phoneAgentRuntimeLooksReady(status)) {
    return { code: 'agent_not_initialized', message: '手机 Agent 服务尚未就绪，请在手机端打开 APKClaw 并保持前台运行。' };
  }
  if (requireModel && (status?.modelConfigured === false || status?.llmConfigured === false)) {
    return { code: 'model_not_configured', message: '手机 Agent 模型尚未配置，请先在麓鸣里同步手机模型。' };
  }
  if (requireModel && status?.modelReady === false) {
    return { code: 'model_not_ready', message: '手机 Agent 模型尚未就绪，请稍后重试或重新同步手机模型。' };
  }
  return null;
}

async function assertReadyForFastPath(config) {
  let status;
  try {
    status = await probeDeviceStatus(config);
  } catch (error) {
    throw new Error(`device_offline: ${error?.message || error}`);
  }
  const stop = earlyStopReason(status, { requireModel: false });
  if (stop) {
    throw new Error(`${stop.code}: ${stop.message}`);
  }
  return status;
}

function fixedFastPathPlan(config) {
  if (config.command !== 'run') return null;
  if (config.assignmentId) return null;
  const template = normalizeFixedName(config.templateName);
  const prompt = normalizePromptForFastPath(config.prompt);

  if (READ_SCREEN_TEMPLATES.has(template) || toolPolicy(config.mode) === 'observe_only' || isSimpleReadScreenPrompt(prompt)) {
    return {
      kind: 'observe',
      mode: 'observe_fast',
      executionLayer: template ? 'template' : 'direct',
      templateName: config.templateName || '',
      endpoint: '/api/lumi/agent/observe_fast?_lumi=1',
      fallbackToAgent: false,
    };
  }
  if (SCREENSHOT_TEMPLATES.has(template) || isSimpleScreenshotPrompt(prompt)) {
    return {
      kind: 'screenshot',
      mode: 'screenshot',
      executionLayer: template ? 'template' : 'direct',
      templateName: config.templateName || '',
      endpoint: '/api/lumi/vision/frame?_lumi=1',
      fallbackToAgent: false,
    };
  }
  if (OPEN_SETTINGS_TEMPLATES.has(template) || isSimpleOpenSettingsPrompt(prompt)) {
    return actionFastPlan(config, {
      action: 'open_app',
      packageName: 'com.android.settings',
      targetLabel: 'Android Settings',
      reason: 'LOOM deterministic open-settings template',
      checkLaunchDialog: false,
      verifyForeground: true,
    }, template);
  }
  const packageName = explicitOpenAppPackage(template);
  if (packageName) {
    return actionFastPlan(config, {
      action: 'open_app',
      packageName,
      reason: 'LOOM deterministic open-app template',
      checkLaunchDialog: false,
      verifyForeground: true,
    }, template);
  }
  if (BACK_TEMPLATES.has(template) || isSimpleBackPrompt(prompt)) {
    return actionFastPlan(config, {
      action: 'back',
      reason: 'LOOM deterministic back template',
    }, template);
  }
  if (HOME_TEMPLATES.has(template) || isSimpleHomePrompt(prompt)) {
    return actionFastPlan(config, {
      action: 'home',
      reason: 'LOOM deterministic home template',
    }, template);
  }
  return null;
}

function actionFastPlan(config, body, template) {
  return {
    kind: 'action',
    mode: 'action_fast',
    executionLayer: template ? 'template' : 'direct',
    templateName: config.templateName || '',
    endpoint: '/api/lumi/agent/action_fast',
    body: {
      observeAfter: true,
      ...body,
    },
    fallbackToAgent: true,
  };
}

function normalizeFixedName(value) {
  return String(value || '').trim().toLowerCase().replace(/[\s_]+/g, '-');
}

function normalizePromptForFastPath(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[。．｡，,！!？?\s]/g, '');
}

function isSimpleReadScreenPrompt(prompt) {
  return /^(读取|读一下|查看|观察|识别|总结)?(当前)?(手机)?(屏幕|页面|画面)(内容|摘要)?$/.test(prompt)
    || /^(read|observe|inspect|summarize)(current)?(phone)?screen$/.test(prompt);
}

function isSimpleScreenshotPrompt(prompt) {
  return /^(截图|截屏|拍屏幕|保存截图)$/.test(prompt)
    || /^(screenshot|takescreenshot|capturecurrentscreen)$/.test(prompt);
}

function isSimpleOpenSettingsPrompt(prompt) {
  return /^(打开|开启|进入)(系统|安卓|android)?设置$/.test(prompt)
    || /^(open|launch)(android|system)?settings$/.test(prompt);
}

function isSimpleBackPrompt(prompt) {
  return /^(返回|后退|按返回键|返回上一页)$/.test(prompt)
    || /^(back|pressback|goback)$/.test(prompt);
}

function isSimpleHomePrompt(prompt) {
  return /^(回桌面|回到桌面|主页|按home键|返回桌面)$/.test(prompt)
    || /^(home|presshome|gohome)$/.test(prompt);
}

function explicitOpenAppPackage(template) {
  if (!template.startsWith('open-app-') && !template.startsWith('open-app:')) return '';
  const value = template.replace(/^open-app[:-]/, '').replace(/-/g, '.').trim();
  return /^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/.test(value) ? value : '';
}

async function runFixedFastPath(config, plan) {
  const startedAt = Date.now();
  const payload = plan.kind === 'action'
    ? await signedJsonRequest(config, 'POST', plan.endpoint, plan.body, config.stepTimeoutSec * 1000)
    : await signedJsonRequest(config, 'GET', plan.endpoint, undefined, config.stepTimeoutSec * 1000);
  return fixedFastPathResult(config, plan, payload, Date.now() - startedAt);
}

function fixedFastPathResult(config, plan, payload, wallMs) {
  const data = payload?.data || payload || {};
  const payloadSuccess = payload?.success !== false;
  const dataSuccess = data?.success !== false;
  const ok = payloadSuccess && dataSuccess;
  const metrics = {
    ...(data?.metrics || payload?.metrics || {}),
    mode: data?.metrics?.mode || plan.mode,
    rounds: Number.isFinite(Number(data?.metrics?.rounds)) ? Number(data.metrics.rounds) : 0,
  };
  if (!Number.isFinite(Number(metrics.totalMs))) metrics.totalMs = wallMs;
  const currentStep = data?.currentStep || (ok ? 'success' : 'error');
  const final = {
    status: ok ? 'success' : 'error',
    prompt: config.prompt,
    result: data,
    metrics,
    mode: metrics.mode,
    executionLayer: plan.executionLayer,
    templateName: plan.templateName || undefined,
    finishedAt: Date.now(),
    error: ok ? '' : (data?.error || payload?.error || 'fast_path_failed'),
  };
  return {
    ok,
    fastPath: true,
    executionLayer: plan.executionLayer,
    templateName: plan.templateName || undefined,
    final,
    metrics,
    mode: metrics.mode,
    currentStep,
    events: data?.events,
    ...fastPathPublicFields(data),
    queue: { queueMs: 0, queueDepth: 0, cancelRequested: false },
    payload,
    data,
    error: final.error || undefined,
  };
}

function fastPathPublicFields(data) {
  const fields = {};
  for (const key of ['action', 'screenHash', 'summary', 'currentPackage', 'beforeHash', 'afterHash', 'changed', 'actionMs', 'verifyMs']) {
    if (data?.[key] !== undefined) fields[key] = data[key];
  }
  return fields;
}

function fixedFastPathError(config, plan, error, wallMs) {
  const message = error?.message || String(error || 'fast_path_failed');
  return {
    ok: false,
    fastPath: true,
    executionLayer: plan.executionLayer,
    templateName: plan.templateName || undefined,
    final: {
      status: 'error',
      prompt: config.prompt,
      result: { error: message },
      metrics: { mode: plan.mode, rounds: 0, totalMs: wallMs },
      mode: plan.mode,
      executionLayer: plan.executionLayer,
      templateName: plan.templateName || undefined,
      finishedAt: Date.now(),
      error: message,
    },
    metrics: { mode: plan.mode, rounds: 0, totalMs: wallMs },
    mode: plan.mode,
    currentStep: 'error',
    queue: { queueMs: 0, queueDepth: 0, cancelRequested: false },
    payload: null,
    data: { error: message },
    error: message,
  };
}

function summarizeFastPath(result) {
  const data = result?.data || result?.final?.result || {};
  const summary = data?.summary || data?.message || data?.answer || '';
  const error = result?.error || data?.error || '';
  return [
    `status=${result?.ok ? 'success' : 'error'}`,
    `mode=${result?.mode || 'fast_path'}`,
    summary ? `summary=${summary}` : '',
    error ? `error=${error}` : '',
  ].filter(Boolean).join('\n');
}

async function submitTask(config) {
  const payload = await signedJsonRequest(config, 'POST', '/api/lumi/agent/tasks', taskBody(config), config.stepTimeoutSec * 1000);
  const data = payload?.data || payload;
  const taskId = data?.taskId || data?.id;
  if (!taskId) throw new Error('APKClaw did not return a task id.');
  return { payload, taskId };
}

async function getTask(config, taskId) {
  return signedJsonRequest(config, 'GET', `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}`, undefined, config.stepTimeoutSec * 1000);
}

async function getTaskEvents(config, taskId) {
  const payload = await signedJsonRequest(config, 'GET', `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}/events`, undefined, config.stepTimeoutSec * 1000);
  const data = payload?.data || payload;
  if (!data || typeof data !== 'object') return payload;
  const progressLog = normalizeProgressLog(data.progressLog, data.events);
  if (payload?.data && typeof payload.data === 'object') {
    return { ...payload, data: { ...payload.data, progressLog } };
  }
  return { ...payload, progressLog };
}

async function cancelTask(config, taskId) {
  return signedJsonRequest(config, 'POST', `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}/cancel`, {}, config.stepTimeoutSec * 1000);
}

async function getMetrics(config) {
  return signedJsonRequest(config, 'GET', '/api/lumi/metrics', undefined, config.stepTimeoutSec * 1000);
}

async function runWeChatReply(config) {
  if (!config.replyText.trim()) throw new Error('Missing --reply');
  const payload = await signedJsonRequest(config, 'POST', '/api/lumi/wechat/auto_reply', {
    replyText: config.replyText,
    contact: config.contact || undefined,
    autoSend: Boolean(config.autoSend),
    whitelist: config.whitelist,
    allowGroupChat: Boolean(config.allowGroupChat),
  }, config.stepTimeoutSec * 1000);
  const data = payload?.data || payload || {};
  const ok = payload?.success !== false && data?.success !== false;
  return {
    ok,
    mode: data.mode || 'wechat_auto_reply',
    currentStep: data.currentStep || (ok ? 'success' : 'error'),
    contact: data.contact || '',
    latestMessage: data.latestMessage || '',
    replyText: data.replyText || config.replyText,
    autoSend: Boolean(data.autoSend ?? config.autoSend),
    drafted: Boolean(data.drafted),
    sent: Boolean(data.sent),
    shouldSend: Boolean(data.shouldSend),
    errorCode: data.errorCode || payload?.errorCode || '',
    message: data.message || payload?.error || '',
    data,
    payload,
  };
}

async function waitForTask(config, taskId) {
  const startedAt = Date.now();
  const maxWaitMs = Math.max(30, config.maxWaitSec) * 1000;
  let lastStatus = null;
  let pollAttempt = 0;
  while (Date.now() - startedAt < maxWaitMs) {
    const delayMs = adaptivePollDelayMs(pollAttempt, config.pollMs);
    pollAttempt += 1;
    if (delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
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

function adaptivePollDelayMs(attempt, pollCapMs) {
  if (attempt <= 0) return 0;
  const schedule = [500, 800, 1200];
  const scheduled = schedule[Math.min(attempt - 1, schedule.length - 1)];
  const cap = Math.max(500, Math.min(1200, Number(pollCapMs) || 1200));
  return Math.min(scheduled, cap);
}

function summarizeTask(task) {
  const result = task?.result || task?.data || {};
  const answer = result?.answer || task?.answer || '';
  const error = result?.error || task?.error || '';
  const events = Array.isArray(task?.events) ? task.events : Array.isArray(result?.events) ? result.events : [];
  const lastEvent = events.at(-1);
  const lastProgress = normalizeProgressLog(task?.progressLog || result?.progressLog, events).at(-1);
  return [
    `status=${task?.status || 'unknown'}`,
    task?.taskId || task?.id ? `task=${String(task.taskId || task.id).slice(0, 8)}` : '',
    answer ? `answer=${answer}` : '',
    error ? `error=${error}` : '',
    lastProgress?.text ? `progress=${lastProgress.text}` : lastEvent?.message ? `last=${lastEvent.message}` : '',
  ].filter(Boolean).join('\n');
}

function queueFields(task) {
  const result = task?.result || task?.data || {};
  const candidates = [
    task?.queue,
    result?.queue,
    task,
    result,
  ].filter((item) => item && typeof item === 'object');
  const queue = {};
  for (const source of candidates) {
    for (const key of ['queueMs', 'queueDepth', 'queuePosition']) {
      if (queue[key] !== undefined) continue;
      const value = Number.parseInt(source[key], 10);
      if (Number.isFinite(value) && value >= 0) queue[key] = value;
    }
    if (queue.currentTaskId === undefined && typeof source.currentTaskId === 'string' && source.currentTaskId.trim()) {
      queue.currentTaskId = source.currentTaskId.trim();
    }
    if (queue.cancelRequested === undefined && typeof source.cancelRequested === 'boolean') {
      queue.cancelRequested = source.cancelRequested;
    }
  }
  return Object.keys(queue).length ? queue : undefined;
}

function publicTaskResult(task) {
  const result = task?.result || task?.data || {};
  const metrics = result?.metrics || task?.metrics || undefined;
  const queue = queueFields(task);
  const events = Array.isArray(result?.events) ? result.events : Array.isArray(task?.events) ? task.events : undefined;
  const progressLog = normalizeProgressLog(result?.progressLog || task?.progressLog, events);
  return {
    final: task,
    metrics,
    mode: result?.mode || task?.mode || metrics?.mode,
    currentStep: result?.currentStep || task?.currentStep || task?.status,
    events,
    progressLog,
    queue,
  };
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
  if (/(phone_locked|locked|screen off|熄屏|锁屏)/i.test(text)) return 'phone_locked';
  if (/(model_not_configured|model.*not.*configured|模型.*配置|llm.*not.*configured)/i.test(text)) return 'model_not_configured';
  if (/(accessibility|无障碍|screen.?tree|node tree|permission)/i.test(text)) return 'accessibility_off';
  if (/(timeout|timed out|超时)/i.test(text)) return 'timeout';
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

function print(config, payload, human) {
  if (config.json) console.log(JSON.stringify(withConfigSource(config, payload), null, 2));
  else console.log(human);
}

function printPhoneEvent(config, event) {
  const payload = {
    ok: true,
    type: 'phone_event',
    ...event,
    deviceId: config.deviceId || '',
    configSource: config.source || '',
    receivedAt: new Date().toISOString(),
  };
  if (config.json) console.log(JSON.stringify(payload));
  else console.log(`${payload.receivedAt} ${payload.event} ${payload.id || ''}`.trim());
}

function printPhoneEventSyncSummary(config, summary) {
  const payload = {
    ok: true,
    type: 'phone_event_sync_summary',
    ...summary,
    deviceId: config.deviceId || '',
    configSource: config.source || '',
    receivedAt: new Date().toISOString(),
  };
  if (config.json) console.log(JSON.stringify(payload));
  else console.log(`event sync stopped: ${summary.stoppedBy}, events=${summary.eventCount}`);
}

function withConfigSource(config, payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return payload;
  return {
    ...payload,
    configSource: payload.configSource || config.source || '',
  };
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

  ensurePhoneConfig(config);

  if (config.command === 'config-sync') {
    const imported = await importPhoneLlmConfig(config);
    if (!imported.ok) {
      const exported = await exportPhoneLlmConfig(config);
      if (phoneHasUsableLlmConfig(exported)) {
        print(
          config,
          { ok: true, imported: false, phoneAlreadyConfigured: true, phone: publicPhoneLlmExport(exported), local: publicPhoneLlmConfig(config) },
          `phone model already configured: ${firstNonEmpty(exported.model, exported.modelName)}`,
        );
        return;
      }
      throw new Error(`model_config_sync_failed: ${imported.error || exported.error || 'unknown'}`);
    }
    let status = {};
    try {
      status = await probeDeviceStatus(config);
    } catch (error) {
      status = { error: error?.message || String(error) };
    }
    print(
      config,
      { ok: true, imported: true, model: imported.model, phone: imported.phone, local: publicPhoneLlmConfig(config), status },
      `phone model synced: ${imported.model}`,
    );
    return;
  }

  if (config.command === 'metrics') {
    if (config.daemon !== 'off') {
      const daemonAttempt = await tryGetMetricsViaDaemon(config);
      if (daemonAttempt.usedDaemon) {
        if (daemonAttempt.error) throw daemonAttempt.error;
        const result = daemonAttempt.result;
        print(config, result, `metrics taskCount=${result.metrics?.taskCount ?? '-'} queueDepth=${result.metrics?.queueDepth ?? '-'}`);
        return;
      }
      if (config.daemon === 'require') {
        throw new Error(`daemon_required: ${daemonAttempt.error?.message || daemonAttempt.error}`);
      }
    }
    const result = await getPhoneMetrics(config);
    print(config, result, `metrics taskCount=${result.metrics?.taskCount ?? '-'} queueDepth=${result.metrics?.queueDepth ?? '-'}`);
    return;
  }

  if (config.command === 'events-sync') {
    if (config.daemon !== 'off') {
      const daemonAttempt = await trySyncEventsViaDaemon(config, (event) => printPhoneEvent(config, event));
      if (daemonAttempt.usedDaemon) {
        if (daemonAttempt.error) throw daemonAttempt.error;
        printPhoneEventSyncSummary(config, daemonAttempt.result.summary || { ok: true, eventCount: daemonAttempt.result.events?.length || 0 });
        return;
      }
      if (config.daemon === 'require') {
        throw new Error(`daemon_required: ${daemonAttempt.error?.message || daemonAttempt.error}`);
      }
    }
    const summary = await syncPhoneEvents(config, (event) => printPhoneEvent(config, event));
    printPhoneEventSyncSummary(config, summary);
    return;
  }

  if (config.command === 'wechat-reply' || config.command === 'wechat_reply') {
    const result = await runWeChatReply(config);
    await appendHistory({
      command: 'wechat-reply',
      status: result.ok ? 'success' : 'error',
      submittedAt: new Date().toISOString(),
      finishedAt: new Date().toISOString(),
      mode: result.mode,
      summary: result.currentStep,
      error: result.message || result.errorCode || '',
      device: publicDevice(config),
    });
    print(config, result, result.ok ? `wechat ${result.currentStep}` : (result.message || result.errorCode || 'wechat_reply_failed'));
    return;
  }

  if (config.command === 'submit') {
    if (!config.prompt.trim()) throw new Error('Missing --prompt');
    const submitted = await submitTask(config);
    await appendHistory({
      command: config.command,
      status: 'submitted',
      submittedAt: new Date().toISOString(),
      taskId: submitted.taskId,
      mode: toolPolicy(config.mode),
      timeoutSec: config.timeoutSec,
      maxRounds: config.maxRounds,
      maxWaitSec: config.maxWaitSec,
      executionLayer: config.executionLayer,
      templateName: config.templateName,
      stepTimeoutSec: config.stepTimeoutSec,
      promptPreview: promptPreview(config.prompt),
      device: publicDevice(config),
    });
    if (config.command === 'submit') {
      print(config, { ok: true, taskId: submitted.taskId, submitted: submitted.payload }, `submitted task=${submitted.taskId}`);
      return;
    }
  }

  if (config.command === 'run') {
    if (!config.prompt.trim()) throw new Error('Missing --prompt');
    if (config.daemon !== 'off') {
      const daemonAttempt = await tryRunViaDaemon(config);
      if (daemonAttempt.usedDaemon) {
        if (daemonAttempt.error) {
          throw daemonAttempt.error;
        }
        await appendHistory({
          command: config.command,
          status: daemonAttempt.result.ok ? 'success' : 'error',
          submittedAt: new Date().toISOString(),
          finishedAt: new Date().toISOString(),
          taskId: daemonAttempt.result.taskId || '',
          mode: daemonAttempt.result.mode || '',
          metrics: daemonAttempt.result.metrics || {},
          summary: daemonAttempt.result.currentStep || '',
          error: daemonAttempt.result.error || '',
        });
        print(config, daemonAttempt.result, daemonAttempt.result.currentStep || daemonAttempt.result.mode || 'daemon result');
        return;
      }
      if (config.daemon === 'require') {
        throw new Error(`daemon_required: ${daemonAttempt.error?.message || daemonAttempt.error}`);
      }
    }
    const result = await runPhoneCommand(config);
    await appendHistory({
      command: config.command,
      status: result.ok ? 'success' : 'error',
      submittedAt: new Date().toISOString(),
      finishedAt: new Date().toISOString(),
      taskId: result.taskId || '',
      mode: result.mode || '',
      metrics: result.metrics || {},
      summary: result.currentStep || '',
      error: result.error || '',
    });
    print(config, result, result.ok ? summarizeFastPath(result) : result.error);
    return;
  }

  if (config.command === 'status') {
    if (!config.taskId.trim()) throw new Error('Missing --task-id');
    const payload = await getTask(config, config.taskId);
    print(config, payload, summarizeTask(payload?.data || payload));
    return;
  }

  if (config.command === 'events' || config.command === 'task-events' || config.command === 'task_events') {
    if (!config.taskId.trim()) throw new Error('Missing --task-id');
    const payload = await getTaskEvents(config, config.taskId);
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
  const config = lastConfig || lastArgs || {};
  const payload = phoneBridgeErrorPayload(error, config, config.command || 'phone');
  if (config.json || process.argv.includes('--json')) {
    console.log(JSON.stringify(payload, null, 2));
  } else {
    console.error(`ERROR: ${payload.message}`);
  }
  process.exitCode = 1;
});
