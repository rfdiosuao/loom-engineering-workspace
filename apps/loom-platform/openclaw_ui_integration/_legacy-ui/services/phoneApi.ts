import { invoke } from '@tauri-apps/api/core';

export interface PhoneConnectionConfig {
  id?: string;
  name?: string;
  baseUrl: string;
  token: string;
  relayBaseUrl?: string;
  relayChannelId?: string;
  relayToken?: string;
  launcherId?: string;
  launcherSecret?: string;
  secureChannelPairedAt?: string;
  visualizeActions?: boolean;
  useDeviceProfileContext?: boolean;
  enabled?: boolean;
  tags?: string[];
  lastSeenAt?: string;
}

export interface PhoneDeviceStore {
  version: 1;
  selectedDeviceId: string | null;
  devices: PhoneConnectionConfig[];
  updatedAt?: string;
}

export interface PhoneApiResult<T> {
  ok: boolean;
  data?: T;
  error?: string;
  raw?: unknown;
}

export interface PhoneStatus {
  online: boolean;
  taskRunning: boolean;
  agentInitialized: boolean;
  llmConfigured: boolean;
  accessibilityRunning: boolean;
  screenshotSupported?: boolean;
  screenInfoSupported?: boolean;
  overlayPermission?: boolean;
  cursorOverlayEnabled?: boolean;
  cursorPreviewSupported?: boolean;
  screenOn?: boolean;
  interactive?: boolean;
  keyguardLocked?: boolean;
  deviceLocked?: boolean;
  version?: string;
  versionCode?: number;
  versionInfo?: string;
  serverPort?: number;
}

export interface PhoneWakeState {
  screenOn?: boolean;
  interactive?: boolean;
  keyguardLocked?: boolean;
  deviceLocked?: boolean;
}

export interface PhoneWakeResult extends PhoneWakeState {
  wakeAttempted?: boolean;
  wakeRequested?: boolean;
  message?: string;
  before?: PhoneWakeState;
  after?: PhoneWakeState;
}

export interface PhoneScreenshot {
  mime: string;
  base64: string;
  dataUrl: string;
  capturedAt: string;
  width?: number;
  height?: number;
  orientation?: string;
}

export interface PhoneTapRequest {
  x: number;
  y: number;
  durationMs?: number;
  traceId?: string;
  visualize?: boolean;
}

export interface PhoneTapResult {
  x: number;
  y: number;
  durationMs?: number;
  traceId?: string;
  visualize?: boolean;
  executedAt?: string;
  message?: string;
}

export interface PhoneLongPressRequest {
  x: number;
  y: number;
  durationMs?: number;
  traceId?: string;
  visualize?: boolean;
}

export interface PhoneLongPressResult {
  x: number;
  y: number;
  durationMs?: number;
  traceId?: string;
  executedAt?: string;
  message?: string;
}

export interface PhoneSwipeRequest {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  durationMs?: number;
  traceId?: string;
  visualize?: boolean;
}

export interface PhoneSwipeResult {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  durationMs?: number;
  traceId?: string;
  executedAt?: string;
  message?: string;
}

export interface PhoneDragRequest {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  holdMs?: number;
  durationMs?: number;
  traceId?: string;
  visualize?: boolean;
}

export interface PhoneDragResult {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  holdMs?: number;
  durationMs?: number;
  traceId?: string;
  executedAt?: string;
  message?: string;
}

export interface PhoneVisionFrameOptions {
  includeScreenshot?: boolean;
  overlayGrid?: boolean;
  format?: 'jpeg' | 'png';
  quality?: number;
  maxLongSide?: number;
  gridColumns?: number;
  gridRows?: number;
}

export interface PhoneRelayScreenshotOptions extends PhoneVisionFrameOptions {
  waitSec?: number;
  pollMs?: number;
}

export interface PhoneVisionImage {
  mime: string;
  base64: string;
  dataUrl: string;
  width?: number;
  height?: number;
  originalWidth?: number;
  originalHeight?: number;
  orientation?: string;
  format?: string;
  quality?: number;
  overlayGrid?: boolean;
  maxLongSide?: number;
}

export interface PhoneVisionCoordinateSpace {
  screenWidth?: number;
  screenHeight?: number;
  imageWidth?: number;
  imageHeight?: number;
  actionCoordinates?: string;
  imageToScreenX?: number;
  imageToScreenY?: number;
  grid?: {
    columns?: number;
    rows?: number;
    cellFormat?: string;
    firstCell?: string;
    lastCell?: string;
  };
}

export interface PhoneVisionFrame {
  mode?: string;
  capturedAt?: string;
  currentScreen?: Record<string, unknown>;
  vision?: Record<string, unknown>;
  input?: Record<string, unknown>;
  safety?: Record<string, unknown>;
  image?: PhoneVisionImage;
  coordinateSpace?: PhoneVisionCoordinateSpace;
}

export interface PhoneVisionPoint {
  x?: number;
  y?: number;
  nx?: number;
  ny?: number;
  imageX?: number;
  imageY?: number;
  gridCell?: string;
}

export interface PhoneVisionActionRequest extends PhoneVisionPoint {
  action: 'tap' | 'long_press' | 'swipe' | 'drag' | string;
  start?: PhoneVisionPoint;
  end?: PhoneVisionPoint;
  from?: PhoneVisionPoint;
  to?: PhoneVisionPoint;
  imageWidth?: number;
  imageHeight?: number;
  screenWidth?: number;
  screenHeight?: number;
  gridColumns?: number;
  gridRows?: number;
  durationMs?: number;
  holdMs?: number;
  traceId?: string;
  visualize?: boolean;
}

export interface PhoneVisionActionResult {
  action?: string;
  blocked?: boolean;
  safety?: Record<string, unknown>;
  point?: Record<string, unknown>;
  start?: Record<string, unknown>;
  end?: Record<string, unknown>;
  durationMs?: number;
  holdMs?: number;
  traceId?: string;
  visualize?: boolean;
  executedAt?: string;
  message?: string;
}

export interface PhoneAgentTaskRequest {
  prompt: string;
  useTemplate?: boolean;
  forceAgent?: boolean;
  learnTemplate?: boolean;
  readOnly?: boolean;
  toolPolicy?: 'observe_only' | 'safe_action' | 'full_access';
  templateParams?: Record<string, string>;
  timeoutSec?: number;
}

export interface PhoneAgentEvent {
  type: string;
  round: number;
  time?: number;
  toolId?: string;
  toolName?: string;
  parameters?: string;
  success?: boolean;
  message?: string;
}

export interface PhoneAgentTaskResult {
  success: boolean;
  mode?: 'agent' | 'template' | string;
  readOnly?: boolean;
  toolPolicy?: string;
  answer?: string;
  error?: string;
  rounds?: number;
  tokens?: number;
  templateId?: string;
  templateName?: string;
  stepsExecuted?: number;
  stepsTotal?: number;
  executionTimeMs?: number;
  events?: PhoneAgentEvent[];
}

export interface PhoneAgentAsyncTask {
  taskId: string;
  status: 'queued' | 'running' | 'success' | 'error' | 'cancelled' | string;
  prompt?: string;
  createdAt?: number;
  startedAt?: number;
  finishedAt?: number;
  error?: string;
  result?: PhoneAgentTaskResult;
  events?: PhoneAgentEvent[];
}

export interface PhoneCursorPreviewRequest {
  x?: number;
  y?: number;
  action?: 'tap' | 'long_press' | 'swipe' | 'drag' | string;
  durationMs?: number;
  traceId?: string;
}

export interface PhoneCursorPreviewResult {
  x: number;
  y: number;
  action: string;
  durationMs?: number;
  traceId?: string;
  enabled?: boolean;
}

export interface PhoneInstalledApp {
  label: string;
  packageName: string;
  activityName?: string;
  launchable?: boolean;
}

export interface PhoneDeviceProfile {
  profileVersion?: number;
  capturedAt?: number;
  device?: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
  memory?: Record<string, unknown>;
  storage?: Record<string, unknown>;
  battery?: Record<string, unknown>;
  currentScreen?: Record<string, unknown>;
  vision?: Record<string, unknown>;
  publicDirectories?: Array<Record<string, unknown>>;
  apps?: PhoneInstalledApp[];
  privacyNote?: string;
}

export type PhoneInitializationTone = 'ok' | 'warn' | 'error' | 'info';

export interface PhoneInitializationCheck {
  id: string;
  label: string;
  value: string;
  ok: boolean;
  tone: PhoneInitializationTone;
  detail?: string;
}

export interface PhoneInitializationReport {
  generatedAt: string;
  summary: string;
  passed: number;
  total: number;
  preferredBrowser?: PhoneInstalledApp;
  recommendations: string[];
  checks: PhoneInitializationCheck[];
}

export interface PhoneDeviceProfileCache {
  baseUrl: string;
  savedAt: string;
  profile: PhoneDeviceProfile;
  healthReport?: PhoneInitializationReport;
}

export interface PhoneScreenBounds {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
  centerX: number;
  centerY: number;
}

export interface PhoneScreenNode {
  id: string;
  parentId?: string | null;
  depth: number;
  className: string;
  text?: string | null;
  description?: string | null;
  resourceId?: string | null;
  packageName?: string | null;
  clickable?: boolean;
  longClickable?: boolean;
  scrollable?: boolean;
  editable?: boolean;
  checkable?: boolean;
  checked?: boolean;
  enabled?: boolean;
  focused?: boolean;
  selected?: boolean;
  visible?: boolean;
  slider?: boolean;
  loading?: boolean;
  bounds: PhoneScreenBounds;
}

export interface PhoneScreenTree {
  screen: {
    width?: number;
    height?: number;
    orientation?: string;
  };
  nodes: PhoneScreenNode[];
}

export interface PhoneMediaImportResult {
  uri?: string;
  contentUri?: string;
  relativePath?: string;
  path?: string;
  filename?: string;
  mime?: string;
  size?: number;
  width?: number;
  height?: number;
  message?: string;
}

export interface PhoneScreenRecordFile {
  exists: boolean;
  id?: string;
  filename?: string;
  path?: string;
  sizeBytes?: number;
  modifiedAt?: string;
  downloadUrl?: string;
  mimeType?: string;
}

export interface PhoneScreenRecordStatus {
  state: 'idle' | 'requesting_permission' | 'recording' | 'error' | string;
  recording: boolean;
  accepted?: boolean;
  reason?: string;
  requiresUserConsent?: boolean;
  startedAt?: string;
  durationMs?: number;
  width?: number;
  height?: number;
  lastError?: string;
  current?: PhoneScreenRecordFile;
  latest?: PhoneScreenRecordFile;
}

export interface PhoneScreenRecordStartRequest {
  filename?: string;
  maxSeconds?: number;
  fps?: number;
  bitRate?: number;
  width?: number;
  height?: number;
}

export interface PhoneVideoListResult {
  recordings: PhoneScreenRecordFile[];
}

const STORAGE_KEY = 'lumi_phone_connector_config';
const DEVICE_STORE_KEY = 'lumi_phone_connector_devices';
const DEVICE_PROFILE_STORAGE_PREFIX = 'lumi_phone_device_profile';
const LUMI_LAUNCHER_ID_HEADER = 'X-LUMI-LAUNCHER-ID';
const LUMI_TIMESTAMP_HEADER = 'X-LUMI-TIMESTAMP';
const LUMI_NONCE_HEADER = 'X-LUMI-NONCE';
const LUMI_SIGNATURE_HEADER = 'X-LUMI-SIGNATURE';
const LUMI_BODY_SHA256_HEADER = 'X-LUMI-BODY-SHA256';
const DEFAULT_PHONE_NAME = 'Android Phone';
const PREFERRED_BROWSER_PACKAGES = new Set(['mark.via', 'mark.via.gp']);
const PHONE_PORT_SCAN_RANGE = Array.from({ length: 10 }, (_, index) => 9527 + index);
const PHONE_STATUS_TIMEOUT_MS = 5000;
const PHONE_STATUS_FALLBACK_TIMEOUT_MS = 3500;
const PHONE_REQUEST_TIMEOUT_MS = 30000;
const PHONE_AGENT_TASK_TIMEOUT_SEC = 600;
const PHONE_AGENT_TASK_TIMEOUT_MS = PHONE_AGENT_TASK_TIMEOUT_SEC * 1000 + 15000;
const DEFAULT_CONFIG: PhoneConnectionConfig = {
  id: 'android-phone',
  name: DEFAULT_PHONE_NAME,
  baseUrl: 'http://192.168.1.100:9527',
  token: '',
  relayBaseUrl: '',
  relayChannelId: '',
  relayToken: '',
  visualizeActions: true,
  useDeviceProfileContext: true,
  enabled: true,
  tags: [],
};

type PhoneRequestOptions = RequestInit & {
  timeoutMs?: number;
  extraHeaders?: Record<string, string>;
};

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '');
}

function parseBaseUrl(baseUrl: string): URL | null {
  const normalized = normalizeBaseUrl(baseUrl);
  if (!normalized) return null;
  try {
    return new URL(normalized);
  } catch {
    return null;
  }
}

function isLocalPhoneHost(hostname: string): boolean {
  const value = hostname.trim().toLowerCase();
  if (!value) return false;
  if (value === 'localhost' || value === '127.0.0.1' || value === '::1') return true;

  const ipv4 = value.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!ipv4) return false;

  const first = Number(ipv4[1]);
  const second = Number(ipv4[2]);
  return first === 10 || first === 127 || (first === 192 && second === 168) || (first === 172 && second >= 16 && second <= 31);
}

function withPort(baseUrl: string, port: number): string {
  const url = parseBaseUrl(baseUrl);
  if (!url) return normalizeBaseUrl(baseUrl);
  url.port = String(port);
  url.pathname = '';
  url.search = '';
  url.hash = '';
  return url.toString().replace(/\/+$/, '');
}

function buildPhoneBaseUrlCandidates(baseUrl: string): string[] {
  const normalized = normalizeBaseUrl(baseUrl);
  const parsed = parseBaseUrl(normalized);
  if (!parsed || !isLocalPhoneHost(parsed.hostname)) {
    return normalized ? [normalized] : [];
  }

  const ports = new Set<number>();
  const currentPort = parsed.port ? Number(parsed.port) : 9527;
  if (Number.isFinite(currentPort) && currentPort > 0) {
    ports.add(currentPort);
  }
  PHONE_PORT_SCAN_RANGE.forEach((port) => ports.add(port));

  return Array.from(ports).map((port) => withPort(normalized, port));
}

function profileStorageKey(config: PhoneConnectionConfig): string {
  const source = (config.id || normalizeBaseUrl(config.baseUrl).toLowerCase() || 'default').trim();
  const safe = source.replace(/[^a-z0-9]+/gi, '_').replace(/^_+|_+$/g, '') || 'default';
  return `${DEVICE_PROFILE_STORAGE_PREFIX}_${safe}`;
}

function slugifyDeviceName(value: string): string {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/https?:\/\//g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return normalized || 'phone-device';
}

function createPhoneDeviceId(config: Partial<PhoneConnectionConfig>, existingIds: Set<string> = new Set()): string {
  const url = parseBaseUrl(String(config.baseUrl || ''));
  const host = url?.hostname ? slugifyDeviceName(url.hostname) : '';
  const port = url?.port ? `-${url.port}` : '';
  const name = slugifyDeviceName(String(config.name || ''));
  const base = [name || 'phone', host].filter(Boolean).join('-') || `phone${port || ''}`;
  let candidate = `${base}${port}`.replace(/-+/g, '-');
  if (!candidate) candidate = 'phone-device';
  let counter = 2;
  while (existingIds.has(candidate)) {
    candidate = `${base}${port}-${counter}`;
    counter += 1;
  }
  return candidate;
}

function normalizeTags(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter(Boolean)
    .slice(0, 12);
}

function normalizePhoneConfig(
  config: Partial<PhoneConnectionConfig>,
  existingIds: Set<string> = new Set(),
  preferredId?: string
): PhoneConnectionConfig {
  const requestedId = typeof config.id === 'string' ? config.id.trim() : '';
  const existingIdSet = new Set(existingIds);
  if (requestedId) {
    existingIdSet.delete(requestedId);
  }
  if (preferredId) {
    existingIdSet.delete(preferredId);
  }
  const id = preferredId || requestedId || createPhoneDeviceId(config, existingIdSet);
  return {
    id,
    name: typeof config.name === 'string' ? config.name : DEFAULT_PHONE_NAME,
    baseUrl: typeof config.baseUrl === 'string' ? config.baseUrl.trim() : '',
    token: String(config.token || '').trim(),
    relayBaseUrl: typeof config.relayBaseUrl === 'string' ? config.relayBaseUrl.trim() : '',
    relayChannelId: typeof config.relayChannelId === 'string' ? config.relayChannelId.trim() : '',
    relayToken: typeof config.relayToken === 'string' ? config.relayToken.trim() : '',
    launcherId: typeof config.launcherId === 'string' ? config.launcherId : undefined,
    launcherSecret: typeof config.launcherSecret === 'string' ? config.launcherSecret : undefined,
    secureChannelPairedAt:
      typeof config.secureChannelPairedAt === 'string' ? config.secureChannelPairedAt : undefined,
    visualizeActions: config.visualizeActions !== false,
    useDeviceProfileContext: config.useDeviceProfileContext !== false,
    enabled: config.enabled !== false,
    tags: normalizeTags(config.tags),
    lastSeenAt: typeof config.lastSeenAt === 'string' ? config.lastSeenAt : undefined,
  };
}

function buildDefaultDeviceStore(): PhoneDeviceStore {
  const device = normalizePhoneConfig(DEFAULT_CONFIG);
  return {
    version: 1,
    selectedDeviceId: device.id || null,
    devices: [device],
    updatedAt: new Date().toISOString(),
  };
}

function dedupeDeviceIds(configs: Partial<PhoneConnectionConfig>[]): PhoneConnectionConfig[] {
  const usedIds = new Set<string>();
  return configs.map((config) => {
    const normalized = normalizePhoneConfig(config, usedIds);
    if (normalized.id) {
      usedIds.add(normalized.id);
    }
    return normalized;
  });
}

export function loadPhoneDeviceStore(): PhoneDeviceStore {
  try {
    const raw = window.localStorage.getItem(DEVICE_STORE_KEY);
    if (!raw) {
      const legacy = loadPhoneConfig();
      return {
        version: 1,
        selectedDeviceId: legacy.id || null,
        devices: [legacy],
        updatedAt: new Date().toISOString(),
      };
    }
    const parsed = JSON.parse(raw) as Partial<PhoneDeviceStore>;
    const devices = dedupeDeviceIds(Array.isArray(parsed?.devices) ? parsed.devices : []);
    if (!devices.length) {
      return buildDefaultDeviceStore();
    }
    const selectedDeviceId =
      typeof parsed?.selectedDeviceId === 'string' && devices.some((device) => device.id === parsed.selectedDeviceId)
        ? parsed.selectedDeviceId
        : devices[0].id || null;
    return {
      version: 1,
      selectedDeviceId,
      devices,
      updatedAt: typeof parsed?.updatedAt === 'string' ? parsed.updatedAt : undefined,
    };
  } catch {
    const legacy = loadPhoneConfig();
    return {
      version: 1,
      selectedDeviceId: legacy.id || null,
      devices: [legacy],
      updatedAt: new Date().toISOString(),
    };
  }
}

export function savePhoneDeviceStore(store: PhoneDeviceStore): PhoneDeviceStore {
  const devices = dedupeDeviceIds(store.devices);
  const selectedDeviceId =
    store.selectedDeviceId && devices.some((device) => device.id === store.selectedDeviceId)
      ? store.selectedDeviceId
      : devices[0]?.id || null;
  const clean: PhoneDeviceStore = {
    version: 1,
    selectedDeviceId,
    devices,
    updatedAt: new Date().toISOString(),
  };
  window.localStorage.setItem(DEVICE_STORE_KEY, JSON.stringify(clean));
  return clean;
}

export function loadPhoneDevices(): PhoneConnectionConfig[] {
  return loadPhoneDeviceStore().devices;
}

export function loadSelectedPhoneDeviceId(): string | null {
  return loadPhoneDeviceStore().selectedDeviceId;
}

export function setSelectedPhoneDeviceId(deviceId: string | null): PhoneDeviceStore {
  const store = loadPhoneDeviceStore();
  return savePhoneDeviceStore({
    ...store,
    selectedDeviceId: deviceId,
  });
}

export function upsertPhoneDevice(config: PhoneConnectionConfig): PhoneDeviceStore {
  const store = loadPhoneDeviceStore();
  const devices = [...store.devices];
  const index = devices.findIndex((device) => device.id === config.id);
  const usedIds = new Set(devices.filter((_, currentIndex) => currentIndex !== index).map((device) => device.id || ''));
  const normalized = normalizePhoneConfig(config, usedIds, config.id);
  if (index >= 0) {
    devices[index] = normalized;
  } else {
    devices.push(normalized);
  }
  return savePhoneDeviceStore({
    ...store,
    selectedDeviceId: normalized.id || store.selectedDeviceId,
    devices,
  });
}

export function removePhoneDevice(deviceId: string): PhoneDeviceStore {
  const store = loadPhoneDeviceStore();
  const devices = store.devices.filter((device) => device.id !== deviceId);
  const nextStore =
    devices.length > 0
      ? {
          ...store,
          devices,
          selectedDeviceId:
            store.selectedDeviceId === deviceId ? devices[0].id || null : store.selectedDeviceId,
        }
      : buildDefaultDeviceStore();
  return savePhoneDeviceStore(nextStore);
}

export function getSelectedPhoneConfig(deviceId?: string | null): PhoneConnectionConfig {
  const store = loadPhoneDeviceStore();
  const selected =
    (deviceId ? store.devices.find((device) => device.id === deviceId) : undefined) ||
    store.devices.find((device) => device.id === store.selectedDeviceId) ||
    store.devices[0];
  return selected ? { ...selected } : normalizePhoneConfig(DEFAULT_CONFIG);
}

function asObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function parseMaybeJsonObject(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try {
      return asObject(JSON.parse(value));
    } catch {
      return {};
    }
  }
  return asObject(value);
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function formatProfileBytes(value: unknown): string {
  const bytes = asNumber(value);
  if (!bytes || bytes <= 0) return 'unknown';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unit]}`;
}

function isViaBrowserApp(app: PhoneInstalledApp): boolean {
  const label = app.label.toLowerCase();
  const packageName = app.packageName.toLowerCase();
  return PREFERRED_BROWSER_PACKAGES.has(packageName) || packageName.startsWith('mark.via') || label === 'via' || label.includes('via browser');
}

function appSortRank(app: PhoneInstalledApp): number {
  return isViaBrowserApp(app) ? 0 : 1;
}

function sortProfileApps(apps: PhoneInstalledApp[]): PhoneInstalledApp[] {
  return [...apps].sort((a, b) => {
    const rank = appSortRank(a) - appSortRank(b);
    if (rank !== 0) return rank;
    const label = a.label.localeCompare(b.label, undefined, { sensitivity: 'base' });
    if (label !== 0) return label;
    return a.packageName.localeCompare(b.packageName);
  });
}

function payloadData(payload: unknown): unknown {
  const body = asObject(payload);
  return body.data ?? payload;
}

function dataUrlToBlob(dataUrl: string): { blob: Blob; mime: string } {
  const match = /^data:([^;,]+)?(;base64)?,(.*)$/s.exec(dataUrl);
  if (!match) throw new Error('invalid_data_url');
  const mime = match[1] || 'image/png';
  const isBase64 = Boolean(match[2]);
  const payload = match[3] || '';
  const binary = isBase64 ? window.atob(payload) : decodeURIComponent(payload);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return { blob: new Blob([bytes], { type: mime }), mime };
}

function normalizeRelayBaseUrl(baseUrl: string): string {
  return String(baseUrl || '').trim().replace(/\/+$/, '');
}

export function hasRelayScreenshotConfig(config: PhoneConnectionConfig): boolean {
  return Boolean(
    normalizeRelayBaseUrl(config.relayBaseUrl || '') &&
      String(config.relayChannelId || '').trim() &&
      String(config.relayToken || '').trim()
  );
}

function relayAuthHeaders(relayToken: string, headers: Record<string, string> = {}): Record<string, string> {
  if (!relayToken.trim()) return headers;
  return {
    ...headers,
    Authorization: `Bearer ${relayToken.trim()}`,
    'X-OpenClaw-Relay-Token': relayToken.trim(),
  };
}

function headersToRecord(headers?: HeadersInit): Record<string, string> {
  if (!headers) return {};
  if (headers instanceof Headers) {
    return Object.fromEntries(headers.entries());
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers.map(([key, value]) => [key, String(value)]));
  }
  return Object.fromEntries(
    Object.entries(headers).map(([key, value]) => [key, String(value)])
  );
}

async function fetchJsonWithTimeout(url: string, options: RequestInit = {}, timeoutMs = PHONE_REQUEST_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeout);
  }
}

async function readJsonResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text.trim()) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function relayUrl(baseUrl: string, endpoint: string): string {
  const normalized = normalizeRelayBaseUrl(baseUrl);
  if (!normalized) return '';
  const base = normalized.endsWith('/') ? normalized : `${normalized}/`;
  return new URL(endpoint.replace(/^\//, ''), base).toString();
}

async function requestRelayJson(
  relayBaseUrl: string,
  endpoint: string,
  options: RequestInit = {},
  token = '',
  timeoutMs = PHONE_REQUEST_TIMEOUT_MS
): Promise<{ ok: boolean; data?: unknown; error?: string; raw?: unknown }> {
  const url = relayUrl(relayBaseUrl, endpoint);
  if (!url) return { ok: false, error: 'missing_relay_base_url' };
  const response = await fetchJsonWithTimeout(url, {
    ...options,
    headers: relayAuthHeaders(token, {
      Accept: 'application/json',
      ...headersToRecord(options.headers),
    }),
  }, timeoutMs);
  const payload = await readJsonResponse(response);
  if (!response.ok) {
    const body = asObject(payload);
    return {
      ok: false,
      error: body.error ? String(body.error) : `relay_http_${response.status}`,
      raw: payload,
    };
  }
  return { ok: true, data: payload, raw: payload };
}

function transformRelayScreenshotResult(result: unknown): PhoneScreenshot {
  return transformScreenshot({ data: result });
}

async function waitForRelayRecord(
  relayBaseUrl: string,
  packetId: string,
  relayToken: string,
  waitSec: number,
  pollMs: number
): Promise<PhoneApiResult<Record<string, unknown>>> {
  const deadline = Date.now() + Math.max(5, waitSec) * 1000;
  let lastRecord: Record<string, unknown> | null = null;

  while (Date.now() <= deadline) {
    const status = await requestRelayJson(
      relayBaseUrl,
      `/api/lumi/relay/status?id=${encodeURIComponent(packetId)}`,
      { method: 'GET' },
      relayToken,
      Math.max(5000, pollMs + 5000)
    );
    if (!status.ok) {
      return { ok: false, error: status.error || 'relay_status_failed', raw: status.raw };
    }
    const record = asObject(payloadData(status.data));
    lastRecord = record;
    if (record.status === 'done') {
      return { ok: true, data: record, raw: status.raw };
    }
    if (record.status === 'failed') {
      return {
        ok: false,
        data: record,
        error: asString(record.lastError) || 'relay_packet_failed',
        raw: status.raw,
      };
    }
    await new Promise((resolve) => window.setTimeout(resolve, Math.max(500, pollMs)));
  }

  return {
    ok: false,
    data: lastRecord || undefined,
    error: 'relay_timeout',
  };
}

function transformMediaImport(payload: unknown): PhoneMediaImportResult {
  const data = asObject(payloadData(payload));
  return {
    uri: asString(data.uri),
    contentUri: asString(data.contentUri) || asString(data.uri),
    relativePath: asString(data.relativePath),
    path: asString(data.path),
    filename: asString(data.filename) || asString(data.fileName),
    mime: asString(data.mime) || asString(data.mimeType),
    size: asNumber(data.size),
    width: asNumber(data.width),
    height: asNumber(data.height),
    message: asString(data.message),
  };
}

function transformScreenRecordFile(value: unknown): PhoneScreenRecordFile {
  const data = asObject(value);
  return {
    exists: asBoolean(data.exists) ?? false,
    id: asString(data.id),
    filename: asString(data.filename),
    path: asString(data.path),
    sizeBytes: asNumber(data.sizeBytes),
    modifiedAt: asString(data.modifiedAt),
    downloadUrl: asString(data.downloadUrl),
    mimeType: asString(data.mimeType),
  };
}

function transformScreenRecordStatus(payload: unknown): PhoneScreenRecordStatus {
  const data = asObject(payloadData(payload));
  return {
    state: asString(data.state) || 'unknown',
    recording: asBoolean(data.recording) ?? false,
    accepted: asBoolean(data.accepted),
    reason: asString(data.reason),
    requiresUserConsent: asBoolean(data.requiresUserConsent),
    startedAt: asString(data.startedAt),
    durationMs: asNumber(data.durationMs),
    width: asNumber(data.width),
    height: asNumber(data.height),
    lastError: asString(data.lastError),
    current: transformScreenRecordFile(data.current),
    latest: transformScreenRecordFile(data.latest),
  };
}

function transformVideoList(payload: unknown): PhoneVideoListResult {
  const data = asObject(payloadData(payload));
  const recordings = Array.isArray(data.recordings) ? data.recordings.map(transformScreenRecordFile) : [];
  return { recordings };
}

function transformVisionFrame(payload: unknown): PhoneVisionFrame {
  const data = asObject(payloadData(payload));
  const image = asObject(data.image);
  const mime = asString(image.mime) || 'image/jpeg';
  const base64 = asString(image.base64) || '';
  const coordinateSpace = asObject(data.coordinateSpace);
  const grid = asObject(coordinateSpace.grid);
  return {
    mode: asString(data.mode),
    capturedAt: asString(data.capturedAt),
    currentScreen: asObject(data.currentScreen),
    vision: asObject(data.vision),
    input: asObject(data.input),
    safety: asObject(data.safety),
    image: base64
      ? {
          mime,
          base64,
          dataUrl: `data:${mime};base64,${base64}`,
          width: asNumber(image.width),
          height: asNumber(image.height),
          originalWidth: asNumber(image.originalWidth),
          originalHeight: asNumber(image.originalHeight),
          orientation: asString(image.orientation),
          format: asString(image.format),
          quality: asNumber(image.quality),
          overlayGrid: asBoolean(image.overlayGrid),
          maxLongSide: asNumber(image.maxLongSide),
        }
      : undefined,
    coordinateSpace: {
      screenWidth: asNumber(coordinateSpace.screenWidth),
      screenHeight: asNumber(coordinateSpace.screenHeight),
      imageWidth: asNumber(coordinateSpace.imageWidth),
      imageHeight: asNumber(coordinateSpace.imageHeight),
      actionCoordinates: asString(coordinateSpace.actionCoordinates),
      imageToScreenX: asNumber(coordinateSpace.imageToScreenX),
      imageToScreenY: asNumber(coordinateSpace.imageToScreenY),
      grid: {
        columns: asNumber(grid.columns),
        rows: asNumber(grid.rows),
        cellFormat: asString(grid.cellFormat),
        firstCell: asString(grid.firstCell),
        lastCell: asString(grid.lastCell),
      },
    },
  };
}

function transformVisionAction(payload: unknown): PhoneVisionActionResult {
  const data = asObject(payloadData(payload));
  return {
    action: asString(data.action),
    blocked: asBoolean(data.blocked),
    safety: asObject(data.safety),
    point: asObject(data.point),
    start: asObject(data.start),
    end: asObject(data.end),
    durationMs: asNumber(data.durationMs),
    holdMs: asNumber(data.holdMs),
    traceId: asString(data.traceId),
    visualize: asBoolean(data.visualize),
    executedAt: asString(data.executedAt),
    message: asString(data.message),
  };
}

interface LumiPairingResult {
  paired: boolean;
  launcherId: string;
  launcherName?: string;
  launcherSecret: string;
  pairedAt?: number;
  algorithm?: string;
  signatureVersion?: number;
}

function transformLumiPairing(payload: unknown): LumiPairingResult {
  const data = asObject(payloadData(payload));
  return {
    paired: asBoolean(data.paired) ?? true,
    launcherId: asString(data.launcherId) || '',
    launcherName: asString(data.launcherName),
    launcherSecret: asString(data.launcherSecret) || '',
    pairedAt: asNumber(data.pairedAt),
    algorithm: asString(data.algorithm),
    signatureVersion: asNumber(data.signatureVersion),
  };
}

function randomHex(bytes = 8): string {
  const data = new Uint8Array(bytes);
  window.crypto.getRandomValues(data);
  return Array.from(data).map((value) => value.toString(16).padStart(2, '0')).join('');
}

function createLauncherId(): string {
  if (typeof window.crypto.randomUUID === 'function') {
    return `openclaw-${window.crypto.randomUUID()}`;
  }
  return `openclaw-${Date.now().toString(36)}-${randomHex(8)}`;
}

function arrayBufferToBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return window.btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function hmacBase64Url(secret: string, text: string): Promise<string> {
  const key = await window.crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const signature = await window.crypto.subtle.sign('HMAC', key, new TextEncoder().encode(text));
  return arrayBufferToBase64Url(signature);
}

async function buildLumiHeaders(
  config: PhoneConnectionConfig,
  method: string,
  path: string,
  body: string
): Promise<Record<string, string>> {
  if (!config.launcherId || !config.launcherSecret) {
    throw new Error('missing_lumi_pairing');
  }
  const timestamp = String(Date.now());
  const nonce = randomHex(16);
  const bodyHash = await sha256Hex(body);
  const signatureInput = [
    method.toUpperCase(),
    path,
    timestamp,
    nonce,
    bodyHash,
  ].join('\n');
  const signature = await hmacBase64Url(config.launcherSecret, signatureInput);
  return {
    [LUMI_LAUNCHER_ID_HEADER]: config.launcherId,
    [LUMI_TIMESTAMP_HEADER]: timestamp,
    [LUMI_NONCE_HEADER]: nonce,
    [LUMI_BODY_SHA256_HEADER]: bodyHash,
    [LUMI_SIGNATURE_HEADER]: signature,
  };
}

async function request<T>(
  config: PhoneConnectionConfig,
  path: string,
  options: PhoneRequestOptions = {},
  transform: (payload: unknown) => T
): Promise<PhoneApiResult<T>> {
  const baseUrl = normalizeBaseUrl(config.baseUrl);
  if (!baseUrl) return { ok: false, error: 'missing_base_url' };
  if (!config.token.trim()) return { ok: false, error: 'missing_token' };

  return requestAtBaseUrl(baseUrl, config.token, path, options, transform);
}

async function requestAtBaseUrl<T>(
  baseUrl: string,
  token: string,
  path: string,
  options: PhoneRequestOptions = {},
  transform: (payload: unknown) => T
): Promise<PhoneApiResult<T>> {
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl);
  if (!normalizedBaseUrl) return { ok: false, error: 'missing_base_url' };
  if (!token.trim()) return { ok: false, error: 'missing_token' };

  let responseText: string;
  try {
    responseText = await invoke<string>('phone_proxy_request', {
      baseUrl: normalizedBaseUrl,
      path,
      method: String(options.method || 'GET').toUpperCase(),
      body: typeof options.body === 'string' ? options.body : undefined,
      token,
      timeoutMs: options.timeoutMs ?? PHONE_REQUEST_TIMEOUT_MS,
      extraHeaders: options.extraHeaders,
    });
  } catch (error: any) {
    const message = String(error?.message || error || 'network_error');
    if (message.includes('[401]')) return { ok: false, error: 'unauthorized' };
    return { ok: false, error: message };
  }

  let payload: unknown;
  try {
    payload = JSON.parse(responseText);
  } catch {
    return { ok: false, error: 'invalid_response' };
  }

  const body = asObject(payload);
  if (body.success === false) {
    const data = asObject(body.data);
    let transformed: T | undefined;
    try {
      transformed = transform(payload);
    } catch {
      transformed = undefined;
    }
    return {
      ok: false,
      data: transformed,
      error: typeof body.error === 'string' ? body.error : asString(data.error) || 'request_failed',
      raw: payload,
    };
  }

  try {
    return { ok: true, data: transform(payload), raw: payload };
  } catch (error: any) {
    return { ok: false, error: error?.message || 'invalid_response', raw: payload };
  }
}

async function pairLumiSecureChannel(config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneConnectionConfig>> {
  const baseUrl = normalizeBaseUrl(config.baseUrl);
  if (!baseUrl) return { ok: false, error: 'missing_base_url' };
  if (!config.token.trim()) return { ok: false, error: 'missing_token' };

  const launcherId = config.launcherId || createLauncherId();
  const result = await requestAtBaseUrl(
    baseUrl,
    config.token,
    '/api/lumi/security/pair',
    {
      method: 'POST',
      body: JSON.stringify({
        launcherId,
        launcherName: 'OpenClaw Portable AI Console',
        clientVersion: 'openclaw-launcher',
      }),
      timeoutMs: PHONE_STATUS_TIMEOUT_MS,
    },
    transformLumiPairing
  );

  if (!result.ok || !result.data?.launcherSecret || !result.data.launcherId) {
    return {
      ok: false,
      error: result.error || 'lumi_pair_failed',
      raw: result.raw,
    };
  }

  const pairedConfig = savePhoneConfig({
    ...config,
    baseUrl,
    launcherId: result.data.launcherId,
    launcherSecret: result.data.launcherSecret,
    secureChannelPairedAt: new Date(result.data.pairedAt || Date.now()).toISOString(),
  });
  return { ok: true, data: pairedConfig, raw: result.raw };
}

async function ensureLumiSecureConfig(config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneConnectionConfig>> {
  if (config.launcherId && config.launcherSecret) {
    return { ok: true, data: config };
  }
  return pairLumiSecureChannel(config);
}

async function secureRequest<T>(
  config: PhoneConnectionConfig,
  path: string,
  options: PhoneRequestOptions = {},
  transform: (payload: unknown) => T,
  retryPairing = true
): Promise<PhoneApiResult<T>> {
  const secureConfig = await ensureLumiSecureConfig(config);
  if (!secureConfig.ok || !secureConfig.data) {
    return { ok: false, error: secureConfig.error || 'lumi_pair_failed', raw: secureConfig.raw };
  }

  const method = String(options.method || 'GET').toUpperCase();
  const body = typeof options.body === 'string' ? options.body : '';
  let headers: Record<string, string>;
  try {
    headers = await buildLumiHeaders(secureConfig.data, method, path, body);
  } catch (error: any) {
    return { ok: false, error: error?.message || 'lumi_sign_failed' };
  }

  const result = await requestAtBaseUrl(
    secureConfig.data.baseUrl,
    secureConfig.data.token,
    path,
    {
      ...options,
      method,
      extraHeaders: {
        ...(options.extraHeaders || {}),
        ...headers,
      },
    },
    transform
  );

  if (!result.ok && retryPairing && String(result.error || '').includes('[403]')) {
    const repaired = await pairLumiSecureChannel({
      ...secureConfig.data,
      launcherSecret: undefined,
      secureChannelPairedAt: undefined,
    });
    if (repaired.ok && repaired.data) {
      return secureRequest(repaired.data, path, options, transform, false);
    }
  }

  return result;
}

function transformStatus(payload: unknown): PhoneStatus {
  const data = parseMaybeJsonObject(payloadData(payload));
  return {
    online: true,
    taskRunning: Boolean(data.taskRunning),
    agentInitialized: Boolean(data.agentInitialized),
    llmConfigured: Boolean(data.llmConfigured),
    accessibilityRunning: Boolean(data.accessibilityRunning),
    screenshotSupported: asBoolean(data.screenshotSupported),
    screenInfoSupported: asBoolean(data.screenInfoSupported),
    overlayPermission: asBoolean(data.overlayPermission),
    cursorOverlayEnabled: asBoolean(data.cursorOverlayEnabled),
    cursorPreviewSupported: asBoolean(data.cursorPreviewSupported),
    screenOn: asBoolean(data.screenOn),
    interactive: asBoolean(data.interactive),
    keyguardLocked: asBoolean(data.keyguardLocked),
    deviceLocked: asBoolean(data.deviceLocked),
    version: asString(data.version),
    versionCode: asNumber(data.versionCode),
    versionInfo: asString(data.versionInfo),
    serverPort: asNumber(data.serverPort),
  };
}

function transformWakeState(payload: unknown): PhoneWakeState {
  const data = asObject(payload);
  return {
    screenOn: asBoolean(data.screenOn),
    interactive: asBoolean(data.interactive),
    keyguardLocked: asBoolean(data.keyguardLocked),
    deviceLocked: asBoolean(data.deviceLocked),
  };
}

function transformWakeResult(payload: unknown): PhoneWakeResult {
  const data = asObject(payloadData(payload));
  return {
    screenOn: asBoolean(data.screenOn),
    interactive: asBoolean(data.interactive),
    keyguardLocked: asBoolean(data.keyguardLocked),
    deviceLocked: asBoolean(data.deviceLocked),
    wakeAttempted: asBoolean(data.wakeAttempted),
    wakeRequested: asBoolean(data.wakeRequested),
    message: asString(data.message),
    before: transformWakeState(data.before),
    after: transformWakeState(data.after),
  };
}

function transformScreenshot(payload: unknown): PhoneScreenshot {
  const data = payloadData(payload);
  let base64 = '';
  let mime = 'image/png';
  let capturedAt = new Date().toISOString();
  let width: number | undefined;
  let height: number | undefined;
  let orientation: string | undefined;

  if (typeof data === 'string') {
    base64 = data;
  } else {
    const obj = asObject(data);
    base64 = String(obj.base64 || '');
    mime = asString(obj.mime) || mime;
    capturedAt = asString(obj.capturedAt) || capturedAt;
    width = asNumber(obj.width);
    height = asNumber(obj.height);
    orientation = asString(obj.orientation);
  }

  if (!base64) throw new Error('empty_screenshot');
  return {
    mime,
    base64,
    dataUrl: `data:${mime};base64,${base64}`,
    capturedAt,
    width,
    height,
    orientation,
  };
}

function transformScreenTree(payload: unknown): PhoneScreenTree {
  const data = asObject(payloadData(payload));
  const screen = asObject(data.screen);
  const rawNodes = Array.isArray(data.nodes) ? data.nodes : [];
  return {
    screen: {
      width: asNumber(screen.width),
      height: asNumber(screen.height),
      orientation: asString(screen.orientation),
    },
    nodes: rawNodes.map((node, index) => {
      const obj = asObject(node);
      const bounds = asObject(obj.bounds);
      return {
        id: asString(obj.id) || `node-${index + 1}`,
        parentId: asString(obj.parentId) || null,
        depth: asNumber(obj.depth) || 0,
        className: asString(obj.className) || 'View',
        text: asString(obj.text) || null,
        description: asString(obj.description) || null,
        resourceId: asString(obj.resourceId) || null,
        packageName: asString(obj.packageName) || null,
        clickable: asBoolean(obj.clickable),
        longClickable: asBoolean(obj.longClickable),
        scrollable: asBoolean(obj.scrollable),
        editable: asBoolean(obj.editable),
        checkable: asBoolean(obj.checkable),
        checked: asBoolean(obj.checked),
        enabled: asBoolean(obj.enabled),
        focused: asBoolean(obj.focused),
        selected: asBoolean(obj.selected),
        visible: asBoolean(obj.visible),
        slider: asBoolean(obj.slider),
        loading: asBoolean(obj.loading),
        bounds: {
          left: asNumber(bounds.left) || 0,
          top: asNumber(bounds.top) || 0,
          right: asNumber(bounds.right) || 0,
          bottom: asNumber(bounds.bottom) || 0,
          width: asNumber(bounds.width) || 0,
          height: asNumber(bounds.height) || 0,
          centerX: asNumber(bounds.centerX) || 0,
          centerY: asNumber(bounds.centerY) || 0,
        },
      };
    }),
  };
}

function transformAgentTask(payload: unknown): PhoneAgentTaskResult {
  const data = asObject(payloadData(payload));
  const rawEvents = Array.isArray(data.events) ? data.events : [];
  return {
    success: asBoolean(data.success) ?? true,
    mode: asString(data.mode),
    readOnly: asBoolean(data.readOnly),
    toolPolicy: asString(data.toolPolicy),
    answer: asString(data.answer),
    error: asString(data.error),
    rounds: asNumber(data.rounds),
    tokens: asNumber(data.tokens),
    templateId: asString(data.templateId),
    templateName: asString(data.templateName),
    stepsExecuted: asNumber(data.stepsExecuted),
    stepsTotal: asNumber(data.stepsTotal),
    executionTimeMs: asNumber(data.executionTimeMs),
    events: rawEvents.map((event) => {
      const obj = asObject(event);
      return {
        type: asString(obj.type) || 'event',
        round: asNumber(obj.round) ?? 0,
        time: asNumber(obj.time),
        toolId: asString(obj.toolId),
        toolName: asString(obj.toolName),
        parameters: asString(obj.parameters),
        success: asBoolean(obj.success),
        message: asString(obj.message),
      } satisfies PhoneAgentEvent;
    }).filter((event) => Boolean(event.type)),
  };
}

function transformAgentAsyncTask(payload: unknown): PhoneAgentAsyncTask {
  const data = asObject(payloadData(payload));
  const rawEvents = Array.isArray(data.events) ? data.events : [];
  const rawResult = asObject(data.result);
  return {
    taskId: asString(data.taskId) || '',
    status: asString(data.status) || 'unknown',
    prompt: asString(data.prompt),
    createdAt: asNumber(data.createdAt),
    startedAt: asNumber(data.startedAt),
    finishedAt: asNumber(data.finishedAt),
    error: asString(data.error),
    result: Object.keys(rawResult).length ? transformAgentTask({ data: rawResult }) : undefined,
    events: rawEvents.map((event) => {
      const obj = asObject(event);
      return {
        type: asString(obj.type) || 'event',
        round: asNumber(obj.round) ?? 0,
        time: asNumber(obj.time),
        toolId: asString(obj.toolId),
        toolName: asString(obj.toolName),
        parameters: asString(obj.parameters),
        success: asBoolean(obj.success),
        message: asString(obj.message),
      } satisfies PhoneAgentEvent;
    }).filter((event) => Boolean(event.type)),
  };
}

function transformCursorPreview(payload: unknown): PhoneCursorPreviewResult {
  const data = asObject(payloadData(payload));
  return {
    x: asNumber(data.x) || 0,
    y: asNumber(data.y) || 0,
    action: asString(data.action) || 'tap',
    durationMs: asNumber(data.durationMs),
    traceId: asString(data.traceId),
    enabled: asBoolean(data.enabled),
  };
}

function transformDeviceProfile(payload: unknown): PhoneDeviceProfile {
  const data = asObject(payloadData(payload));
  const rawApps = Array.isArray(data.apps) ? data.apps : [];
  const apps = rawApps.map((app) => {
    const obj = asObject(app);
    return {
      label: asString(obj.label) || asString(obj.packageName) || 'App',
      packageName: asString(obj.packageName) || '',
      activityName: asString(obj.activityName),
      launchable: asBoolean(obj.launchable),
    };
  }).filter((app) => app.packageName);
  return {
    profileVersion: asNumber(data.profileVersion),
    capturedAt: asNumber(data.capturedAt),
    device: asObject(data.device),
    capabilities: asObject(data.capabilities),
    memory: asObject(data.memory),
    storage: asObject(data.storage),
    battery: asObject(data.battery),
    currentScreen: asObject(data.currentScreen),
    vision: asObject(data.vision),
    publicDirectories: Array.isArray(data.publicDirectories)
      ? data.publicDirectories.map((item) => asObject(item))
      : [],
    apps: sortProfileApps(apps),
    privacyNote: asString(data.privacyNote),
  };
}

function summarizeCurrentScreen(currentScreen: Record<string, unknown>): {
  packageName: string;
  title: string;
  nodeCount: number;
  textNodeCount: number;
  clickableNodeCount: number;
  imageNodeCount: number;
} {
  return {
    packageName: asString(currentScreen.packageName) || 'unknown',
    title: asString(currentScreen.title) || asString(currentScreen.pageTitle) || asString(currentScreen.activityName) || 'unknown',
    nodeCount: asNumber(currentScreen.nodeCount) || 0,
    textNodeCount: asNumber(currentScreen.textNodeCount) || 0,
    clickableNodeCount: asNumber(currentScreen.clickableNodeCount) || 0,
    imageNodeCount: asNumber(currentScreen.imageNodeCount) || 0,
  };
}

function summarizeVisionHint(vision: Record<string, unknown>): {
  recommended: boolean;
  mode: string;
  reason: string;
  confidence?: number;
} {
  return {
    recommended: vision.recommended === true || vision.recommended === 'true',
    mode: asString(vision.mode) || 'unknown',
    reason: asString(vision.reason) || 'unknown',
    confidence: asNumber(vision.confidence),
  };
}

export function loadPhoneConfig(): PhoneConnectionConfig {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return normalizePhoneConfig(DEFAULT_CONFIG);
    const parsed = JSON.parse(raw);
    return normalizePhoneConfig(parsed);
  } catch {
    return normalizePhoneConfig(DEFAULT_CONFIG);
  }
}

export function savePhoneConfig(config: PhoneConnectionConfig): PhoneConnectionConfig {
  const clean = normalizePhoneConfig(config);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(clean));
  const store = loadPhoneDeviceStore();
  const matchingDevice =
    (clean.id && store.devices.find((device) => device.id === clean.id)) ||
    store.devices.find(
      (device) =>
        normalizeBaseUrl(device.baseUrl) === clean.baseUrl &&
        (device.name || DEFAULT_PHONE_NAME) === clean.name
    );
  savePhoneDeviceStore({
    ...store,
    selectedDeviceId: matchingDevice?.id || clean.id || store.selectedDeviceId,
    devices: matchingDevice
      ? store.devices.map((device) => (device.id === matchingDevice.id ? clean : device))
      : [...store.devices, clean],
  });
  return clean;
}

export function loadPhoneDeviceProfile(config: PhoneConnectionConfig): PhoneDeviceProfileCache | null {
  try {
    const baseUrl = normalizeBaseUrl(config.baseUrl);
    if (!baseUrl) return null;
    const raw = window.localStorage.getItem(profileStorageKey(config));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PhoneDeviceProfileCache;
    if (!parsed?.profile || parsed.baseUrl !== baseUrl) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function savePhoneDeviceProfile(
  config: PhoneConnectionConfig,
  profile: PhoneDeviceProfile,
  healthReport?: PhoneInitializationReport
): PhoneDeviceProfileCache {
  const baseUrl = normalizeBaseUrl(config.baseUrl);
  const cache: PhoneDeviceProfileCache = {
    baseUrl,
    savedAt: new Date().toISOString(),
    profile,
    healthReport,
  };
  window.localStorage.setItem(profileStorageKey(config), JSON.stringify(cache));
  return cache;
}

export function clearPhoneDeviceProfile(config: PhoneConnectionConfig): void {
  window.localStorage.removeItem(profileStorageKey(config));
}

export function buildPhoneInitializationReport(
  status: PhoneStatus | null | undefined,
  profile: PhoneDeviceProfile,
  screenTree?: PhoneScreenTree | null
): PhoneInitializationReport {
  const device = profile.device || {};
  const capabilities = profile.capabilities || {};
  const memory = profile.memory || {};
  const storage = asObject(profile.storage);
  const dataStorage = asObject(storage.data);
  const externalStorage = asObject(storage.external);
  const battery = profile.battery || {};
  const currentScreen = profile.currentScreen || {};
  const currentScreenSummary = summarizeCurrentScreen(currentScreen);
  const visionHint = summarizeVisionHint(profile.vision || {});
  const apps = profile.apps || [];
  const preferredBrowser = apps.find(isViaBrowserApp);
  const apkVersion = status?.version || asString(device.apkVersion) || 'unknown';
  const apkVersionCode = status?.versionCode || asNumber(device.apkVersionCode);
  const availableMemory = asNumber(memory.availableBytes);
  const availableDataStorage = asNumber(dataStorage.availableBytes);
  const availableExternalStorage = asNumber(externalStorage.availableBytes);
  const batteryPercent = asNumber(battery.percent);
  const charging = Boolean(battery.charging);
  const nodeCount = screenTree?.nodes.length || currentScreenSummary.nodeCount || 0;
  const screenPackage = screenTree?.nodes.find((node) => node.packageName)?.packageName || currentScreenSummary.packageName || 'unknown';
  const recommendations: string[] = [];
  const checks: PhoneInitializationCheck[] = [];

  const addCheck = (check: PhoneInitializationCheck, recommendation?: string) => {
    checks.push(check);
    if (!check.ok && recommendation) recommendations.push(recommendation);
  };

  addCheck(
    {
      id: 'agent-version',
      label: 'APKClaw 版本',
      value: apkVersionCode ? `v${apkVersion} (${apkVersionCode})` : `v${apkVersion}`,
      ok: Boolean(status?.online && apkVersionCode && apkVersionCode >= 680),
      tone: status?.online && apkVersionCode && apkVersionCode >= 680 ? 'ok' : 'warn',
      detail: '建议保持 v6.8 或更新版本，确保任务模式、拖拽、Via 优先级、新指针和任务前唤醒可用。',
    },
    '升级或重新打开最新 Agent Phone，确保手机端是 v6.8+。'
  );

  addCheck(
    {
      id: 'core-permissions',
      label: '核心权限',
      value: status?.accessibilityRunning && status?.overlayPermission ? '无障碍和悬浮窗已开启' : '权限不完整',
      ok: Boolean(status?.accessibilityRunning && status?.overlayPermission),
      tone: status?.accessibilityRunning && status?.overlayPermission ? 'ok' : 'error',
      detail: `accessibility=${Boolean(status?.accessibilityRunning || capabilities.accessibilityRunning)}, overlay=${Boolean(status?.overlayPermission || capabilities.overlayPermission)}`,
    },
    '先补齐无障碍服务和悬浮窗权限，否则 Agent 无法稳定观察和执行动作。'
  );

  addCheck(
    {
      id: 'agent-capabilities',
      label: '观察能力',
      value: status?.screenshotSupported && status?.screenInfoSupported ? '截图和结构树正常' : '观察能力异常',
      ok: Boolean(status?.screenshotSupported && status?.screenInfoSupported),
      tone: status?.screenshotSupported && status?.screenInfoSupported ? 'ok' : 'error',
      detail: `screenshot=${Boolean(status?.screenshotSupported || capabilities.screenshotSupported)}, screenTree=${Boolean(status?.screenInfoSupported || capabilities.screenInfoSupported)}`,
    },
    '检查截图能力和读屏能力，必要时重启 Agent Phone 或重新开启无障碍服务。'
  );

  addCheck(
    {
      id: 'wake-state',
      label: '亮屏状态',
      value: status?.interactive || status?.screenOn ? '屏幕已亮' : status ? '屏幕可能已息屏' : '未知',
      ok: Boolean(status?.interactive || status?.screenOn),
      tone: status?.interactive || status?.screenOn ? 'ok' : 'warn',
      detail: `interactive=${Boolean(status?.interactive)}, screenOn=${Boolean(status?.screenOn)}, keyguardLocked=${Boolean(status?.keyguardLocked)}, deviceLocked=${Boolean(status?.deviceLocked)}`,
    },
    '运行任务前让 OpenClaw 自动调用唤醒；如果手机仍锁屏，请先手动解锁。'
  );

  addCheck(
    {
      id: 'llm',
      label: '手机端 LLM',
      value: status?.llmConfigured ? '已配置' : '未配置',
      ok: Boolean(status?.llmConfigured),
      tone: status?.llmConfigured ? 'ok' : 'warn',
      detail: '手机端 Agent 自主执行任务时需要可用模型配置。',
    },
    '在手机端配置 LLM，或者只使用桌面端下发的低层工具。'
  );

  addCheck(
    {
      id: 'device',
      label: '设备识别',
      value: `${String(device.brand || device.manufacturer || 'Android')} ${String(device.model || '')}`.trim(),
      ok: Boolean(device.model),
      tone: device.model ? 'ok' : 'warn',
      detail: `Android ${String(device.androidRelease || 'unknown')} · ${String(device.screenWidth || '?')}x${String(device.screenHeight || '?')}`,
    },
    '重新运行初始化体检，确保设备型号和屏幕信息已采集。'
  );

  addCheck(
    {
      id: 'memory',
      label: '可用内存',
      value: formatProfileBytes(availableMemory),
      ok: Boolean(availableMemory && availableMemory >= 512 * 1024 * 1024),
      tone: availableMemory && availableMemory >= 512 * 1024 * 1024 ? 'ok' : 'warn',
      detail: `total=${formatProfileBytes(memory.totalBytes)}`,
    },
    '可用内存偏低，长任务前建议清掉后台大应用。'
  );

  addCheck(
    {
      id: 'storage',
      label: '可用存储',
      value: `data ${formatProfileBytes(availableDataStorage)} / external ${formatProfileBytes(availableExternalStorage)}`,
      ok: Boolean((availableDataStorage || 0) >= 1024 * 1024 * 1024 || (availableExternalStorage || 0) >= 1024 * 1024 * 1024),
      tone: (availableDataStorage || 0) >= 1024 * 1024 * 1024 || (availableExternalStorage || 0) >= 1024 * 1024 * 1024 ? 'ok' : 'warn',
      detail: '用于 APK 下载、截图缓存和文件操作的空间余量。',
    },
    '可用存储偏低，下载 APK 或处理文件前建议先清理空间。'
  );

  addCheck(
    {
      id: 'battery',
      label: '电量',
      value: batteryPercent === undefined ? 'unknown' : `${batteryPercent}%${charging ? ' · charging' : ''}`,
      ok: batteryPercent === undefined ? true : batteryPercent >= 20 || charging,
      tone: batteryPercent === undefined || batteryPercent >= 20 || charging ? 'ok' : 'warn',
      detail: '长任务和自动更新期间建议保持电量充足。',
    },
    '电量偏低，建议接电后再跑长任务。'
  );

  addCheck(
    {
      id: 'browser',
      label: '优先浏览器',
      value: preferredBrowser ? `${preferredBrowser.label} · ${preferredBrowser.packageName}` : '未检测到 Via',
      ok: Boolean(preferredBrowser),
      tone: preferredBrowser ? 'ok' : 'warn',
      detail: '网页、搜索、APK 下载任务优先使用 Via，减少系统拦截和复杂弹窗。',
    },
    '安装或保留 Via 浏览器，并让 Agent 优先使用 Via 处理网页和下载任务。'
  );

  addCheck(
    {
      id: 'apps',
      label: '可启动应用',
      value: `${apps.length} apps`,
      ok: apps.length > 0,
      tone: apps.length > 0 ? 'ok' : 'warn',
      detail: apps.slice(0, 5).map((app) => `${app.label}(${app.packageName})`).join(', ') || 'no apps captured',
    },
    '应用列表为空，重新运行初始化体检或检查 APKClaw 应用查询权限。'
  );

  addCheck(
    {
      id: 'current-screen',
      label: '当前屏幕',
      value: `${screenPackage} · ${nodeCount} nodes`,
      ok: nodeCount > 0,
      tone: nodeCount > 0 ? 'ok' : 'warn',
      detail: `title=${currentScreenSummary.title} · text=${currentScreenSummary.textNodeCount} · clickable=${currentScreenSummary.clickableNodeCount} · image=${currentScreenSummary.imageNodeCount}`,
    },
    '当前屏幕结构为空，先亮屏并停在可见页面后重新体检。'
  );

  addCheck(
    {
      id: 'vision-hint',
      label: '视觉建议',
      value: visionHint.recommended ? `推荐视觉 · ${visionHint.mode}` : visionHint.mode,
      ok: !visionHint.recommended,
      tone: visionHint.recommended ? 'warn' : 'ok',
      detail: `reason=${visionHint.reason}${visionHint.confidence !== undefined ? ` · confidence=${visionHint.confidence}` : ''}`,
    },
    visionHint.recommended
      ? '当前屏幕更适合视觉模式，优先让 APKClaw 走截图/视觉反馈，不要继续堆结构树。'
      : undefined
  );

  addCheck(
    {
      id: 'cursor',
      label: '可视指针',
      value: status?.cursorPreviewSupported || status?.cursorOverlayEnabled ? '可用' : '未知/不可用',
      ok: Boolean(status?.cursorPreviewSupported || status?.cursorOverlayEnabled),
      tone: status?.cursorPreviewSupported || status?.cursorOverlayEnabled ? 'ok' : 'warn',
      detail: '用于让用户看见 Agent 即将点击、长按或拖动的位置。',
    },
    '检查悬浮窗权限，保证 AI 指针可见。'
  );

  const passed = checks.filter((check) => check.ok).length;
  const total = checks.length;
  const summary = passed === total
    ? '这台手机已完成初始化体检，可以直接接收 OpenClaw Agent 任务。'
    : `这台手机体检通过 ${passed}/${total} 项，建议先处理 ${total - passed} 个风险点。`;

  return {
    generatedAt: new Date().toISOString(),
    summary,
    passed,
    total,
    preferredBrowser,
    recommendations: [...new Set(recommendations)],
    checks,
  };
}

export function buildDeviceProfilePromptContext(profile?: PhoneDeviceProfile | null): string {
  if (!profile) return '';
  const device = profile.device || {};
  const capabilities = profile.capabilities || {};
  const memory = profile.memory || {};
  const storage = asObject(profile.storage);
  const dataStorage = asObject(storage.data);
  const externalStorage = asObject(storage.external);
  const battery = profile.battery || {};
  const currentScreen = profile.currentScreen || {};
  const currentScreenSummary = summarizeCurrentScreen(currentScreen);
  const visionHint = summarizeVisionHint(profile.vision || {});
  const dirs = profile.publicDirectories || [];
  const apps = profile.apps || [];
  const preferredBrowser = apps.find(isViaBrowserApp);
  const appLimit = 60;
  const appLines = apps.slice(0, appLimit).map((app) => `- ${app.label}: ${app.packageName}`);
  if (apps.length > appLimit) {
    appLines.push(`- ... ${apps.length - appLimit} more launchable apps omitted from context`);
  }
  const dirLines = dirs.slice(0, 8).map((dir) => {
    const type = String(dir.type || 'public');
    const path = String(dir.path || '');
    const canRead = dir.canRead === true ? 'readable' : 'read unknown';
    return `- ${type}: ${path} (${canRead})`;
  });

  return [
    '## OpenClaw Device Profile Context',
    'Use this cached device profile to avoid guessing this phone environment. If the live screen conflicts with this profile, trust the live screen.',
    '',
    `Device: ${String(device.brand || device.manufacturer || 'Android')} ${String(device.model || '')}`.trim(),
    `Android: ${String(device.androidRelease || 'unknown')} (SDK ${String(device.sdkInt || 'unknown')})`,
    `Screen: ${String(device.screenWidth || 'unknown')}x${String(device.screenHeight || 'unknown')}, densityDpi=${String(device.densityDpi || 'unknown')}`,
    `APKClaw: v${String(device.apkVersion || 'unknown')} (${String(device.apkVersionCode || 'unknown')})`,
    `Capabilities: accessibility=${Boolean(capabilities.accessibilityRunning)}, screenshot=${Boolean(capabilities.screenshotSupported)}, screenTree=${Boolean(capabilities.screenInfoSupported)}, overlay=${Boolean(capabilities.overlayPermission)}, cursorPreview=${Boolean(capabilities.cursorPreviewSupported)}, llmConfigured=${Boolean(capabilities.llmConfigured)}`,
    `Memory: available=${formatProfileBytes(memory.availableBytes)}, total=${formatProfileBytes(memory.totalBytes)}`,
    `Storage: dataAvailable=${formatProfileBytes(dataStorage.availableBytes)}, externalAvailable=${formatProfileBytes(externalStorage.availableBytes)}`,
    `Battery: ${String(battery.percent ?? 'unknown')}%, charging=${Boolean(battery.charging)}`,
    `Current screen: package=${currentScreenSummary.packageName}, title=${currentScreenSummary.title}, nodes=${currentScreenSummary.nodeCount}, textNodes=${currentScreenSummary.textNodeCount}, clickableNodes=${currentScreenSummary.clickableNodeCount}, imageNodes=${currentScreenSummary.imageNodeCount}`,
    `Vision hint: recommended=${visionHint.recommended}, mode=${visionHint.mode}, reason=${visionHint.reason}${visionHint.confidence !== undefined ? `, confidence=${visionHint.confidence}` : ''}`,
    'If vision is recommended or the current screen has zero nodes, prefer screenshot/vision fallback and rewrite the next APKClaw Agent prompt before forcing more accessibility scraping.',
    preferredBrowser
      ? `Preferred browser: ${preferredBrowser.label} (${preferredBrowser.packageName}). For web browsing, URL opening, APK downloads, and browser searches, use this before Chrome or system browsers.`
      : 'Preferred browser: if Via Browser is installed, prefer it for web browsing, URL opening, APK downloads, and browser searches before Chrome or system browsers.',
    '',
    'Launchable apps known on this phone:',
    ...(appLines.length ? appLines : ['- No app list captured']),
    '',
    'Public directories metadata:',
    ...(dirLines.length ? dirLines : ['- No public directory metadata captured']),
    '',
    'Safety boundary: this profile does not grant permission to read private file contents. Only inspect files or make changes when the user explicitly asks.',
    '',
    '## User Task',
  ].join('\n');
}

export function buildAgentPromptWithDeviceProfile(prompt: string, profile?: PhoneDeviceProfile | null): string {
  const context = buildDeviceProfilePromptContext(profile);
  if (!context) return prompt;
  return `${context}\n${prompt}`;
}

function agentTaskBody(requestBody: PhoneAgentTaskRequest): Record<string, unknown> {
  return {
    prompt: requestBody.prompt,
    use_template: requestBody.useTemplate !== false,
    force_agent: requestBody.forceAgent === true,
    learn_template: requestBody.learnTemplate === true,
    read_only: requestBody.readOnly === true,
    tool_policy: requestBody.toolPolicy,
    template_params: requestBody.templateParams || {},
    timeout_sec: requestBody.timeoutSec ?? PHONE_AGENT_TASK_TIMEOUT_SEC,
  };
}

async function waitForAsyncAgentTask(
  config: PhoneConnectionConfig,
  taskId: string,
  maxWaitMs: number
): Promise<PhoneApiResult<PhoneAgentTaskResult>> {
  const startedAt = Date.now();
  let lastTask: PhoneAgentAsyncTask | undefined;
  while (Date.now() - startedAt < maxWaitMs) {
    await new Promise((resolve) => window.setTimeout(resolve, 1800));
    const task = await secureRequest(
      config,
      `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}`,
      { method: 'GET', timeoutMs: PHONE_STATUS_TIMEOUT_MS },
      transformAgentAsyncTask
    );
    if (!task.ok || !task.data) return { ok: false, error: task.error || 'async_task_poll_failed', raw: task.raw };
    lastTask = task.data;
    if (task.data.status === 'success') {
      return {
        ok: true,
        data: task.data.result || { success: true, answer: '', events: task.data.events || [] },
        raw: task.raw,
      };
    }
    if (task.data.status === 'error' || task.data.status === 'cancelled') {
      return {
        ok: false,
        data: task.data.result,
        error: task.data.error || task.data.result?.error || task.data.status,
        raw: task.raw,
      };
    }
  }

  return {
    ok: false,
    data: lastTask?.result,
    error: 'desktop_async_wait_timeout',
  };
}

export const phoneApi = {
  async status(config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneStatus>> {
    const baseUrl = normalizeBaseUrl(config.baseUrl);
    if (!baseUrl) return { ok: false, error: 'missing_base_url' };
    if (!config.token.trim()) return { ok: false, error: 'missing_token' };

    const primary = await requestAtBaseUrl(
      baseUrl,
      config.token,
      '/api/device/status',
      { timeoutMs: PHONE_STATUS_TIMEOUT_MS },
      transformStatus
    );
    if (
      primary.ok ||
      primary.error === 'unauthorized' ||
      primary.error === 'missing_base_url' ||
      primary.error === 'missing_token'
    ) {
      return primary;
    }

    const candidates = buildPhoneBaseUrlCandidates(baseUrl).filter((candidate) => candidate !== baseUrl);
    for (const candidate of candidates) {
      const result = await requestAtBaseUrl(
        candidate,
        config.token,
        '/api/device/status',
        { timeoutMs: PHONE_STATUS_FALLBACK_TIMEOUT_MS },
        transformStatus
      );
      if (
        result.ok ||
        result.error === 'unauthorized' ||
        result.error === 'missing_base_url' ||
        result.error === 'missing_token'
      ) {
        return result;
      }
    }

    return request(config, '/api/agent/status', { timeoutMs: PHONE_STATUS_FALLBACK_TIMEOUT_MS }, transformStatus);
  },

  wake: (config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneWakeResult>> =>
    request(
      config,
      '/api/device/wake',
      {
        method: 'POST',
      },
      transformWakeResult
    ),

  screenshot: (config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneScreenshot>> =>
    request(config, '/api/tool/screenshot', {}, transformScreenshot),

  relayScreenshot: async (
    config: PhoneConnectionConfig,
    options: PhoneRelayScreenshotOptions = {}
  ): Promise<PhoneApiResult<PhoneScreenshot>> => {
    const relayBaseUrl = normalizeRelayBaseUrl(config.relayBaseUrl || '');
    const relayChannelId = String(config.relayChannelId || '').trim();
    const relayToken = String(config.relayToken || '').trim();
    if (!relayBaseUrl) return { ok: false, error: 'missing_relay_base_url' };
    if (!relayChannelId) return { ok: false, error: 'missing_relay_channel_id' };
    if (!relayToken) return { ok: false, error: 'missing_relay_token' };

    const packet = {
      schema: 'openclaw.phone.screenshot.v1',
      createdAt: new Date().toISOString(),
      requestId: `relay_screenshot_${Date.now()}`,
      channelId: relayChannelId,
      options: {
        format: options.format || 'jpeg',
        quality: options.quality ?? 82,
        maxLongSide: options.maxLongSide ?? 1600,
        overlayGrid: options.overlayGrid ?? false,
        gridColumns: options.gridColumns ?? 6,
        gridRows: options.gridRows ?? 12,
      },
    };

    const enqueue = await requestRelayJson(
      relayBaseUrl,
      '/api/lumi/relay/packet',
      {
        method: 'POST',
        body: JSON.stringify(packet),
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
        },
      },
      relayToken,
      PHONE_REQUEST_TIMEOUT_MS
    );
    if (!enqueue.ok || !enqueue.data) {
      return { ok: false, error: enqueue.error || 'relay_packet_failed', raw: enqueue.raw };
    }

    const packetData = asObject(payloadData(enqueue.data));
    const packetId = asString(packetData.packetId) || asString(packetData.id);
    if (!packetId) {
      return { ok: false, error: 'relay_missing_packet_id', raw: enqueue.raw };
    }

    const waitResult = await waitForRelayRecord(
      relayBaseUrl,
      packetId,
      relayToken,
      options.waitSec ?? 60,
      options.pollMs ?? 1500
    );
    if (!waitResult.ok || !waitResult.data) {
      return {
        ok: false,
        error: waitResult.error || 'relay_timeout',
        raw: waitResult.raw,
      };
    }

    const result = asObject(waitResult.data.result);
    if (!Object.keys(result).length) {
      return { ok: false, error: 'empty_screenshot', raw: waitResult.raw };
    }

    try {
      return { ok: true, data: transformRelayScreenshotResult(result), raw: waitResult.raw };
    } catch (error: any) {
      return { ok: false, error: error?.message || 'invalid_response', raw: waitResult.raw };
    }
  },

  screenTree: (config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneScreenTree>> =>
    request(config, '/api/tool/screen_tree', {}, transformScreenTree),

  deviceProfile: (config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneDeviceProfile>> =>
    secureRequest(config, '/api/lumi/device/profile?includeApps=true&appLimit=220', {}, transformDeviceProfile),

  visionStatus: (config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneVisionFrame>> =>
    secureRequest(config, '/api/lumi/vision/status?_lumi=1', { method: 'GET' }, transformVisionFrame),

  visionFrame: (
    config: PhoneConnectionConfig,
    options: PhoneVisionFrameOptions = {}
  ): Promise<PhoneApiResult<PhoneVisionFrame>> => {
    const query = new URLSearchParams({ _lumi: '1' });
    if (options.includeScreenshot !== undefined) query.set('includeScreenshot', String(options.includeScreenshot));
    if (options.overlayGrid !== undefined) query.set('overlayGrid', String(options.overlayGrid));
    if (options.format) query.set('format', options.format);
    if (options.quality !== undefined) query.set('quality', String(options.quality));
    if (options.maxLongSide !== undefined) query.set('maxLongSide', String(options.maxLongSide));
    if (options.gridColumns !== undefined) query.set('gridColumns', String(options.gridColumns));
    if (options.gridRows !== undefined) query.set('gridRows', String(options.gridRows));
    return secureRequest(config, `/api/lumi/vision/frame?${query.toString()}`, { method: 'GET', timeoutMs: 45000 }, transformVisionFrame);
  },

  visionAction: (
    config: PhoneConnectionConfig,
    requestBody: PhoneVisionActionRequest
  ): Promise<PhoneApiResult<PhoneVisionActionResult>> =>
    secureRequest(
      config,
      '/api/lumi/vision/action',
      {
        method: 'POST',
        body: JSON.stringify(requestBody),
      },
      transformVisionAction
    ),

  previewCursor: (config: PhoneConnectionConfig, requestBody: PhoneCursorPreviewRequest): Promise<PhoneApiResult<PhoneCursorPreviewResult>> =>
    request(
      config,
      '/api/overlay/cursor/preview',
      {
        method: 'POST',
        body: JSON.stringify({
          x: requestBody.x,
          y: requestBody.y,
          action: requestBody.action || 'tap',
          durationMs: requestBody.durationMs || 2600,
          traceId: requestBody.traceId,
        }),
      },
      transformCursorPreview
    ),

  async executeTask(config: PhoneConnectionConfig, requestBody: PhoneAgentTaskRequest): Promise<PhoneApiResult<PhoneAgentTaskResult>> {
    const timeoutMs = Math.min(
      (requestBody.timeoutSec ?? PHONE_AGENT_TASK_TIMEOUT_SEC) * 1000 + 15000,
      PHONE_AGENT_TASK_TIMEOUT_MS
    );
    const body = agentTaskBody(requestBody);
    const started = await secureRequest(
      config,
      '/api/lumi/agent/tasks',
      {
        method: 'POST',
        body: JSON.stringify(body),
        timeoutMs: PHONE_REQUEST_TIMEOUT_MS,
      },
      transformAgentAsyncTask
    );
    if (started.ok && started.data?.taskId) {
      return waitForAsyncAgentTask(config, started.data.taskId, timeoutMs);
    }

    if (String(started.error || '').includes('[404]') || String(started.error || '').includes('not found')) {
      return secureRequest(
        config,
        '/api/lumi/agent/execute_task',
        {
          method: 'POST',
          body: JSON.stringify(body),
          timeoutMs,
        },
        transformAgentTask
      );
    }
    return { ok: false, error: started.error || 'async_task_start_failed', raw: started.raw };
  },

  startTask: (config: PhoneConnectionConfig, requestBody: PhoneAgentTaskRequest): Promise<PhoneApiResult<PhoneAgentAsyncTask>> =>
    secureRequest(
      config,
      '/api/lumi/agent/tasks',
      {
        method: 'POST',
        body: JSON.stringify(agentTaskBody(requestBody)),
        timeoutMs: PHONE_REQUEST_TIMEOUT_MS,
      },
      transformAgentAsyncTask
    ),

  getTask: (config: PhoneConnectionConfig, taskId: string): Promise<PhoneApiResult<PhoneAgentAsyncTask>> =>
    secureRequest(
      config,
      `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}`,
      { method: 'GET', timeoutMs: PHONE_STATUS_TIMEOUT_MS },
      transformAgentAsyncTask
    ),

  getTaskEvents: (config: PhoneConnectionConfig, taskId: string): Promise<PhoneApiResult<{ taskId: string; status: string; events: PhoneAgentEvent[] }>> =>
    secureRequest(
      config,
      `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}/events`,
      { method: 'GET', timeoutMs: PHONE_STATUS_TIMEOUT_MS },
      (payload) => {
        const data = asObject(payloadData(payload));
        const task = transformAgentAsyncTask({ data });
        return { taskId: task.taskId, status: task.status, events: task.events || [] };
      }
    ),

  cancelTaskById: (config: PhoneConnectionConfig, taskId: string): Promise<PhoneApiResult<PhoneAgentAsyncTask>> =>
    secureRequest(
      config,
      `/api/lumi/agent/tasks/${encodeURIComponent(taskId)}/cancel`,
      {
        method: 'POST',
        body: JSON.stringify({}),
        timeoutMs: PHONE_REQUEST_TIMEOUT_MS,
      },
      transformAgentAsyncTask
    ),

  cancelTask: (config: PhoneConnectionConfig): Promise<PhoneApiResult<{ message?: string }>> =>
    secureRequest(
      config,
      '/api/lumi/agent/cancel_task',
      {
        method: 'POST',
        body: JSON.stringify({}),
      },
      (payload) => {
        const data = payloadData(payload);
        return { message: typeof data === 'string' ? data : asString(asObject(data).message) };
      }
    ),

  tap: (config: PhoneConnectionConfig, requestBody: PhoneTapRequest): Promise<PhoneApiResult<PhoneTapResult>> =>
    request(
      config,
      '/api/tool/tap',
      {
        method: 'POST',
        body: JSON.stringify({
          x: requestBody.x,
          y: requestBody.y,
          durationMs: requestBody.durationMs,
          traceId: requestBody.traceId,
          visualize: requestBody.visualize,
        }),
      },
      (payload) => {
        const data = asObject(payloadData(payload));
        return {
          x: asNumber(data.x) || requestBody.x,
          y: asNumber(data.y) || requestBody.y,
          durationMs: asNumber(data.durationMs),
          traceId: asString(data.traceId) || requestBody.traceId,
          visualize: asBoolean(data.visualize) ?? requestBody.visualize,
          executedAt: asString(data.executedAt),
          message: asString(data.message),
        };
      }
    ),

  longPress: (config: PhoneConnectionConfig, requestBody: PhoneLongPressRequest): Promise<PhoneApiResult<PhoneLongPressResult>> =>
    request(
      config,
      '/api/tool/long_press',
      {
        method: 'POST',
        body: JSON.stringify({
          x: requestBody.x,
          y: requestBody.y,
          durationMs: requestBody.durationMs,
          traceId: requestBody.traceId,
          visualize: requestBody.visualize,
        }),
      },
      (payload) => {
        const data = asObject(payloadData(payload));
        return {
          x: asNumber(data.x) || requestBody.x,
          y: asNumber(data.y) || requestBody.y,
          durationMs: asNumber(data.durationMs) || requestBody.durationMs,
          traceId: asString(data.traceId) || requestBody.traceId,
          executedAt: asString(data.executedAt),
          message: asString(data.message),
        };
      }
    ),

  swipe: (config: PhoneConnectionConfig, requestBody: PhoneSwipeRequest): Promise<PhoneApiResult<PhoneSwipeResult>> =>
    request(
      config,
      '/api/tool/swipe',
      {
        method: 'POST',
        body: JSON.stringify({
          startX: requestBody.startX,
          startY: requestBody.startY,
          endX: requestBody.endX,
          endY: requestBody.endY,
          durationMs: requestBody.durationMs,
          traceId: requestBody.traceId,
          visualize: requestBody.visualize,
        }),
      },
      (payload) => {
        const data = asObject(payloadData(payload));
        return {
          startX: asNumber(data.startX) || requestBody.startX,
          startY: asNumber(data.startY) || requestBody.startY,
          endX: asNumber(data.endX) || requestBody.endX,
          endY: asNumber(data.endY) || requestBody.endY,
          durationMs: asNumber(data.durationMs) || requestBody.durationMs,
          traceId: asString(data.traceId) || requestBody.traceId,
          executedAt: asString(data.executedAt),
          message: asString(data.message),
        };
      }
    ),

  drag: (config: PhoneConnectionConfig, requestBody: PhoneDragRequest): Promise<PhoneApiResult<PhoneDragResult>> =>
    request(
      config,
      '/api/tool/drag',
      {
        method: 'POST',
        body: JSON.stringify({
          startX: requestBody.startX,
          startY: requestBody.startY,
          endX: requestBody.endX,
          endY: requestBody.endY,
          holdMs: requestBody.holdMs,
          durationMs: requestBody.durationMs,
          traceId: requestBody.traceId,
          visualize: requestBody.visualize,
        }),
      },
      (payload) => {
        const data = asObject(payloadData(payload));
        return {
          startX: asNumber(data.startX) || requestBody.startX,
          startY: asNumber(data.startY) || requestBody.startY,
          endX: asNumber(data.endX) || requestBody.endX,
          endY: asNumber(data.endY) || requestBody.endY,
          holdMs: asNumber(data.holdMs) || requestBody.holdMs,
          durationMs: asNumber(data.durationMs) || requestBody.durationMs,
          traceId: asString(data.traceId) || requestBody.traceId,
          executedAt: asString(data.executedAt),
          message: asString(data.message),
        };
      }
    ),

  screenRecordStatus: (config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneScreenRecordStatus>> =>
    secureRequest(config, '/api/lumi/media/record/status?_lumi=1', { method: 'GET' }, transformScreenRecordStatus),

  startScreenRecord: (
    config: PhoneConnectionConfig,
    requestBody: PhoneScreenRecordStartRequest = {}
  ): Promise<PhoneApiResult<PhoneScreenRecordStatus>> =>
    secureRequest(
      config,
      '/api/lumi/media/record/start',
      {
        method: 'POST',
        body: JSON.stringify(requestBody),
      },
      transformScreenRecordStatus
    ),

  stopScreenRecord: (config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneScreenRecordStatus>> =>
    secureRequest(config, '/api/lumi/media/record/stop', { method: 'POST', body: JSON.stringify({}) }, transformScreenRecordStatus),

  listScreenRecordings: (config: PhoneConnectionConfig): Promise<PhoneApiResult<PhoneVideoListResult>> =>
    secureRequest(config, '/api/lumi/media/videos?_lumi=1', { method: 'GET' }, transformVideoList),

  importImageDataUrl: async (
    config: PhoneConnectionConfig,
    dataUrl: string,
    options: { album?: string; filename?: string } = {}
  ): Promise<PhoneApiResult<PhoneMediaImportResult>> => {
    try {
      dataUrlToBlob(dataUrl);
    } catch (error: any) {
      return { ok: false, error: error?.message || 'invalid_data_url' };
    }

    return secureRequest(
      config,
      '/api/lumi/media/import_image',
      {
        method: 'POST',
        body: JSON.stringify({
          dataUrl,
          album: options.album || 'OpenClaw',
          filename: options.filename || `openclaw-image-${Date.now()}.png`,
        }),
      },
      transformMediaImport
    );
  },

  importVideoDataUrl: async (
    config: PhoneConnectionConfig,
    dataUrl: string,
    options: { album?: string; filename?: string } = {}
  ): Promise<PhoneApiResult<PhoneMediaImportResult>> => {
    try {
      dataUrlToBlob(dataUrl);
    } catch (error: any) {
      return { ok: false, error: error?.message || 'invalid_data_url' };
    }

    return secureRequest(
      config,
      '/api/lumi/media/import_video',
      {
        method: 'POST',
        body: JSON.stringify({
          dataUrl,
          album: options.album || 'OpenClaw',
          filename: options.filename || `openclaw-video-${Date.now()}.mp4`,
        }),
      },
      transformMediaImport
    );
  },
};
