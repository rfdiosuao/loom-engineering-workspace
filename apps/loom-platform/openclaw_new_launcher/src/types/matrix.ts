export const MATRIX_DISPATCH_SCHEMA = 'loom.matrix.dispatch.v2' as const;
export const MATRIX_CAMPAIGN_SCHEMA = 'loom.matrix.campaign.v2' as const;
export const MATRIX_SCREEN_SCHEMA = 'loom.matrix.screen.v1' as const;
export const MATRIX_DEVICE_LEASE_SCHEMA = 'loom.matrix.device_lease.v1' as const;

export type MatrixExecutionMode = 'observe' | 'safe' | 'full';
export type MatrixExecutionProfile = 'fast' | 'standard' | 'deep';

interface MatrixAssignmentBase {
  assignmentId: string;
  deviceId: string;
  input: Record<string, unknown>;
  timeoutSec: number;
  retryBudget: number;
}

export type MatrixDeviceAssignment = MatrixAssignmentBase & (
  | { prompt: string; templateId?: string }
  | { prompt?: string; templateId: string }
);

export interface MatrixDispatchRequest {
  schema: typeof MATRIX_DISPATCH_SCHEMA;
  campaignId: string;
  concurrency: number;
  mode?: MatrixExecutionMode;
  profile?: MatrixExecutionProfile;
  deviceAssignments: MatrixDeviceAssignment[];
}

interface LegacyMatrixDispatchBase {
  campaignId?: string;
  concurrency?: number;
  mode?: MatrixExecutionMode;
  profile?: MatrixExecutionProfile;
  input?: Record<string, unknown>;
  confirmed?: boolean;
}

type LegacyMatrixTarget =
  | { deviceIds: string[]; groups?: never; allOnline?: never }
  | { deviceIds?: never; groups: string[]; allOnline?: never }
  | { deviceIds?: never; groups?: never; allOnline: true };

type LegacyMatrixTargetSelection =
  | { deviceIds: string[]; target?: never }
  | { deviceIds?: never; target: LegacyMatrixTarget };

type LegacyMatrixOperation =
  | { prompt: string; template?: string; templateId?: string; action?: string }
  | { prompt?: string; template: string; templateId?: string; action?: string }
  | { prompt?: string; template?: string; templateId: string; action?: string }
  | { prompt?: string; template?: string; templateId?: string; action: string };

export type LegacyMatrixDispatchRequest = LegacyMatrixDispatchBase
  & LegacyMatrixTargetSelection
  & LegacyMatrixOperation;

export type MatrixDeviceTaskStatus =
  | 'queued'
  | 'preflight'
  | 'running'
  | 'completed'
  | 'failed'
  | 'needs_human'
  | 'paused'
  | 'cancelled'
  | 'retrying';

export interface MatrixDeviceTask {
  assignmentId: string;
  deviceTaskId: string;
  deviceId: string;
  jobId: string | null;
  status: MatrixDeviceTaskStatus;
  attempt: number;
  failureCode?: string;
  failureReason?: string;
}

export type MatrixCampaignStatus =
  | 'queued'
  | 'running'
  | 'partial'
  | 'completed'
  | 'failed'
  | 'paused'
  | 'cancelled';

export interface MatrixCampaignCounts {
  total: number;
  queued: number;
  running: number;
  completed: number;
  failed: number;
  needsHuman: number;
}

export interface MatrixCampaign {
  schema: typeof MATRIX_CAMPAIGN_SCHEMA;
  campaignId: string;
  status: MatrixCampaignStatus;
  concurrency: number;
  counts: MatrixCampaignCounts;
  deviceTasks: MatrixDeviceTask[];
}

export interface MatrixAssignmentEventData extends Record<string, unknown> {
  campaignId: string;
  assignmentId: string;
  deviceTaskId: string;
  deviceId: string;
  jobId: string | null;
  attempt: number;
  status: MatrixDeviceTaskStatus;
  progress?: number;
}

interface MatrixScreenBase {
  schema: typeof MATRIX_SCREEN_SCHEMA;
  deviceId: string;
  capturedAt: string;
  screenHash: string;
  mime: 'image/jpeg' | 'image/png' | 'image/webp';
  width: number;
  height: number;
}

export type MatrixScreen = MatrixScreenBase & (
  | { notModified: true; image?: never }
  | { notModified: false; image: string }
);

export interface MatrixScreenBatchRequest {
  deviceId: string;
  knownHash?: string;
  focused?: boolean;
}

export interface MatrixScreenBatchError {
  deviceId: string;
  errorCode: string;
  error: string;
}

export interface MatrixScreenBatchResponse {
  schema: 'loom.matrix.screens.v1';
  screens: MatrixScreen[];
  errors: MatrixScreenBatchError[];
}

export type MatrixLeaseHolderType = 'agent' | 'human';

export interface MatrixDeviceLease {
  schema: typeof MATRIX_DEVICE_LEASE_SCHEMA;
  leaseId: string;
  deviceId: string;
  holderType: MatrixLeaseHolderType;
  holderId: string;
  mode: 'control';
  expiresAt: string;
}

export interface AcquireMatrixLeaseRequest {
  holderType: MatrixLeaseHolderType;
  holderId: string;
  mode?: 'control';
  leaseId?: string;
}

interface MatrixControlBase {
  leaseId: string;
  clientCommandId: string;
}

export type MatrixControlRequest = MatrixControlBase & (
  | { action: 'tap'; x: number; y: number }
  | { action: 'swipe'; x: number; y: number; endX: number; endY: number; durationMs?: number }
  | { action: 'input_text'; text: string }
  | { action: 'back' | 'home' | 'recent' | 'screenshot' | 'rotate' }
);

export interface MatrixCommandResponse {
  status: 'requested' | 'applied' | 'too_late' | string;
  code?: string;
  error?: string;
  campaign?: MatrixCampaign;
  deviceTask?: MatrixDeviceTask;
  lease?: MatrixDeviceLease | null;
  commandId?: string;
}

export interface MatrixDeviceSummary {
  deviceId: string;
  name?: string;
  group?: string;
  groups?: string[];
  online: boolean;
  busy?: boolean;
  heartbeatAt?: string;
  presenceObservedAt?: string;
  lastEventAt?: string;
  streamStatus?: string;
  streamLatencyMs?: number;
  currentPackage?: string;
  foregroundApp?: string;
  accessibilityRunning?: boolean | null;
  screenOn?: boolean | null;
  deviceLocked?: boolean | null;
  runningTaskCount?: number;
  currentTaskId?: string;
  currentScreenSummary?: string;
  failureCount?: number;
  model?: string;
  lastResult?: string;
  updatedAt?: string;
  source?: string;
  selected?: boolean;
  platform?: string;
  account?: string;
  progress?: number;
  queue?: number;
  elapsedMs?: number;
}

export interface MatrixStatusSnapshot {
  schema: string;
  updatedAt?: string;
  devices: MatrixDeviceSummary[];
  summary?: {
    total?: number;
    online?: number;
    busy?: number;
    failed?: number;
  };
  campaigns?: Array<MatrixCampaign | Record<string, unknown>>;
}

export interface MatrixEvent {
  eventId?: string;
  seq?: number;
  timestamp?: string;
  type: string;
  campaignId?: string;
  missionId?: string;
  assignmentId?: string;
  deviceTaskId?: string;
  jobId?: string;
  deviceId?: string;
  message?: string;
  data?: Record<string, unknown>;
}

export interface MatrixDispatchResponse {
  jobId?: string;
  campaign?: MatrixCampaign;
  task?: Record<string, unknown>;
  status?: MatrixStatusSnapshot;
}
