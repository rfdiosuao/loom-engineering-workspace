import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  authHeaders,
  ensurePhoneConfig,
  fetchWithTimeout,
  normalizePhoneUrl,
  PhoneBridgeError,
  signedFetch,
  signedJsonRequest,
} from '../openclaw-phone-secure.mjs';
import { normalizeProgressLog, withProgressLogsInSseEvent } from './phone-progress-log.mjs';

const READ_SCREEN_TEMPLATES = new Set(['read-screen', 'screen-summary', 'observe', 'observe-fast', 'observe_fast']);
const SCREENSHOT_TEMPLATES = new Set(['screenshot', 'take-screenshot', 'take_screenshot', 'screen-shot']);
const BACK_TEMPLATES = new Set(['back', 'press-back', 'press_back', 'system-back', 'system_back']);
const HOME_TEMPLATES = new Set(['home', 'press-home', 'press_home', 'system-home', 'system_home']);
const OPEN_SETTINGS_TEMPLATES = new Set(['open-settings', 'open_settings', 'settings', 'android-settings', 'android_settings']);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
const ACTION_LOCK_DIR = path.join(PROJECT_ROOT, 'data', '.openclaw', 'runtime', 'phone-action-locks');
const ACTION_LOCK_STALE_MS = 90_000;

export const QUEUE_KIND = Object.freeze({
  READ: 'read',
  SCREENSHOT: 'screenshot',
  ACTION: 'action',
});

export function commandQueueKind(config) {
  const plan = fixedFastPathPlan(config);
  if (plan?.kind === 'observe') return QUEUE_KIND.READ;
  if (plan?.kind === 'screenshot') return QUEUE_KIND.SCREENSHOT;
  return QUEUE_KIND.ACTION;
}

export function fixedFastPathPlan(config) {
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

export async function runPhoneCommand(config) {
  if (commandQueueKind(config) === QUEUE_KIND.ACTION) {
    return withDeviceMutationLock(config, () => runPhoneCommandUnlocked(config));
  }
  return runPhoneCommandUnlocked(config);
}

async function runPhoneCommandUnlocked(config) {
  if (await cancellationRequested(config.cancelFile)) {
    return cancelledPhoneCommandResult(config);
  }
  const plan = fixedFastPathPlan(config);
  if (plan) {
    if (config.fastPathReadyStatus && typeof config.fastPathReadyStatus === 'object') {
      assertKnownReadyForFastPath(config.fastPathReadyStatus);
    } else {
      await probeFastPathReadyStatus(config);
    }
    const startedAt = Date.now();
    let fastResult;
    try {
      fastResult = await runFixedFastPath(config, plan);
    } catch (error) {
      fastResult = fixedFastPathError(config, plan, error, Date.now() - startedAt);
    }
    if (!fastResult.ok && plan.kind === 'action' && isLumiAuthFailureMessage(fastResult.error)) return fastResult;
    if (fastResult.ok || !plan.fallbackToAgent) return fastResult;
  }
  return runAgentCommand(config);
}

export async function getPhoneMetrics(config) {
  await probeDeviceStatus(config);
  const payload = await signedJsonRequest(config, 'GET', '/api/lumi/agent/metrics?_lumi=1', undefined, config.stepTimeoutSec * 1000);
  return { ok: true, metrics: payload?.data?.metrics || payload?.data || payload };
}

export async function syncPhoneEvents(config, onEvent) {
  await probeDeviceStatus(config);
  const response = await signedFetch(config, 'GET', '/api/lumi/events', (config.maxSec + 5) * 1000);
  if (!response.ok) {
    throw new PhoneBridgeError(
      'phone_event_stream_failed',
      `手机事件流连接失败：HTTP ${response.status}`,
      { retryable: response.status >= 500 || response.status === 404, currentStep: 'events_sync', details: { status: response.status } },
    );
  }
  return readSseChunksWithDeadline(response, config, (event) => onEvent(withProgressLogsInSseEvent(event)));
}

async function withDeviceMutationLock(config, fn) {
  const key = deviceMutationLockKey(config);
  const lockPath = path.join(ACTION_LOCK_DIR, `${key}.lock`);
  const waitTimeoutMs = Math.max(10_000, Math.min(60_000, Number(config.stepTimeoutSec || 10) * 4_000));
  await fs.mkdir(ACTION_LOCK_DIR, { recursive: true });
  const startedAt = Date.now();
  let handle = null;
  while (!handle) {
    try {
      handle = await fs.open(lockPath, 'wx');
      await handle.writeFile(JSON.stringify({
        pid: process.pid,
        deviceId: config.deviceId || '',
        phoneUrl: normalizePhoneUrl(config.phoneUrl),
        acquiredAt: new Date().toISOString(),
      }));
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      await removeStaleMutationLock(lockPath);
      if (Date.now() - startedAt > waitTimeoutMs) {
        throw new PhoneBridgeError(
          'phone_action_queue_timeout',
          '同一台手机正在执行另一个写动作，请稍后重试。',
          { retryable: true, currentStep: 'queue', details: { lockPath, waitTimeoutMs } },
        );
      }
      await sleep(120);
    }
  }
  try {
    return await fn();
  } finally {
    try {
      await handle.close();
    } catch {
      // Closing the lock handle is best-effort.
    }
    try {
      await fs.unlink(lockPath);
    } catch {
      // A stale lock cleanup may already have removed it.
    }
  }
}

async function removeStaleMutationLock(lockPath) {
  try {
    const stat = await fs.stat(lockPath);
    if (Date.now() - stat.mtimeMs > ACTION_LOCK_STALE_MS) {
      await fs.unlink(lockPath);
    }
  } catch {
    // If the lock disappeared between checks, the next acquire loop can proceed.
  }
}

function deviceMutationLockKey(config) {
  const raw = [
    config.deviceId || '',
    normalizePhoneUrl(config.phoneUrl),
    String(config.phoneToken || ''),
  ].join('\n');
  return crypto.createHash('sha256').update(raw, 'utf8').digest('hex').slice(0, 32);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toolPolicy(mode) {
  if (mode === 'observe' || mode === 'observe_only') return 'observe_only';
  if (mode === 'full' || mode === 'full_access') return 'full_access';
  if (mode === 'safe' || mode === 'safe_action') return 'safe_action';
  throw new Error(`Invalid --mode: ${mode}. Use observe, safe, or full.`);
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

async function runAgentCommand(config) {
  await assertReadyForAgent(config);
  if (await cancellationRequested(config.cancelFile)) {
    return cancelledPhoneCommandResult(config);
  }
  const submitted = await submitTask(config);
  const finalTask = await waitForTask(config, submitted.taskId);
  const ok = finalTask.task?.status === 'success';
  return {
    ok,
    taskId: submitted.taskId,
    submitted: submitted.payload,
    ...publicTaskResult(finalTask.task),
    error: ok ? '' : (finalTask.task?.result?.error || finalTask.task?.error || ''),
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
  const status = payload?.data || payload;
  assertConfigServerReady(status);
  return status;
}

function assertConfigServerReady(status) {
  const value = status?.configServerRunning ?? status?.lanConfigEnabled ?? status?.lanServerRunning;
  if (value === false) {
    throw new PhoneBridgeError(
      'phone_config_server_disabled',
      'APKClaw 局域网服务未启动。请打开 APKClaw -> Settings -> LAN Config，并开启局域网配置。',
      {
        retryable: true,
        currentStep: 'preflight',
        details: {
          configServerRunning: status?.configServerRunning,
          lanConfigEnabled: status?.lanConfigEnabled,
          lanServerRunning: status?.lanServerRunning,
        },
      },
    );
  }
}

async function assertReadyForAgent(config) {
  let status;
  try {
    status = await probeDeviceStatus(config);
  } catch (error) {
    if (error instanceof PhoneBridgeError || error?.errorCode) throw error;
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

function firstNonEmpty(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function hasPhoneLlmConfig(config) {
  const llm = config?.phoneLlm || {};
  return Boolean(firstNonEmpty(llm.baseUrl) && firstNonEmpty(llm.apiKey) && firstNonEmpty(llm.model));
}

function publicPhoneLlmConfig(config) {
  const llm = config?.phoneLlm || {};
  return {
    configured: hasPhoneLlmConfig(config),
    baseUrlConfigured: Boolean(firstNonEmpty(llm.baseUrl)),
    apiKeyConfigured: Boolean(firstNonEmpty(llm.apiKey)),
    model: firstNonEmpty(llm.model),
    source: llm.source || '',
  };
}

async function importPhoneLlmConfig(config) {
  if (!hasPhoneLlmConfig(config)) {
    return { ok: false, skipped: true, reason: 'missing_phone_llm_config' };
  }
  try {
    const llm = config.phoneLlm;
    const payload = await signedJsonRequest(
      config,
      'POST',
      '/api/lumi/config/llm/import',
      {
        baseUrl: llm.baseUrl,
        apiKey: llm.apiKey,
        model: llm.model,
      },
      config.stepTimeoutSec * 1000,
    );
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

export async function probeFastPathReadyStatus(config) {
  let status;
  try {
    status = await probeDeviceStatus(config);
  } catch (error) {
    if (error instanceof PhoneBridgeError || error?.errorCode) throw error;
    throw new Error(`device_offline: ${error?.message || error}`);
  }
  assertKnownReadyForFastPath(status);
  return status;
}

function assertKnownReadyForFastPath(status) {
  const stop = earlyStopReason(status, { requireModel: false });
  if (stop) {
    throw new Error(`${stop.code}: ${stop.message}`);
  }
}

function actionFastPlan(config, body, template) {
  return {
    kind: 'action',
    mode: 'action_fast',
    executionLayer: template ? 'template' : 'direct',
    templateName: config.templateName || '',
    endpoint: '/api/lumi/agent/action_fast?_lumi=1',
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
  const stalePossible = plan.kind === 'observe' || plan.kind === 'screenshot';
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
    stalePossible,
    freshness: {
      stalePossible,
      reason: stalePossible ? '读屏/截图允许并发，结果可能与正在执行的写动作存在短暂差异。' : '',
    },
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
  const errorCode = error?.errorCode || error?.code || message.match(/^([a-z][a-z0-9_:-]{2,64}):/i)?.[1]?.replace(/[:-]+$/, '') || 'fast_path_failed';
  return {
    ok: false,
    errorCode,
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
    stalePossible: plan.kind === 'observe' || plan.kind === 'screenshot',
    payload: null,
    data: { error: message, errorCode },
    error: message,
  };
}

function isLumiAuthFailureMessage(message) {
  return /(invalid lumi signature|invalid signature|unauthorized|forbidden|auth(?:entication|orization)?)/i.test(String(message || ''));
}

async function submitTask(config) {
  const payload = await signedJsonRequest(config, 'POST', '/api/lumi/agent/tasks', taskBody(config), config.stepTimeoutSec * 1000);
  const data = payload?.data || payload;
  const taskId = data?.taskId || data?.id;
  if (!taskId) throw new Error('APKClaw did not return a task id.');
  return { payload, taskId };
}

async function getTask(config, taskId, signal = undefined) {
  return signedJsonRequest(
    config,
    'GET',
    `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}`,
    undefined,
    config.stepTimeoutSec * 1000,
    true,
    { signal },
  );
}

async function cancelRemoteTask(config, taskId) {
  await signedJsonRequest(
    config,
    'POST',
    `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}/cancel`,
    {},
    Math.min(3_000, config.stepTimeoutSec * 1000),
  );
}

async function waitForTask(config, taskId) {
  const startedAt = Date.now();
  const maxWaitMs = Math.max(1, config.maxWaitSec) * 1000;
  let lastStatus = null;
  let lastPollError = null;
  let consecutivePollFailures = 0;
  let totalPollFailures = 0;
  let pollAttempt = 0;
  while (Date.now() - startedAt < maxWaitMs) {
    if (await cancellationRequested(config.cancelFile)) {
      await cancelRemoteTask(config, taskId);
      return {
        payload: null,
        task: { taskId, status: 'cancelled', error: 'cancelled' },
      };
    }
    const delayMs = adaptivePollDelayMs(pollAttempt, config.pollMs);
    pollAttempt += 1;
    if (delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
    if (await cancellationRequested(config.cancelFile)) {
      await cancelRemoteTask(config, taskId);
      return {
        payload: null,
        task: { taskId, status: 'cancelled', error: 'cancelled' },
      };
    }
    const pollController = new AbortController();
    const taskPoll = getTask(config, taskId, pollController.signal)
      .then((payload) => ({ type: 'task', payload }))
      .catch((error) => {
        if (pollController.signal.aborted && error?.code === 'phone_request_cancelled') {
          return { type: 'poll_cancelled', payload: null };
        }
        throw error;
      });
    const cancellationPoll = waitForCancellation(config.cancelFile, pollController.signal)
      .then((cancelled) => ({ type: cancelled ? 'cancel' : 'watch_stopped', payload: null }));
    let outcome;
    try {
      outcome = await Promise.race([taskPoll, cancellationPoll]);
      if (outcome.type === 'cancel') {
        pollController.abort();
        await taskPoll;
        await cancelRemoteTask(config, taskId);
        return {
          payload: null,
          task: { taskId, status: 'cancelled', error: 'cancelled' },
        };
      }
    } catch (error) {
      consecutivePollFailures += 1;
      totalPollFailures += 1;
      lastPollError = {
        errorCode: String(error?.errorCode || error?.code || 'phone_task_poll_failed'),
        message: String(error?.message || 'Phone task status poll failed').slice(0, 300),
      };
      if (isRetryableTaskPollError(error) && consecutivePollFailures < 4) {
        continue;
      }
      throw error;
    } finally {
      pollController.abort();
    }
    const payload = outcome.payload;
    const data = payload?.data || payload;
    lastStatus = data;
    consecutivePollFailures = 0;
    if (['success', 'error', 'cancelled'].includes(data?.status)) {
      return { payload, task: data };
    }
  }
  throw new PhoneBridgeError(
    'timeout',
    `Timed out waiting for APKClaw task after ${config.maxWaitSec}s`,
    {
      retryable: true,
      currentStep: 'wait_task',
      details: {
        taskId,
        lastStatus: lastStatus?.status || 'unknown',
        lastPollError,
        totalPollFailures,
        executionMayContinue: true,
      },
    },
  );
}

function isRetryableTaskPollError(error) {
  const code = String(error?.errorCode || error?.code || '');
  if (error?.retryable === false) return false;
  return !new Set([
    'auth_failed',
    'missing_phone_url',
    'missing_phone_token',
    'phone_config_server_disabled',
    'phone_request_cancelled',
  ]).has(code);
}

export async function cancellationRequested(cancelFile) {
  if (!cancelFile) return false;
  try {
    await fs.access(cancelFile);
    return true;
  } catch {
    return false;
  }
}

export function cancelledPhoneCommandResult(config = {}) {
  return {
    ok: false,
    success: false,
    cancelled: true,
    error: 'cancelled',
    errorCode: 'cancelled',
    currentStep: 'cancelled',
    executionLayer: config.executionLayer || 'agent',
  };
}

async function waitForCancellation(cancelFile, signal) {
  while (!signal?.aborted) {
    if (await cancellationRequested(cancelFile)) return true;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return false;
}

function adaptivePollDelayMs(attempt, pollCapMs) {
  if (attempt <= 0) return 0;
  const schedule = [500, 800, 1200];
  const scheduled = schedule[Math.min(attempt - 1, schedule.length - 1)];
  const cap = Math.max(500, Math.min(1200, Number(pollCapMs) || 1200));
  return Math.min(scheduled, cap);
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

function parseSseFrame(frame) {
  const event = {
    id: '',
    event: 'message',
    retry: undefined,
    data: '',
  };
  const dataLines = [];
  for (const rawLine of String(frame || '').split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(':')) continue;
    const colon = rawLine.indexOf(':');
    const field = colon >= 0 ? rawLine.slice(0, colon) : rawLine;
    let value = colon >= 0 ? rawLine.slice(colon + 1) : '';
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'id') event.id = value;
    else if (field === 'event') event.event = value || 'message';
    else if (field === 'retry') event.retry = Number.parseInt(value, 10);
    else if (field === 'data') dataLines.push(value);
  }
  if (!event.id && !event.event && dataLines.length === 0) return null;
  const dataText = dataLines.join('\n');
  event.data = dataText;
  if (dataText.trim()) {
    try {
      event.data = JSON.parse(dataText);
    } catch {
      event.data = dataText;
    }
  }
  return event;
}

function extractSseFrames(buffer) {
  const frames = [];
  let rest = buffer;
  while (true) {
    const match = /\r?\n\r?\n/.exec(rest);
    if (!match) break;
    frames.push(rest.slice(0, match.index));
    rest = rest.slice(match.index + match[0].length);
  }
  return { frames, rest };
}

async function readSseChunksWithDeadline(response, config, onEvent) {
  if (!response.body || typeof response.body.getReader !== 'function') {
    throw new Error('Phone event stream does not expose a readable body');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventCount = 0;
  const startedAt = Date.now();
  const deadline = startedAt + config.maxSec * 1000;
  const stop = (stoppedBy) => ({ ok: true, eventCount, elapsedMs: Date.now() - startedAt, stoppedBy });
  try {
    while (true) {
      const remainingMs = deadline - Date.now();
      if (remainingMs <= 0) {
        await reader.cancel();
        return stop('max_sec');
      }
      const readResult = await Promise.race([
        reader.read(),
        new Promise((resolve) => setTimeout(() => resolve({ timeout: true }), remainingMs)),
      ]);
      if (readResult?.timeout) {
        await reader.cancel();
        return stop('max_sec');
      }
      if (readResult.done) break;
      buffer += decoder.decode(readResult.value, { stream: true });
      const parsed = extractSseFrames(buffer);
      buffer = parsed.rest;
      for (const frame of parsed.frames) {
        const event = parseSseFrame(frame);
        if (!event || (!event.id && event.event === 'message' && !event.data)) continue;
        eventCount += 1;
        onEvent(event);
        if (config.maxEvents > 0 && eventCount >= config.maxEvents) {
          await reader.cancel();
          return stop('max_events');
        }
      }
    }
  } finally {
    const tail = decoder.decode();
    if (tail) buffer += tail;
    try {
      reader.releaseLock();
    } catch {
      // Some runtimes keep the reader locked after cancel; the stream is already closing.
    }
  }
  return stop('eof');
}
