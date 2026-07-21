import React from 'react';
import { Camera, CheckCircle2, Copy, KeyRound, PlayCircle, Plus, RefreshCcw, Save, ShieldCheck, Smartphone, StopCircle, Trash2, Unlock } from 'lucide-react';
import { Button, Chip, EmptyState, Field, Input, InlineState, Modal, Panel, SectionHeader, Select, Tabs, TextArea, Toggle } from '../components/ui';
import { formatDateTime, maskSecret } from '../lib/format';
import { loadDesktopModelConfig, readConfigValue, requestBridgeData, requestPhoneData, writeConfigValue } from '../api/adapters';
import { clearPhoneSecurePairing, isTauriRuntime, resolveBridgeBaseUrl, warmPhoneSecurePairing, type PhonePairingSummary } from '../api/client';
import { displayPhoneBaseUrl, normalizeOrCleanPhoneBaseUrl, normalizePhoneBaseUrl } from '../lib/phoneUrl';
import {
  PHONE_AUTOMATION_CONFIG_PATH,
  applyTemplateVariables,
  automationRiskLabel,
  automationRiskTone,
  automationStatusLabel,
  automationStatusTone,
  createAutomationId,
  createDefaultAutomationState,
  normalizeAutomationState,
  readCachedAutomationState,
  writeCachedAutomationState,
  type AutomationLogStatus,
  type AutomationRunLog,
  type AutomationRunMode,
  type AutomationSchedule,
  type AutomationTemplate,
  type PhoneAutomationState,
} from '../lib/phoneAutomation';
import { usePreviewStore } from '../store/appStore';
import { translatePhoneError } from '../lib/errors';
import QRCode from 'qrcode';

// 手机端 App(APKClaw)下载地址。更新 apk 时只改这一行;
// 建议 Gitee 上用固定文件名(如 OpenClaw-AgentPhone.apk)让链接永久不变,二维码一劳永逸。
const PHONE_APK_DOWNLOAD_URL =
  'https://gitee.com/rfdiosuao/lumiapkclaw/releases/download/lumiclaw13241/OpenClaw-AgentPhone.apk';

interface PhoneDevice {
  id: string;
  name: string;
  baseUrl: string;
  token: string;
  relayBaseUrl?: string;
  relayChannelId?: string;
  relayToken?: string;
  enabled?: boolean;
  tags?: string[];
  online?: boolean;
  active?: boolean;
  lastSeenAt?: string;
  lastAuthorizedAt?: string;
}

interface PhoneSnapshot {
  status: any;
  screenshotUrl: string;
  profile: any;
  vision: any;
  tree: any;
  recordings: any[];
  recordStatus: any;
  agentTask: any;
}

type TaskLogTone = 'info' | 'ok' | 'warn' | 'danger';

interface TaskLogEntry {
  id: string;
  at: string;
  tone: TaskLogTone;
  title: string;
  detail?: string;
}

interface AuthState {
  tone: 'neutral' | 'ok' | 'warn' | 'danger';
  title: string;
  detail?: string;
  pairing?: PhonePairingSummary;
}

const PHONE_AGENT_PATH = 'data/.openclaw/launcher/phone-agent.json';
const PHONE_AGENTS_PATH = 'data/.openclaw/launcher/phone-agents.json';
const TERMINAL_TASK_STATES = new Set(['success', 'error', 'cancelled', 'canceled']);
const CORE_SNAPSHOT_TIMEOUT_MS = 7000;
const EXTRA_SNAPSHOT_TIMEOUT_MS = 2200;
const PHONE_AGENT_TASK_TIMEOUT_SEC = 600;
const PHONE_AGENT_TASK_MAX_ROUNDS = 60;
const PHONE_AGENT_TASK_POLL_SECONDS = PHONE_AGENT_TASK_TIMEOUT_SEC + 20;
const FLEET_CONCURRENCY = 2;

interface FleetRun {
  id: number;
  deviceId: string;
  deviceName: string;
  status: 'queued' | 'running' | 'success' | 'error' | 'cancelled';
  detail?: string;
}

type AutomationTab = 'library' | 'schedules' | 'logs';

interface ScheduleDraft {
  label: string;
  templateId: string;
  deviceIds: string[];
  cadence: string;
  timeWindow: string;
  mode: AutomationRunMode;
  enabled: boolean;
  allowUnattended: boolean;
}

interface SchedulerStatus {
  running?: boolean;
  pollSeconds?: number;
  scheduleCount?: number;
  lastTick?: {
    checkedAt?: string;
    enqueued?: unknown[];
    skipped?: unknown[];
  };
}

const MOCK_STATE_STORAGE_KEY = 'ui-redesign-preview.mock-state';

// Read the locally-cached device inventory directly (no mock module import), so
// the phone page can seed instantly without pulling the heavy mock bundle.
function readCachedPhoneInventory(): { selectedDeviceId: string | null; devices: any[] } {
  try {
    const parsed = JSON.parse(localStorage.getItem(MOCK_STATE_STORAGE_KEY) || '{}');
    return {
      selectedDeviceId: parsed?.phone?.selectedDeviceId || null,
      devices: Array.isArray(parsed?.phone?.devices) ? parsed.phone.devices : [],
    };
  } catch {
    return { selectedDeviceId: null, devices: [] };
  }
}

function shouldSyncAutomationDefaults(saved: unknown): boolean {
  if (!saved || typeof saved !== 'object') return true;
  const rawTemplates = Array.isArray((saved as Partial<PhoneAutomationState>).templates)
    ? (saved as Partial<PhoneAutomationState>).templates || []
    : [];
  const savedIds = new Set(rawTemplates.map((item) => (item as AutomationTemplate)?.id).filter(Boolean));
  return createDefaultAutomationState().templates.some((template) => !savedIds.has(template.id));
}

function createEmptySnapshot(): PhoneSnapshot {
  return {
    status: null,
    screenshotUrl: '',
    profile: null,
    vision: null,
    tree: null,
    recordings: [],
    recordStatus: null,
    agentTask: null,
  };
}

// Module-level snapshot cache so revisiting the phone page (it unmounts on
// navigation) shows the last device snapshot instantly instead of re-running
// the heavy probe+snapshot sequence and blocking with a spinner. Within the TTL
// the network is skipped entirely; past it we show the cached snapshot and
// refresh in the background.
const PHONE_SNAPSHOT_TTL_MS = 15000;
const phoneSnapshotCache = new Map<string, { snapshot: PhoneSnapshot; at: number }>();

// Parse a phone pairing code into {baseUrl, token, name}. The APKClaw「电脑配对」
// screen shows a QR + code; both encode the phone's own connection info so the
// desktop can fill the form in one paste instead of typing IP/port/Token.
// Accepts: lumi://pair?b=&t=&n= , base64url(JSON{b,t,n}) , or raw JSON.
function parsePairCode(raw: string): { baseUrl: string; token: string; name?: string } | null {
  const code = (raw || '').trim();
  if (!code) return null;
  const pick = (obj: Record<string, any>) => {
    const baseUrl = String(obj.b || obj.baseUrl || obj.url || '').trim();
    const token = String(obj.t || obj.token || '').trim();
    const name = String(obj.n || obj.name || '').trim();
    return baseUrl && token ? { baseUrl, token, name: name || undefined } : null;
  };
  try {
    if (code.toLowerCase().startsWith('lumi://pair')) {
      const q = new URLSearchParams(code.slice(code.indexOf('?') + 1));
      return pick(Object.fromEntries(q.entries()));
    }
    try {
      let b64 = code.replace(/-/g, '+').replace(/_/g, '/');
      while (b64.length % 4) b64 += '=';
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      return pick(JSON.parse(new TextDecoder().decode(bytes)));
    } catch {
      return pick(JSON.parse(code));
    }
  } catch {
    return null;
  }
}

function defaultDevice(baseUrl = '', token = ''): PhoneDevice {
  return {
    id: 'primary-phone',
    name: '主 APKClaw 设备',
    baseUrl: normalizePhoneBaseUrl(baseUrl),
    token,
    relayBaseUrl: '',
    relayChannelId: '',
    relayToken: '',
    enabled: true,
    tags: ['primary'],
    online: false,
    active: true,
  };
}

function createPhoneDeviceDraft(existing: PhoneDevice[]): PhoneDevice {
  const used = new Set(existing.map((item) => item.id));
  let id = `phone-${Date.now().toString(36)}`;
  let counter = 2;
  while (used.has(id)) {
    id = `phone-${Date.now().toString(36)}-${counter}`;
    counter += 1;
  }
  return {
    id,
    name: 'APKClaw 设备',
    baseUrl: '',
    token: '',
    relayBaseUrl: '',
    relayChannelId: '',
    relayToken: '',
    enabled: true,
    tags: [],
    online: false,
    active: true,
  };
}

function snapshotRequest<T>(promise: Promise<T>, label: string, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(`${label} timeout after ${timeoutMs}ms`)), timeoutMs);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function hasVisibleSnapshot(snapshot: PhoneSnapshot) {
  return Boolean(snapshot.status || snapshot.screenshotUrl || snapshot.profile || snapshot.vision);
}

function formatBattery(profile: any) {
  const level = profile?.battery?.level ?? profile?.batteryLevel ?? profile?.batteryPercent;
  const numeric = Number(level);
  return Number.isFinite(numeric) ? `${Math.round(numeric)}%` : '暂无';
}

function nowIso() {
  return new Date().toISOString();
}

function terminalTaskStatus(value: unknown): boolean {
  return TERMINAL_TASK_STATES.has(String(value || '').toLowerCase());
}

function taskEvents(task: any): any[] {
  if (Array.isArray(task?.events)) return task.events;
  if (Array.isArray(task?.result?.events)) return task.result.events;
  return [];
}

function formatAgentEvent(event: any, index: number): { title: string; detail?: string; tone: TaskLogTone } {
  const type = String(event?.type || event?.event || `step_${index + 1}`);
  const round = event?.round != null ? `R${event.round} ` : '';
  const tool = event?.toolName || event?.tool_id || event?.toolId;
  const message = event?.message || event?.answer || event?.error || event?.parameters || '';
  const success = event?.success;
  return {
    title: `${round}${tool ? `${tool}` : type}`,
    detail: typeof message === 'string' ? message : JSON.stringify(message),
    tone: success === false || type.toLowerCase().includes('error') ? 'danger' : success === true ? 'ok' : 'info',
  };
}

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error || 'unknown_error');
}

function isLumiRepairError(message: string): boolean {
  const lower = message.toLowerCase();
  return lower.includes('lumi_signature_repair_failed') || lower.includes('invalid lumi signature') || lower.includes('unknown lumi launcher') || lower.includes('missing lumi security headers');
}

function authErrorHelp(message: string): string {
  const lower = message.toLowerCase();
  if (lower.includes('missing_token')) return '缺少 APKClaw Token。请在手机端查看控制台令牌并填入。';
  if (lower.includes('invalid_phone_base_url') || lower.includes('invalid url') || lower.includes('ipv4')) return '手机地址格式不正确。局域网地址应类似 http://192.168.1.4:9527。';
  if (lower.includes('lumi_signature_repair_failed') || lower.includes('invalid lumi signature')) return 'Lumi 安全签名修复失败。启动器已尝试重新配对仍未通过；请确认电脑和手机时间一致，手机端 APKClaw 服务仍是最新版本，然后点击“重新配对”。';
  if (lower.includes('lumi body hash mismatch')) return 'Lumi 请求体校验失败。通常是任务内容在代理转发时被改写；请重新提交任务，若仍失败请升级启动器和 APKClaw。';
  if (lower.includes('lumi request timestamp') || lower.includes('invalid lumi timestamp')) return 'Lumi 时间戳校验失败。请把电脑和手机时间同步到自动网络时间后再重试。';
  if (lower.includes('lumi nonce has already been used')) return 'Lumi 防重放校验触发。请稍等几秒后重新提交任务。';
  if (lower.includes('missing lumi security headers') || lower.includes('unknown lumi launcher') || lower.includes('lumi_pair_failed')) return '安全配对失败或已失效。请确认 APKClaw 版本支持 Lumi 安全通道，然后点击“重新配对”。';
  if (lower.includes('401') || lower.includes('unauthorized')) return 'Token 无效。请重新复制手机端显示的令牌。';
  if (lower.includes('failed to fetch') || lower.includes('sending request') || lower.includes('network')) return '无法访问手机服务。确认电脑和手机在同一网络，APKClaw 控制服务正在运行。';
  return message;
}

// 任务执行模式（给新手看的中文措辞）。底层 payload 仍用原值，不改。
// 只演练 → read_only=true（只读屏、不点击改状态）
// 执行但需确认 → tool_policy 'safe_action'（默认，遇敏感动作停在确认前）
// 自动执行 → force_agent=true（放手让 Agent 连续执行）
type TaskRunMode = 'dryRun' | 'confirm' | 'auto';

const TASK_RUN_MODE_OPTIONS: Array<{ value: TaskRunMode; label: string; hint: string }> = [
  { value: 'dryRun', label: '只演练', hint: '只读屏、不点击，先看看会怎么做' },
  { value: 'confirm', label: '执行但需确认', hint: '正常执行，遇到敏感动作停在确认前' },
  { value: 'auto', label: '自动执行', hint: '放手连续执行，适合熟悉后的常规任务' },
];

function taskRunModePayload(mode: TaskRunMode): { use_template: boolean; force_agent: boolean; read_only: boolean; tool_policy: string } {
  switch (mode) {
    case 'dryRun':
      return { use_template: true, force_agent: false, read_only: true, tool_policy: 'safe_action' };
    case 'auto':
      return { use_template: true, force_agent: true, read_only: false, tool_policy: 'safe_action' };
    case 'confirm':
    default:
      return { use_template: true, force_agent: false, read_only: false, tool_policy: 'safe_action' };
  }
}

function fleetStatusLabel(status: FleetRun['status']): string {
  switch (status) {
    case 'queued': return '排队中';
    case 'running': return '执行中';
    case 'success': return '成功';
    case 'cancelled': return '已取消';
    default: return '失败';
  }
}

function createScheduleDraft(deviceId?: string | null): ScheduleDraft {
  return {
    label: '每天上午擦亮闲鱼商品',
    templateId: 'xianyu-polish',
    deviceIds: deviceId ? [deviceId] : [],
    cadence: '每天 09:30',
    timeWindow: '09:00-10:30',
    mode: 'dry-run',
    enabled: true,
    allowUnattended: false,
  };
}

function cloneTemplate(template: AutomationTemplate): AutomationTemplate {
  return {
    ...template,
    tags: [...template.tags],
    variables: template.variables.map((item) => ({ ...item })),
  };
}

function createCustomTemplateDraft(): AutomationTemplate {
  return {
    id: createAutomationId('custom-template'),
    packId: 'generic',
    title: '自定义任务',
    description: '',
    appName: '任意应用',
    mode: 'dry-run',
    riskLevel: 'low',
    enabled: true,
    requiresManualConfirmation: false,
    tags: ['自定义'],
    variables: [],
    prompt: '',
    updatedAt: nowIso(),
  };
}

export function PhonePage() {
  const settings = usePreviewStore((state) => state.settings);
  const updateSettings = usePreviewStore((state) => state.updateSettings);
  const selectedPhoneId = usePreviewStore((state) => state.selectedPhoneId);
  const setSelectedPhoneId = usePreviewStore((state) => state.setSelectedPhoneId);
  const pushToast = usePreviewStore((state) => state.pushToast);
  // Best-effort instant seed from the locally-cached inventory, read inline so
  // the heavy mock module stays out of the production bundle. The config-load
  // effect below is the source of truth and corrects this on mount.
  const initialInventory = React.useMemo(() => readCachedPhoneInventory(), []);
  const [devices, setDevices] = React.useState<PhoneDevice[]>(() => initialInventory.devices.map((item: any, index: number) => normalizePhoneDevice(item, `mock-${index + 1}`)).filter(Boolean) as PhoneDevice[]);
  const [snapshot, setSnapshot] = React.useState<PhoneSnapshot>(() => createEmptySnapshot());
  const [selectedId, setSelectedId] = React.useState<string | null>(selectedPhoneId || initialInventory.selectedDeviceId || devices[0]?.id || null);
  const [deviceDraft, setDeviceDraft] = React.useState<PhoneDevice>(() => devices[0] || defaultDevice(settings.phoneBaseUrl, settings.phoneToken));
  const [configOpen, setConfigOpen] = React.useState(false);
  const [pairCode, setPairCode] = React.useState('');
  const [syncingModel, setSyncingModel] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [checkingDevice, setCheckingDevice] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [authState, setAuthState] = React.useState<AuthState>({ tone: 'neutral', title: '等待授权检查' });
  const [apkModalOpen, setApkModalOpen] = React.useState(false);
  const [apkQrDataUrl, setApkQrDataUrl] = React.useState('');

  // 任务执行模式（只演练/执行但需确认/自动执行）。底层值仍走 taskRunModePayload。
  const [taskRunMode, setTaskRunMode] = React.useState<TaskRunMode>('confirm');
  // 高级诊断折叠块（默认收起）。
  const [advancedOpen, setAdvancedOpen] = React.useState(false);
  // 一键修复连接的运行状态与最终结论。
  const [repairRunning, setRepairRunning] = React.useState(false);
  const [repairResult, setRepairResult] = React.useState<{ tone: 'ok' | 'warn' | 'danger'; title: string; detail?: string } | null>(null);
  // 新增设备时高亮配置区。
  const [addingDevice, setAddingDevice] = React.useState(false);
  const configSectionRef = React.useRef<HTMLDivElement | null>(null);

  // 统一的手机错误提示：友好标题 + 下一步，原始报错放进“复制诊断”。
  const pushPhoneError = React.useCallback((err: unknown, fallbackTitle?: string) => {
    const f = translatePhoneError(err);
    pushToast({ tone: 'danger', title: fallbackTitle || f.title, detail: f.hint, diagnostic: f.diagnostic, logRoute: f.logRoute });
    return f;
  }, [pushToast]);

  React.useEffect(() => {
    if (!apkModalOpen) return;
    let cancelled = false;
    QRCode.toDataURL(PHONE_APK_DOWNLOAD_URL, { width: 240, margin: 1 })
      .then((url) => { if (!cancelled) setApkQrDataUrl(url); })
      .catch(() => { if (!cancelled) setApkQrDataUrl(''); });
    return () => { cancelled = true; };
  }, [apkModalOpen]);

  const [actionPrompt, setActionPrompt] = React.useState('读取当前屏幕，判断下一步可以安全执行的动作。');
  const [sending, setSending] = React.useState(false);
  const [activeTaskId, setActiveTaskId] = React.useState('');
  const [taskLogs, setTaskLogs] = React.useState<TaskLogEntry[]>([]);
  const initialAutomationState = React.useMemo(() => readCachedAutomationState(), []);
  const automationStateRef = React.useRef<PhoneAutomationState>(initialAutomationState);
  const automationTimersRef = React.useRef<number[]>([]);
  const [automationState, setAutomationState] = React.useState<PhoneAutomationState>(initialAutomationState);
  const [automationLoaded, setAutomationLoaded] = React.useState(false);
  const [automationTab, setAutomationTab] = React.useState<AutomationTab>('library');
  const [templateDraft, setTemplateDraft] = React.useState<AutomationTemplate | null>(null);
  const [scheduleDraft, setScheduleDraft] = React.useState<ScheduleDraft>(() => createScheduleDraft(selectedPhoneId || initialInventory.selectedDeviceId || devices[0]?.id || null));
  const [schedulerStatus, setSchedulerStatus] = React.useState<SchedulerStatus | null>(null);
  const [schedulerBusy, setSchedulerBusy] = React.useState(false);
  const [automationRunning, setAutomationRunning] = React.useState(false);
  const [fleetTargetIds, setFleetTargetIds] = React.useState<string[]>([]);
  const [fleetRuns, setFleetRuns] = React.useState<FleetRun[]>([]);
  const [fleetRunning, setFleetRunning] = React.useState(false);
  const [fleetCancelling, setFleetCancelling] = React.useState(false);
  const fleetCancelRef = React.useRef(false);
  const fleetRunSeqRef = React.useRef(0);
  const fleetInFlightRef = React.useRef<Map<number, { device: PhoneDevice; taskId: string }>>(new Map());
  const taskRunRef = React.useRef(0);
  const selectedDeviceRef = React.useRef<PhoneDevice | null>(null);
  const refreshRunRef = React.useRef(0);
  const refreshInFlightRef = React.useRef(false);
  const taskBusyRef = React.useRef(false);

  // Mock mode is only ever entered explicitly or in non-Tauri web preview; the
  // real desktop app stays 'live'. Keep the mock device-store sync gated to mock
  // mode and lazy-loaded so the ~969-line mock module stays out of the live
  // first-load bundle.
  const mockMode =
    settings.transportMode === 'mock' ||
    (settings.transportMode === 'auto' && !isTauriRuntime() && !resolveBridgeBaseUrl(settings.bridgeBaseUrl));

  const upsertMockPhoneDevice = React.useCallback((device: PhoneDevice | Record<string, any>) => {
    if (!mockMode) return;
    void import('../api/mock').then((mock) => mock.upsertMockPhoneDevice(device)).catch(() => undefined);
  }, [mockMode]);
  const setMockPhoneSelection = React.useCallback((deviceId: string | null) => {
    if (!mockMode) return;
    void import('../api/mock').then((mock) => mock.setMockPhoneSelection(deviceId)).catch(() => undefined);
  }, [mockMode]);
  const removeMockPhoneDevice = React.useCallback((deviceId: string) => {
    if (!mockMode) return;
    void import('../api/mock').then((mock) => mock.removeMockPhoneDevice(deviceId)).catch(() => undefined);
  }, [mockMode]);

  const draftPersisted = Boolean(deviceDraft.id && devices.some((device) => device.id === deviceDraft.id));
  const selectedDevice = selectedId ? devices.find((device) => device.id === selectedId) || null : null;

  React.useEffect(() => {
    selectedDeviceRef.current = selectedDevice;
  }, [selectedDevice]);

  const addTaskLog = React.useCallback((tone: TaskLogTone, title: string, detail?: string) => {
    setTaskLogs((items) => [
      ...items,
      { id: `${Date.now()}-${Math.random().toString(16).slice(2)}`, at: nowIso(), tone, title, detail },
    ].slice(-120));
  }, []);

  const commitAutomationState = React.useCallback((updater: (current: PhoneAutomationState) => PhoneAutomationState) => {
    const next = normalizeAutomationState({
      ...updater(automationStateRef.current),
      updatedAt: nowIso(),
    });
    automationStateRef.current = next;
    setAutomationState(next);
    writeCachedAutomationState(next);
    void writeConfigValue(settings, PHONE_AUTOMATION_CONFIG_PATH, next).catch((err) => {
      addTaskLog('warn', '自动化配置暂未写入桥接', errorText(err));
    });
    return next;
  }, [settings, addTaskLog]);

  React.useEffect(() => {
    let cancelled = false;
    async function loadAutomationState() {
      const fallback = readCachedAutomationState();
      try {
        const saved = await readConfigValue(settings, PHONE_AUTOMATION_CONFIG_PATH, fallback).catch(() => fallback);
        if (cancelled) return;
        const next = normalizeAutomationState(saved || fallback);
        automationStateRef.current = next;
        setAutomationState(next);
        writeCachedAutomationState(next);
        if (shouldSyncAutomationDefaults(saved)) {
          void writeConfigValue(settings, PHONE_AUTOMATION_CONFIG_PATH, next).catch(() => undefined);
        }
      } finally {
        if (!cancelled) setAutomationLoaded(true);
      }
    }
    loadAutomationState();
    return () => {
      cancelled = true;
    };
  }, [settings.bridgeBaseUrl, settings.bridgeToken, settings.transportMode]);

  React.useEffect(() => {
    return () => {
      automationTimersRef.current.forEach((timer) => window.clearTimeout(timer));
      automationTimersRef.current = [];
    };
  }, []);

  const refreshSchedulerStatus = React.useCallback(async () => {
    try {
      const response = await requestBridgeData<SchedulerStatus>(settings, '/api/phone-automation/scheduler/status');
      setSchedulerStatus(response.data || null);
    } catch {
      setSchedulerStatus(null);
    }
  }, [settings]);

  const runSchedulerCommand = React.useCallback(async (command: 'start' | 'stop' | 'tick') => {
    setSchedulerBusy(true);
    try {
      const response = await requestBridgeData<SchedulerStatus | { enqueued?: unknown[]; skipped?: unknown[] }>(
        settings,
        `/api/phone-automation/scheduler/${command}`,
        'POST',
        {},
      );
      if (command === 'tick') {
        pushToast({ tone: 'ok', title: '已检查计划' });
        await refreshSchedulerStatus();
      } else {
        setSchedulerStatus(response.data as SchedulerStatus);
        pushToast({ tone: 'ok', title: command === 'start' ? '调度器已启动' : '调度器已停止' });
      }
    } catch (error) {
      pushToast({ tone: 'danger', title: '调度器操作失败', detail: errorText(error) });
    } finally {
      setSchedulerBusy(false);
    }
  }, [settings, pushToast, refreshSchedulerStatus]);

  React.useEffect(() => {
    if (automationTab !== 'schedules') return;
    void refreshSchedulerStatus();
  }, [automationTab, refreshSchedulerStatus]);

  const updateDeviceRuntime = React.useCallback((deviceId: string, patch: Partial<PhoneDevice>) => {
    setDevices((items) => items.map((item) => (item.id === deviceId ? { ...item, ...patch } : item)));
    setDeviceDraft((state) => (state.id === deviceId ? { ...state, ...patch } : state));
  }, []);

  React.useEffect(() => {
    let cancelled = false;

    async function loadPersistedDevices() {
      try {
        const [store, single] = await Promise.all([
          readConfigValue(settings, PHONE_AGENTS_PATH, null).catch(() => null),
          readConfigValue(settings, PHONE_AGENT_PATH, null).catch(() => null),
        ]);
        const loaded = normalizePhoneInventory(store, single);
        if (cancelled) return;

        if (loaded.devices.length) {
          const nextSelected =
            loaded.devices.find((device) => device.id === (selectedPhoneId || loaded.selectedDeviceId)) ||
            loaded.devices[0];
          setDevices(loaded.devices);
          setSelectedId(nextSelected.id);
          setDeviceDraft(nextSelected);
          loaded.devices.forEach(upsertMockPhoneDevice);
          setMockPhoneSelection(nextSelected.id);
          if (settings.phoneBaseUrl !== nextSelected.baseUrl || settings.phoneToken !== nextSelected.token) {
            updateSettings({ phoneBaseUrl: nextSelected.baseUrl, phoneToken: nextSelected.token });
          }
          return;
        }

        if (settings.phoneBaseUrl.trim() && settings.phoneToken.trim()) {
          const migrated = normalizePhoneDevice({
            ...defaultDevice(settings.phoneBaseUrl, settings.phoneToken),
            name: '主 APKClaw 设备',
          }, 'primary-phone');
          if (!migrated) return;
          await savePhoneInventoryConfig(settings, [migrated], migrated.id);
          if (cancelled) return;
          setDevices([migrated]);
          setSelectedId(migrated.id);
          setDeviceDraft(migrated);
          upsertMockPhoneDevice(migrated);
          setMockPhoneSelection(migrated.id);
          pushToast({ tone: 'ok', title: '手机配置已迁移', detail: PHONE_AGENT_PATH });
          return;
        }

        setDevices([]);
        setSelectedId(null);
        setDeviceDraft(defaultDevice(settings.phoneBaseUrl, settings.phoneToken));
      } catch {
        if (!cancelled && !initialInventory.devices.length) {
          setDevices([]);
          setSelectedId(null);
        }
      }
    }

    loadPersistedDevices();
    return () => {
      cancelled = true;
    };
  }, [
    settings.bridgeBaseUrl,
    settings.bridgeToken,
    settings.transportMode,
    settings.phoneBaseUrl,
    settings.phoneToken,
    selectedPhoneId,
    updateSettings,
    pushToast,
    initialInventory.devices.length,
  ]);

  React.useEffect(() => {
    if (!selectedId && devices[0]) setSelectedId(devices[0].id);
  }, [devices, selectedId]);

  React.useEffect(() => {
    if (!selectedId) return;
    setSelectedPhoneId(selectedId);
    setMockPhoneSelection(selectedId);
    const next = devices.find((device) => device.id === selectedId);
    if (next) setDeviceDraft(next);
  }, [selectedId, devices, setSelectedPhoneId]);

  const selectDevice = React.useCallback(async (device: PhoneDevice) => {
    setSelectedId(device.id);
    setDeviceDraft(device);
    setSelectedPhoneId(device.id);
    setMockPhoneSelection(device.id);
    updateSettings({ phoneBaseUrl: device.baseUrl, phoneToken: device.token });
    setSnapshot(createEmptySnapshot());
    setError(null);
    setAuthState({ tone: device.lastAuthorizedAt ? 'ok' : 'neutral', title: device.lastAuthorizedAt ? '已保存安全配对' : '等待授权检查', detail: device.lastAuthorizedAt ? `最近验证 ${formatDateTime(device.lastAuthorizedAt)}` : undefined });
    try {
      await savePhoneInventoryConfig(settings, devices, device.id);
    } catch {
      // Selection is still useful locally even if the bridge is temporarily unavailable.
    }
  }, [devices, settings, setSelectedPhoneId, updateSettings]);

  const testDevice = React.useCallback(async (device: PhoneDevice, forcePair = false): Promise<PhoneDevice> => {
    const context = { baseUrl: device.baseUrl, token: device.token };
    const status = await requestPhoneData<any>(settings, context, '/api/device/status');
    const pairing = await warmPhoneSecurePairing(device.baseUrl, device.token, forcePair);
    await requestPhoneData(settings, context, '/api/lumi/device/profile?includeApps=false&appLimit=1', 'GET', undefined, { timeoutMs: 12_000 });
    const now = nowIso();
    setAuthState({
      tone: 'ok',
      title: 'Token 与 Lumi 安全通道已验证',
      detail: `Launcher ${pairing.launcherId.slice(0, 18)} · 过期 ${formatDateTime(pairing.expiresAt)}`,
      pairing,
    });
    return {
      ...device,
      online: Boolean((status.data as any)?.online ?? true),
      lastSeenAt: now,
      lastAuthorizedAt: now,
    };
  }, [settings]);

  const refresh = React.useCallback(async (_reason: 'auto' | 'manual' = 'manual') => {
    const device = selectedDeviceRef.current;
    if (!device) return;
    if (!device.baseUrl.trim() || !device.token.trim()) return;
    if (refreshInFlightRef.current) return;
    if (taskBusyRef.current) return;
    const runId = refreshRunRef.current + 1;
    refreshRunRef.current = runId;
    refreshInFlightRef.current = true;
    // Only block with a spinner on the very first load of a device; a revisit
    // already shows the cached snapshot and refreshes quietly in the background.
    if (!phoneSnapshotCache.has(device.id)) setLoading(true);
    setError(null);
    try {
      const context = { baseUrl: device.baseUrl, token: device.token };
      // 并发拉快照前,先用一个轻量探针把 Lumi 安全通道配好/自愈一次。
      // 否则下面那批并发签名请求会各自发现密钥失效(例如刚重装手机端 APKClaw、
      // 密钥被重置后)、各自抢着重新配对、互相清掉对方刚配好的密钥,刷出好几条
      // “任务失败”。先探针 → 内置重试只干净地重配一次 → 这批请求复用好密钥。
      try {
        // device/status 是 token 鉴权(手机时钟偏差也能通过),且携带 serverTime →
        // 先拿它把"手机↔电脑时钟偏差"记下来,后面的签名请求才能落在手机的时间窗口内,
        // 避免客户手机时间不准导致 Lumi 签名 403。
        await requestPhoneData(settings, context, '/api/device/status', 'GET', undefined, { timeoutMs: 12_000 });
        await warmPhoneSecurePairing(device.baseUrl, device.token);
        await requestPhoneData(
          settings,
          context,
          '/api/lumi/device/profile?includeApps=false&appLimit=1',
          'GET',
          undefined,
          { timeoutMs: 12_000 },
        );
      } catch {
        // 探针失败不阻断快照:基于 token 的 status/截图/screen_tree 仍可返回,
        // 真正的配对/时间问题会由下面的快照给出一条清晰错误。
      }
      const settled = await Promise.allSettled([
        snapshotRequest(requestPhoneData<any>(settings, context, '/api/device/status', 'GET', undefined, { timeoutMs: CORE_SNAPSHOT_TIMEOUT_MS }), '/api/device/status', CORE_SNAPSHOT_TIMEOUT_MS),
        snapshotRequest(requestPhoneData<any>(settings, context, '/api/tool/screenshot', 'GET', undefined, { timeoutMs: CORE_SNAPSHOT_TIMEOUT_MS }), '/api/tool/screenshot', CORE_SNAPSHOT_TIMEOUT_MS),
        snapshotRequest(requestPhoneData<any>(settings, context, '/api/lumi/device/profile?includeApps=true&appLimit=80', 'GET', undefined, { timeoutMs: CORE_SNAPSHOT_TIMEOUT_MS }), '/api/lumi/device/profile', CORE_SNAPSHOT_TIMEOUT_MS),
        snapshotRequest(requestPhoneData<any>(settings, context, '/api/lumi/vision/frame?_lumi=1', 'GET', undefined, { timeoutMs: CORE_SNAPSHOT_TIMEOUT_MS }), '/api/lumi/vision/frame', CORE_SNAPSHOT_TIMEOUT_MS),
        snapshotRequest(requestPhoneData<any>(settings, context, '/api/tool/screen_tree', 'GET', undefined, { timeoutMs: EXTRA_SNAPSHOT_TIMEOUT_MS }), '/api/tool/screen_tree', EXTRA_SNAPSHOT_TIMEOUT_MS),
        snapshotRequest(requestPhoneData<any>(settings, context, '/api/lumi/media/videos?_lumi=1', 'GET', undefined, { timeoutMs: EXTRA_SNAPSHOT_TIMEOUT_MS }), '/api/lumi/media/videos', EXTRA_SNAPSHOT_TIMEOUT_MS),
        snapshotRequest(requestPhoneData<any>(settings, context, '/api/lumi/media/record/status?_lumi=1', 'GET', undefined, { timeoutMs: EXTRA_SNAPSHOT_TIMEOUT_MS }), '/api/lumi/media/record/status', EXTRA_SNAPSHOT_TIMEOUT_MS),
      ]);
      if (refreshRunRef.current !== runId || selectedDeviceRef.current?.id !== device.id) return;
      const [status, screenshot, profile, vision, tree, recordings, recordStatus] = settled.map((item) => (item.status === 'fulfilled' ? item.value.data : null));
      const failures = settled
        .map((item) => (item.status === 'rejected' ? authErrorHelp(errorText(item.reason)) : ''))
        .filter(Boolean);
      const coreReady = Boolean(status || screenshot || profile || vision);

      setSnapshot((state) => {
        const next = {
          ...state,
          status: status || state.status,
          screenshotUrl: extractScreenshotUrl(screenshot) || extractScreenshotUrl(vision?.image) || state.screenshotUrl,
          profile: profile || state.profile,
          vision: vision || state.vision,
          tree: tree || state.tree,
          recordings: recordings?.recordings || state.recordings,
          recordStatus: recordStatus || state.recordStatus,
        };
        phoneSnapshotCache.set(device.id, { snapshot: next, at: Date.now() });
        return next;
      });

      if (status || profile || vision) {
        const now = nowIso();
        updateDeviceRuntime(device.id, { online: true, lastSeenAt: now, lastAuthorizedAt: profile || vision ? now : device.lastAuthorizedAt });
        setAuthState({
          tone: profile || vision ? 'ok' : 'warn',
          title: profile || vision ? '授权正常' : '基础连接正常，安全接口未完成',
          detail: failures[0],
        });
      }
      if (failures.length) {
        if (!coreReady) setError(failures[0]);
        addTaskLog('warn', coreReady ? '设备附加快照部分失败' : '设备快照读取失败', failures[0]);
      }
    } catch (err) {
      const message = authErrorHelp(errorText(err));
      setError(message);
      setAuthState({ tone: 'danger', title: '授权或连接失败', detail: message });
      updateDeviceRuntime(device.id, { online: false });
      addTaskLog('danger', '刷新失败', message);
    } finally {
      refreshInFlightRef.current = false;
      if (refreshRunRef.current === runId) setLoading(false);
    }
  }, [addTaskLog, settings, updateDeviceRuntime]);

  React.useEffect(() => {
    const dev = selectedDevice;
    if (!dev) return;
    const cached = phoneSnapshotCache.get(dev.id);
    if (cached) {
      // Show the last snapshot immediately so a revisit isn't blank/blocking.
      setSnapshot(cached.snapshot);
      setLoading(false);
      // Within the TTL, skip the network entirely — instant, no probe storm.
      if (Date.now() - cached.at < PHONE_SNAPSHOT_TTL_MS) return;
    }
    // Stale or first time: refresh (background if we already showed a cache).
    refresh('auto');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, selectedDevice?.id, selectedDevice?.baseUrl, selectedDevice?.token]);

  const runPhoneAction = async (label: string, path: string, body: Record<string, unknown> = {}) => {
    if (!selectedDevice) return null;
    try {
      const result = await requestPhoneData(settings, { baseUrl: selectedDevice.baseUrl, token: selectedDevice.token }, path, 'POST', body, { timeoutMs: 30_000 });
      pushToast({ tone: 'ok', title: label, detail: selectedDevice.name });
      addTaskLog('ok', label, selectedDevice.name);
      return result.data;
    } catch (err) {
      const f = pushPhoneError(err, `${label}失败`);
      addTaskLog('danger', `${label}失败`, `${f.title} · ${f.hint}`);
      return null;
    }
  };

  const handleCapture = async () => {
    if (!selectedDevice) return;
    try {
      const response = await requestPhoneData(settings, { baseUrl: selectedDevice.baseUrl, token: selectedDevice.token }, '/api/tool/screenshot', 'GET', undefined, { timeoutMs: 12_000 });
      const screenshotUrl = extractScreenshotUrl(response.data);
      if (!screenshotUrl) {
        pushToast({ tone: 'warn', title: '截图已返回但没有图片数据', detail: selectedDevice.name });
        addTaskLog('warn', '截图无图片数据', selectedDevice.name);
        return;
      }
      setSnapshot((state) => ({ ...state, screenshotUrl }));
      pushToast({ tone: 'ok', title: '截图已获取', detail: selectedDevice.name });
      addTaskLog('ok', '截图已获取', selectedDevice.name);
    } catch (err) {
      const f = pushPhoneError(err, '截图失败');
      addTaskLog('danger', '截图失败', `${f.title} · ${f.hint}`);
    }
  };

  const handleWake = async () => {
    await runPhoneAction('唤醒指令已发送', '/api/device/wake');
    refresh('manual');
  };

  const handleTask = async () => {
    if (!selectedDevice) return;
    if (sending) return;
    const prompt = actionPrompt.trim();
    if (!prompt) {
      pushToast({ tone: 'warn', title: '任务说明不能为空' });
      return;
    }
    const runId = taskRunRef.current + 1;
    const seenEvents = new Set<string>();
    taskRunRef.current = runId;
    taskBusyRef.current = true;
    refreshRunRef.current += 1;
    setLoading(false);
    setSending(true);
    setError(null);
    addTaskLog('info', '提交手机任务', prompt);
    try {
      const start = await requestPhoneData<any>(
        settings,
        { baseUrl: selectedDevice.baseUrl, token: selectedDevice.token },
        '/api/lumi/agent/tasks',
        'POST',
        {
          prompt,
          ...taskRunModePayload(taskRunMode),
          timeout_sec: PHONE_AGENT_TASK_TIMEOUT_SEC,
          max_rounds: PHONE_AGENT_TASK_MAX_ROUNDS,
        },
        { timeoutMs: 60_000 },
      );
      const taskId = extractTaskId(start.data);
      if (!taskId) throw new Error('APKClaw did not return a task id.');
      setActiveTaskId(taskId);
      setSnapshot((state) => ({ ...state, agentTask: { ...start.data, taskId, status: start.data?.status || 'running' } }));
      pushToast({ tone: 'ok', title: '任务已提交', detail: selectedDevice.name });
      addTaskLog('ok', '任务已提交', taskId);

      for (let i = 0; i < PHONE_AGENT_TASK_POLL_SECONDS; i += 1) {
        if (taskRunRef.current !== runId) return;
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const result = await requestPhoneData<any>(
          settings,
          { baseUrl: selectedDevice.baseUrl, token: selectedDevice.token },
          `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}`,
          'GET',
          undefined,
          { timeoutMs: 15_000 },
        );
        const task = result.data;
        setSnapshot((state) => ({ ...state, agentTask: task }));
        taskEvents(task).forEach((event, index) => {
          const key = `${event?.round || ''}:${event?.type || ''}:${event?.toolId || event?.toolName || ''}:${event?.message || ''}:${index}`;
          if (seenEvents.has(key)) return;
          seenEvents.add(key);
          const formatted = formatAgentEvent(event, index);
          addTaskLog(formatted.tone, formatted.title, formatted.detail);
        });
        if (terminalTaskStatus(task?.status)) {
          addTaskLog(task.status === 'success' ? 'ok' : task.status === 'cancelled' ? 'warn' : 'danger', `任务${task.status === 'success' ? '完成' : '结束'}`, task?.error || task?.result?.answer || taskId);
          return;
        }
      }
      addTaskLog('warn', '任务轮询超时', taskId);
    } catch (err) {
      const f = pushPhoneError(err, '任务失败');
      addTaskLog('danger', '任务失败', `${f.title} · ${f.hint}`);
    } finally {
      if (taskRunRef.current === runId) {
        setSending(false);
        setActiveTaskId('');
      }
      taskBusyRef.current = false;
    }
  };

  const handleCancelTask = async () => {
    if (!selectedDevice) return;
    const taskId = activeTaskId || extractTaskId(snapshot.agentTask);
    if (!taskId) return;
    taskRunRef.current += 1;
    taskBusyRef.current = true;
    setSending(false);
    setActiveTaskId('');
    addTaskLog('warn', '请求停止任务', taskId);
    try {
      const cancelled = await requestPhoneData(
        settings,
        { baseUrl: selectedDevice.baseUrl, token: selectedDevice.token },
        `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}/cancel`,
        'POST',
        {},
        { timeoutMs: 30_000 },
      );
      setSnapshot((state) => ({ ...state, agentTask: cancelled.data || { taskId, status: 'cancelled' } }));
      pushToast({ tone: 'warn', title: '任务已停止', detail: taskId.slice(0, 12) });
      addTaskLog('warn', '任务已停止', taskId);
    } catch (err) {
      const f = pushPhoneError(err, '停止任务失败');
      addTaskLog('danger', '停止任务失败', `${f.title} · ${f.hint}`);
    } finally {
      taskBusyRef.current = false;
    }
  };

  const toggleFleetTarget = React.useCallback((deviceId: string) => {
    setFleetTargetIds((current) =>
      current.includes(deviceId) ? current.filter((id) => id !== deviceId) : [...current, deviceId],
    );
  }, []);

  const handleCancelFleet = React.useCallback(async () => {
    if (!fleetCancelRef.current) {
      fleetCancelRef.current = true;
      setFleetCancelling(true);
      addTaskLog('warn', '正在停止群控批次…');
    }
    // 还没开跑的立即标记取消；在飞的逐个向手机发取消请求，让其轮询循环尽快结束。
    setFleetRuns((runs) => runs.map((run) => (run.status === 'queued' ? { ...run, status: 'cancelled', detail: '已取消' } : run)));
    const inflight = Array.from(fleetInFlightRef.current.values());
    await Promise.all(
      inflight.map(({ device, taskId }) =>
        requestPhoneData(
          settings,
          { baseUrl: device.baseUrl, token: device.token },
          `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}/cancel`,
          'POST',
          {},
          { timeoutMs: 30_000 },
        ).catch(() => undefined),
      ),
    );
  }, [settings, addTaskLog]);

  const handleRunFleet = async () => {
    const prompt = actionPrompt.trim();
    if (!prompt) {
      pushToast({ tone: 'warn', title: '任务说明不能为空' });
      return;
    }
    // 目标从当前设备列表取，并过滤掉没配置 baseUrl/token 的，避免提交必然失败的请求。
    const selected = devices.filter((device) => fleetTargetIds.includes(device.id));
    const targets = selected.filter((device) => normalizePhoneBaseUrl(device.baseUrl) && device.token.trim());
    if (!targets.length) {
      pushToast({ tone: 'warn', title: selected.length ? '所选设备还没配置地址/Token' : '请至少选择一台设备' });
      return;
    }
    const skipped = selected.length - targets.length;
    if (skipped > 0) addTaskLog('warn', `已跳过 ${skipped} 台未配置的设备`);

    fleetCancelRef.current = false;
    fleetInFlightRef.current = new Map();
    setFleetCancelling(false);
    setFleetRunning(true);
    const batch: FleetRun[] = targets.map((device) => ({
      id: (fleetRunSeqRef.current += 1),
      deviceId: device.id,
      deviceName: device.name || device.id,
      status: 'queued',
    }));
    setFleetRuns(batch);
    addTaskLog('info', `群控任务已启动：${targets.length} 台`, prompt);

    let success = 0;
    let failed = 0;
    let cancelled = 0;

    const runFleetDevice = async (device: PhoneDevice, runId: number): Promise<FleetRun['status']> => {
      const update = (patch: Partial<FleetRun>) =>
        setFleetRuns((runs) => runs.map((run) => (run.id === runId ? { ...run, ...patch } : run)));
      update({ status: 'running' });
      try {
        const start = await requestPhoneData<any>(
          settings,
          { baseUrl: device.baseUrl, token: device.token },
          '/api/lumi/agent/tasks',
          'POST',
          {
            prompt,
            use_template: true,
            force_agent: false,
            read_only: false,
            tool_policy: 'safe_action',
            timeout_sec: PHONE_AGENT_TASK_TIMEOUT_SEC,
            max_rounds: PHONE_AGENT_TASK_MAX_ROUNDS,
          },
          { timeoutMs: 60_000 },
        );
        const taskId = extractTaskId(start.data);
        if (!taskId) throw new Error('APKClaw did not return a task id.');
        fleetInFlightRef.current.set(runId, { device, taskId });
        for (let i = 0; i < PHONE_AGENT_TASK_POLL_SECONDS; i += 1) {
          if (fleetCancelRef.current) break;
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
          if (fleetCancelRef.current) break;
          const result = await requestPhoneData<any>(
            settings,
            { baseUrl: device.baseUrl, token: device.token },
            `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}`,
            'GET',
            undefined,
            { timeoutMs: 15_000 },
          );
          const task = result.data;
          if (terminalTaskStatus(task?.status)) {
            const lower = String(task?.status || '').toLowerCase();
            const outcome: FleetRun['status'] = lower === 'success' ? 'success' : lower.includes('cancel') ? 'cancelled' : 'error';
            update({ status: outcome, detail: task?.result?.answer || task?.error || '' });
            return outcome;
          }
        }
        if (fleetCancelRef.current) {
          update({ status: 'cancelled', detail: '已取消' });
          return 'cancelled';
        }
        update({ status: 'error', detail: '任务轮询超时' });
        return 'error';
      } catch (err) {
        const aborted = fleetCancelRef.current;
        const message = aborted ? '已取消' : authErrorHelp(errorText(err));
        update({ status: aborted ? 'cancelled' : 'error', detail: message });
        return aborted ? 'cancelled' : 'error';
      } finally {
        fleetInFlightRef.current.delete(runId);
      }
    };

    let nextIndex = 0;
    const worker = async () => {
      while (nextIndex < targets.length) {
        if (fleetCancelRef.current) break;
        const index = nextIndex;
        nextIndex += 1;
        const outcome = await runFleetDevice(targets[index], batch[index].id);
        if (outcome === 'success') success += 1;
        else if (outcome === 'cancelled') cancelled += 1;
        else failed += 1;
      }
    };

    try {
      await Promise.all(Array.from({ length: Math.min(FLEET_CONCURRENCY, targets.length) }, worker));
      // 补算「还没轮到就被取消」的目标。
      cancelled += Math.max(0, targets.length - (success + failed + cancelled));
      if (fleetCancelRef.current) {
        pushToast({ tone: 'warn', title: '群控已停止', detail: `成功 ${success} · 失败 ${failed} · 取消 ${cancelled}` });
      } else if (failed > 0) {
        pushToast({ tone: failed === targets.length ? 'danger' : 'warn', title: '群控完成', detail: `成功 ${success}/${targets.length}（失败 ${failed}）` });
      } else {
        pushToast({ tone: 'ok', title: '群控完成', detail: `${success} 台全部成功` });
      }
      addTaskLog(failed || cancelled ? 'warn' : 'ok', '群控结束', `成功 ${success} · 失败 ${failed} · 取消 ${cancelled}`);
    } finally {
      fleetCancelRef.current = false;
      fleetInFlightRef.current = new Map();
      setFleetCancelling(false);
      setFleetRunning(false);
    }
  };

  const handleToggleRecord = async () => {
    const active = Boolean(snapshot.recordStatus?.recording);
    const result = await runPhoneAction(active ? '录屏已停止' : '录屏已开始', active ? '/api/lumi/media/record/stop' : '/api/lumi/media/record/start');
    if (result) setSnapshot((state) => ({ ...state, recordStatus: result }));
  };

  const handleAddDevice = () => {
    const draft = createPhoneDeviceDraft(devices);
    setDeviceDraft(draft);
    setConfigOpen(true);
    setAddingDevice(true);
    setAuthState({ tone: 'neutral', title: '新设备待验证', detail: '输入局域网 IP 会自动补全 http:// 和 9527 端口。' });
    // 滚到配置区并短暂高亮，告诉新手“在这里填”。
    window.setTimeout(() => {
      configSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 60);
    window.setTimeout(() => setAddingDevice(false), 1600);
  };

  // 一键修复连接：用页面已有的探针/校验，逐项检查，最后只给一个结论。
  const runConnectionRepair = async () => {
    if (repairRunning) return;
    const device = selectedDevice;
    if (!device) {
      pushToast({ tone: 'warn', title: '请先选择一台设备' });
      return;
    }
    setRepairRunning(true);
    setRepairResult(null);
    const context = { baseUrl: device.baseUrl, token: device.token };
    const fail = (title: string, detail?: string) => {
      setRepairResult({ tone: 'danger', title, detail });
      addTaskLog('warn', '一键修复连接', `${title}${detail ? ' · ' + detail : ''}`);
    };
    try {
      // 1. IP/可达性 + Token：device/status 是 token 鉴权，能同时验证“连得上”和“令牌有效”。
      if (!normalizePhoneBaseUrl(device.baseUrl) || !device.token.trim()) {
        fail('手机地址或 Token 未填写', '请到下方设备配置补全 APKClaw 地址和 Token。');
        return;
      }
      try {
        await requestPhoneData(settings, context, '/api/device/status', 'GET', undefined, { timeoutMs: 12_000 });
      } catch (err) {
        const f = translatePhoneError(err);
        fail(f.title, f.hint);
        return;
      }
      // 2. Lumi 安全配对：warm 会自愈一次；失败即配对/时间问题。
      try {
        await warmPhoneSecurePairing(device.baseUrl, device.token);
      } catch (err) {
        const f = translatePhoneError(err);
        fail(f.title, f.hint);
        return;
      }
      // 3. APK 版本 / 签名通道：profile 走 Lumi 签名，能确认版本与安全通道都正常。
      try {
        await requestPhoneData(settings, context, '/api/lumi/device/profile?includeApps=false&appLimit=1', 'GET', undefined, { timeoutMs: 12_000 });
      } catch (err) {
        const f = translatePhoneError(err);
        fail(f.title, f.hint);
        return;
      }
      const now = nowIso();
      updateDeviceRuntime(device.id, { online: true, lastSeenAt: now, lastAuthorizedAt: now });
      setRepairResult({ tone: 'ok', title: '连接正常', detail: '地址、Token、安全配对和 APP 版本都已通过。' });
      addTaskLog('ok', '一键修复连接', '连接正常');
    } finally {
      setRepairRunning(false);
    }
  };

  const handleApplyPairCode = () => {
    const parsed = parsePairCode(pairCode);
    if (!parsed) {
      pushToast({ tone: 'danger', title: '配对码无法识别', detail: '请粘贴手机「电脑配对」里显示的配对码或二维码内容。' });
      return;
    }
    setDeviceDraft((state) => ({
      ...state,
      name: parsed.name || state.name,
      baseUrl: normalizePhoneInputDraft(parsed.baseUrl),
      token: parsed.token,
    }));
    setConfigOpen(true);
    setPairCode('');
    pushToast({ tone: 'ok', title: '已填入配对码', detail: '地址和 Token 已自动填好，点「保存并验证」完成安全配对。' });
  };

  const handleSyncModel = async () => {
    if (!selectedDevice) return;
    setSyncingModel(true);
    try {
      const cfg = await loadDesktopModelConfig(settings);
      if (!cfg) {
        pushToast({ tone: 'danger', title: '电脑未配置主模型', detail: '请先在「统一设置 → 主模型网关」填好地址和密钥。' });
        return;
      }
      const device = selectedDevice;
      const context = { baseUrl: device.baseUrl, token: device.token };
      const syncOnce = async (forcePair = false, rotateLauncherId = false) => {
        await requestPhoneData(settings, context, '/api/device/status', 'GET', undefined, { timeoutMs: 12_000 });
        const pairing = await warmPhoneSecurePairing(device.baseUrl, device.token, forcePair, rotateLauncherId);
        await requestPhoneData(settings, context, '/api/lumi/device/profile?includeApps=false&appLimit=1', 'GET', undefined, { timeoutMs: 12_000 });
        await requestPhoneData(
          settings,
          context,
          '/api/lumi/config/llm/import',
          'POST',
          cfg,
          { timeoutMs: 15_000 },
        );
        return pairing;
      };

      let pairing: PhonePairingSummary;
      try {
        pairing = await syncOnce(false, false);
      } catch (firstError) {
        const rawMessage = errorText(firstError);
        if (!isLumiRepairError(rawMessage)) throw firstError;
        addTaskLog('warn', '安全通道失效，正在重建', authErrorHelp(rawMessage));
        await clearPhoneSecurePairing(device.baseUrl, device.token);
        pairing = await syncOnce(true, true);
      }
      const now = nowIso();
      updateDeviceRuntime(device.id, { online: true, lastSeenAt: now, lastAuthorizedAt: now });
      setAuthState({
        tone: 'ok',
        title: 'Token 与 Lumi 安全通道已验证',
        detail: `Launcher ${pairing.launcherId.slice(0, 18)} · 过期 ${formatDateTime(pairing.expiresAt)}`,
        pairing,
      });
      pushToast({ tone: 'ok', title: '模型已同步到手机', detail: `${cfg.model || '默认模型'} · ${selectedDevice.name}` });
      addTaskLog('ok', '模型已同步到手机', `${cfg.baseUrl} / ${cfg.model}`);
    } catch (err) {
      const f = pushPhoneError(err, '同步模型失败');
      addTaskLog('danger', '同步模型失败', `${f.title} · ${f.hint}`);
    } finally {
      setSyncingModel(false);
    }
  };

  const buildValidatedDraft = React.useCallback((): { device?: PhoneDevice; error?: string } => {
    const normalizedBaseUrl = normalizePhoneBaseUrl(deviceDraft.baseUrl);
    if (deviceDraft.baseUrl.trim() && !normalizedBaseUrl) {
      return { error: `手机地址格式不正确：${deviceDraft.baseUrl.trim()}` };
    }
    const token = textValue(deviceDraft.token);
    if (!normalizedBaseUrl || !token) {
      return { error: '请填写 APKClaw 地址和 Token。' };
    }
    const usedIds = new Set(devices.filter((item) => item.id !== deviceDraft.id).map((item) => item.id));
    const id = uniqueDeviceId(textValue(deviceDraft.id) || slugFromUrl(normalizedBaseUrl), usedIds);
    return {
      device: {
        ...deviceDraft,
        id,
        name: textValue(deviceDraft.name) || 'APKClaw 设备',
        baseUrl: normalizedBaseUrl,
        token,
        relayBaseUrl: normalizePhoneBaseUrl(deviceDraft.relayBaseUrl),
        relayChannelId: textValue(deviceDraft.relayChannelId),
        relayToken: textValue(deviceDraft.relayToken),
        enabled: deviceDraft.enabled !== false,
        tags: deviceDraft.tags || [],
      },
    };
  }, [deviceDraft, devices]);

  const persistDevice = React.useCallback(async (device: PhoneDevice) => {
    const persisted = upsertPhoneDeviceList(devices, device);
    await savePhoneInventoryConfig(settings, persisted, device.id);
    setDevices(persisted);
    upsertMockPhoneDevice(device);
    setSelectedId(device.id);
    setDeviceDraft(device);
    setSelectedPhoneId(device.id);
    setMockPhoneSelection(device.id);
    updateSettings({ phoneBaseUrl: device.baseUrl, phoneToken: device.token });
  }, [devices, settings, setSelectedPhoneId, updateSettings]);

  const handleSaveDevice = async (mode: 'save' | 'test') => {
    const { device, error: validationError } = buildValidatedDraft();
    if (!device) {
      const message = validationError || '设备配置不完整。';
      setAuthState({ tone: 'danger', title: '设备配置无效', detail: message });
      pushToast({ tone: 'danger', title: '设备配置无效', detail: message });
      return;
    }
    setSaving(true);
    setCheckingDevice(mode === 'test');
    try {
      const next = mode === 'test' ? await testDevice(device, false) : device;
      await persistDevice(next);
      pushToast({ tone: 'ok', title: mode === 'test' ? '设备已验证并保存' : '设备已保存', detail: next.name });
      addTaskLog('ok', mode === 'test' ? '设备验证通过' : '设备已保存', `${next.name} · ${next.baseUrl}`);
      setConfigOpen(false);
    } catch (err) {
      const f = pushPhoneError(err, '设备验证失败');
      setAuthState({ tone: 'danger', title: f.title, detail: f.hint });
      addTaskLog('danger', '设备验证失败', `${f.title} · ${f.hint}`);
    } finally {
      setSaving(false);
      setCheckingDevice(false);
    }
  };

  const handleRepairPairing = async () => {
    const { device, error: validationError } = buildValidatedDraft();
    if (!device) {
      setAuthState({ tone: 'danger', title: '无法重新配对', detail: validationError });
      return;
    }
    setCheckingDevice(true);
    try {
      await clearPhoneSecurePairing(device.baseUrl, device.token);
      const repaired = await testDevice(device, true);
      await persistDevice(repaired);
      pushToast({ tone: 'ok', title: '安全通道已重新配对', detail: repaired.name });
      addTaskLog('ok', '安全通道已重新配对', repaired.baseUrl);
    } catch (err) {
      const f = pushPhoneError(err, '重新配对失败');
      setAuthState({ tone: 'danger', title: f.title, detail: f.hint });
      addTaskLog('danger', '重新配对失败', `${f.title} · ${f.hint}`);
    } finally {
      setCheckingDevice(false);
    }
  };

  const handleRemoveDevice = async (id: string) => {
    const removed = devices.find((item) => item.id === id);
    const persisted = devices.filter((item) => item.id !== id);
    const nextSelected = persisted[0] || null;
    try {
      await savePhoneInventoryConfig(settings, persisted, nextSelected?.id || '');
      if (removed) await clearPhoneSecurePairing(removed.baseUrl, removed.token);
    } catch (err) {
      pushToast({ tone: 'danger', title: '手机配置写入失败', detail: errorText(err) });
      return;
    }
    setDevices(persisted);
    removeMockPhoneDevice(id);
    setSelectedId(nextSelected?.id || null);
    if (nextSelected) {
      setDeviceDraft(nextSelected);
      updateSettings({ phoneBaseUrl: nextSelected.baseUrl, phoneToken: nextSelected.token });
    } else {
      updateSettings({ phoneBaseUrl: '', phoneToken: '' });
      setDeviceDraft(defaultDevice('', ''));
      setSnapshot(createEmptySnapshot());
    }
    pushToast({ tone: 'warn', title: '设备已移除', detail: id });
    addTaskLog('warn', '设备已移除', id);
  };

  const automationTemplates = automationState.templates;
  const selectedAutomationTemplate =
    automationTemplates.find((template) => template.id === scheduleDraft.templateId) ||
    automationTemplates[0] ||
    createDefaultAutomationState().templates[0];
  const xianyuTemplates = automationTemplates.filter((template) => template.packId === 'xianyu');
  const genericTemplates = automationTemplates.filter((template) => template.packId === 'generic');

  React.useEffect(() => {
    if (scheduleDraft.deviceIds.length) return;
    const fallbackId = selectedId || devices[0]?.id || null;
    if (!fallbackId) return;
    setScheduleDraft((state) => ({ ...state, deviceIds: [fallbackId] }));
  }, [devices, scheduleDraft.deviceIds.length, selectedId]);

  const handleApplyAutomationTemplate = (template: AutomationTemplate) => {
    setActionPrompt(applyTemplateVariables(template));
    setScheduleDraft((state) => ({ ...state, templateId: template.id, mode: template.mode }));
    pushToast({ tone: 'ok', title: '模板已填入任务说明', detail: template.title });
  };

  // 常用自动化快捷卡：找到内置模板就套用，找不到就把说明文字预填到任务输入框（不报错）。
  const handleQuickAutomation = (templateId: string, label: string, fallbackPrompt: string) => {
    const template = automationTemplates.find((item) => item.id === templateId);
    if (template) {
      handleApplyAutomationTemplate(template);
      return;
    }
    setActionPrompt(fallbackPrompt);
    pushToast({ tone: 'warn', title: '未找到内置模板', detail: `已预填「${label}」说明，可手动调整后执行。` });
  };

  const QUICK_AUTOMATIONS: Array<{ id: string; label: string; fallback: string }> = [
    { id: 'xianyu-polish', label: '闲鱼擦亮', fallback: '打开闲鱼，进入「我的」→「我发布的」，仅当出现「一键擦亮」时点击一次，然后读取截图结束。' },
    { id: 'xianyu-checkin', label: '签到', fallback: '打开闲鱼签到入口，只点击明确的「签到/领取奖励」按钮，不要点抽奖、支付或发布。' },
    { id: 'xianyu-listing-inspection', label: '读取发布状态', fallback: '打开闲鱼「我的」→「我发布的」，只读取商品标题、状态和异常提示，不要点击改价、删除或发布。' },
    { id: 'generic-ad-watch-reward', label: '广告等待', fallback: '处理当前广告或奖励等待页，等待到最短时长后只点击安全的「领取奖励/关闭/返回」，不要下载或安装任何应用。' },
  ];

  const handleToggleAutomationTemplate = (templateId: string, enabled: boolean) => {
    commitAutomationState((current) => ({
      ...current,
      templates: current.templates.map((template) =>
        template.id === templateId ? { ...template, enabled, updatedAt: nowIso() } : template,
      ),
    }));
    pushToast({ tone: enabled ? 'ok' : 'warn', title: enabled ? '模板已启用' : '模板已停用' });
  };

  const handleEditAutomationTemplate = (template: AutomationTemplate) => {
    setTemplateDraft(cloneTemplate(template));
    setAutomationTab('library');
  };

  const handleSaveTemplateDraft = () => {
    if (!templateDraft) return;
    const draft = {
      ...templateDraft,
      title: templateDraft.title.trim() || '未命名模板',
      prompt: templateDraft.prompt.trim(),
      tags: templateDraft.tags.map((item) => item.trim()).filter(Boolean),
      updatedAt: nowIso(),
    };
    if (!draft.prompt) {
      pushToast({ tone: 'danger', title: '模板提示词不能为空' });
      return;
    }
    commitAutomationState((current) => ({
      ...current,
      templates: current.templates.some((template) => template.id === draft.id)
        ? current.templates.map((template) => (template.id === draft.id ? draft : template))
        : [draft, ...current.templates],
    }));
    setTemplateDraft(null);
    pushToast({ tone: 'ok', title: '模板已保存', detail: draft.title });
  };

  const handleCreateTemplateDraft = () => {
    setTemplateDraft(createCustomTemplateDraft());
    setAutomationTab('library');
  };

  const handleResetAutomationLibrary = () => {
    const defaults = createDefaultAutomationState().templates;
    commitAutomationState((current) => ({ ...current, templates: defaults }));
    setTemplateDraft(null);
    pushToast({ tone: 'warn', title: '已恢复内置任务模板' });
  };

  const handleToggleScheduleDevice = (deviceId: string) => {
    setScheduleDraft((state) => ({
      ...state,
      deviceIds: state.deviceIds.includes(deviceId)
        ? state.deviceIds.filter((id) => id !== deviceId)
        : [...state.deviceIds, deviceId],
    }));
  };

  const handleCreateSchedule = () => {
    const template = automationTemplates.find((item) => item.id === scheduleDraft.templateId);
    if (!template) {
      pushToast({ tone: 'danger', title: '请选择有效模板' });
      return;
    }
    if (!scheduleDraft.deviceIds.length) {
      pushToast({ tone: 'warn', title: '请选择至少一台设备' });
      return;
    }
    const now = nowIso();
    const schedule: AutomationSchedule = {
      id: createAutomationId('auto-schedule'),
      label: scheduleDraft.label.trim() || template.title,
      templateId: template.id,
      deviceIds: scheduleDraft.deviceIds,
      cadence: scheduleDraft.cadence.trim() || '手动',
      timeWindow: scheduleDraft.timeWindow.trim() || '不限',
      mode: scheduleDraft.mode,
      enabled: scheduleDraft.enabled,
      allowUnattended: scheduleDraft.allowUnattended,
      createdAt: now,
      updatedAt: now,
      nextRunHint: scheduleDraft.enabled ? `${scheduleDraft.cadence.trim() || '手动'} · ${scheduleDraft.timeWindow.trim() || '不限'}` : '已停用',
    };
    commitAutomationState((current) => ({ ...current, schedules: [schedule, ...current.schedules].slice(0, 60) }));
    pushToast({ tone: 'ok', title: '任务计划已创建', detail: schedule.label });
  };

  const handleToggleSchedule = (scheduleId: string, enabled: boolean) => {
    commitAutomationState((current) => ({
      ...current,
      schedules: current.schedules.map((schedule) =>
        schedule.id === scheduleId
          ? { ...schedule, enabled, updatedAt: nowIso(), nextRunHint: enabled ? `${schedule.cadence} · ${schedule.timeWindow}` : '已停用' }
          : schedule,
      ),
    }));
  };

  const handleRemoveSchedule = (scheduleId: string) => {
    commitAutomationState((current) => ({
      ...current,
      schedules: current.schedules.filter((schedule) => schedule.id !== scheduleId),
    }));
    pushToast({ tone: 'warn', title: '任务计划已删除' });
  };

  const handleRunAutomation = async (templateId: string, deviceIds: string[], mode: AutomationRunMode, schedule?: AutomationSchedule) => {
    if (automationRunning) return;
    const template = automationTemplates.find((item) => item.id === templateId);
    if (!template) {
      pushToast({ tone: 'danger', title: '模板不存在' });
      return;
    }
    if (!template.enabled) {
      pushToast({ tone: 'warn', title: '模板已停用', detail: template.title });
      return;
    }
    const targets = deviceIds
      .map((id) => devices.find((device) => device.id === id))
      .filter(Boolean) as PhoneDevice[];
    if (!targets.length) {
      pushToast({ tone: 'warn', title: '没有可执行设备' });
      return;
    }

    setAutomationRunning(true);
    const queueId = createAutomationId('auto-queue');
    const queuedAt = nowIso();
    const queueItem = {
      id: queueId,
      scheduleId: schedule?.id,
      templateId: template.id,
      deviceIds: targets.map((device) => device.id),
      status: 'pending' as AutomationLogStatus,
      createdAt: queuedAt,
      updatedAt: queuedAt,
      mode,
      result: '提交后台调度器',
    };
    const logs: AutomationRunLog[] = targets.map((device) => ({
      id: createAutomationId('auto-log'),
      queueId,
      scheduleId: schedule?.id,
      templateId: template.id,
      templateTitle: template.title,
      deviceId: device.id,
      deviceName: device.name || device.id,
      status: 'pending',
      mode,
      queuedAt,
      result: '等待后台调度器确认',
      screenshotPath: `data/.openclaw/automation/screenshots/${queueId}-${device.id}.png`,
    }));
    commitAutomationState((current) => ({
      ...current,
      queue: [queueItem, ...current.queue].slice(0, 80),
      logs: [...logs, ...current.logs].slice(0, 200),
    }));
    addTaskLog('info', '提交自动化任务', `${template.title} · ${targets.length} 台设备`);
    try {
      const startedAt = nowIso();
      commitAutomationState((current) => ({
        ...current,
        queue: current.queue.map((item) =>
          item.id === queueId ? { ...item, status: 'running', updatedAt: startedAt, result: '后台调度器处理中' } : item,
        ),
        logs: current.logs.map((log) =>
          log.queueId === queueId && log.status === 'pending'
            ? { ...log, status: 'running', startedAt, result: '正在写入 phone-agent 队列' }
            : log,
        ),
      }));
      const response = await requestBridgeData<{ enqueued?: Array<{ deviceId?: string; queueId?: string }>; skipped?: Array<{ reason?: string; deviceId?: string }> }>(
        settings,
        '/api/phone-automation/scheduler/run_once',
        'POST',
        {
          templateId,
          deviceIds: targets.map((device) => device.id),
          mode,
          allowUnattended: schedule?.allowUnattended ?? scheduleDraft.allowUnattended,
        },
      );
      const finishedAt = nowIso();
      const enqueued = response.data?.enqueued || [];
      const skippedItems = response.data?.skipped || [];
      const enqueuedByDevice = new Map(enqueued.map((item) => [String(item.deviceId || ''), item.queueId || '']));
      const skippedReason = skippedItems.map((item) => item.reason).filter(Boolean).join(', ');
      commitAutomationState((current) => {
        const nextLogs = current.logs.map((log) => {
          if (log.queueId !== queueId) return log;
          const backendQueueId = enqueuedByDevice.get(log.deviceId);
          if (!backendQueueId) {
            return {
              ...log,
              status: 'skipped' as AutomationLogStatus,
              finishedAt,
              result: skippedReason || '后台调度器未入队',
              failureReason: skippedReason || 'not_enqueued',
            };
          }
          return {
            ...log,
            status: 'success' as AutomationLogStatus,
            finishedAt,
            result: `已写入后台队列 ${backendQueueId}`,
          };
        });
        const success = nextLogs.filter((log) => log.queueId === queueId && log.status === 'success').length;
        const skipped = nextLogs.filter((log) => log.queueId === queueId && log.status === 'skipped').length;
        const finalStatus: AutomationLogStatus = skipped && !success ? 'skipped' : 'success';
        return {
          ...current,
          queue: current.queue.map((item) =>
            item.id === queueId ? { ...item, status: finalStatus, updatedAt: finishedAt, result: `入队 ${success} · 跳过 ${skipped}` } : item,
          ),
          logs: nextLogs,
        };
      });
      const ok = enqueued.length > 0;
      pushToast({ tone: ok ? 'ok' : 'warn', title: ok ? '已提交后台队列' : '未入队', detail: skippedReason || template.title });
      addTaskLog(ok ? 'ok' : 'warn', ok ? '已提交后台队列' : '自动化未入队', skippedReason || `${template.title} · ${enqueued.length} 条`);
      await refreshSchedulerStatus();
    } catch (error) {
      const finishedAt = nowIso();
      const detail = errorText(error);
      commitAutomationState((current) => ({
        ...current,
        queue: current.queue.map((item) =>
          item.id === queueId ? { ...item, status: 'failed', updatedAt: finishedAt, result: detail } : item,
        ),
        logs: current.logs.map((log) =>
          log.queueId === queueId ? { ...log, status: 'failed', finishedAt, failureReason: detail } : log,
        ),
      }));
      pushToast({ tone: 'danger', title: '提交失败', detail });
      addTaskLog('danger', '自动化提交失败', detail);
    } finally {
      setAutomationRunning(false);
    }
  };

  const handleGenerateAutomationFixture = () => {
    const template = selectedAutomationTemplate;
    const device = selectedDevice || devices[0] || defaultDevice('', '');
    const statuses: AutomationLogStatus[] = ['pending', 'running', 'success', 'failed', 'skipped'];
    const now = nowIso();
    const scheduleId = createAutomationId('auto-fixture-schedule');
    const queueId = createAutomationId('auto-fixture');
    const fixtureDeviceId = device.id || 'fixture-device';
    const fixtureSchedule: AutomationSchedule = {
      id: scheduleId,
      label: '样例计划：闲鱼一键擦亮',
      templateId: template.id,
      deviceIds: [fixtureDeviceId],
      cadence: '每天 09:30',
      timeWindow: '09:00-10:30',
      mode: 'dry-run',
      enabled: true,
      createdAt: now,
      updatedAt: now,
      nextRunHint: 'fixture · dry-run',
    };
    const logs: AutomationRunLog[] = statuses.map((status) => ({
      id: createAutomationId(`auto-log-${status}`),
      queueId,
      scheduleId,
      templateId: template.id,
      templateTitle: template.title,
      deviceId: fixtureDeviceId,
      deviceName: device.name || '演示设备',
      status,
      mode: 'dry-run',
      queuedAt: now,
      startedAt: status === 'pending' ? undefined : now,
      finishedAt: status === 'pending' || status === 'running' ? undefined : now,
      result: status === 'failed' ? undefined : `状态样例：${automationStatusLabel(status)}`,
      failureReason: status === 'failed' ? 'fixture_failure_for_ui_check' : undefined,
      screenshotPath: `data/.openclaw/automation/screenshots/${queueId}-${status}.png`,
    }));
    commitAutomationState((current) => ({
      ...current,
      schedules: [fixtureSchedule, ...current.schedules].slice(0, 60),
      queue: [
        {
          id: queueId,
          scheduleId,
          templateId: template.id,
          deviceIds: [fixtureDeviceId],
          status: 'running' as AutomationLogStatus,
          createdAt: now,
          updatedAt: now,
          mode: 'dry-run' as AutomationRunMode,
          result: 'UI 状态流样例',
        },
        ...current.queue,
      ].slice(0, 80),
      logs: [...logs, ...current.logs].slice(0, 200),
    }));
    pushToast({ tone: 'ok', title: '状态样例已生成', detail: 'pending/running/success/failed/skipped' });
  };

  return (
    <div className="page-grid">
      <section className="hero-band">
        <div className="hero-copy">
          <div className="eyebrow">APKClaw 星桥</div>
          <h1>手机控制台只做安全控制桥。</h1>
          <p>桌面端负责授权、下发任务和留痕；APKClaw 只接收经过 Token 与 Lumi 签名校验的控制请求。</p>
        </div>
        <div className="hero-actions">
          <Button variant="quiet" icon={Smartphone} onClick={() => setApkModalOpen(true)}>下载手机端App</Button>
          <Button variant="primary" icon={RefreshCcw} onClick={() => refresh('manual')} disabled={!selectedDevice || loading}>刷新</Button>
          <Button variant="secondary" icon={Camera} onClick={handleCapture} disabled={!selectedDevice}>截图</Button>
          <Button variant="secondary" icon={Save} onClick={handleSyncModel} disabled={!selectedDevice || syncingModel}>{syncingModel ? '同步中…' : '同步模型到手机'}</Button>
          <Button variant="success" icon={Unlock} onClick={handleWake} disabled={!selectedDevice}>唤醒</Button>
        </div>
      </section>

      <Panel className="surface-panel">
        <SectionHeader
          eyebrow="第一步"
          title="连接手机"
          subtitle="先选好/添加手机，验证 Token 与安全配对。遇到连不上，点「一键修复连接」自动排查。"
          action={
            <Button variant="primary" icon={ShieldCheck} onClick={() => void runConnectionRepair()} disabled={!selectedDevice || repairRunning}>
              {repairRunning ? '检查中…' : '一键修复连接'}
            </Button>
          }
        />
        {repairRunning ? (
          <InlineState tone="neutral" title="正在检查连接" description="依次检查 地址可达性 → Token → 安全配对 → APP 版本…" />
        ) : repairResult ? (
          <InlineState tone={repairResult.tone} title={repairResult.title} description={repairResult.detail} />
        ) : null}
      </Panel>

      <section className="content-grid content-grid-phone">
        <Panel className="surface-panel surface-panel-narrow">
          <SectionHeader
            eyebrow="设备"
            title="已保存设备"
            subtitle="选择一个目标设备；新增设备先验证 Token 与安全通道。"
            action={<Button variant="quiet" icon={Plus} onClick={handleAddDevice}>新增</Button>}
          />
          <div className="device-list device-list-compact">
            {devices.length ? devices.map((device) => (
              <button
                key={device.id}
                type="button"
                className={selectedId === device.id ? 'device-card device-card-active' : 'device-card'}
                onClick={() => void selectDevice(device)}
              >
                <div className="device-card-head">
                  <strong>{device.name}</strong>
                  <Chip tone={device.online ? 'ok' : device.lastAuthorizedAt ? 'warn' : 'neutral'}>{device.online ? '在线' : device.lastAuthorizedAt ? '已授权' : '已保存'}</Chip>
                </div>
                <div className="device-card-meta">{displayPhoneBaseUrl(device.baseUrl)}</div>
                <div className="device-card-meta">{maskSecret(device.token)}</div>
                {device.lastSeenAt ? <div className="device-card-meta">最近连接 {formatDateTime(device.lastSeenAt)}</div> : null}
              </button>
            )) : (
              <EmptyState title="没有设备" description="点击新增，填入 APKClaw 局域网地址和 Token。" />
            )}
          </div>
        </Panel>

        <div className="phone-workspace phone-workspace-simple">
          <Panel className="surface-panel phone-focus-panel">
            <SectionHeader
              eyebrow="实时状态"
              title={selectedDevice?.name || '未选择设备'}
              subtitle={selectedDevice ? displayPhoneBaseUrl(selectedDevice.baseUrl) : '先新增 APKClaw 设备。'}
              action={<Chip tone={snapshot.status?.online || selectedDevice?.online ? 'ok' : authState.tone === 'danger' ? 'danger' : 'warn'}>{snapshot.status?.online || selectedDevice?.online ? '已连接' : '待确认'}</Chip>}
            />
            {!selectedDevice ? (
              <EmptyState title="没有设备" description="在设备配置区新增 APKClaw 地址和 Token。" />
            ) : loading && !hasVisibleSnapshot(snapshot) ? (
              <div className="panel-loading-inline">正在读取设备快照...</div>
            ) : error ? (
              <InlineState tone="danger" title="设备快照读取失败" description={error} />
            ) : (
              <div className="phone-simple-grid">
                <div className="phone-screen">
                  {snapshot.screenshotUrl ? <img src={snapshot.screenshotUrl} alt="APKClaw screenshot" /> : <div className="phone-screen-placeholder" aria-label="暂无截图" />}
                </div>
                <div className="phone-summary">
                  {(() => {
                    const st = snapshot.status as any;
                    if (!st) return null;
                    const issues: string[] = [];
                    if (st.accessibilityRunning === false) {
                      issues.push('无障碍服务未开启：截图、点击、滑动都会失效。请到手机「设置 → 无障碍」开启本应用（若开关是灰色，先到「应用信息 → ⋮ → 允许受限的设置」）。');
                    }
                    if (st.keyguardLocked === true || st.deviceLocked === true) {
                      issues.push('手机当前锁屏：请点上方「唤醒」或手动解锁后再操作。');
                    }
                    if (st.overlayPermission === false) {
                      issues.push('悬浮窗权限未开：光标预览不可用（不影响截图与点击）。');
                    }
                    if (!issues.length) return null;
                    const critical = st.accessibilityRunning === false;
                    return (
                      <InlineState
                        tone={critical ? 'danger' : 'warn'}
                        title={critical ? '演示前请先修复：手机无障碍服务已关闭' : '设备状态提醒'}
                        description={issues.join(' ')}
                      />
                    );
                  })()}
                  <div className="detail-stack">
                    <div className="detail-row"><span className="detail-label">版本</span><span className="detail-value">{snapshot.status?.versionInfo || snapshot.status?.version || '暂无'}</span></div>
                    <div className="detail-row"><span className="detail-label">屏幕</span><span className="detail-value">{snapshot.status?.screenOn ? '亮屏' : '未知'}</span></div>
                    <div className="detail-row"><span className="detail-label">无障碍</span><span className="detail-value">{snapshot.status?.accessibilityRunning ? '运行中' : (snapshot.status ? '未开启 ⚠' : '未确认')}</span></div>
                    <div className="detail-row"><span className="detail-label">电量</span><span className="detail-value">{formatBattery(snapshot.profile)}</span></div>
                  </div>
                  {loading ? <InlineState tone="neutral" title="正在刷新快照" description="截图和状态会先显示，视频/录屏等附加能力稍后更新。" /> : null}
                  <InlineState tone={authState.tone} title={authState.title} description={authState.detail} icon={authState.tone === 'ok' ? ShieldCheck : KeyRound} />

                  <div className="eyebrow" style={{ marginTop: 4 }}>第二步 · 执行任务</div>
                  <div className="quick-automation-row" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {QUICK_AUTOMATIONS.map((item) => (
                      <Button key={item.id} variant="quiet" icon={PlayCircle} onClick={() => handleQuickAutomation(item.id, item.label, item.fallback)}>
                        {item.label}
                      </Button>
                    ))}
                  </div>
                  <Field label="执行方式" hint={TASK_RUN_MODE_OPTIONS.find((item) => item.value === taskRunMode)?.hint}>
                    <Select value={taskRunMode} onChange={(event) => setTaskRunMode(event.target.value as TaskRunMode)}>
                      {TASK_RUN_MODE_OPTIONS.map((item) => (
                        <option key={item.value} value={item.value}>{item.label}</option>
                      ))}
                    </Select>
                  </Field>
                  <div className="button-row">
                    <Button variant="secondary" icon={Camera} onClick={handleCapture}>截图</Button>
                    <Button variant="success" icon={PlayCircle} onClick={handleTask} disabled={sending}>{sending ? '执行中...' : '执行任务'}</Button>
                    {activeTaskId || sending ? <Button variant="danger" icon={StopCircle} onClick={() => void handleCancelTask()}>停止任务</Button> : null}
                    <Button variant="danger" icon={StopCircle} onClick={handleToggleRecord}>录屏</Button>
                  </div>
                  <Field label="任务说明" hint="/api/lumi/agent/tasks">
                    <TextArea rows={5} value={actionPrompt} onChange={(event) => setActionPrompt(event.target.value)} />
                  </Field>
                </div>
              </div>
            )}
          </Panel>

          <Panel className="surface-panel">
            <SectionHeader
              eyebrow="群控 Fleet"
              title="多设备批量执行"
              subtitle="对选中的设备并发下发同一个「任务说明」，可随时停止，结束后汇总成败。"
              action={
                <Button
                  variant="quiet"
                  onClick={() => setFleetTargetIds(devices.filter((device) => normalizePhoneBaseUrl(device.baseUrl) && device.token.trim()).map((device) => device.id))}
                  disabled={fleetRunning || devices.length === 0}
                >
                  全选已配置
                </Button>
              }
            />
            {devices.length === 0 ? (
              <EmptyState title="还没有设备" description="先在上方新增并验证至少一台 APKClaw 设备。" />
            ) : (
              <div className="detail-stack">
                {devices.map((device) => {
                  const configured = Boolean(normalizePhoneBaseUrl(device.baseUrl) && device.token.trim());
                  return (
                    <label
                      key={device.id}
                      className="detail-row"
                      style={{ cursor: configured && !fleetRunning ? 'pointer' : 'not-allowed', opacity: configured ? 1 : 0.5 }}
                    >
                      <span className="detail-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input
                          type="checkbox"
                          checked={fleetTargetIds.includes(device.id)}
                          disabled={fleetRunning || !configured}
                          onChange={() => toggleFleetTarget(device.id)}
                        />
                        {device.name || device.id}
                      </span>
                      <span className="detail-value">{configured ? displayPhoneBaseUrl(device.baseUrl) : '未配置'}</span>
                    </label>
                  );
                })}
              </div>
            )}
            <div className="button-row">
              {fleetRunning ? (
                <Button variant="danger" icon={StopCircle} onClick={() => void handleCancelFleet()} disabled={fleetCancelling}>
                  {fleetCancelling ? '停止中...' : '停止群控'}
                </Button>
              ) : (
                <Button variant="success" icon={PlayCircle} onClick={() => void handleRunFleet()} disabled={fleetTargetIds.length === 0}>
                  运行选中设备（{fleetTargetIds.length}）
                </Button>
              )}
            </div>
            {fleetRuns.length > 0 ? (
              <div className="detail-stack">
                {fleetRuns.map((run) => (
                  <div key={run.id} className="detail-row">
                    <span className="detail-label">{run.deviceName}</span>
                    <span className="detail-value" style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                      <Chip tone={run.status === 'success' ? 'ok' : run.status === 'error' ? 'danger' : run.status === 'cancelled' ? 'warn' : 'neutral'}>
                        {fleetStatusLabel(run.status)}
                      </Chip>
                      {run.detail ? (
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 200, fontSize: 12, opacity: 0.75 }}>
                          {run.detail}
                        </span>
                      ) : null}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </Panel>

          <Panel className="surface-panel phone-automation-panel">
            <SectionHeader
              eyebrow="第三步 · 定时任务"
              title="任务模板、定时计划与执行日志"
              subtitle="打开下面的「定时任务总开关」后，已启用的计划会按时自动执行。"
              action={
                <div className="section-action-row">
                  <Button variant="quiet" icon={Plus} onClick={handleCreateTemplateDraft}>新建模板</Button>
                  <Button variant="quiet" icon={RefreshCcw} onClick={handleResetAutomationLibrary}>恢复内置模板</Button>
                  <Button variant="quiet" icon={PlayCircle} onClick={handleGenerateAutomationFixture}>生成演示数据</Button>
                </div>
              }
            />
            <div className="detail-row" style={{ alignItems: 'center', gap: 12 }}>
              <Toggle
                checked={Boolean(schedulerStatus?.running)}
                onChange={(checked) => void runSchedulerCommand(checked ? 'start' : 'stop')}
                label="定时任务总开关"
                hint={schedulerBusy ? '处理中…' : schedulerStatus?.running ? `运行中${schedulerStatus.pollSeconds ? ` · 每 ${schedulerStatus.pollSeconds}s 检查` : ''}` : '关闭时所有计划都不会自动执行'}
              />
              <Button variant="quiet" icon={RefreshCcw} onClick={() => void refreshSchedulerStatus()} disabled={schedulerBusy}>刷新状态</Button>
              <Button variant="quiet" icon={PlayCircle} onClick={() => void runSchedulerCommand('tick')} disabled={schedulerBusy}>立即检查一次</Button>
            </div>
            <Tabs
              value={automationTab}
              onChange={(value) => setAutomationTab(value as AutomationTab)}
              items={[
                { key: 'library', label: '模板库' },
                { key: 'schedules', label: '任务计划' },
                { key: 'logs', label: '执行日志' },
              ]}
            />
            {!automationLoaded ? (
              <InlineState tone="neutral" title="正在加载任务库配置" />
            ) : null}

            {automationTab === 'library' ? (
              <div className="automation-layout">
                <div className="automation-template-groups">
                  <div className="automation-group-title">闲鱼任务包</div>
                  <div className="automation-template-list">
                    {xianyuTemplates.map((template) => (
                      <div key={template.id} className="automation-template-row">
                        <div className="automation-template-main">
                          <div className="automation-template-head">
                            <strong>{template.title}</strong>
                            <span className="chip-row">
                              <Chip tone={template.enabled ? 'ok' : 'neutral'}>{template.enabled ? '已启用' : '已停用'}</Chip>
                              <Chip tone={automationRiskTone(template.riskLevel)}>{automationRiskLabel(template.riskLevel)}</Chip>
                              <Chip tone={template.mode === 'safe' ? 'warn' : 'neutral'}>{template.mode === 'safe' ? '安全执行' : '只演练'}</Chip>
                              {template.requiresManualConfirmation ? <Chip tone="warn">确认前停止</Chip> : null}
                            </span>
                          </div>
                          <div className="automation-tags">{template.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                        </div>
                        <div className="automation-template-actions">
                          <Button variant="secondary" icon={PlayCircle} onClick={() => handleApplyAutomationTemplate(template)}>套用</Button>
                          <Button variant="quiet" icon={Save} onClick={() => handleEditAutomationTemplate(template)}>编辑</Button>
                          <Toggle checked={template.enabled} onChange={(checked) => handleToggleAutomationTemplate(template.id, checked)} label="启用" />
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="automation-group-title">通用手机任务</div>
                  <div className="automation-template-list">
                    {genericTemplates.map((template) => (
                      <div key={template.id} className="automation-template-row">
                        <div className="automation-template-main">
                          <div className="automation-template-head">
                            <strong>{template.title}</strong>
                            <span className="chip-row">
                              <Chip tone={template.enabled ? 'ok' : 'neutral'}>{template.enabled ? '已启用' : '已停用'}</Chip>
                              <Chip tone={automationRiskTone(template.riskLevel)}>{automationRiskLabel(template.riskLevel)}</Chip>
                              <Chip tone={template.mode === 'safe' ? 'warn' : 'neutral'}>{template.mode === 'safe' ? '安全执行' : '只演练'}</Chip>
                            </span>
                          </div>
                          <div className="automation-tags">{template.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                        </div>
                        <div className="automation-template-actions">
                          <Button variant="secondary" icon={PlayCircle} onClick={() => handleApplyAutomationTemplate(template)}>套用</Button>
                          <Button variant="quiet" icon={Save} onClick={() => handleEditAutomationTemplate(template)}>编辑</Button>
                          <Toggle checked={template.enabled} onChange={(checked) => handleToggleAutomationTemplate(template.id, checked)} label="启用" />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="automation-editor">
                  {templateDraft ? (
                    <>
                      <div className="automation-group-title">编辑模板</div>
                      <div className="form-grid">
                        <Field label="模板名称">
                          <Input value={templateDraft.title} onChange={(event) => setTemplateDraft((state) => state ? { ...state, title: event.target.value } : state)} />
                        </Field>
                        <Field label="执行模式">
                          <Select value={templateDraft.mode} onChange={(event) => setTemplateDraft((state) => state ? { ...state, mode: event.target.value as AutomationRunMode } : state)}>
                            <option value="dry-run">只演练（只生成计划、不实际操作）</option>
                            <option value="safe">安全执行（遇敏感动作前停下确认）</option>
                          </Select>
                        </Field>
                        <Field label="风险">
                          <Select value={templateDraft.riskLevel} onChange={(event) => setTemplateDraft((state) => state ? { ...state, riskLevel: event.target.value as AutomationTemplate['riskLevel'] } : state)}>
                            <option value="low">低风险</option>
                            <option value="medium">需确认</option>
                            <option value="high">高风险</option>
                          </Select>
                        </Field>
                        <Field label="应用名称">
                          <Input value={templateDraft.appName} onChange={(event) => setTemplateDraft((state) => state ? { ...state, appName: event.target.value } : state)} />
                        </Field>
                        <Field label="标签">
                          <Input value={templateDraft.tags.join(', ')} onChange={(event) => setTemplateDraft((state) => state ? { ...state, tags: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) } : state)} />
                        </Field>
                      </div>
                      <Field label="任务提示词">
                        <TextArea rows={8} value={templateDraft.prompt} onChange={(event) => setTemplateDraft((state) => state ? { ...state, prompt: event.target.value } : state)} />
                      </Field>
                      {templateDraft.variables.length ? (
                        <div className="form-grid">
                          {templateDraft.variables.map((variable) => (
                            <Field key={variable.key} label={variable.label}>
                              <Input
                                value={variable.value}
                                onChange={(event) => setTemplateDraft((state) => state ? {
                                  ...state,
                                  variables: state.variables.map((item) => item.key === variable.key ? { ...item, value: event.target.value } : item),
                                } : state)}
                              />
                            </Field>
                          ))}
                        </div>
                      ) : null}
                      <Toggle
                        checked={templateDraft.requiresManualConfirmation}
                        onChange={(checked) => setTemplateDraft((state) => state ? { ...state, requiresManualConfirmation: checked } : state)}
                        label="需要人工最终确认"
                        hint="适合曝光、发布、支付等动作。"
                      />
                      <div className="button-row">
                        <Button variant="primary" icon={Save} onClick={handleSaveTemplateDraft}>保存模板</Button>
                        <Button variant="quiet" onClick={() => setTemplateDraft(null)}>取消</Button>
                      </div>
                    </>
                  ) : (
                    <InlineState
                      tone="neutral"
                      title="选择一个模板编辑"
                    />
                  )}
                </div>
              </div>
            ) : null}

            {automationTab === 'schedules' ? (
              <div className="automation-layout">
                <details className="settings-details automation-schedule-form">
                  <summary>新建定时计划（高级）</summary>
                  <p style={{ fontSize: 12, opacity: 0.7, margin: '6px 0' }}>
                    日常只需在右侧已保存计划里开关「启用」。需要新建或试运行时再展开这里。
                  </p>
                  <div className="form-grid">
                    <Field label="计划名称">
                      <Input value={scheduleDraft.label} onChange={(event) => setScheduleDraft((state) => ({ ...state, label: event.target.value }))} />
                    </Field>
                    <Field label="模板">
                      <Select value={scheduleDraft.templateId} onChange={(event) => setScheduleDraft((state) => ({ ...state, templateId: event.target.value, mode: automationTemplates.find((item) => item.id === event.target.value)?.mode || state.mode }))}>
                        {automationTemplates.map((template) => <option key={template.id} value={template.id}>{template.title}</option>)}
                      </Select>
                    </Field>
                    <Field label="频率">
                      <Input value={scheduleDraft.cadence} onChange={(event) => setScheduleDraft((state) => ({ ...state, cadence: event.target.value }))} placeholder="每隔 5 分钟 / 每 6 小时 / 每天 09:30" />
                    </Field>
                    <Field label="执行窗口">
                      <Input value={scheduleDraft.timeWindow} onChange={(event) => setScheduleDraft((state) => ({ ...state, timeWindow: event.target.value }))} placeholder="09:00-10:30" />
                    </Field>
                    <Field label="执行方式">
                      <Select value={scheduleDraft.mode} onChange={(event) => setScheduleDraft((state) => ({ ...state, mode: event.target.value as AutomationRunMode }))}>
                        <option value="dry-run">只演练：只生成计划并留痕</option>
                        <option value="safe">自动执行：交给手机安全执行</option>
                      </Select>
                    </Field>
                    <Toggle checked={scheduleDraft.enabled} onChange={(checked) => setScheduleDraft((state) => ({ ...state, enabled: checked }))} label="启用计划" />
                    <Toggle checked={scheduleDraft.allowUnattended} onChange={(checked) => setScheduleDraft((state) => ({ ...state, allowUnattended: checked }))} label="允许无人值守" />
                  </div>
                  <div className="automation-device-picker">
                    <div className="automation-group-title">选择设备</div>
                    {devices.length ? devices.map((device) => {
                      const configured = Boolean(normalizePhoneBaseUrl(device.baseUrl) && device.token.trim());
                      return (
                        <label key={device.id} className="automation-device-option">
                          <input
                            type="checkbox"
                            checked={scheduleDraft.deviceIds.includes(device.id)}
                            onChange={() => handleToggleScheduleDevice(device.id)}
                          />
                          <span>
                            <strong>{device.name || device.id}</strong>
                            <small>{configured ? displayPhoneBaseUrl(device.baseUrl) : '未配置地址或 Token'}</small>
                          </span>
                        </label>
                      );
                    }) : <EmptyState title="暂无设备" />}
                  </div>
                  <div className="button-row">
                    <Button variant="primary" icon={Plus} onClick={handleCreateSchedule}>创建计划</Button>
                    <Button
                      variant="success"
                      icon={PlayCircle}
                      onClick={() => handleRunAutomation(scheduleDraft.templateId, scheduleDraft.deviceIds, scheduleDraft.mode)}
                      disabled={automationRunning || !scheduleDraft.deviceIds.length}
                    >
                      试运行当前配置
                    </Button>
                  </div>
                </details>

                <div className="automation-schedule-list">
                  <div className="automation-group-title">已保存计划</div>
                  {automationState.schedules.length ? automationState.schedules.map((schedule) => {
                    const template = automationTemplates.find((item) => item.id === schedule.templateId);
                    const deviceNames = schedule.deviceIds
                      .map((id) => devices.find((device) => device.id === id)?.name || id)
                      .join('、');
                    return (
                      <div key={schedule.id} className="automation-schedule-row">
                        <div>
                          <div className="automation-template-head">
                            <strong>{schedule.label}</strong>
                            <span className="chip-row">
                              <Chip tone={schedule.enabled ? 'ok' : 'neutral'}>{schedule.enabled ? '启用' : '停用'}</Chip>
                              {template ? <Chip tone={automationRiskTone(template.riskLevel)}>{automationRiskLabel(template.riskLevel)}</Chip> : null}
                            </span>
                          </div>
                          <p>{template?.title || schedule.templateId} · {schedule.cadence} · {schedule.timeWindow}</p>
                          <small>{deviceNames || '未选择设备'}</small>
                        </div>
                        <div className="automation-template-actions">
                          <Button variant="success" icon={PlayCircle} onClick={() => handleRunAutomation(schedule.templateId, schedule.deviceIds, schedule.mode, schedule)} disabled={automationRunning || !schedule.enabled}>试运行</Button>
                          <Toggle checked={schedule.enabled} onChange={(checked) => handleToggleSchedule(schedule.id, checked)} label="启用" />
                          <Button variant="danger" icon={Trash2} onClick={() => handleRemoveSchedule(schedule.id)}>删除</Button>
                        </div>
                      </div>
                    );
                  }) : <EmptyState title="暂无计划" />}
                </div>
              </div>
            ) : null}

            {automationTab === 'logs' ? (
              <div className="automation-log-layout">
                <div className="automation-log-toolbar">
                  <div className="automation-group-title">执行日志</div>
                  <Button
                    variant="danger"
                    icon={Trash2}
                    onClick={() => commitAutomationState((current) => ({ ...current, logs: [], queue: [] }))}
                  >
                    清空执行日志
                  </Button>
                </div>
                <div className="automation-queue-strip">
                  {automationState.queue.slice(0, 6).map((item) => {
                    const template = automationTemplates.find((tpl) => tpl.id === item.templateId);
                    return (
                      <div key={item.id} className="automation-queue-item">
                        <Chip tone={automationStatusTone(item.status)}>{automationStatusLabel(item.status)}</Chip>
                        <strong>{template?.title || item.templateId}</strong>
                        <span>{formatDateTime(item.updatedAt)}</span>
                        <small>{item.result || item.id}</small>
                      </div>
                    );
                  })}
                </div>
                <div className="automation-log-table">
                  {automationState.logs.length ? automationState.logs.map((log) => (
                    <div key={log.id} className={`automation-log-row automation-log-${log.status}`}>
                      <span>{formatDateTime(log.finishedAt || log.startedAt || log.queuedAt)}</span>
                      <Chip tone={automationStatusTone(log.status)}>{automationStatusLabel(log.status)}</Chip>
                      <strong>{log.deviceName}</strong>
                      <strong>{log.templateTitle}</strong>
                      <p>{log.scheduleId ? `计划 ${log.scheduleId} · ` : '手动 · '}{log.failureReason || log.result || '暂无结果'}</p>
                      <code>{log.screenshotPath || '-'}</code>
                    </div>
                  )) : <EmptyState title="暂无执行日志" />}
                </div>
              </div>
            ) : null}
          </Panel>

          <div
            ref={configSectionRef}
            style={addingDevice ? { outline: '2px solid var(--accent, #4f8cff)', borderRadius: 12, transition: 'outline 0.3s ease', boxShadow: '0 0 0 4px rgba(79,140,255,0.18)' } : { transition: 'outline 0.3s ease' }}
          >
          <Panel className="surface-panel">
            <details
              className="settings-details"
              open={configOpen}
              onToggle={(event) => setConfigOpen(event.currentTarget.open)}
            >
              <summary>{addingDevice ? '正在添加新手机' : '设备配置'}</summary>
              <div className="phone-paircode">
                <Field label="扫码配对 · 配对码" hint="手机 APKClaw「电脑配对」里显示配对码/二维码，粘贴到这里自动填好地址和 Token">
                  <div className="phone-paircode-row">
                    <Input value={pairCode} onChange={(event) => setPairCode(event.target.value)} placeholder="粘贴 lumi://pair... 或配对码" />
                    <Button variant="secondary" onClick={handleApplyPairCode} disabled={!pairCode.trim()}>解析</Button>
                  </div>
                </Field>
              </div>
              <div className="form-grid form-grid-phone">
                <Field label="设备 ID"><Input value={deviceDraft.id} onChange={(event) => setDeviceDraft((state) => ({ ...state, id: event.target.value }))} /></Field>
                <Field label="名称"><Input value={deviceDraft.name} onChange={(event) => setDeviceDraft((state) => ({ ...state, name: event.target.value }))} placeholder="Redmi Note" /></Field>
                <Field label="APKClaw 地址" hint={normalizePhoneBaseUrl(deviceDraft.baseUrl) || '输入 192.168.1.4 会自动补 http:// 和 :9527'}>
                  <Input
                    value={deviceDraft.baseUrl}
                    onChange={(event) => setDeviceDraft((state) => ({ ...state, baseUrl: normalizePhoneInputDraft(event.target.value) }))}
                    onBlur={(event) => setDeviceDraft((state) => ({ ...state, baseUrl: normalizeOrCleanPhoneBaseUrl(event.target.value) }))}
                    placeholder="http://192.168.1.4:9527"
                  />
                </Field>
                <Field label="Token"><Input type="password" value={deviceDraft.token} onChange={(event) => setDeviceDraft((state) => ({ ...state, token: event.target.value.trim() }))} placeholder="APKClaw 控制台令牌" /></Field>
                <Field label="转发地址">
                  <Input
                    value={deviceDraft.relayBaseUrl || ''}
                    onChange={(event) => setDeviceDraft((state) => ({ ...state, relayBaseUrl: normalizePhoneInputDraft(event.target.value) }))}
                    onBlur={(event) => setDeviceDraft((state) => ({ ...state, relayBaseUrl: normalizeOrCleanPhoneBaseUrl(event.target.value) }))}
                  />
                </Field>
                <Field label="转发频道"><Input value={deviceDraft.relayChannelId || ''} onChange={(event) => setDeviceDraft((state) => ({ ...state, relayChannelId: event.target.value }))} /></Field>
                <Field label="转发 Token"><Input type="password" value={deviceDraft.relayToken || ''} onChange={(event) => setDeviceDraft((state) => ({ ...state, relayToken: event.target.value.trim() }))} /></Field>
                <Field label="标签"><Input value={(deviceDraft.tags || []).join(', ')} onChange={(event) => setDeviceDraft((state) => ({ ...state, tags: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) }))} /></Field>
              </div>
              <div className="button-row">
                <Button variant="primary" icon={CheckCircle2} onClick={() => void handleSaveDevice('test')} disabled={saving || checkingDevice}>{checkingDevice ? '验证中...' : '测试并保存'}</Button>
                <Button variant="secondary" icon={Save} onClick={() => void handleSaveDevice('save')} disabled={saving}>仅保存</Button>
                <Button variant="quiet" icon={ShieldCheck} onClick={() => void handleRepairPairing()} disabled={checkingDevice}>重新配对</Button>
                {draftPersisted ? <Button variant="danger" icon={Trash2} onClick={() => handleRemoveDevice(deviceDraft.id)}>移除当前</Button> : null}
                <Toggle checked={deviceDraft.enabled !== false} onChange={(checked) => setDeviceDraft((state) => ({ ...state, enabled: checked }))} label="启用" hint="控制该设备是否可被选择。" />
              </div>
            </details>
          </Panel>
          </div>

          <Panel className="surface-panel">
            <details
              className="settings-details"
              open={advancedOpen}
              onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
            >
              <summary>高级诊断（一般无需打开）</summary>
              <div className="automation-group-title">原始状态</div>
              <div className="detail-stack">
                <div className="detail-row"><span className="detail-label">在线</span><span className="detail-value">{snapshot.status?.online ? '是' : snapshot.status ? '否' : '未确认'}</span></div>
                <div className="detail-row"><span className="detail-label">无障碍服务</span><span className="detail-value">{snapshot.status ? (snapshot.status.accessibilityRunning ? '运行中' : '未开启') : '未确认'}</span></div>
                <div className="detail-row"><span className="detail-label">锁屏</span><span className="detail-value">{snapshot.status?.keyguardLocked || snapshot.status?.deviceLocked ? '是' : '否'}</span></div>
              </div>
              <div className="automation-group-title">采集与可靠性</div>
              <div className="detail-stack">
                <div className="detail-row"><span className="detail-label">采集时间</span><span className="detail-value">{formatDateTime(snapshot.profile?.capturedAt)}</span></div>
                <div className="detail-row"><span className="detail-label">应用数量</span><span className="detail-value">{Array.isArray(snapshot.profile?.apps) ? snapshot.profile.apps.length : 0}</span></div>
                <div className="detail-row"><span className="detail-label">视觉状态</span><span className="detail-value">{snapshot.vision?.mode || snapshot.vision?.currentScreen?.title || '暂无'}</span></div>
                <div className="detail-row"><span className="detail-label">任务状态</span><span className="detail-value">{snapshot.agentTask?.status || 'idle'}</span></div>
              </div>
              <div className="tree-list">
                {Array.isArray(snapshot.tree?.nodes) && snapshot.tree.nodes.length ? snapshot.tree.nodes.slice(0, 8).map((node: any, index: number) => (
                  <div key={node.id || index} className="tree-row">
                    <span>{node.depth}</span>
                    <strong>{node.className}</strong>
                    <span>{node.text || node.description || node.resourceId || 'node'}</span>
                  </div>
                )) : <EmptyState title="暂无节点树" description="刷新快照后获取界面层级。" />}
              </div>
              <div className="recording-list">
                {snapshot.recordings.length ? snapshot.recordings.map((record: any) => (
                  <div key={record.id || record.path} className="record-card">
                    <strong>{record.filename || 'recording'}</strong>
                    <span>{record.downloadUrl || record.path}</span>
                    <span>{record.mimeType || 'video/mp4'}</span>
                  </div>
                )) : <EmptyState title="暂无录屏" description="需要留证时使用录屏按钮。" />}
              </div>

              <div className="automation-log-toolbar">
                <div className="automation-group-title">手机执行日志</div>
                <Button variant="quiet" icon={Trash2} onClick={() => setTaskLogs([])}>清空</Button>
              </div>
              <div className="phone-task-log">
                {taskLogs.length ? taskLogs.map((item) => (
                  <div key={item.id} className={`phone-task-log-row phone-task-log-row-${item.tone}`}>
                    <span>{formatDateTime(item.at)}</span>
                    <strong>{item.title}</strong>
                    {item.detail ? <p>{item.detail}</p> : null}
                  </div>
                )) : <EmptyState title="暂无任务日志" description="执行手机任务后，步骤和结果会显示在这里。" />}
              </div>
            </details>
          </Panel>
        </div>
      </section>

      <Modal
        open={apkModalOpen}
        title="下载手机端 App"
        subtitle="让客户用手机扫码下载安装 APKClaw"
        onClose={() => setApkModalOpen(false)}
      >
        <div className="apk-download-modal">
          {apkQrDataUrl ? (
            <img
              src={apkQrDataUrl}
              alt="手机端 App 下载二维码"
              width={240}
              height={240}
              style={{ display: 'block', margin: '0 auto', borderRadius: 12 }}
            />
          ) : (
            <div style={{ textAlign: 'center', padding: '40px 0' }}>二维码生成中...</div>
          )}
          <p style={{ textAlign: 'center', marginTop: 12 }}>
            让客户用手机相机/浏览器扫码，或复制下方链接在手机里打开下载。
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
            <code
              style={{
                flex: 1,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontSize: 12,
                padding: '8px 10px',
                background: 'rgba(0,0,0,0.06)',
                borderRadius: 8,
              }}
            >
              {PHONE_APK_DOWNLOAD_URL}
            </code>
            <Button
              variant="secondary"
              icon={Copy}
              onClick={() => {
                void navigator.clipboard?.writeText(PHONE_APK_DOWNLOAD_URL);
                pushToast({ tone: 'ok', title: '链接已复制' });
              }}
            >
              复制
            </Button>
          </div>
          <InlineState
            tone="neutral"
            title="安装三步"
            description="① 手机文件管理器点 apk 安装　② 小米/红米先到开发者选项关「MIUI 优化」　③ 开无障碍若变灰，到 应用信息→右上角⋮→允许受限的设置。"
          />
        </div>
      </Modal>
    </div>
  );
}

function normalizePhoneInventory(store: any, single: any): { selectedDeviceId: string; devices: PhoneDevice[] } {
  const storeDevices = Array.isArray(store?.devices)
    ? store.devices
        .map((item: any, index: number) => normalizePhoneDevice(item, `phone-${index + 1}`))
        .filter(Boolean) as PhoneDevice[]
    : [];
  if (storeDevices.length) {
    return {
      selectedDeviceId: textValue(store?.selectedDeviceId) || storeDevices[0].id,
      devices: storeDevices,
    };
  }

  const singleDevice = normalizePhoneDevice(single, 'primary-phone');
  return {
    selectedDeviceId: singleDevice?.id || '',
    devices: singleDevice ? [singleDevice] : [],
  };
}

function extractScreenshotUrl(value: any): string {
  if (!value) return '';
  if (typeof value === 'string') return normalizeImageString(value, 'image/png');
  if (typeof value !== 'object') return '';
  const mime = textValue(value.mime || value.mimeType || value.image?.mime || value.image?.mimeType) || 'image/png';
  return (
    normalizeImageString(value.dataUrl, mime) ||
    normalizeImageString(value.screenshot, mime) ||
    normalizeImageString(value.screenshotBase64, mime) ||
    normalizeImageString(value.imageBase64, mime) ||
    normalizeImageString(value.base64, mime) ||
    normalizeImageString(value.bitmap, mime) ||
    normalizeImageString(value.content, mime) ||
    normalizeImageString(value.image?.dataUrl, mime) ||
    normalizeImageString(value.image?.base64, mime) ||
    normalizeImageString(value.image?.imageBase64, mime) ||
    normalizeImageString(value.data?.dataUrl, mime) ||
    normalizeImageString(value.data?.screenshot, mime) ||
    normalizeImageString(value.data?.screenshotBase64, mime) ||
    normalizeImageString(value.data?.imageBase64, mime) ||
    normalizeImageString(value.data?.base64, mime) ||
    ''
  );
}

function normalizeImageString(value: unknown, mime: string): string {
  const text = textValue(value);
  if (!text) return '';
  if (/^data:image\//i.test(text) || /^https?:\/\//i.test(text) || /^blob:/i.test(text)) return text;
  if (/^[A-Za-z0-9+/=\r\n]+$/.test(text) && text.replace(/\s/g, '').length > 100) {
    return `data:${mime || 'image/png'};base64,${text.replace(/\s/g, '')}`;
  }
  return '';
}

function extractTaskId(value: any): string {
  if (!value || typeof value !== 'object') return '';
  return textValue(value.taskId || value.id || value.data?.taskId || value.data?.id);
}

function normalizePhoneDevice(value: any, fallbackId: string): PhoneDevice | null {
  if (!value || typeof value !== 'object') return null;
  const baseUrl = normalizePhoneBaseUrl(value.baseUrl || value.phoneUrl);
  const token = textValue(value.token || value.phoneToken);
  const id = textValue(value.id) || fallbackId;
  const name = textValue(value.name) || 'APKClaw 设备';
  if (!id && !baseUrl && !token && !name) return null;
  return {
    id,
    name,
    baseUrl,
    token,
    relayBaseUrl: normalizePhoneBaseUrl(value.relayBaseUrl),
    relayChannelId: textValue(value.relayChannelId),
    relayToken: textValue(value.relayToken),
    enabled: value.enabled !== false,
    tags: Array.isArray(value.tags) ? value.tags.map(textValue).filter(Boolean) : [],
    online: Boolean(value.online),
    active: value.active !== false,
    lastSeenAt: textValue(value.lastSeenAt),
    lastAuthorizedAt: textValue(value.lastAuthorizedAt),
  };
}

function upsertPhoneDeviceList(devices: PhoneDevice[], device: PhoneDevice): PhoneDevice[] {
  const index = devices.findIndex((item) => item.id === device.id);
  const next = [...devices];
  if (index >= 0) next[index] = device;
  else next.unshift(device);
  return next;
}

async function savePhoneInventoryConfig(settings: any, devices: PhoneDevice[], selectedDeviceId: string) {
  const selected = devices.find((device) => device.id === selectedDeviceId) || devices[0] || null;
  await Promise.all([
    writeConfigValue(settings, PHONE_AGENTS_PATH, {
      schema: 'openclaw.launcher.phone-agents.v1',
      updatedAt: new Date().toISOString(),
      selectedDeviceId: selected?.id || '',
      devices: devices.map(toStoredPhoneDevice),
    }),
    writeConfigValue(settings, PHONE_AGENT_PATH, selected ? toStoredPhoneDevice(selected) : {}),
  ]);
}

function toStoredPhoneDevice(device: PhoneDevice) {
  return {
    id: device.id,
    name: device.name,
    baseUrl: normalizePhoneBaseUrl(device.baseUrl),
    token: device.token,
    relayBaseUrl: normalizePhoneBaseUrl(device.relayBaseUrl),
    relayChannelId: device.relayChannelId || '',
    relayToken: device.relayToken || '',
    enabled: device.enabled !== false,
    tags: device.tags || [],
    lastSeenAt: device.lastSeenAt || '',
    lastAuthorizedAt: device.lastAuthorizedAt || '',
  };
}

function uniqueDeviceId(seed: string, usedIds: Set<string>): string {
  const base = slugValue(seed) || 'phone-device';
  let candidate = base;
  let counter = 2;
  while (usedIds.has(candidate)) {
    candidate = `${base}-${counter}`;
    counter += 1;
  }
  return candidate;
}

function slugFromUrl(baseUrl: string): string {
  try {
    const url = new URL(baseUrl);
    return `phone-${url.hostname}-${url.port || '9527'}`;
  } catch {
    return 'phone-device';
  }
}

function slugValue(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function normalizePhoneInputDraft(value: string): string {
  const text = value.trim();
  if (/^\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?$/.test(text)) {
    return normalizePhoneBaseUrl(text) || value;
  }
  return value;
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
