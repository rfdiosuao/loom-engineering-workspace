export type RouteKey =
  | 'dashboard'
  | 'service'
  | 'agents'
  | 'license'
  | 'studio'
  | 'phone'
  | 'desktop'
  | 'skills'
  | 'diagnostics'
  | 'settings'
  | 'integrations';

export type TransportMode = 'auto' | 'live' | 'mock';
export type DataSource = 'live' | 'mock' | 'mixed';
export type StatusTone = 'idle' | 'ok' | 'warn' | 'danger' | 'busy';

export interface ToastMessage {
  id: string;
  tone: Exclude<StatusTone, 'idle' | 'busy'>;
  title: string;
  detail?: string;
  // Full machine error text shown under “展开详情” and copied by “复制诊断”.
  diagnostic?: string;
  // When true the toast stays until dismissed (defaults to true for danger).
  sticky?: boolean;
  // Where “打开日志” jumps to (defaults to the service page).
  logRoute?: RouteKey;
}

export interface ServiceSnapshot {
  source: DataSource;
  running: boolean;
  pid: number | null;
  startupState: string;
  startupElapsedSec: number;
  startupTimeoutSec: number;
  startupStage: string;
  startupError: string;
  portReady: boolean;
  processAlive: boolean;
  statusLabel: string;
  logTail: string[];
  update: {
    current: string;
    latest: string;
    hasUpdate: boolean;
  };
  system: {
    nodePath: string;
    basePath: string;
    version: string;
  };
  licenseGate: string;
}

export interface LicenseSnapshot {
  source: DataSource;
  authorized: boolean;
  licensee: string;
  edition: string;
  expires: string;
  features: string[];
  installId: string;
  memberId: string;
  plan: string;
  memberMode: boolean;
  issuedAt: string;
  leaseExpiresAt: string;
  gatewayBaseUrl: string;
  gatewayImageBaseUrl: string;
  gatewayVideoBaseUrl: string;
  gatewayTokenMasked: string;
  gatewayImageTokenMasked: string;
  gatewayVideoTokenMasked: string;
  gatewayDefaultModel: string;
  gatewayImageModel: string;
  gatewayVideoModel: string;
  quotas: Record<string, number | null>;
  usage: Record<string, number | null>;
  cardSite: {
    enabled: boolean;
    label: string;
    url: string;
  } | null;
  rawHint: string;
}

export interface MemberSnapshot {
  source: DataSource;
  memberId: string;
  leaseId: string;
  status: string;
  usage: Record<string, number | null>;
  quota: Record<string, number | null>;
  expiresAt: string;
  renewAt: string;
  gatewayBaseUrl: string;
  gatewayTokenMasked: string;
}

export interface GatewaySnapshot {
  source: DataSource;
  hasGateway: boolean;
  baseUrl: string;
  imageBaseUrl: string;
  videoBaseUrl: string;
  apiKeyMasked: string;
  imageApiKeyMasked: string;
  videoApiKeyMasked: string;
  defaultModel: string;
  imageModel: string;
  videoModel: string;
  mode: 'member' | 'manual' | 'unknown';
}

export interface AccountSnapshot {
  loggedIn: boolean;
  source: string;
  account: string;
  memberId?: string;
  plan?: string;
  status?: string;
  baseUrl?: string;
  gatewayBaseUrl?: string;
  tokenMasked?: string;
  models: {
    text: string[];
    image: string[];
    video: string[];
  };
  usage: Record<string, unknown>;
  lastOnlineAt?: string;
  graceExpiresAt?: string;
  offline?: boolean;
  stale?: boolean;
  lastSyncResults?: Array<{ target: string; ok: boolean; error?: string }>;
}

export interface ImageResult {
  prompt: string;
  size: string;
  count: number;
  previewUrls: string[];
  files: Array<{
    path: string;
    filename: string;
    size: number;
    mime: string;
  }>;
  source: DataSource;
}

export interface VideoResult {
  prompt: string;
  mode: string;
  resolution: string;
  ratio: string;
  duration: number;
  previewUrl: string;
  mime: string;
  file?: {
    path: string;
    filename: string;
    size: number;
    mime: string;
  };
  source: DataSource;
}

export interface StudioSnapshot {
  source: DataSource;
  gateway: GatewaySnapshot;
  imageDefaults: {
    baseUrl: string;
    apiKey: string;
    apiKeyMasked: string;
    model: string;
  };
  videoDefaults: {
    apiBase: string;
    apiKey: string;
    apiKeyMasked: string;
    model: string;
    providerId: string;
  };
  imageHistory: ImageResult[];
  videoHistory: VideoResult[];
}

export interface PromptTemplate {
  id: number;
  kind: 'image' | 'video';
  title: string;
  prompt: string;
  params: Record<string, any>;
  coverUrl: string;
  tags: string[];
  sort: number;
}

export interface PhoneDeviceSummary {
  id: string;
  name: string;
  baseUrl: string;
  tokenMasked: string;
  online: boolean;
  active: boolean;
  tags: string[];
  relayEnabled: boolean;
}

export interface PhoneSnapshot {
  source: DataSource;
  devices: PhoneDeviceSummary[];
  selectedDeviceId: string | null;
  status: Record<string, unknown> | null;
  screenshotUrl: string;
  deviceProfile: Record<string, unknown> | null;
  visionFrame: Record<string, unknown> | null;
  screenTree: Record<string, unknown> | null;
  agentTask: Record<string, unknown> | null;
  recordings: Array<Record<string, unknown>>;
}

export interface DesktopSnapshot {
  source: DataSource;
  configured: boolean;
  present: boolean;
  running: boolean;
  pid: number | null;
  apiReady: boolean;
  health: Record<string, unknown> | null;
  command: string[];
  config: Record<string, unknown>;
}

export interface SkillSummary {
  id: string;
  name: string;
  version: string;
  description: string;
  category: string;
  runtime: string;
  icon: string;
  installed: boolean;
  enabled: boolean;
  writable: boolean;
  hasReadme: boolean;
  path: string;
  source: string;
  sourceLabel: string;
}

export interface SkillSnapshot {
  source: DataSource;
  skills: SkillSummary[];
  directories: Array<{ key: string; label: string; path: string; writable: boolean }>;
  sites: Array<{ name: string; url: string }>;
  statePath: string;
}

export interface ComponentSummary {
  id: string;
  name: string;
  version: string;
  installedVersion: string | null;
  previousVersion: string | null;
  status: string;
  jobId?: string | null;
  platform: string;
  arch: string;
  type: string;
  size: number;
  entry: string | null;
  installPath: string;
  category: string;
  officialUrl?: string | null;
  description?: string | null;
  urls: string[];
  updatedAt?: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
}

export interface ComponentSnapshot {
  source: DataSource;
  manifest: {
    schemaVersion: number;
    product: string;
    channel: string;
    version: string;
    publishedAt: string;
    minLauncherVersion: string;
  } | null;
  components: ComponentSummary[];
  error?: string | null;
}

export interface DiagnosticsSnapshot {
  source: DataSource;
  basePath: string;
  serviceRunning: boolean;
  servicePid: number | null;
  startupState: string;
  startupElapsedSec: number;
  startupTimeoutSec: number;
  startupError: string;
  startupDurationMs: number | null;
  startupStage: string;
  startupSnapshotPath: string;
  summary: {
    status: 'ok' | 'warn' | 'fail';
    ok: number;
    warnings: number;
    failed: number;
    total: number;
  };
  checks: Array<{
    id: string;
    label: string;
    status: 'ok' | 'warn' | 'fail';
    message: string;
    detail?: string;
    repairable?: boolean;
  }>;
  reliability?: {
    schema?: string;
    updatedAt?: string;
    summary?: {
      recentFailures?: number;
      retryableFailures?: number;
      dangerFailures?: number;
      activeQueuedPhoneTasks?: number;
      classes?: Record<string, number>;
    };
    failedJobs?: unknown[];
    failedPhoneTasks?: unknown[];
    phoneQueue?: unknown;
    startupFailure?: unknown;
  };
  repairAvailable: boolean;
}

export interface SettingsSnapshot {
  source: DataSource;
  bridgeBaseUrl: string;
  bridgeTokenMasked: string;
  transportMode: TransportMode;
  proxyTarget: string;
  env: Array<{ key: string; value: string; note: string }>;
  configPaths: Array<{ key: string; path: string; writable: boolean }>;
  themeName: string;
}
