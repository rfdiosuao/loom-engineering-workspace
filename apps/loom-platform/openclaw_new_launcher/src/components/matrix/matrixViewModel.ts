import { MATRIX_CAMPAIGN_SCHEMA } from '../../types/matrix';
import type {
  MatrixCampaign,
  MatrixCampaignStatus,
  MatrixDeviceSummary,
  MatrixDeviceTask,
  MatrixEvent,
  MatrixStatusSnapshot,
} from '../../types/matrix';

export type MatrixDeviceStatus = 'online_idle' | 'running' | 'waiting' | 'error' | 'offline';
export type MatrixDensity = 'compact' | 'balanced' | 'comfortable';

export interface MatrixDeviceView extends MatrixDeviceSummary {
  status: MatrixDeviceStatus;
  task?: MatrixDeviceTask;
  taskLabel: string;
  progressValue: number;
  lastScreenAt?: string;
}

export interface MatrixDeviceGroup {
  id: string;
  label: string;
  deviceIds: string[];
  abnormal: boolean;
}

export interface MatrixNavigationTarget {
  campaignId?: string;
  deviceId?: string;
}

export interface MatrixNavigationResolution {
  campaignFound: boolean;
  selectedIds: string[];
  focusedId?: string;
  groupId: string;
  missingDeviceId?: string;
}

export interface MatrixStreamHealthInput {
  enabled: boolean;
  hasSnapshot: boolean;
  syncHealthy: boolean;
  syncError: string;
  transportConnected: boolean;
  transportReconnecting: boolean;
  transportError: string;
}

export interface MatrixStreamPresentation {
  loading: boolean;
  connected: boolean;
  reconnecting: boolean;
  error: string;
}

interface MatrixManualControlInput {
  mode: 'ai' | 'manual';
  leasedDeviceId?: string;
  deviceId: string;
  hasFrame: boolean;
  screenError?: string;
}

interface MatrixDispatchConfirmationInput {
  prompt: string;
  templateId: string;
  mode: string;
  profile: string;
  selectedDeviceIds: Iterable<string>;
}

interface RectGeometry {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface SizeGeometry {
  width: number;
  height: number;
}

export function deriveMatrixStreamPresentation(input: MatrixStreamHealthInput): MatrixStreamPresentation {
  const error = input.syncError || input.transportError;
  const loading = input.enabled && !input.hasSnapshot && !input.syncError;
  const connected = (
    input.enabled
    && input.hasSnapshot
    && input.syncHealthy
    && input.transportConnected
    && !error
  );
  const reconnecting = (
    input.enabled
    && !loading
    && !connected
    && !error
    && input.transportReconnecting
  );
  return { loading, connected, reconnecting, error };
}

export function canUseMatrixManualControls(input: MatrixManualControlInput): boolean {
  return input.mode === 'manual' && input.leasedDeviceId === input.deviceId && input.hasFrame;
}

export function matrixDispatchFingerprint(input: MatrixDispatchConfirmationInput): string {
  return JSON.stringify([
    input.prompt,
    input.templateId,
    input.mode,
    input.profile,
    [...input.selectedDeviceIds].sort(),
  ]);
}

export function normalizeObjectContainPoint(
  container: RectGeometry,
  media: SizeGeometry,
  point: { x: number; y: number },
): { x: number; y: number } | null {
  if (container.width <= 0 || container.height <= 0 || media.width <= 0 || media.height <= 0) return null;
  const scale = Math.min(container.width / media.width, container.height / media.height);
  const renderedWidth = media.width * scale;
  const renderedHeight = media.height * scale;
  const left = container.left + (container.width - renderedWidth) / 2;
  const top = container.top + (container.height - renderedHeight) / 2;
  if (point.x < left || point.x > left + renderedWidth || point.y < top || point.y > top + renderedHeight) return null;
  return {
    x: Math.max(0, Math.min(1, (point.x - left) / renderedWidth)),
    y: Math.max(0, Math.min(1, (point.y - top) / renderedHeight)),
  };
}

export function supportedMatrixTaskActions(status: MatrixDeviceTask['status']): { pause: boolean; resume: boolean } {
  return {
    pause: status === 'queued' || status === 'running',
    resume: status === 'paused',
  };
}

const ACTIVE_TASK_STATUSES = new Set<MatrixDeviceTask['status']>(['preflight', 'running', 'retrying']);
const WAITING_TASK_STATUSES = new Set<MatrixDeviceTask['status']>(['queued', 'paused']);
const ERROR_TASK_STATUSES = new Set<MatrixDeviceTask['status']>(['failed', 'needs_human']);
const CANCELLABLE_TASK_STATUSES = new Set<MatrixDeviceTask['status']>([
  'queued',
  'preflight',
  'running',
  'retrying',
  'paused',
]);

const TASK_STATUS_ALIASES: Record<string, MatrixDeviceTask['status']> = {
  queued: 'queued',
  preflight: 'preflight',
  running: 'running',
  retrying: 'retrying',
  paused: 'paused',
  needs_human: 'needs_human',
  failed: 'failed',
  error: 'failed',
  cancelled: 'cancelled',
  canceled: 'cancelled',
  succeeded: 'completed',
  success: 'completed',
  completed: 'completed',
};

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : null;
}

function normalizeDeviceTask(value: unknown): MatrixDeviceTask | null {
  const raw = record(value);
  if (!raw) return null;
  const deviceTaskId = String(raw.deviceTaskId || '').trim();
  const deviceId = String(raw.deviceId || '').trim();
  const status = TASK_STATUS_ALIASES[String(raw.status || '').toLowerCase()];
  if (!deviceTaskId || !deviceId || !status) return null;
  const attempt = Number(raw.attempt);
  return {
    assignmentId: String(raw.assignmentId || deviceTaskId),
    deviceTaskId,
    deviceId,
    jobId: typeof raw.jobId === 'string' && raw.jobId ? raw.jobId : null,
    status,
    attempt: Number.isFinite(attempt) && attempt >= 0 ? attempt : 0,
    failureCode: typeof raw.failureCode === 'string' ? raw.failureCode : undefined,
    failureReason: typeof raw.failureReason === 'string' ? raw.failureReason : undefined,
  };
}

function campaignTasks(raw: Record<string, unknown>): MatrixDeviceTask[] {
  const directTasks = Array.isArray(raw.deviceTasks) ? raw.deviceTasks : [];
  const nestedTasks = Array.isArray(raw.missions)
    ? raw.missions.flatMap((mission) => {
      const value = record(mission);
      return value && Array.isArray(value.deviceTasks) ? value.deviceTasks : [];
    })
    : [];
  return (directTasks.length ? directTasks : nestedTasks)
    .map(normalizeDeviceTask)
    .filter((task): task is MatrixDeviceTask => Boolean(task));
}

function campaignStatus(rawStatus: unknown, tasks: MatrixDeviceTask[]): MatrixCampaignStatus {
  if (!tasks.length) {
    const status = String(rawStatus || '').toLowerCase();
    if (status === 'queued' || status === 'paused' || status === 'cancelled' || status === 'failed') return status;
    if (status === 'succeeded' || status === 'completed') return 'completed';
    return 'running';
  }
  const statuses = new Set(tasks.map((task) => task.status));
  if ([...statuses].every((status) => status === 'completed')) return 'completed';
  if ([...statuses].every((status) => status === 'cancelled')) return 'cancelled';
  if ([...statuses].every((status) => status === 'queued')) return 'queued';
  if ([...statuses].every((status) => status === 'paused')) return 'paused';
  if ([...statuses].some((status) => CANCELLABLE_TASK_STATUSES.has(status))) return 'running';
  if (statuses.has('failed') && statuses.size === 1) return 'failed';
  return 'partial';
}

export function normalizeMatrixCampaigns(value: unknown[] | undefined): MatrixCampaign[] {
  return (value || []).flatMap((item) => {
    const raw = record(item);
    const campaignId = String(raw?.campaignId || '').trim();
    if (!raw || !campaignId) return [];
    const deviceTasks = campaignTasks(raw);
    const total = deviceTasks.length;
    const concurrency = Number(raw.concurrency);
    return [{
      schema: MATRIX_CAMPAIGN_SCHEMA,
      campaignId,
      status: campaignStatus(raw.status, deviceTasks),
      concurrency: Number.isFinite(concurrency) && concurrency > 0 ? Math.floor(concurrency) : 1,
      counts: {
        total,
        queued: deviceTasks.filter((task) => task.status === 'queued').length,
        running: deviceTasks.filter((task) => ACTIVE_TASK_STATUSES.has(task.status)).length,
        completed: deviceTasks.filter((task) => task.status === 'completed').length,
        failed: deviceTasks.filter((task) => task.status === 'failed').length,
        needsHuman: deviceTasks.filter((task) => task.status === 'needs_human').length,
      },
      deviceTasks,
    }];
  });
}

export interface MatrixEmergencyScope {
  campaignIds: string[];
  requestDeviceIds: string[];
  affectedDeviceIds: string[];
  affectedTaskCount: number;
}

export function resolveCampaignAtomicEmergencyScope(
  campaigns: MatrixCampaign[],
  selectedDeviceIds: Iterable<string>,
): MatrixEmergencyScope {
  const selected = new Set(selectedDeviceIds);
  const matched = campaigns.filter((campaign) => campaign.deviceTasks.some((task) => (
    selected.has(task.deviceId) && CANCELLABLE_TASK_STATUSES.has(task.status)
  )));
  const affectedTasks = matched.flatMap((campaign) => (
    campaign.deviceTasks.filter((task) => CANCELLABLE_TASK_STATUSES.has(task.status))
  ));
  return {
    campaignIds: matched.map((campaign) => campaign.campaignId),
    requestDeviceIds: [...new Set(affectedTasks.filter((task) => selected.has(task.deviceId)).map((task) => task.deviceId))],
    affectedDeviceIds: [...new Set(affectedTasks.map((task) => task.deviceId))],
    affectedTaskCount: affectedTasks.length,
  };
}

export function deriveDeviceStatus(
  device: MatrixDeviceSummary,
  task?: MatrixDeviceTask,
): MatrixDeviceStatus {
  if (!device.online) return 'offline';
  if ((device.failureCount || 0) > 0 || (task && ERROR_TASK_STATUSES.has(task.status))) return 'error';
  if (device.busy || device.currentTaskId || (task && ACTIVE_TASK_STATUSES.has(task.status))) return 'running';
  if ((device.queue || 0) > 0 || (task && WAITING_TASK_STATUSES.has(task.status))) return 'waiting';
  return 'online_idle';
}

export function stableDeviceOrder(
  devices: MatrixDeviceSummary[],
  previousOrder: string[] = [],
): MatrixDeviceSummary[] {
  const byId = new Map(devices.map((device) => [device.deviceId, device]));
  const retained = previousOrder.filter((deviceId) => byId.has(deviceId));
  const retainedIds = new Set(retained);
  const appended = devices
    .map((device) => device.deviceId)
    .filter((deviceId) => !retainedIds.has(deviceId))
    .sort((left, right) => left.localeCompare(right, 'zh-CN'));
  return [...retained, ...appended].map((deviceId) => byId.get(deviceId)!);
}

function uniqueGroups(device: MatrixDeviceSummary): string[] {
  return [...new Set([device.group, ...(device.groups || [])].filter((value): value is string => Boolean(value?.trim())))]
    .sort((left, right) => left.localeCompare(right, 'zh-CN'));
}

export function buildDeviceGroups(devices: MatrixDeviceSummary[]): MatrixDeviceGroup[] {
  const groups = new Map<string, string[]>();
  for (const device of devices) {
    for (const group of uniqueGroups(device)) {
      const ids = groups.get(group) || [];
      if (!ids.includes(device.deviceId)) groups.set(group, [...ids, device.deviceId]);
    }
  }

  const abnormalIds = devices
    .filter((device) => !device.online || (device.failureCount || 0) > 0)
    .map((device) => device.deviceId);
  const result: MatrixDeviceGroup[] = [{
    id: 'all',
    label: '全部设备',
    deviceIds: devices.map((device) => device.deviceId),
    abnormal: false,
  }];
  for (const [id, deviceIds] of [...groups.entries()].sort(([left], [right]) => left.localeCompare(right, 'zh-CN'))) {
    result.push({ id, label: id, deviceIds, abnormal: false });
  }
  if (abnormalIds.length) {
    result.push({ id: 'abnormal', label: '异常设备', deviceIds: abnormalIds, abnormal: true });
  }
  return result;
}

export function resolveMatrixNavigation(
  devices: MatrixDeviceSummary[],
  campaigns: MatrixCampaign[],
  groups: MatrixDeviceGroup[],
  target: MatrixNavigationTarget,
): MatrixNavigationResolution {
  const knownIds = new Set(devices.map((device) => device.deviceId));
  const campaign = target.campaignId
    ? campaigns.find((item) => item.campaignId === target.campaignId)
    : undefined;
  const campaignIds = campaign
    ? [...new Set(campaign.deviceTasks.map((item) => item.deviceId).filter((deviceId) => knownIds.has(deviceId)))]
    : [];
  const missingDeviceId = target.deviceId && !knownIds.has(target.deviceId)
    ? target.deviceId
    : undefined;
  const focusedId = missingDeviceId
    ? undefined
    : target.deviceId || campaignIds[0];
  const selectedIds = campaignIds.length
    ? campaignIds
    : focusedId ? [focusedId] : [];
  const groupId = focusedId
    ? groups.find((group) => group.id !== 'all' && group.id !== 'abnormal' && group.deviceIds.includes(focusedId))?.id || 'all'
    : 'all';
  return {
    campaignFound: !target.campaignId || Boolean(campaign),
    selectedIds,
    focusedId,
    groupId,
    missingDeviceId,
  };
}

export function mergeMatrixSnapshot(
  current: MatrixStatusSnapshot | null,
  incoming: MatrixStatusSnapshot,
): MatrixStatusSnapshot {
  if (!current) return incoming;
  const incomingById = new Map(incoming.devices.map((device) => [device.deviceId, device]));
  const devices = current.devices.map((device) => {
    const update = incomingById.get(device.deviceId);
    if (!update) return device;
    incomingById.delete(device.deviceId);
    return { ...device, ...update };
  });
  devices.push(...incomingById.values());
  return {
    ...current,
    ...incoming,
    summary: { ...current.summary, ...incoming.summary },
    devices,
    campaigns: incoming.campaigns ?? current.campaigns,
  };
}

export function mergeMatrixEvents(current: MatrixEvent[], incoming: MatrixEvent[], limit = 200): MatrixEvent[] {
  const byKey = new Map<string, MatrixEvent>();
  for (const event of [...current, ...incoming]) {
    const key = event.eventId || [event.seq, event.type, event.deviceId, event.deviceTaskId, event.timestamp].join('|');
    byKey.set(key, event);
  }
  return [...byKey.values()]
    .sort((left, right) => (left.seq ?? 0) - (right.seq ?? 0) || String(left.timestamp).localeCompare(String(right.timestamp)))
    .slice(-limit);
}

function campaignsFromSnapshot(snapshot: MatrixStatusSnapshot | null): MatrixCampaign[] {
  return normalizeMatrixCampaigns(snapshot?.campaigns);
}

export function latestTasksByDevice(snapshot: MatrixStatusSnapshot | null): Map<string, MatrixDeviceTask> {
  const tasks = campaignsFromSnapshot(snapshot).flatMap((campaign) => campaign.deviceTasks);
  const result = new Map<string, MatrixDeviceTask>();
  for (const task of tasks) {
    result.set(task.deviceId, task);
  }
  return result;
}

export function buildDeviceViews(
  snapshot: MatrixStatusSnapshot | null,
  previousOrder: string[] = [],
): MatrixDeviceView[] {
  const tasks = latestTasksByDevice(snapshot);
  return stableDeviceOrder(snapshot?.devices || [], previousOrder).map((device) => {
    const task = tasks.get(device.deviceId);
    const status = deriveDeviceStatus(device, task);
    const progress = Math.max(0, Math.min(100, device.progress || (status === 'running' ? 5 : status === 'online_idle' ? 100 : 0)));
    return {
      ...device,
      status,
      task,
      taskLabel: device.currentScreenSummary
        || (task ? `${task.deviceTaskId} · ${task.status}` : status === 'online_idle' ? '等待任务' : '无活动任务'),
      progressValue: progress,
      lastScreenAt: device.lastEventAt || device.updatedAt || device.heartbeatAt,
    };
  });
}

export function visibleDeviceViews(
  devices: MatrixDeviceView[],
  group: MatrixDeviceGroup | undefined,
  query: string,
): MatrixDeviceView[] {
  const groupIds = new Set(group?.deviceIds || devices.map((device) => device.deviceId));
  const needle = query.trim().toLocaleLowerCase('zh-CN');
  return devices.filter((device) => {
    if (!groupIds.has(device.deviceId)) return false;
    if (!needle) return true;
    return [device.deviceId, device.name, device.account, device.model, device.currentPackage, device.foregroundApp]
      .some((value) => String(value || '').toLocaleLowerCase('zh-CN').includes(needle));
  });
}
