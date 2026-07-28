import React from 'react';
import {
  accountApi,
  jobApi,
  matrixApi,
  parseErrorText,
  phoneApi,
  wireApi,
  type BridgeJob,
  type MatrixDeviceSummary,
  type MatrixStatusSnapshot,
  type PhoneConfigSnapshot,
  type PhoneAdbDevice,
  type PhoneDeviceSummary,
  type PhoneTaskMode,
  type PhoneTaskProfile,
} from '../../services/api';
import { BusyOverlay, Button, Input, Modal, Select, TextArea, showConfirm, showToast } from '../common';
import { APP_DISPLAY_NAME } from '../../version';

type CliResult = {
  success?: boolean;
  stdout?: string;
  stderr?: string;
  code?: number | string;
  message?: string;
  error?: string;
  wire?: {
    models?: {
      phone?: string;
      text?: string;
    };
  };
  syncResults?: Array<{ target?: string; ok?: boolean; error?: string }>;
};

type UiTone = 'ok' | 'warn' | 'neutral';

type DeviceRuntimeState = {
  status: 'checking' | 'online' | 'offline';
  summary: string;
  checkedAt: number;
};

type PhoneStatusResult = {
  ok: boolean;
  summary: string;
};

const PHONE_JOB_LABELS = new Set([
  '手机控制',
  '多设备',
  '手机视觉',
  '手机录屏',
  '手机设备',
  '手机连接',
  '手机截图',
  '读取屏幕',
  '手机最近任务',
  '手机模型同步',
]);
const DEFAULT_PHONE_PORT = '9527';
const DEFAULT_PHONE_MODEL = 'qwen3.7-plus';
const PHONE_AGENT_APK_URL = 'https://gitee.com/rfdiosuao/lumiapkclaw/releases/download/lumiclaw13241/OpenClaw-AgentPhone.apk';
const PHONE_AGENT_QR_SRC = '/phone-agent-apk-qr.svg';
const DEFAULT_READ_PROMPT = '只读取当前手机屏幕，不要点击、输入或滑动。请用中文返回当前页面名称和三个可见内容。';
const DEFAULT_ACTION_PROMPT = '请观察当前手机屏幕，并完成一个明确的小任务。执行后用中文返回做了什么、当前页面名称和是否需要我继续。';

const TASK_MODE_OPTIONS: Array<{ value: PhoneTaskMode; title: string; desc: string; badge: string }> = [
  { value: 'observe', title: '只读', desc: '只读屏幕，不点击、不输入、不滑动。', badge: 'observe' },
  { value: 'safe', title: '受控', desc: '允许执行任务，敏感动作会按安全策略收敛。', badge: 'safe' },
  { value: 'full', title: '完整控制', desc: '允许点击、输入、滑动等完整手机控制。', badge: 'full' },
];

const TASK_PROFILE_OPTIONS: Array<{ value: PhoneTaskProfile; title: string; desc: string }> = [
  { value: 'fast', title: '快速', desc: '演示优先，读屏和轻动作更快返回。' },
  { value: 'standard', title: '标准', desc: '保留原有稳定预算。' },
  { value: 'deep', title: '深度', desc: '复杂任务使用更长等待窗口。' },
];

const DEFAULT_PHONE_WAIT_BUDGET_MS = 45_000;
const PHONE_LONG_TASK_SETTLE_MS = 1_800;
const PHONE_JOB_POLL_DELAYS_MS = [500, 800, 1200];

type PhoneTaskBudget = {
  timeoutSec: number;
  maxWaitSec: number;
  maxRounds: number;
  pollMs: number;
};

type RunPhoneOptions = {
  waitBudgetMs?: number;
  releaseWhenSubmitted?: boolean;
  deviceId?: string;
};

const TASK_PROFILE_BUDGETS: Record<PhoneTaskProfile, Record<PhoneTaskMode, PhoneTaskBudget>> = {
  fast: {
    observe: { timeoutSec: 45, maxWaitSec: 60, maxRounds: 4, pollMs: 500 },
    safe: { timeoutSec: 120, maxWaitSec: 75, maxRounds: 12, pollMs: 500 },
    full: { timeoutSec: 300, maxWaitSec: 75, maxRounds: 30, pollMs: 500 },
  },
  standard: {
    observe: { timeoutSec: 90, maxWaitSec: 105, maxRounds: 8, pollMs: 800 },
    safe: { timeoutSec: 240, maxWaitSec: 260, maxRounds: 30, pollMs: 800 },
    full: { timeoutSec: 600, maxWaitSec: 620, maxRounds: 60, pollMs: 800 },
  },
  deep: {
    observe: { timeoutSec: 180, maxWaitSec: 210, maxRounds: 12, pollMs: 1200 },
    safe: { timeoutSec: 600, maxWaitSec: 630, maxRounds: 60, pollMs: 1200 },
    full: { timeoutSec: 900, maxWaitSec: 930, maxRounds: 90, pollMs: 1200 },
  },
};

const QUICK_TASKS = [
  '读取当前屏幕，告诉我页面名称和三个可见内容。',
  '返回上一页，然后告诉我现在停留在哪个页面。',
  '回到桌面，并告诉我桌面上能看到哪些主要应用。',
  '打开系统设置，停在设置首页后返回页面名称。',
];

function statusLabel(status: string): string {
  const key = String(status || '').toLowerCase();
  if (key === 'queued') return '排队中';
  if (key === 'running') return '执行中';
  if (['succeeded', 'success', 'completed', 'complete'].includes(key)) return '已完成';
  if (['failed', 'error'].includes(key)) return '失败';
  return status || '-';
}

function jobTone(status: string): string {
  const key = String(status || '').toLowerCase();
  if (['succeeded', 'success', 'completed', 'complete'].includes(key)) return 'border-status-success/30 bg-status-success/10 text-status-success';
  if (['failed', 'error'].includes(key)) return 'border-status-danger/30 bg-status-danger/10 text-status-danger';
  if (['queued', 'running'].includes(key)) return 'border-accent/30 bg-accent/10 text-accent';
  return 'border-border/70 bg-surface/35 text-text-muted';
}

function parseJsonMaybe(text?: string): any {
  const value = String(text || '').trim();
  if (!value) return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function isDoneStatus(status: string): boolean {
  return ['succeeded', 'success', 'completed', 'complete'].includes(String(status || '').toLowerCase());
}

function isFailedStatus(status: string): boolean {
  return ['failed', 'error', 'cancelled', 'canceled'].includes(String(status || '').toLowerCase());
}

function friendlyPhoneText(input?: string): string {
  const text = String(input || '').trim();
  if (!text) return '';
  if (/不支持的方法:\s*DELETE|unsupported_method:\s*DELETE/i.test(text)) {
    return '当前桌面组件版本不支持删除手机，请更新到最新版本后重试。';
  }
  if (/No APKClaw devices are configured|no target device selected/i.test(text)) {
    return '未配置手机设备。请先打开手机端“与 LOOM 配对”，粘贴完整配对信息；使用 USB 时也可输入 6 位配对码。';
  }
  if (/Missing phone URL|missing_phone_url/i.test(text)) {
    return '缺少手机地址。局域网请粘贴手机生成的完整配对信息；使用 USB 时可输入 6 位配对码。';
  }
  if (/Missing phone token|missing_phone_token/i.test(text)) {
    return '这台手机尚未完成安全配对。请在手机端生成新的配对码。';
  }
  if (/phone_pairing_code_expired/i.test(text)) {
    return '配对码已过期，请在手机端刷新配对码后重试。';
  }
  if (/phone_pairing_code_replayed/i.test(text)) {
    return '这个配对码已经使用，请在手机端生成新的配对码。';
  }
  if (/phone_pairing_rate_limited/i.test(text)) {
    return '配对尝试次数过多，请在手机端刷新配对码后稍后重试。';
  }
  if (/phone_pairing_device_mismatch/i.test(text)) {
    return '配对信息与当前手机不一致，请重新扫码或复制配对信息。';
  }
  if (/phone_pairing_usb_unauthorized/i.test(text)) {
    return 'USB 调试尚未授权，请在手机弹窗中允许这台电脑后重试。';
  }
  if (/phone_pairing_(lan_unreachable|endpoint_unavailable)/i.test(text)) {
    return '无法连接手机配对服务。请保持手机配对页面打开，并检查 USB 或局域网。';
  }
  if (/phone_pairing_credential_invalid/i.test(text)) {
    return '手机安全校验未通过，旧连接未被修改。请刷新配对码后重试。';
  }
  if (/phone_pairing_confirmation_pending/i.test(text)) {
    return '桌面凭据已安全保存，手机暂未确认。请保持手机连接服务在线，LOOM 会自动重试。';
  }
  if (/Unknown APKClaw device id/i.test(text)) {
    return '未找到指定手机设备。请刷新设备列表后重新选择。';
  }
  if (/auth_failed|unauthorized|forbidden|invalid.*token|token mismatch|HTTP\s*(401|403)\b/i.test(text)) {
    return '手机安全凭据已失效。请在手机端生成新的配对码并重新配对。';
  }
  if (/phone_config_server_unreachable|fetch failed|ECONNREFUSED|EHOSTUNREACH|ENETUNREACH/i.test(text)) {
    return '无法连接手机端 APKClaw。请确认 App 和 LAN Config 服务已启动，并且手机与电脑在同一网络。';
  }
  if (/ETIMEDOUT|timed out|timeout/i.test(text)) {
    return '手机连接请求超时。请确认手机未休眠、网络稳定，并检查 IP 和 9527 端口。';
  }
  if (/daemon_unauthorized/i.test(text)) {
    return '手机后台服务授权已失效，请重启麓鸣后重新检测。';
  }
  if (/daemon.*(not running|stopped|unavailable)|手机后台服务.*未/i.test(text)) {
    return '手机后台服务未启动，请重启麓鸣或在诊断页启动手机后台服务。';
  }
  if (/event[ _-]?stream.*snapshot/i.test(text)) return '手机状态已同步';
  if (/Task accepted by APKClaw/i.test(text)) return '手机任务已接收';
  if (/Task completed/i.test(text)) return '手机任务已完成';
  if (/Reached round/i.test(text)) return '任务已达到执行轮次上限';
  return text;
}

function friendlyPhoneStep(value?: string): string {
  const text = String(value || '').trim();
  const key = text.toLowerCase().replace(/[\s_-]+/g, '');
  if (!key) return '-';
  if (/submitted|queued|accepted/.test(key)) return '任务已提交';
  if (/connect|status|handshake/.test(key)) return '检测手机连接';
  if (/screen|tree|observe/.test(key)) return '读取当前屏幕';
  if (/tool|action|execute|running/.test(key)) return '执行手机操作';
  if (/complete|success|result/.test(key)) return '整理任务结果';
  if (/error|failed|daemon/.test(key)) return '任务执行异常';
  return friendlyPhoneText(text).slice(0, 60);
}

async function waitForPhoneJob(
  jobId: string,
  timeoutMs = DEFAULT_PHONE_WAIT_BUDGET_MS,
  options: { onProgress?: (job: BridgeJob<CliResult>) => void } = {},
): Promise<BridgeJob<CliResult>> {
  const deadline = Date.now() + timeoutMs;
  let lastJob: BridgeJob<CliResult> | null = null;
  while (Date.now() < deadline) {
    const resp = await jobApi.get(jobId) as { job: BridgeJob<CliResult> };
    lastJob = resp.job;
    options.onProgress?.(lastJob);
    if (isDoneStatus(lastJob.status) || isFailedStatus(lastJob.status)) return lastJob;
    const delay = PHONE_JOB_POLL_DELAYS_MS[Math.min(PHONE_JOB_POLL_DELAYS_MS.length - 1, Math.max(0, Math.floor((Date.now() + timeoutMs - deadline) / 1200)))];
    await new Promise((resolve) => window.setTimeout(resolve, delay));
  }
  throw { error: lastJob?.progress?.message || lastJob?.message || '手机任务超时，请检查手机连接状态。' };
}

function phoneWaitBudgetMs(maxWaitSec?: number): number {
  const seconds = Number.isFinite(maxWaitSec) ? Number(maxWaitSec) : DEFAULT_PHONE_WAIT_BUDGET_MS / 1000;
  return Math.max(8_000, Math.min(15 * 60 * 1000, (seconds + 12) * 1000));
}

function phoneStatusResult(job: BridgeJob<CliResult>, deviceId: string): PhoneStatusResult {
  const parsed = parseJsonMaybe(job.result?.stdout);
  const rows = Array.isArray(parsed?.results) ? parsed.results : [];
  const target = rows.find((item: any) => String(item?.device?.id || '') === deviceId) || rows[0];
  const jobSucceeded = isDoneStatus(job.status) && !isFailedStatus(job.status) && job.result?.success !== false;
  const ok = Boolean(jobSucceeded && parsed?.ok === true && target?.ok === true && target?.status?.online === true);
  if (ok) return { ok: true, summary: '手机连接在线' };
  const detail = friendlyPhoneText(
    target?.message
    || target?.error
    || parsed?.message
    || parsed?.error
    || job.result?.error
    || job.error
    || firstResultText(job),
  );
  return { ok: false, summary: detail || '手机连接失败，请检查手机端服务和连接配置。' };
}

function firstResultText(job: BridgeJob<CliResult> | null): string {
  const result = job?.result;
  if (result?.wire?.models?.phone) {
    const failed = result.syncResults?.find((item) => item.ok === false);
    if (failed) return friendlyPhoneText(failed.error || result.error || '手机模型同步失败');
    return `手机模型已同步：${result.wire.models.phone}`;
  }
  if (result?.message) return friendlyPhoneText(result.message);
  const parsed = parseJsonMaybe(result?.stdout);
  if (parsed?.final?.result?.summary) return String(parsed.final.result.summary);
  if (parsed?.final?.result?.text) return String(parsed.final.result.text);
  if (parsed?.final?.summary) return String(parsed.final.summary);
  if (parsed?.filePath || parsed?.path) {
    return '截图已保存，可在诊断日志中查看。';
  }
  if (parsed?.rows?.length) {
    return parsed.rows
      .slice(0, 3)
      .map((row: any) => row.summary || row.error || row.status || row.taskId || '')
      .filter(Boolean)
      .join('\n');
  }
  if (parsed?.devices?.length) {
    return parsed.devices
      .map((device: any) => `${device.selected ? '* ' : ''}${device.name || device.id || 'Android'}：${device.configured ? '已配置' : '未配置'}`)
      .join('\n');
  }
  if (parsed?.results?.length) {
    return parsed.results
      .map((item: any) => {
        const label = item.device?.name || item.device?.id || '设备';
        const state = item.ok === false
          ? friendlyPhoneText(item.message || item.error || '连接失败')
          : item.status?.online === true
            ? '在线'
            : '状态未知';
        return `${label}：${state}`;
      })
      .join('\n');
  }
  return friendlyPhoneText(result?.stdout || result?.stderr || job?.error || job?.message || '');
}

function phoneResultDetails(job: BridgeJob<CliResult> | null): string {
  if (!job) return '';
  const result = job.result;
  const parsed = parseJsonMaybe(result?.stdout);
  if (parsed) return JSON.stringify(parsed, null, 2);
  return String(result?.stdout || result?.stderr || result?.error || job.error || job.message || '').trim();
}

function phoneResultSummary(job: BridgeJob<CliResult> | null) {
  const parsed = parseJsonMaybe(job?.result?.stdout) || {};
  const final = parsed?.final || {};
  const finalResult = final?.result || {};
  const durationMs = Number(
    parsed?.durationMs
    || parsed?.metrics?.totalMs
    || final?.durationMs
    || finalResult?.durationMs
    || 0,
  );
  const remediation = parsed?.remediation || final?.remediation || finalResult?.remediation || [];
  return {
    step: friendlyPhoneStep(String(
      parsed?.currentStep
      || final?.currentStep
      || job?.progress?.currentStep
      || job?.progress?.phase
      || '-',
    )),
    duration: durationMs > 0 ? `${Math.max(1, Math.round(durationMs / 1000))} 秒` : '-',
    summary: firstResultText(job).slice(0, 1200),
    error: friendlyPhoneText(
      parsed?.error
      || final?.error
      || finalResult?.error
      || job?.result?.error
      || job?.error
      || '',
    ).slice(0, 800),
    remediation: Array.isArray(remediation)
      ? remediation.map((item: unknown) => String(item || '').trim()).filter(Boolean).slice(0, 5)
      : [],
  };
}

function phoneJobDeviceId(job: BridgeJob<CliResult> | null): string {
  if (!job) return '';
  const parsed = parseJsonMaybe(job.result?.stdout) || {};
  return String(
    parsed?.deviceId
    || parsed?.submitted?.deviceId
    || parsed?.submitted?.device?.id
    || parsed?.data?.deviceId
    || parsed?.final?.deviceId
    || job.progress?.deviceId
    || '',
  ).trim();
}

function isUserPhoneJob(job: BridgeJob<CliResult> | null): boolean {
  if (!job) return false;
  const kind = String(job.kind || '').toLowerCase();
  const label = String(job.label || '');
  if (/status|devices|history|sync/.test(kind)) return false;
  if (['手机连接', '手机设备', '手机最近任务', '手机模型同步'].includes(label)) return false;
  return /phone\.(task|read|frame|screenshot|vision)/.test(kind)
    || ['手机控制', '手机视觉', '手机截图', '读取屏幕', '手机任务'].includes(label);
}

function phoneJobs(jobs: BridgeJob[]): BridgeJob[] {
  return jobs.filter((job) => PHONE_JOB_LABELS.has(String(job.label || '')) || String(job.kind || '').startsWith('phone.'));
}

function mergePhoneJob(jobs: BridgeJob[], job?: BridgeJob | null): BridgeJob[] {
  if (!job?.id) return jobs;
  return [job, ...jobs.filter((item) => item.id !== job.id)].slice(0, 12);
}

function pickActivePhoneJob(jobs: BridgeJob[]): BridgeJob<CliResult> | null {
  return (jobs.find((job) => {
    const status = String(job.status || '');
    return !isDoneStatus(status) && !isFailedStatus(status);
  }) as BridgeJob<CliResult> | undefined) || null;
}

function pickLatestPhoneJob(jobs: BridgeJob[]): BridgeJob<CliResult> | null {
  return (jobs[0] as BridgeJob<CliResult> | undefined) || null;
}

function createOptimisticPhoneJob(key: string): BridgeJob<CliResult> {
  const message = key === 'task'
    ? '手机任务已提交，正在进入执行中'
    : key === 'read'
      ? '读屏任务已提交，正在读取节点树'
      : key === 'frame'
        ? '截图任务已提交，正在获取低清帧'
        : '手机任务已提交，正在处理';
  return {
    id: `pending_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    kind: `phone.${key}`,
    label: '手机任务',
    status: 'running',
    message,
    progress: {
      message,
      tone: 'neutral',
      history: [{ message, tone: 'neutral', updatedAt: Date.now() / 1000 }],
    },
  };
}

function selectedPhoneDevice(snapshot?: PhoneConfigSnapshot, preferredId?: string): PhoneDeviceSummary | null {
  const devices = snapshot?.devices || [];
  const selectedId = String(preferredId || snapshot?.selectedDeviceId || '').trim();
  return devices.find((device) => device.id && device.id === selectedId) || devices[0] || null;
}

function nextPhoneDeviceId(devices: PhoneDeviceSummary[]): string {
  const usedIds = new Set(devices.map((device) => String(device.id || '').trim()).filter(Boolean));
  let index = Math.max(1, devices.length + 1);
  while (usedIds.has(`phone-${index}`)) index += 1;
  return `phone-${index}`;
}

function cleanPhoneAddressInput(value?: string): string {
  return String(value || '')
    .trim()
    .replace(/[：﹕꞉]/g, ':')
    .replace(/[／⁄]/g, '/')
    .replace(/[。．｡]/g, '.')
    .replace(/\s+/g, '')
    .replace(/^http:\/(?!\/)/i, 'http://')
    .replace(/^https:\/(?!\/)/i, 'https://');
}

function displayPhoneAddress(baseUrl?: string): string {
  const text = cleanPhoneAddressInput(baseUrl).replace(/\/+$/, '');
  if (!text) return '';
  try {
    const parsed = new URL(text.includes('://') ? text : `http://${text}`);
    const host = parsed.hostname || text;
    return parsed.port && parsed.port !== DEFAULT_PHONE_PORT ? `${host}:${parsed.port}` : host;
  } catch {
    return text.replace(/^https?:\/\//i, '');
  }
}

function editablePhoneAddress(device?: PhoneDeviceSummary | null): string {
  if (device?.connectionMode === 'usb') {
    return device.lanBaseUrl || '';
  }
  return device?.baseUrl || '';
}

function detectDirectPhoneAction(text: string): 'back' | 'home' | '' {
  const normalized = String(text || '').toLowerCase().replace(/\s+/g, '');
  if (/^(返回|返回上一页|上一页|后退|back|pressback)$/.test(normalized)) return 'back';
  if (/^(回到桌面|返回桌面|桌面|主页|回主页|home|presshome)$/.test(normalized)) return 'home';
  return '';
}

function toneTextClass(tone: UiTone): string {
  return tone === 'ok' ? 'text-status-success' : tone === 'warn' ? 'text-status-warning' : 'text-text';
}

const Metric: React.FC<{ label: string; value: string; tone?: UiTone }> = ({ label, value, tone = 'neutral' }) => (
  <div className="min-h-[82px] border-t border-border/70 py-4">
    <div className="text-xs font-bold text-text-subtle">{label}</div>
    <div className={`mt-2 truncate text-xl font-black ${toneTextClass(tone)}`} title={value}>
      {value}
    </div>
  </div>
);

export const PhoneDemoPage: React.FC = () => {
  const [jobs, setJobs] = React.useState<BridgeJob[]>([]);
  const [busy, setBusy] = React.useState('');
  const [lastJob, setLastJob] = React.useState<BridgeJob<CliResult> | null>(null);
  const [lastJobDeviceId, setLastJobDeviceId] = React.useState('');
  const knownJobDevices = React.useRef<Record<string, string>>({});
  const [phoneExecutionStage, setPhoneExecutionStage] = React.useState('');
  const [prompt, setPrompt] = React.useState(DEFAULT_READ_PROMPT);
  const [taskMode, setTaskMode] = React.useState<PhoneTaskMode>('safe');
  const [taskProfile, setTaskProfile] = React.useState<PhoneTaskProfile>('fast');
  const [selectedDeviceId, setSelectedDeviceId] = React.useState('phone-1');
  const [deviceName, setDeviceName] = React.useState('Android Phone');
  const [phoneAddress, setPhoneAddress] = React.useState('');
  const [pairingPayload, setPairingPayload] = React.useState('');
  const [pairingCode, setPairingCode] = React.useState('');
  const [tokenAvailable, setTokenAvailable] = React.useState(false);
  const [accountLoggedIn, setAccountLoggedIn] = React.useState(false);
  const [hasWireConfig, setHasWireConfig] = React.useState(false);
  const [phoneAppModalOpen, setPhoneAppModalOpen] = React.useState(false);
  const [usbDevicePickerOpen, setUsbDevicePickerOpen] = React.useState(false);
  const [usbPickerMode, setUsbPickerMode] = React.useState<'pair' | 'connect'>('connect');
  const [usbDevices, setUsbDevices] = React.useState<PhoneAdbDevice[]>([]);
  const [selectedUsbSerial, setSelectedUsbSerial] = React.useState('');
  const [phoneConfigSnapshot, setPhoneConfigSnapshot] = React.useState<PhoneConfigSnapshot | null>(null);
  const [isAddingDevice, setIsAddingDevice] = React.useState(false);
  const [matrixStatus, setMatrixStatus] = React.useState<MatrixStatusSnapshot | null>(null);
  const [deviceRuntime, setDeviceRuntime] = React.useState<Record<string, DeviceRuntimeState>>({});
  const configuredPhones = React.useMemo(() => phoneConfigSnapshot?.devices || [], [phoneConfigSnapshot]);
  const selectedConfiguredPhone = React.useMemo(
    () => configuredPhones.find((device) => device.id === selectedDeviceId) || null,
    [configuredPhones, selectedDeviceId],
  );
  const selectedMatrixDevice = React.useMemo<MatrixDeviceSummary | null>(
    () => matrixStatus?.devices?.find((device) => device.deviceId === selectedDeviceId) || null,
    [matrixStatus, selectedDeviceId],
  );
  const appConfigured = Boolean(
    !isAddingDevice
    && selectedConfiguredPhone?.baseUrl
    && selectedConfiguredPhone?.tokenAvailable,
  );
  const usbConfigured = Boolean(
    !isAddingDevice
    && selectedConfiguredPhone?.tokenAvailable,
  );
  const hasUnsavedPhoneConfig = isAddingDevice
    || Boolean(pairingPayload.trim() || pairingCode.trim())
    || displayPhoneAddress(phoneAddress) !== displayPhoneAddress(editablePhoneAddress(selectedConfiguredPhone))
    || deviceName.trim() !== String(selectedConfiguredPhone?.name || selectedConfiguredPhone?.id || '').trim();
  const canUsePhone = appConfigured;
  const selectedCheckedRuntime = deviceRuntime[selectedDeviceId];
  const selectedRuntimeIsFresh = Boolean(
    selectedCheckedRuntime && Date.now() - selectedCheckedRuntime.checkedAt < 30_000,
  );
  const selectedMatrixPresenceAt = Date.parse(
    selectedMatrixDevice?.presenceObservedAt
    || selectedMatrixDevice?.lastEventAt
    || selectedMatrixDevice?.heartbeatAt
    || '',
  );
  const selectedMatrixIsFresh = Number.isFinite(selectedMatrixPresenceAt)
    && Date.now() - selectedMatrixPresenceAt < 30_000;
  const selectedRuntimeState = selectedCheckedRuntime?.status === 'checking'
    ? 'checking'
    : selectedRuntimeIsFresh && selectedCheckedRuntime
      ? selectedCheckedRuntime.status
      : selectedMatrixDevice && selectedMatrixIsFresh
        ? (selectedMatrixDevice.online ? 'online' : 'offline')
        : 'unknown';
  const connectionVerified = !hasUnsavedPhoneConfig && selectedRuntimeState === 'online';
  const connectionSummary = hasUnsavedPhoneConfig
    ? '待保存'
    : !appConfigured
      ? '未配置'
      : selectedRuntimeState === 'checking'
        ? '检测中'
        : connectionVerified
          ? '已连接'
          : selectedRuntimeState === 'offline'
            ? '离线'
            : '待检测';
  const onlineDeviceCount = matrixStatus?.devices?.filter((device) => device.online).length || 0;
  const deviceSummary = configuredPhones.length
    ? `${configuredPhones.length} 台 / ${onlineDeviceCount} 在线`
    : '未配置设备';
  const resolveJobDeviceId = React.useCallback((job: BridgeJob<CliResult> | null) => {
    if (!job) return '';
    return knownJobDevices.current[job.id] || phoneJobDeviceId(job);
  }, []);
  const currentDeviceJob = lastJob && lastJobDeviceId === selectedDeviceId ? lastJob : null;
  const requireSavedPhoneConfig = React.useCallback(() => {
    if (hasUnsavedPhoneConfig) {
      showToast('当前配对信息或地址尚未保存，请先完成配对或保存修改。', 'info');
      return false;
    }
    if (!appConfigured) {
      showToast('请先与手机完成配对，再执行手机任务。', 'info');
      return false;
    }
    return true;
  }, [appConfigured, hasUnsavedPhoneConfig]);

  const refreshJobs = React.useCallback(async () => {
    try {
      const resp = await jobApi.list(40);
      const nextJobs = phoneJobs(resp.jobs || []);
      const selectedJobs = nextJobs.filter((job) => (
        isUserPhoneJob(job as BridgeJob<CliResult>)
        && resolveJobDeviceId(job as BridgeJob<CliResult>) === selectedDeviceId
      ));
      const activePhoneJob = pickActivePhoneJob(selectedJobs);
      const latestPhoneJob = activePhoneJob || pickLatestPhoneJob(selectedJobs);
      setJobs(nextJobs);
      if (latestPhoneJob) setLastJobDeviceId(selectedDeviceId);
      else if (lastJobDeviceId !== selectedDeviceId) setLastJobDeviceId('');
      setLastJob((current) => {
        if (!current || lastJobDeviceId !== selectedDeviceId) {
          return latestPhoneJob || null;
        }
        const updatedJob = nextJobs.find((updatedJob) => current.id === updatedJob.id) as BridgeJob<CliResult> | undefined;
        if (updatedJob) return updatedJob;
        if (current.id.startsWith('pending_')) return latestPhoneJob || current;
        return current;
      });
      if (activePhoneJob) {
        setPhoneExecutionStage(activePhoneJob.progress?.message || activePhoneJob.message || '');
      }
    } catch {
      // Recent jobs are helpful but not required for the page to load.
    }
  }, []);

  const applyPhoneConfig = React.useCallback((snapshot: PhoneConfigSnapshot, preferredId?: string) => {
    setPhoneConfigSnapshot(snapshot);
    const selected = selectedPhoneDevice(snapshot, preferredId);
    setSelectedDeviceId(selected?.id || preferredId || snapshot.selectedDeviceId || 'phone-1');
    setDeviceName(selected?.name || selected?.id || 'Android Phone');
    setPhoneAddress(displayPhoneAddress(editablePhoneAddress(selected)));
    setTokenAvailable(Boolean(selected?.tokenAvailable));
    setPairingPayload('');
    setPairingCode('');
  }, []);

  const startAddPhone = React.useCallback(() => {
    const nextId = nextPhoneDeviceId(configuredPhones);
    setIsAddingDevice(true);
    setSelectedDeviceId(nextId);
    setDeviceName(`Android Phone ${configuredPhones.length + 1}`);
    setPhoneAddress('');
    setPairingPayload('');
    setPairingCode('');
    setTokenAvailable(false);
    setLastJob(null);
    setLastJobDeviceId('');
  }, [configuredPhones]);

  const selectConfiguredPhone = React.useCallback(async (device: PhoneDeviceSummary) => {
    const nextId = device.id || device.name || 'phone-1';
    setIsAddingDevice(false);
    setSelectedDeviceId(nextId);
    setDeviceName(device.name || nextId);
    setPhoneAddress(displayPhoneAddress(editablePhoneAddress(device)));
    setPairingPayload('');
    setPairingCode('');
    setTokenAvailable(Boolean(device.tokenAvailable));
    const restoredJob = jobs.find((job) => (
      isUserPhoneJob(job as BridgeJob<CliResult>)
      && resolveJobDeviceId(job as BridgeJob<CliResult>) === nextId
    )) as BridgeJob<CliResult> | undefined;
    setLastJob(restoredJob || null);
    setLastJobDeviceId(restoredJob ? nextId : '');
    if (phoneConfigSnapshot?.selectedDeviceId === nextId) return;
    setBusy('select-phone');
    try {
      const snapshot = await phoneApi.saveDevice({
        id: nextId,
        name: device.name || nextId,
        baseUrl: editablePhoneAddress(device),
        selectedDeviceId: nextId,
      });
      applyPhoneConfig(snapshot, nextId);
    } catch (error) {
      showToast(friendlyPhoneText(parseErrorText(error)) || '切换手机失败', 'error');
      const selected = selectedPhoneDevice(phoneConfigSnapshot || undefined);
      if (selected) applyPhoneConfig(phoneConfigSnapshot as PhoneConfigSnapshot, selected.id);
    } finally {
      setBusy('');
    }
  }, [applyPhoneConfig, jobs, phoneConfigSnapshot, resolveJobDeviceId]);

  const loadPhoneConfig = React.useCallback(async () => {
    try {
      const snapshot = await phoneApi.config();
      applyPhoneConfig(snapshot);
      const selected = selectedPhoneDevice(snapshot);
      if (selected?.connectionMode === 'usb') {
        try {
          const restored = await phoneApi.usbConnect({
            deviceId: selected.id,
            confirmed: true,
          });
          applyPhoneConfig(restored.config, selected.id);
        } catch (error) {
          setDeviceRuntime((current) => ({
            ...current,
            [selected.id]: {
              status: 'offline',
              summary: friendlyPhoneText(parseErrorText(error)) || 'USB 连接需要重新建立',
              checkedAt: Date.now(),
            },
          }));
          showToast('已保存的 USB 连接当前不可用，请检查数据线和 USB 调试授权。', 'info');
        }
      }
    } catch (error: any) {
      showToast(parseErrorText(error) || '读取手机连接配置失败', 'error');
    }
  }, [applyPhoneConfig]);

  const loadAccountStatus = React.useCallback(async () => {
    try {
      const resp = await accountApi.current();
      setAccountLoggedIn(Boolean(resp.account?.loggedIn));
      try {
        const current = await wireApi.current();
        setHasWireConfig(Boolean(current.wire?.ok && current.wire?.models?.phone));
      } catch {
        setHasWireConfig(false);
      }
    } catch {
      setAccountLoggedIn(false);
      setHasWireConfig(false);
    }
  }, []);

  const refreshMatrix = React.useCallback(async () => {
    try {
      const status = await matrixApi.status();
      setMatrixStatus(status);
    } catch {
      setMatrixStatus((current) => current || { schema: 'loom.matrix.v1', devices: [], summary: { total: 0, online: 0, busy: 0, failed: 0 } });
    }
  }, [lastJobDeviceId, resolveJobDeviceId, selectedDeviceId]);

  const deleteSelectedPhone = React.useCallback(async () => {
    const device = configuredPhones.find((item) => item.id === selectedDeviceId);
    if (!device || isAddingDevice) return;
    const confirmed = await showConfirm({
      title: '删除手机连接',
      message: `将删除“${device.name || device.id}”的本机地址和安全配对凭据，并停止实时同步。历史任务与审计记录会继续保留。`,
      confirmText: '删除手机',
      cancelText: '取消',
      tone: 'danger',
    });
    if (!confirmed) return;
    setBusy('delete-phone');
    try {
      const snapshot = await phoneApi.deleteDevice(device.id);
      applyPhoneConfig(snapshot, snapshot.selectedDeviceId);
      setIsAddingDevice(false);
      setDeviceRuntime((current) => {
        const next = { ...current };
        delete next[device.id];
        return next;
      });
      await refreshMatrix();
      showToast('手机连接已删除，历史记录已保留', 'success');
    } catch (error) {
      showToast(friendlyPhoneText(parseErrorText(error)) || '删除手机失败', 'error');
    } finally {
      setBusy('');
    }
  }, [applyPhoneConfig, configuredPhones, isAddingDevice, refreshMatrix, selectedDeviceId]);

  const copyPhoneAgentApkUrl = React.useCallback(async () => {
    try {
      await navigator.clipboard.writeText(PHONE_AGENT_APK_URL);
      showToast('下载链接已复制', 'success');
    } catch {
      showToast('复制失败，请手动复制下载链接。', 'error');
    }
  }, []);

  React.useEffect(() => {
    void loadPhoneConfig();
    void loadAccountStatus();
  }, [loadAccountStatus, loadPhoneConfig]);

  React.useEffect(() => {
    let stopped = false;
    let timer = 0;

    const scheduleRefresh = (delayMs: number) => {
      window.clearTimeout(timer);
      if (stopped) return;
      timer = window.setTimeout(async () => {
        if (document.visibilityState !== 'visible') return;
        await Promise.allSettled([refreshJobs(), refreshMatrix()]);
        scheduleRefresh(5000);
      }, delayMs);
    };

    const handleVisibilityChange = () => {
      window.clearTimeout(timer);
      if (document.visibilityState === 'visible') scheduleRefresh(100);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    scheduleRefresh(0);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [refreshJobs, refreshMatrix]);

  const runPhone = React.useCallback(async (
    key: string,
    submit: () => Promise<unknown>,
    onDone?: (job: BridgeJob<CliResult>) => void,
    options: RunPhoneOptions = {},
  ) => {
    const waitBudgetMs = options.waitBudgetMs ?? DEFAULT_PHONE_WAIT_BUDGET_MS;
    const operationDeviceId = options.deviceId || selectedDeviceId;
    setBusy(key);
    const optimisticJob = createOptimisticPhoneJob(key);
    knownJobDevices.current[optimisticJob.id] = operationDeviceId;
    setPhoneExecutionStage(optimisticJob.progress?.message || optimisticJob.message || '');
    setLastJob(optimisticJob);
    setLastJobDeviceId(operationDeviceId);
    setJobs((current) => mergePhoneJob(current, optimisticJob));
    try {
      const submitted = await submit() as { jobId?: string; job?: BridgeJob<CliResult> };
      const jobId = submitted.jobId || submitted.job?.id;
      if (!jobId) throw new Error('手机任务提交失败');
      const submittedJob = submitted.job || null;
      if (submittedJob) {
        knownJobDevices.current[submittedJob.id] = operationDeviceId;
        setLastJob(submittedJob);
        setLastJobDeviceId(operationDeviceId);
        setJobs((current) => mergePhoneJob(current, submittedJob));
      }
      if (options.releaseWhenSubmitted) {
        showToast('手机任务已在后台执行，可以切到其他页面。', 'success');
        await refreshJobs();
        return submittedJob;
      }
      showToast('手机任务已提交', 'success');
      const done = await waitForPhoneJob(jobId, waitBudgetMs, {
        onProgress: (job) => {
          knownJobDevices.current[job.id] = operationDeviceId;
          setPhoneExecutionStage(job.progress?.message || job.message || '');
          setLastJob(job);
          setLastJobDeviceId(operationDeviceId);
          setJobs((current) => mergePhoneJob(current, job));
        },
      });
      knownJobDevices.current[done.id] = operationDeviceId;
      setLastJob(done);
      setLastJobDeviceId(operationDeviceId);
      setPhoneExecutionStage(done.progress?.message || done.message || '');
      onDone?.(done);
      await refreshJobs();
      if (isFailedStatus(done.status)) {
        showToast(firstResultText(done) || '手机任务执行失败，请检查手机连接和诊断日志', 'error');
        return done;
      }
      return done;
    } catch (error: any) {
      showToast(parseErrorText(error) || '手机任务执行失败，请检查手机连接和诊断日志', 'error');
      await refreshJobs();
      return null;
    } finally {
      setPhoneExecutionStage('');
      setBusy('');
    }
  }, [refreshJobs, selectedDeviceId]);

  const saveDeviceAndDetect = async (usbSerial = '') => {
    const cleanAddress = phoneAddress.trim();
    const cleanName = deviceName.trim() || 'Android Phone';
    const cleanPayload = pairingPayload.trim();
    const cleanCode = pairingCode.trim();
    const shouldPair = isAddingDevice || !tokenAvailable || Boolean(cleanPayload || cleanCode || usbSerial);
    if (shouldPair && usbSerial && !cleanPayload && !/^\d{6}$/.test(cleanCode)) {
      showToast('USB 配对请输入手机端生成的 6 位配对码，或粘贴完整配对信息。', 'error');
      return;
    }
    if (shouldPair && !usbSerial && !cleanPayload) {
      showToast('局域网配对必须粘贴手机生成的完整配对信息；6 位码仅用于 USB。', 'error');
      return;
    }
    setBusy('config');
    try {
      const deviceId = selectedDeviceId.trim() || nextPhoneDeviceId(configuredPhones);
      const snapshot = shouldPair
        ? await phoneApi.claimPairing({
            id: deviceId,
            name: cleanName,
            payload: cleanPayload,
            baseUrl: cleanAddress,
            code: cleanCode,
            usbSerial,
          })
        : await phoneApi.saveDevice({
            id: deviceId,
            name: cleanName,
            baseUrl: cleanAddress,
            selectedDeviceId: deviceId,
          });
      applyPhoneConfig(snapshot, deviceId);
      setIsAddingDevice(false);
      const matrixSnapshot = await matrixApi.registerDevice({
        deviceId,
        name: cleanName,
        group: 'default',
        online: false,
        busy: false,
        currentTaskId: '',
        model: DEFAULT_PHONE_MODEL,
      });
      setMatrixStatus(matrixSnapshot.status);
      setPairingPayload('');
      setPairingCode('');
      if (shouldPair) {
        if (snapshot.pairing?.confirmationPending) {
          showToast(
            snapshot.pairing.confirmationStatus
              || '桌面凭据已安全保存，手机暂未确认；旧连接仍保留，LOOM 会自动重试。',
            'info',
          );
        } else {
          showToast(`手机已通过${usbSerial ? ' USB' : '局域网'}安全配对并确认`, 'success');
        }
        await checkConnection(deviceId, true);
      } else if (cleanAddress || selectedConfiguredPhone?.connectionMode === 'usb') {
        showToast('手机名称和地址已保存', 'success');
        await checkConnection(deviceId, true);
      } else {
        showToast('手机名称已保存', 'success');
      }
    } catch (error: any) {
      showToast(friendlyPhoneText(parseErrorText(error)) || '手机配对未完成，旧连接已保留', 'error');
    } finally {
      setBusy('');
    }
  };

  const startUsbPairing = async () => {
    const cleanPayload = pairingPayload.trim();
    const cleanCode = pairingCode.trim();
    if (!cleanPayload && !/^\d{6}$/.test(cleanCode)) {
      showToast('请先输入手机端生成的 6 位配对码，或粘贴完整配对信息。', 'error');
      return;
    }
    setBusy('usb');
    try {
      const response = await phoneApi.usbDevices();
      const readyDevices = (response.devices || []).filter((device) => device.state === 'device');
      if (!response.ok || readyDevices.length === 0) {
        showToast(friendlyPhoneText(response.message || '') || '未检测到已授权的 USB 手机', 'error');
        return;
      }
      if (readyDevices.length === 1) {
        setBusy('');
        await saveDeviceAndDetect(readyDevices[0].serial);
        return;
      }
      setUsbPickerMode('pair');
      setUsbDevices(readyDevices);
      setSelectedUsbSerial(readyDevices[0].serial);
      setUsbDevicePickerOpen(true);
    } catch (error) {
      showToast(friendlyPhoneText(parseErrorText(error)) || '读取 USB 手机失败', 'error');
    } finally {
      setBusy('');
    }
  };

  const checkConnection = async (deviceIdOverride?: string, configurationWasJustSaved = false) => {
    if (!configurationWasJustSaved && !requireSavedPhoneConfig()) return;
    const targetDeviceId = deviceIdOverride || selectedDeviceId;
    setDeviceRuntime((current) => ({
      ...current,
      [targetDeviceId]: { status: 'checking', summary: '正在检测手机连接', checkedAt: Date.now() },
    }));
    const completed = await runPhone('status', () => phoneApi.status({ deviceId: targetDeviceId }), (job) => {
      const result = phoneStatusResult(job, targetDeviceId);
      setDeviceRuntime((current) => ({
        ...current,
        [targetDeviceId]: { status: result.ok ? 'online' : 'offline', summary: result.summary, checkedAt: Date.now() },
      }));
    }, { deviceId: targetDeviceId });
    if (!completed) {
      setDeviceRuntime((current) => ({
        ...current,
        [targetDeviceId]: { status: 'offline', summary: '手机连接检测失败', checkedAt: Date.now() },
      }));
      try {
        const next = await matrixApi.registerDevice({
          deviceId: targetDeviceId,
          online: false,
          busy: false,
          currentTaskId: '',
          failureCount: 1,
        });
        setMatrixStatus(next.status);
      } catch {
        // The connection result remains visible locally when Matrix refresh is unavailable.
      }
    }
    await refreshMatrix();
  };

  const establishUsbConnection = async (serial: string) => {
    const confirmed = await showConfirm({
      title: '通过 USB 连接手机',
      message: `将使用内置 ADB 连接 ${serial}，并验证它与当前手机的安全配对凭据一致。`,
      confirmText: '建立 USB 连接',
      cancelText: '取消',
    });
    if (!confirmed) return;
    setBusy('usb');
    let switched = false;
    try {
      const response = await phoneApi.usbConnect({
        deviceId: selectedDeviceId,
        serial,
        confirmed: true,
      });
      applyPhoneConfig(response.config, selectedDeviceId);
      switched = true;
      showToast(`USB 连接已建立${response.connection.serial ? `：${response.connection.serial}` : ''}`, 'success');
    } catch (error) {
      showToast(friendlyPhoneText(parseErrorText(error)) || 'USB 连接失败', 'error');
    } finally {
      setBusy('');
    }
    if (switched) await checkConnection(selectedDeviceId, true);
  };

  const toggleUsbConnection = async () => {
    if (hasUnsavedPhoneConfig) {
      showToast('当前配对信息或地址尚未保存，请先完成配对或保存修改。', 'info');
      return;
    }
    if (!usbConfigured) {
      showToast('请先与手机完成配对，再建立 USB 连接。', 'info');
      return;
    }
    const usingUsb = selectedConfiguredPhone?.connectionMode === 'usb';
    if (usingUsb) {
      const hasLanFallback = Boolean(selectedConfiguredPhone?.lanBaseUrl);
      const confirmed = await showConfirm({
        title: hasLanFallback ? '切回局域网连接' : '断开 USB 连接',
        message: hasLanFallback
          ? '将移除当前 ADB 端口转发，并恢复这台手机原来的局域网地址。'
          : '将移除当前 ADB 端口转发。这台手机尚未配置局域网地址，断开后会显示为未连接。',
        confirmText: hasLanFallback ? '切回局域网' : '断开 USB',
        cancelText: '取消',
      });
      if (!confirmed) return;
      setBusy('usb');
      let switched = false;
      try {
        const response = await phoneApi.usbDisconnect({ deviceId: selectedDeviceId, confirmed: true });
        applyPhoneConfig(response.config, selectedDeviceId);
        switched = true;
        showToast(hasLanFallback ? '已切回局域网连接' : 'USB 连接已断开', 'success');
      } catch (error) {
        showToast(friendlyPhoneText(parseErrorText(error)) || '切回局域网失败', 'error');
      } finally {
        setBusy('');
      }
      if (switched && hasLanFallback) await checkConnection(selectedDeviceId, true);
      return;
    }

    setBusy('usb');
    try {
      const response = await phoneApi.usbDevices();
      const readyDevices = (response.devices || []).filter((device) => device.state === 'device');
      if (!response.ok || readyDevices.length === 0) {
        showToast(friendlyPhoneText(response.message || '') || '未检测到可连接的 USB 手机', 'error');
        return;
      }
      if (readyDevices.length === 1) {
        setBusy('');
        await establishUsbConnection(readyDevices[0].serial);
        return;
      }
      setUsbPickerMode('connect');
      setUsbDevices(readyDevices);
      setSelectedUsbSerial(readyDevices[0].serial);
      setUsbDevicePickerOpen(true);
    } catch (error) {
      showToast(friendlyPhoneText(parseErrorText(error)) || '读取 USB 手机失败', 'error');
    } finally {
      setBusy('');
    }
  };

  const readScreen = async () => {
    if (!requireSavedPhoneConfig()) return;
    const text = prompt.trim() || DEFAULT_READ_PROMPT;
    await runPhone('read', () => phoneApi.read({ prompt: text, profile: 'fast', deviceId: selectedDeviceId }), undefined, {
      waitBudgetMs: PHONE_LONG_TASK_SETTLE_MS,
      releaseWhenSubmitted: true,
      deviceId: selectedDeviceId,
    });
  };

  const executePhoneTask = async () => {
    if (!requireSavedPhoneConfig()) return;
    const text = prompt.trim() || (taskMode === 'observe' ? DEFAULT_READ_PROMPT : DEFAULT_ACTION_PROMPT);
    if (taskMode === 'full') {
      const confirmed = await showConfirm({
        title: '确认完整控制',
        message: '完整控制会真实点击、输入和滑动当前手机。请确认手机已连接、任务描述清楚，并且当前页面可以操作。',
        confirmText: '开始执行',
        cancelText: '先不执行',
      });
      if (!confirmed) return;
    }
    const budget = TASK_PROFILE_BUDGETS[taskProfile][taskMode];
    const directAction = detectDirectPhoneAction(text);
    await runPhone('task', () => phoneApi.task({
      prompt: text,
      deviceId: selectedDeviceId,
      mode: taskMode,
      profile: taskProfile,
      timeoutSec: budget.timeoutSec,
      maxRounds: budget.maxRounds,
      maxWaitSec: budget.maxWaitSec,
      pollMs: budget.pollMs,
      ...(directAction ? { action: directAction } : {}),
    }), undefined, {
      waitBudgetMs: phoneWaitBudgetMs(budget.maxWaitSec),
      releaseWhenSubmitted: true,
      deviceId: selectedDeviceId,
    });
  };

  const applyQuickTask = (text: string, nextMode?: PhoneTaskMode) => {
    setPrompt(text);
    if (nextMode) setTaskMode(nextMode);
  };

  const syncPhoneModel = async () => {
    if (!accountLoggedIn && !hasWireConfig) {
      showToast('请先在模型账号页完成登录或第三方模型配置，再同步手机模型。', 'info');
      return;
    }
    await runPhone('syncModel', () => phoneApi.syncModel(), (job) => {
      const model = job.result?.wire?.models?.phone;
      if (model) showToast(`手机模型已同步：${model}`, 'success');
    });
  };

  const lastText = firstResultText(currentDeviceJob);
  const resultSummary = phoneResultSummary(currentDeviceJob);
  const technicalResult = phoneResultDetails(currentDeviceJob);
  const phoneTaskRunning = Boolean(busy) || Boolean(currentDeviceJob && !isDoneStatus(currentDeviceJob.status) && !isFailedStatus(currentDeviceJob.status));
  const currentStageText = friendlyPhoneText(phoneExecutionStage || currentDeviceJob?.progress?.message || currentDeviceJob?.message || '');
  const activeJobCount = jobs.filter((job) => !isDoneStatus(job.status) && !isFailedStatus(job.status)).length;
  const busyOverlayTitle = busy === 'config'
    ? '正在读取手机配置'
    : busy === 'select-phone'
      ? '正在切换当前手机'
      : busy === 'usb'
        ? '正在切换手机连接方式'
    : busy === 'status'
      ? '正在检测手机连接'
      : busy === 'devices'
        ? '正在读取设备'
        : busy === 'read'
            ? '正在读取屏幕'
            : busy === 'task'
              ? taskMode === 'full' ? '正在完整控制手机任务' : taskMode === 'safe' ? '正在执行受控任务' : '正在只读手机屏幕'
              : busy === 'syncModel'
                ? '正在同步手机模型'
                : '正在处理手机任务';

  return (
    <div className="h-full overflow-y-auto bg-app-bg">
      <BusyOverlay
        active={Boolean(busy)}
        title={busyOverlayTitle}
        detail={phoneExecutionStage || `${APP_DISPLAY_NAME} 正在等待手机返回结果。`}
      />
      <Modal
        isOpen={usbDevicePickerOpen}
        onClose={() => setUsbDevicePickerOpen(false)}
        title="选择 USB 手机"
      >
        <p className="text-sm leading-6 text-text-muted">
          {usbPickerMode === 'pair'
            ? '检测到多台 USB 手机。请选择正在显示配对码的设备，系统会通过现有 USB 通道完成安全配对。'
            : '检测到多台 USB 手机。请选择要连接的已配对设备，系统会校验设备身份。'}
        </p>
        <Select
          className="mt-5 w-full"
          value={selectedUsbSerial}
          onChange={(event) => setSelectedUsbSerial(event.target.value)}
        >
          {usbDevices.map((device) => (
            <option key={device.serial} value={device.serial}>
              {device.label || device.serial} ({device.serial})
            </option>
          ))}
        </Select>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="quiet" onClick={() => setUsbDevicePickerOpen(false)}>取消</Button>
          <Button
            variant="primary"
            disabled={!selectedUsbSerial}
            onClick={() => {
              const serial = selectedUsbSerial;
              setUsbDevicePickerOpen(false);
              if (usbPickerMode === 'pair') {
                void saveDeviceAndDetect(serial);
              } else {
                void establishUsbConnection(serial);
              }
            }}
          >
            {usbPickerMode === 'pair' ? '与手机配对' : '连接'}
          </Button>
        </div>
      </Modal>
      {phoneAppModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="phone-app-download-title"
            className="max-h-[92vh] w-full max-w-[760px] overflow-y-auto rounded-[24px] border border-border bg-surface shadow-[0_28px_80px_rgba(0,0,0,0.28)]"
          >
            <div className="flex items-start justify-between gap-5 border-b border-border px-7 py-6">
              <div>
                <h2 id="phone-app-download-title" className="text-2xl font-black text-text">下载手机端 App</h2>
                <p className="mt-2 text-sm font-bold text-text-subtle">手机扫码安装后，在手机端生成一次性配对码，再回到{APP_DISPLAY_NAME}完成配对。</p>
              </div>
              <button
                type="button"
                onClick={() => setPhoneAppModalOpen(false)}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[14px] border border-border bg-surface-alt/55 text-2xl leading-none text-text-muted transition hover:border-border-strong hover:text-text"
                aria-label="关闭下载手机端 App"
              >
                ×
              </button>
            </div>
            <div className="grid gap-6 px-7 py-7 md:grid-cols-[260px_minmax(0,1fr)]">
              <div className="flex flex-col items-center justify-center rounded-[18px] border border-border bg-surface p-5">
                <img
                  src={PHONE_AGENT_QR_SRC}
                  alt="手机端 App 下载二维码"
                  className="h-[220px] w-[220px] rounded-[12px] object-contain"
                />
                <div className="mt-4 text-center text-xs font-bold text-text-subtle">手机相机或浏览器扫码下载</div>
              </div>
              <div className="min-w-0">
                <div className="rounded-[18px] border border-border bg-surface/70 p-4">
                  <div className="text-sm font-black text-text">下载链接</div>
                  <div className="mt-3 rounded-[12px] border border-border bg-surface-alt p-3 text-sm font-bold leading-6 text-text-muted">
                    手机端 App 下载链接已准备
                  </div>
                  <Button className="mt-4" variant="primary" onClick={copyPhoneAgentApkUrl}>复制</Button>
                </div>
                <div className="mt-5 rounded-[18px] border border-border bg-surface/70 p-4">
                  <div className="text-sm font-black text-text">安装三步</div>
                  <ol className="mt-3 space-y-2 text-sm leading-6 text-text-muted">
                    <li>1. 手机扫码或复制链接，在手机浏览器下载手机端 App。</li>
                    <li>2. 安装后打开手机端 App，按提示开启无障碍和悬浮窗权限。</li>
                    <li>3. 在手机“与 LOOM 配对”页生成配对信息；局域网粘贴完整信息，USB 可输入 6 位配对码。</li>
                  </ol>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <div className="mx-auto flex w-full max-w-[1480px] flex-col gap-6 px-7 py-6">
        <header className="flex flex-wrap items-end justify-between gap-6 rounded-[8px] border border-border/70 bg-surface/90 px-5 py-4 shadow-[0_14px_36px_rgba(17,24,21,0.06)]">
          <div>
            <div className="text-[11px] font-bold tracking-[0.18em] text-accent">手机控制</div>
            <h1 className="mt-2 text-[30px] font-black leading-tight text-text">手机控制</h1>
            <div className="mt-2 max-w-[680px] truncate text-sm font-bold leading-6 text-text-muted">
              {deviceSummary} · {activeJobCount ? `${activeJobCount} 个任务执行中` : '当前无执行任务'} · {connectionSummary}
            </div>
          </div>
          <div className="flex flex-wrap justify-end gap-3">
            <Button variant="quiet" onClick={() => setPhoneAppModalOpen(true)}>下载手机端 App</Button>
            <Button variant="quiet" onClick={toggleUsbConnection} disabled={Boolean(busy) || !usbConfigured}>
              {selectedConfiguredPhone?.connectionMode === 'usb'
                ? (selectedConfiguredPhone?.lanBaseUrl ? '切回局域网' : '断开 USB')
                : 'USB 连接'}
            </Button>
            <Button variant="primary" onClick={() => checkConnection()} disabled={Boolean(busy) || !canUsePhone}>
              {busy === 'status' ? '检测中...' : '检测连接'}
            </Button>
          </div>
        </header>

        <section className="grid gap-x-8 gap-y-2 md:grid-cols-2">
          <Metric label="设备" value={deviceSummary} tone={deviceSummary.includes('未') ? 'warn' : 'ok'} />
          <Metric label="连接" value={connectionSummary} tone={connectionSummary.includes('已连接') ? 'ok' : 'warn'} />
        </section>

        {phoneTaskRunning ? (
          <section className="border-t border-accent/25 bg-accent/[0.05] px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs font-bold tracking-[0.22em] text-accent">执行中</div>
                <div className="mt-1 truncate text-sm font-black text-text">{currentStageText || '手机任务正在执行'}</div>
              </div>
              <span className="rounded-full border border-accent/30 bg-surface/55 px-3 py-1 text-xs font-bold text-accent">
                {currentDeviceJob?.progress?.executionLayer ? String(currentDeviceJob.progress.executionLayer).toUpperCase() : taskProfile.toUpperCase()}
              </span>
            </div>
          </section>
        ) : null}

        <section className="border-t border-border/70 pt-7">
          <div className="flex flex-wrap items-end justify-between gap-5">
            <div>
              <div className="text-[10px] font-bold tracking-[0.24em] text-text-subtle">操作流程</div>
              <h2 className="mt-1 text-2xl font-black text-text">连接手机、输入任务、查看结果</h2>
            </div>
            <span className="rounded-full border border-border/70 bg-surface-alt/40 px-3 py-1 text-xs font-bold text-text-muted">
              本机连接
            </span>
          </div>

          <div className="mt-6">
            <div className="space-y-8">
              <section className="border-t border-border/70 pt-5">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-black text-text">手机连接配置</h2>
                    <p className="mt-1 text-xs leading-5 text-text-muted">
                      手机生成短时一次性配对码，长期安全凭据由系统自动交换并且永不显示。
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-border/70 bg-surface-alt/40 px-3 py-1 text-xs font-bold text-text-muted">
                      {isAddingDevice
                        ? '新增手机'
                        : <>已保存 {configuredPhones.length} 台 · 当前：{selectedDeviceId || 'phone-1'} · {selectedConfiguredPhone?.connectionMode === 'usb' ? 'USB' : '局域网'}</>}
                    </span>
                    {!isAddingDevice && configuredPhones.some((device) => device.id === selectedDeviceId) ? (
                      <Button variant="danger" onClick={() => void deleteSelectedPhone()} disabled={Boolean(busy)}>
                        删除手机
                      </Button>
                    ) : null}
                    <Button variant="quiet" onClick={startAddPhone} disabled={Boolean(busy)}>
                      添加手机
                    </Button>
                    <Button variant="quiet" onClick={loadPhoneConfig} disabled={Boolean(busy)}>
                      读取配置
                    </Button>
                  </div>
                </div>
                {configuredPhones.length ? (
                  <div className="mb-4 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2">
                    {configuredPhones.map((device) => {
                      const active = !isAddingDevice && device.id === selectedDeviceId;
                      const matrixDevice = matrixStatus?.devices?.find((item) => item.deviceId === device.id);
                      const checkedRuntime = deviceRuntime[device.id];
                      const runtimeState = checkedRuntime && Date.now() - checkedRuntime.checkedAt < 30_000
                        ? checkedRuntime.status
                        : matrixDevice
                          ? (matrixDevice.online ? 'online' : 'offline')
                          : 'unknown';
                      const runtimeLabel = runtimeState === 'online'
                        ? '在线'
                        : runtimeState === 'checking'
                          ? '检测中'
                          : runtimeState === 'offline'
                            ? '离线'
                            : '待检测';
                      return (
                        <button
                          key={device.id}
                          type="button"
                          onClick={() => selectConfiguredPhone(device)}
                          disabled={Boolean(busy)}
                          className={`min-w-0 rounded-[8px] border px-3 py-2 text-left transition ${
                            active
                              ? 'border-accent bg-accent/10 text-accent'
                              : 'border-border/70 bg-surface-alt/40 text-text hover:border-accent/40'
                          } ${busy ? 'opacity-60' : ''}`}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="truncate text-sm font-black">{device.name || device.id}</span>
                            <span className={`shrink-0 text-[11px] font-black ${runtimeState === 'online' ? 'text-status-success' : 'text-text-subtle'}`}>
                              {runtimeLabel}
                            </span>
                          </span>
                          <span className="mt-1 block truncate text-[11px] font-bold text-text-muted">
                            {device.connectionMode === 'usb' ? 'USB · ' : ''}
                            {displayPhoneAddress(device.baseUrl) || '未填写地址'}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ) : null}
                <div className="grid gap-4 lg:grid-cols-[180px_minmax(0,1fr)_220px]">
                  <label className="block">
                    <span className="mb-1 block text-xs font-bold text-text-subtle">设备名称</span>
                    <Input
                      value={deviceName}
                      onChange={(event) => setDeviceName(event.target.value)}
                      placeholder="Android Phone"
                      disabled={Boolean(busy)}
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-bold text-text-subtle">手机 IP</span>
                    <Input
                      value={phoneAddress}
                      onChange={(event) => setPhoneAddress(event.target.value)}
                      placeholder="例如 192.168.1.78"
                      disabled={Boolean(busy)}
                    />
                    <span className="mt-1 block text-[11px] leading-4 text-text-subtle">
                      局域网连接可填写；只使用 USB 时可留空。
                    </span>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-bold text-text-subtle">USB 6 位配对码</span>
                    <Input
                      inputMode="numeric"
                      value={pairingCode}
                      onChange={(event) => setPairingCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                      placeholder={tokenAvailable ? '重新配对时填写' : '例如 123456'}
                      disabled={Boolean(busy)}
                    />
                  </label>
                </div>
                <label className="mt-4 block">
                  <span className="mb-1 block text-xs font-bold text-text-subtle">配对信息（推荐）</span>
                  <TextArea
                    value={pairingPayload}
                    onChange={(event) => setPairingPayload(event.target.value)}
                    placeholder="粘贴手机端显示的完整配对信息；其中不包含长期凭据"
                    disabled={Boolean(busy)}
                    rows={2}
                  />
                  <span className="mt-1 block text-[11px] leading-4 text-text-subtle">
                    局域网必须粘贴完整配对信息；6 位配对码只通过 USB 本机通道使用。
                  </span>
                </label>
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <Button variant="primary" onClick={() => void saveDeviceAndDetect()} disabled={Boolean(busy)}>
                    {busy === 'config' || busy === 'status'
                      ? '配对检测中...'
                      : isAddingDevice || !tokenAvailable || pairingPayload.trim() || pairingCode.trim()
                        ? '与手机配对'
                        : '保存名称和地址'}
                  </Button>
                  <Button variant="quiet" onClick={() => void startUsbPairing()} disabled={Boolean(busy)}>
                    通过 USB 配对
                  </Button>
                  <span className="text-xs font-bold text-text-subtle">
                    {hasUnsavedPhoneConfig
                      ? '当前配对信息或地址尚未保存'
                      : selectedConfiguredPhone?.confirmationPending
                        ? selectedConfiguredPhone.confirmationStatus || '桌面已保存，等待手机确认'
                      : tokenAvailable
                        ? selectedConfiguredPhone?.confirmed === false
                          ? '配对确认状态未知'
                          : '已安全配对并确认'
                        : '尚未配对'}
                  </span>
                </div>
              </section>

              <section className="border-t border-border/70 pt-4">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <div className="text-sm font-black text-text">模型同步</div>
                    <p className="mt-1 text-xs leading-5 text-text-muted">
                      登录模型账号或配置第三方模型后，一键写入手机控制模型。
                    </p>
                  </div>
                  <Button variant="primary" onClick={syncPhoneModel} disabled={Boolean(busy) || (!accountLoggedIn && !hasWireConfig)}>
                    {busy === 'syncModel' ? '同步中...' : (accountLoggedIn || hasWireConfig) ? '同步模型到手机' : '配置后同步'}
                  </Button>
                </div>
              </section>

              <section className="border-t border-border/70 pt-6">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-black text-text">输入任务</h2>
                    <p className="mt-1 text-xs leading-5 text-text-muted">输入要手机完成的事，执行状态和结果会在当前页面持续更新。</p>
                  </div>
                  <span className="text-xs font-bold text-text-subtle">{taskMode}</span>
                </div>
                <div className="mb-4 grid gap-3 md:grid-cols-3">
                  {TASK_MODE_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setTaskMode(option.value)}
                      disabled={Boolean(busy)}
                      className={`rounded-[8px] border p-4 text-left transition-colors duration-150 ${
                        taskMode === option.value
                          ? 'border-accent/60 bg-accent/10 text-text'
                          : 'border-border/70 bg-surface-alt/35 text-text-muted hover:border-border-strong hover:text-text'
                      }`}
                    >
                      <span className="text-sm font-black">{option.title}</span>
                      <span className="mt-1 block text-[11px] font-bold uppercase tracking-[0.16em] text-text-subtle">{option.badge}</span>
                      <span className="mt-2 block text-xs leading-5">{option.desc}</span>
                    </button>
                  ))}
                </div>
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  {TASK_PROFILE_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setTaskProfile(option.value)}
                      disabled={Boolean(busy)}
                      title={option.desc}
                      className={`rounded-full border px-3 py-1.5 text-xs font-bold transition ${
                        taskProfile === option.value
                          ? 'border-accent/60 bg-accent/10 text-accent'
                          : 'border-border/70 bg-surface-alt/35 text-text-muted hover:border-border-strong hover:text-text'
                      }`}
                    >
                      {option.title}
                    </button>
                  ))}
                </div>
                <TextArea
                  aria-label="手机任务描述"
                  rows={4}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder={taskMode === 'observe' ? DEFAULT_READ_PROMPT : DEFAULT_ACTION_PROMPT}
                />
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <Button variant="primary" onClick={executePhoneTask} disabled={Boolean(busy)}>
                    {busy === 'task' ? '执行中...' : '执行'}
                  </Button>
                  <Button variant="quiet" onClick={readScreen} disabled={Boolean(busy)}>
                    {busy === 'read' ? '读取中...' : '读取屏幕'}
                  </Button>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {QUICK_TASKS.map((task, index) => (
                    <button
                      key={task}
                      type="button"
                      onClick={() => applyQuickTask(task, index === 0 ? 'observe' : 'safe')}
                      disabled={Boolean(busy)}
                      className="rounded-full border border-border/70 bg-surface-alt/35 px-3 py-1.5 text-xs font-bold text-text-muted transition hover:border-accent/45 hover:bg-accent/10 hover:text-text"
                    >
                      {task.length > 18 ? `${task.slice(0, 18)}...` : task}
                    </button>
                  ))}
                </div>
              </section>

              <section className="border-t border-border/70 pt-6">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <h2 className="text-lg font-black text-text">任务结果</h2>
                  {currentDeviceJob ? (
                    <span className={`rounded-full border px-3 py-1 text-xs font-bold ${jobTone(currentDeviceJob.status)}`}>
                      {statusLabel(currentDeviceJob.status)}
                    </span>
                  ) : null}
                </div>
                {lastText ? (
                  <div className="border-t border-border/60 pt-4">
                    <div className="text-[11px] font-black tracking-[0.16em] text-text-subtle">任务摘要</div>
                    <div className="mt-3 grid gap-3 sm:grid-cols-3">
                      <div className="rounded-[8px] border border-border/70 bg-surface-alt/35 p-3">
                        <div className="text-[11px] text-text-subtle">状态</div>
                        <div className="mt-1 text-sm font-black text-text">{statusLabel(currentDeviceJob?.status || '')}</div>
                      </div>
                      <div className="rounded-[8px] border border-border/70 bg-surface-alt/35 p-3">
                        <div className="text-[11px] text-text-subtle">当前步骤</div>
                        <div className="mt-1 break-words text-sm font-black text-text">{resultSummary.step}</div>
                      </div>
                      <div className="rounded-[8px] border border-border/70 bg-surface-alt/35 p-3">
                        <div className="text-[11px] text-text-subtle">耗时</div>
                        <div className="mt-1 text-sm font-black text-text">{resultSummary.duration}</div>
                      </div>
                    </div>
                    <div className="mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-text-muted">
                      {resultSummary.summary}
                    </div>
                    {resultSummary.error ? (
                      <div className="mt-3 rounded-[8px] border border-status-danger/30 bg-status-danger/10 p-3 text-sm leading-6 text-status-danger">
                        {resultSummary.error}
                      </div>
                    ) : null}
                    {resultSummary.remediation.length ? (
                      <div className="mt-3 rounded-[8px] border border-status-warning/30 bg-status-warning/10 p-3">
                        <div className="text-xs font-black text-text">修复建议</div>
                        {resultSummary.remediation.map((item) => (
                          <div key={item} className="mt-1 text-xs leading-5 text-text-muted">{item}</div>
                        ))}
                      </div>
                    ) : null}
                    {technicalResult ? (
                      <details data-phone-result-technical-details className="mt-4 rounded-[8px] border border-border/70 bg-surface-alt/25">
                        <summary className="cursor-pointer select-none px-3 py-2 text-xs font-black text-text-muted">技术详情</summary>
                        <div className="border-t border-border/60 p-3">
                          <Button
                            variant="quiet"
                            onClick={() => void navigator.clipboard.writeText(technicalResult).then(
                              () => showToast('技术详情已复制', 'success'),
                              () => showToast('复制失败', 'error'),
                            )}
                            className="mb-3"
                          >
                            复制技术详情
                          </Button>
                          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-[11px] leading-5 text-text-subtle">
                            {technicalResult.slice(0, 20_000)}
                            {technicalResult.length > 20_000 ? '\n\n[界面仅显示前 20000 个字符，复制仍包含完整记录]' : ''}
                          </pre>
                        </div>
                      </details>
                    ) : null}
                  </div>
                ) : (
                  <div className="border-t border-border/60 pt-4 text-sm text-text-muted">
                    点击上方按钮后，这里会显示设备状态、截图结果或屏幕读取结果。
                  </div>
                )}
              </section>
            </div>

          </div>
        </section>
      </div>
    </div>
  );
};
