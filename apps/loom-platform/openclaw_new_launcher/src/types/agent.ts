export const AGENT_SESSION_SCHEMA = 'loom.agent.session.v1' as const;
export const AGENT_MESSAGE_SCHEMA = 'loom.agent.message.v1' as const;
export const AGENT_RUN_SCHEMA = 'loom.agent.run.v1' as const;
export const AGENT_APPROVAL_SCHEMA = 'loom.agent.approval.v1' as const;

export type AgentSessionStatus = 'active' | 'archived';
export type AgentMessageRole = 'user' | 'assistant' | 'system' | 'tool';
export type AgentMessageStatus = 'streaming' | 'completed' | 'failed';
export type AgentRunStatus =
  | 'queued'
  | 'running'
  | 'waiting_approval'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface AgentSession {
  schema: typeof AGENT_SESSION_SCHEMA;
  sessionId: string;
  title: string;
  status: AgentSessionStatus;
  runtimeProfileId: string;
  modelId?: string;
  createdAt: string;
  updatedAt: string;
  lastMessagePreview?: string;
  activeRunId?: string;
}

export type AgentMessageBlockType = 'text' | 'plan' | 'tool' | 'approval' | 'matrix' | 'error';

export interface AgentMessageBlock {
  type: AgentMessageBlockType;
  data: Record<string, unknown>;
}

export interface AgentMessage {
  schema: typeof AGENT_MESSAGE_SCHEMA;
  messageId: string;
  sessionId: string;
  role: AgentMessageRole;
  status: AgentMessageStatus;
  blocks: AgentMessageBlock[];
  createdAt: string;
  completedAt?: string;
}

export interface AgentError {
  code: string;
  message: string;
  recoverable?: boolean;
}

export interface AgentRun {
  schema: typeof AGENT_RUN_SCHEMA;
  runId: string;
  sessionId: string;
  status: AgentRunStatus;
  checkpoint?: string;
  campaignIds: string[];
  modelId?: string;
  modelSource?: 'session' | 'account-default';
  startedAt?: string;
  completedAt?: string;
  error?: AgentError & { recoverable: boolean };
}

export type AgentTraceKind = 'runtime' | 'plan' | 'tool' | 'policy' | 'matrix';

export interface AgentTraceNode {
  traceId: string;
  parentTraceId?: string;
  runId: string;
  kind: AgentTraceKind;
  name: string;
  status: 'running' | 'completed' | 'failed';
  startedAt: string;
  durationMs?: number;
  inputSummary?: unknown;
  outputSummary?: unknown;
  error?: AgentError;
}

export type AgentApprovalRisk = 'outbound' | 'critical';
export type AgentApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired' | 'consumed';

interface AgentApprovalBase {
  schema: typeof AGENT_APPROVAL_SCHEMA;
  approvalId: string;
  sessionId: string;
  runId: string;
  toolCallId: string;
  capability: string;
  inputHash: string;
  actionSummary: string;
  targets: Record<string, unknown>;
  inputSummary: Record<string, unknown>;
  risk: AgentApprovalRisk;
  riskReason: string;
  requestedAt: string;
  expiresAt: string;
}

export type AgentApproval = AgentApprovalBase & (
  | {
      status: 'pending' | 'expired';
      decision?: 'approved' | 'rejected';
      decidedBy?: string;
      decidedAt?: string;
      consumedAt?: string;
    }
  | {
      status: 'approved';
      decision: 'approved';
      decidedBy: string;
      decidedAt: string;
      consumedAt?: string;
    }
  | {
      status: 'rejected';
      decision: 'rejected';
      decidedBy: string;
      decidedAt: string;
      consumedAt?: string;
    }
  | {
      status: 'consumed';
      decision: 'approved';
      decidedBy: string;
      decidedAt: string;
      consumedAt: string;
    }
);

export interface AgentCapabilitySummary {
  name: string;
  displayName?: string;
  description?: string;
  domain?: string;
  targetScope?: string;
  source: 'internal' | 'skill' | 'mcp' | 'cli';
  permission: string;
  risk: string;
  available: boolean;
}

export interface AgentModelSummary {
  modelId: string;
  name: string;
  available: boolean;
}

export interface AgentScope {
  deviceIds: string[];
  groups: string[];
  allOnline: boolean;
}

export interface AgentRuntimeProfile {
  runtimeProfileId: string;
  name: string;
  available: boolean;
  isDefault?: boolean;
  error?: AgentError;
}

export interface AgentBootstrapResponse {
  runtimeProfiles: AgentRuntimeProfile[];
  capabilities: AgentCapabilitySummary[];
  defaultRuntimeProfileId?: string;
  models?: AgentModelSummary[];
  defaultModelId?: string;
  permissions?: Record<string, boolean>;
}

export interface AgentSessionListResponse {
  sessions: AgentSession[];
  nextCursor?: string;
}

export interface AgentSessionDetailResponse {
  session: AgentSession;
  messages: AgentMessage[];
  runs?: AgentRun[];
  nextCursor?: string;
}

export interface CreateAgentSessionRequest {
  title?: string;
  runtimeProfileId?: string;
  modelId?: string;
}

export interface UpdateAgentSessionRequest {
  title?: string;
  status?: AgentSessionStatus;
  modelId?: string;
}

export interface SendAgentMessageRequest {
  clientMessageId: string;
  text: string;
  attachments?: Array<Record<string, unknown>>;
  scopeMode?: 'auto' | 'manual';
  scope?: Partial<AgentScope>;
  runtimeProfileId?: string;
}

export interface SendAgentMessageResponse {
  message: AgentMessage;
  run: AgentRun;
}

export interface AgentRunTraceResponse {
  run: AgentRun;
  trace: AgentTraceNode[];
  approvals?: AgentApproval[];
}

export interface ResolveAgentApprovalRequest {
  decision: 'approve' | 'reject';
  operator?: string;
}
