import {
  AGENT_MESSAGE_SCHEMA,
  AGENT_RUN_SCHEMA,
  type AgentMessage,
  type AgentMessageBlock,
  type AgentMessageRole,
  type AgentModelSummary,
  type AgentRun,
  type AgentRunStatus,
  type UpdateAgentSessionRequest,
} from '../../types/agent';
import type { LoomRealtimeEvent } from '../../types/realtime';

const EVENT_ID_HISTORY_LIMIT = 512;
const SECRET_FIELD = /^(?:api[_-]?key|(?:(?:access|refresh|session|bridge|member)[_-]?)?token|secret|password|cookie|authorization|credential)$/i;

export interface AgentEventState {
  messages: AgentMessage[];
  runs: Record<string, AgentRun>;
  lastSeq: number;
  seenEventIds: string[];
}

export function agentModelSelectionState(
  sessionModelId: string | undefined,
  defaultModelId: string | undefined,
  models: AgentModelSummary[],
): { usesAccountDefault: boolean; effectiveModelId: string; effectiveModelName: string } {
  const availableModels = models.filter((model) => model.available);
  const effectiveModelId = sessionModelId || defaultModelId || availableModels[0]?.modelId || '';
  const effectiveModel = availableModels.find((model) => model.modelId === effectiveModelId);
  return {
    usesAccountDefault: !sessionModelId,
    effectiveModelId,
    effectiveModelName: effectiveModel?.name || effectiveModelId,
  };
}

export function agentModelUpdateRequest(modelId?: string): UpdateAgentSessionRequest {
  return { modelId: modelId || '' };
}

export function shouldShowThinking(
  messages: AgentMessage[],
  run: AgentRun | null,
  sending: boolean,
): boolean {
  let lastUserIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === 'user') {
      lastUserIndex = index;
      break;
    }
  }
  if (
    run?.status === 'failed'
    || run?.status === 'cancelled'
    || run?.status === 'completed'
    || run?.status === 'paused'
    || run?.status === 'waiting_approval'
  ) {
    return false;
  }
  if (lastUserIndex < 0) return sending;

  const userTimestamp = Date.parse(messages[lastUserIndex].createdAt);
  const afterUser = messages.filter((message, index) => {
    if (message.role === 'user') return false;
    if (index > lastUserIndex) return true;
    const messageTimestamp = Date.parse(message.createdAt);
    return Number.isFinite(userTimestamp)
      && Number.isFinite(messageTimestamp)
      && messageTimestamp > userTimestamp;
  });
  const assistantMessages = afterUser.filter((message) => message.role === 'assistant');
  if (assistantMessages.some((message) => message.status === 'streaming')) return false;

  if (run?.status === 'queued') return true;
  if (run?.status === 'running') {
    const toolMessageIndexes = afterUser.flatMap((message, index) => (
      message.blocks.some((block) => block.type === 'tool' && block.data.runId === run.runId)
        ? [index]
        : []
    ));
    const toolBlocks = afterUser.flatMap((message) => message.blocks.filter((block) => (
      block.type === 'tool' && block.data.runId === run.runId
    )));
    const hasActiveTool = toolBlocks.some((block) => block.data.status === 'queued' || block.data.status === 'running');
    if (hasActiveTool) return false;
    if (toolMessageIndexes.length) {
      const lastToolIndex = toolMessageIndexes[toolMessageIndexes.length - 1];
      return !afterUser.slice(lastToolIndex + 1).some((message) => message.role === 'assistant');
    }
    return assistantMessages.length === 0;
  }
  if (sending) return assistantMessages.length === 0;
  return false;
}

export function thinkingStatusLabel(messages: AgentMessage[], run: AgentRun | null): string {
  if (run?.status !== 'running') return '麓鸣正在思考';
  const hasTerminalTool = messages.some((message) => message.blocks.some((block) => (
    block.type === 'tool'
    && block.data.runId === run.runId
    && (block.data.status === 'completed' || block.data.status === 'failed')
  )));
  return hasTerminalTool ? '麓鸣正在整理结果' : '麓鸣正在思考';
}

function runTimestamp(run: AgentRun): number {
  const value = Date.parse(run.startedAt || run.completedAt || '');
  return Number.isFinite(value) ? value : 0;
}

export function selectCurrentAgentRun(
  sessionId: string | null,
  activeRunId: string | undefined,
  runs: Record<string, AgentRun>,
): AgentRun | null {
  if (!sessionId) return null;
  const activeRun = activeRunId ? runs[activeRunId] : undefined;
  if (activeRun?.sessionId === sessionId) return activeRun;

  return Object.values(runs).reduce<AgentRun | null>((latest, run) => {
    if (run.sessionId !== sessionId) return latest;
    if (!latest || runTimestamp(run) >= runTimestamp(latest)) return run;
    return latest;
  }, null);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

export type ToolLifecycleStatus = 'queued' | 'running' | 'completed' | 'failed';

export function normalizeAgentMessages(messages: AgentMessage[]): AgentMessage[] {
  const ranked = messages.map((message, index) => {
    const parsed = Date.parse(message.createdAt);
    return {
      message,
      index,
      timestamp: Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER,
    };
  });
  ranked.sort((left, right) => left.timestamp - right.timestamp || left.index - right.index);
  const ordered = ranked.map((item) => item.message);
  return ordered.every((message, index) => message === messages[index]) ? messages : ordered;
}

export function capabilityActionLabel(capability: unknown, status: unknown = 'running'): string {
  const normalized = typeof capability === 'string'
    ? capability.toLowerCase().replace(/[^a-z0-9]+/g, '.')
    : '';
  const lifecycle: ToolLifecycleStatus = status === 'queued'
    || status === 'completed'
    || status === 'failed'
    ? status
    : 'running';
  const copy = (queued: string, running: string, completed: string, failed: string) => ({
    queued,
    running,
    completed,
    failed,
  }[lifecycle]);
  if (normalized.includes('video') && (normalized.includes('generate') || normalized.includes('submit'))) {
    return copy('等待提交视频任务', '正在提交视频任务', '视频任务已提交', '视频任务提交未完成');
  }
  if (normalized.includes('image') && (normalized.includes('generate') || normalized.includes('create'))) {
    return copy('等待生成图片', '正在生成图片', '图片已生成', '图片生成未完成');
  }
  if (normalized.includes('phone') && (normalized.includes('read') || normalized.includes('screen') || normalized.includes('screenshot'))) {
    return copy('等待读取手机屏幕', '正在读取手机屏幕', '手机屏幕已读取', '手机屏幕读取未完成');
  }
  if (normalized.includes('phone') && normalized.includes('status')) {
    return copy('等待检查手机连接', '正在检查手机连接', '手机连接已检查', '手机连接检查未完成');
  }
  if (normalized.includes('phone') && (normalized.includes('task') || normalized.includes('control') || normalized.includes('tap'))) {
    return copy('等待控制手机', '正在控制手机', '手机操作已完成', '手机操作未完成');
  }
  if (normalized.includes('acquisition') && normalized.includes('agent.run')) {
    return copy('等待启动获客任务', '正在启动获客任务', '获客任务已启动', '获客任务启动未完成');
  }
  if (normalized.includes('acquisition') && normalized.includes('result')) {
    return copy('等待保存获客结果', '正在保存获客结果', '获客结果已保存', '获客结果保存未完成');
  }
  if (normalized.includes('matrix') && normalized.includes('dispatch')) {
    return copy('等待分发矩阵任务', '正在分发矩阵任务', '矩阵任务已分发', '矩阵任务分发未完成');
  }
  if (normalized.includes('matrix') && normalized.includes('cancel')) {
    return copy('等待取消矩阵任务', '正在取消矩阵任务', '矩阵任务已取消', '矩阵任务取消未完成');
  }
  if (normalized.includes('matrix') && (normalized.includes('status') || normalized.includes('list'))) {
    return copy('等待检查矩阵状态', '正在检查矩阵状态', '矩阵状态已检查', '矩阵状态检查未完成');
  }
  if (normalized.includes('log') || normalized.includes('diagnostic') || normalized.includes('status')) {
    return copy('等待检查系统状态', '正在检查系统状态', '系统状态已检查', '系统状态检查未完成');
  }
  if (normalized.includes('job')) {
    return copy('等待查询任务', '正在查询任务', '任务信息已查询', '任务查询未完成');
  }
  if (normalized.includes('model')) {
    return copy('等待检查模型状态', '正在检查模型状态', '模型状态已检查', '模型状态检查未完成');
  }
  if (normalized.includes('agent')) {
    return copy('等待检查智能体状态', '正在检查智能体状态', '智能体状态已检查', '智能体状态检查未完成');
  }
  return copy('等待调用麓鸣能力', '正在调用麓鸣能力', '麓鸣能力调用完成', '麓鸣能力调用未完成');
}

export interface UserFacingAgentError {
  title: string;
  message: string;
  recoverable: boolean;
}

function errorRecord(data: Record<string, unknown>): Record<string, unknown> {
  return isRecord(data.error) ? data.error : data;
}

function errorCode(data: Record<string, unknown>): string {
  return stringValue(errorRecord(data).code)?.toLowerCase() || '';
}

function errorText(data: Record<string, unknown>): string {
  return stringValue(errorRecord(data).message) || '';
}

function actionableErrorText(data: Record<string, unknown>): string {
  return errorText(data)
    .replace(/^Capability failed:[^:]+:\s*/i, '')
    .replace(/^Tool failed:[^:]+:\s*/i, '')
    .trim()
    .slice(0, 280);
}

function isProtocolError(data: Record<string, unknown>): boolean {
  const code = errorCode(data);
  const message = errorText(data).toLowerCase();
  return code === 'capability_not_found'
    || code === 'agent_invalid_tool_call'
    || code.includes('protocol')
    || message.includes('unknown capability')
    || message.includes('unknown tool')
    || message.includes('invalid tool');
}

export function userFacingAgentError(data: Record<string, unknown>): UserFacingAgentError {
  const error = errorRecord(data);
  const code = errorCode(data);
  const message = errorText(data).toLowerCase();
  if (code === 'capability_invalid_input') {
    const missingField = message.match(/input\.([a-z0-9_]+) is required/i)?.[1];
    const fieldGuidance: Record<string, string> = {
      title: '缺少发布标题。麓鸣会根据正文自动补全；若仍失败，请在任务中明确写出标题。',
      body: '缺少发布正文。请补充希望发布的文案内容后重试。',
      deviceid: '缺少目标手机。请在输入框下方选择要操作的手机后重试。',
      mediapaths: '没有找到可发布的图片或视频，请先生成或选择素材。',
    };
    return {
      title: '发布信息不完整',
      message: (missingField && fieldGuidance[missingField.toLowerCase()])
        || '智能体提交的参数不完整，任务已保留，请补充必要信息后重试。',
      recoverable: true,
    };
  }
  if (code === 'agent_account_relogin_required') {
    return {
      title: '模型账号需要重新登录',
      message: '当前模型凭据无法升级，请打开“模型账号”重新登录后再重试。',
      recoverable: true,
    };
  }
  if (code === 'agent_account_login_required') {
    return {
      title: '请先登录模型账号',
      message: '请打开“模型账号”完成登录，然后返回这里重试。',
      recoverable: true,
    };
  }
  if (code === 'agent_model_credential_refresh_failed') {
    return {
      title: '模型账号暂不可用',
      message: '模型凭据刷新失败，请检查网络；若持续出现，请重新登录模型账号。',
      recoverable: true,
    };
  }
  if (code === 'phone_target_scope_required' || code === 'phone_single_target_required') {
    return {
      title: '请选择目标手机',
      message: '自动选择未能确定唯一设备，请在输入框下方选择目标手机后重试。',
      recoverable: true,
    };
  }
  if (code === 'critical_target_required') {
    return {
      title: '请明确操作对象',
      message: '这项操作需要明确目标，请指定要操作的设备或对象后重试。',
      recoverable: true,
    };
  }
  if (code === 'matrix_target_scope_required') {
    return {
      title: '请选择矩阵目标',
      message: '请在输入框下方选择手机、设备组或全部在线设备后重试。',
      recoverable: true,
    };
  }
  if (code === 'matrix_campaign_scope_required') {
    return {
      title: '请选择对应矩阵任务',
      message: '取消或重试需要关联一个已下发的矩阵任务，请返回原会话或打开对应任务后再操作。',
      recoverable: true,
    };
  }
  if (code === 'matrix_campaign_scope_violation') {
    return {
      title: '矩阵任务不匹配',
      message: '当前会话没有关联到要操作的矩阵任务，请打开对应任务后再取消或重试。',
      recoverable: true,
    };
  }
  if (code === 'capability_unavailable') {
    return {
      title: '能力尚未就绪',
      message: '这项能力尚未连接，请检查对应组件是否已安装、配置是否完整以及运行状态是否正常。',
      recoverable: true,
    };
  }
  if (code === 'media_asset_not_found' || code === 'publish_media_missing') {
    return {
      title: '找不到可用素材',
      message: '请先生成图片或视频，或从本地素材库选择仍然存在的文件后再发布。',
      recoverable: true,
    };
  }
  if (
    code === 'phone_task_timeout'
    || code === 'media_job_timeout'
    || code === 'media_transfer_timeout'
    || code === 'publish_job_timeout'
    || code === 'capability_timeout_indeterminate'
  ) {
    return {
      title: '执行状态待确认',
      message: '任务已超过等待时间，停止请求已经发出，但手机端或生成服务可能仍在执行。请先查看目标状态和任务记录，避免重复执行。',
      recoverable: false,
    };
  }
  if (code === 'capability_timeout') {
    return {
      title: '能力等待超时',
      message: '这项能力没有在时间限制内开始执行，本轮没有产生新的操作。请稍后重试；若持续出现，请检查系统负载。',
      recoverable: true,
    };
  }
  if (code === 'agent_repeated_tool_call' || code === 'agent_tool_loop_limit') {
    return {
      title: '已停止重复调用',
      message: '智能体连续调用工具但没有获得新证据，麓鸣已停止本轮执行。请查看运行详情、补充目标或调整任务后重试。',
      recoverable: true,
    };
  }
  if (code === 'agent_restart_inflight_unknown') {
    return {
      title: '执行状态待确认',
      message: '应用关闭或重启时有工具正在执行，麓鸣不会自动重放。请先查看目标设备和任务记录，确认实际结果后再决定是否重试，避免重复执行。',
      recoverable: false,
    };
  }
  if (code === 'agent_service_inflight_unknown') {
    return {
      title: '执行状态待确认',
      message: '智能体服务异常时有工具正在执行，操作可能仍在手机或平台端继续。请先查看目标状态和任务记录，避免重复执行。',
      recoverable: false,
    };
  }
  if (code === 'agent_tool_result_persistence_failed') {
    return {
      title: '执行结果未能保存',
      message: '工具已经执行，但麓鸣未能可靠保存结果。请先检查手机、矩阵任务、素材库或发布记录，确认实际状态后再决定是否重试。',
      recoverable: false,
    };
  }
  if (code === 'approval_rejected' || code === 'approval_expired') {
    return {
      title: '操作未获授权',
      message: '这项操作没有执行。需要继续时，请确认目标和内容后重新发起。',
      recoverable: true,
    };
  }
  if (
    code === 'approval_conflict'
    || code === 'approval_already_resolved'
    || code === 'approval_scope_mismatch'
  ) {
    return {
      title: '审批状态已变化',
      message: '这项审批已在其他操作中处理或不再匹配当前任务，请刷新会话查看最新状态。',
      recoverable: true,
    };
  }
  if (code === 'phone_target_not_found' || code === 'phone_target_unavailable') {
    return {
      title: '目标手机不可用',
      message: '原目标已不存在或当前不可用，请刷新设备状态并重新选择一台在线手机。',
      recoverable: true,
    };
  }
  if (code === 'agent_runtime_output_too_large' || code === 'agent_model_output_too_large') {
    return {
      title: '智能体输出过多',
      message: '麓鸣已停止本轮模型进程以保护工作台，尚未继续执行新的工具。请缩短任务、减少一次处理的内容或更换模型后重试。',
      recoverable: true,
    };
  }
  if (
    code === 'agent_runtime_invalid_output'
    || code === 'agent_runtime_empty_output'
    || code === 'agent_runtime_invalid_tool_calls'
    || code === 'agent_model_protocol_invalid'
  ) {
    return {
      title: '模型响应格式异常',
      message: '模型没有返回麓鸣可执行的结构化结果，本轮未继续执行新的工具。可以重试；若持续出现，请切换模型。',
      recoverable: true,
    };
  }
  if (code === 'agent_runtime_event_failed') {
    return {
      title: '运行记录写入失败',
      message: '麓鸣已停止智能体子进程，没有继续执行后续工具。请重试；若持续出现，请前往环境诊断导出日志。',
      recoverable: true,
    };
  }
  if (code === 'agent_runtime_timeout' || code === 'agent_model_timeout') {
    return {
      title: '模型响应超时',
      message: '本轮模型响应超过时间限制，麓鸣已停止等待，尚未继续执行新的工具。请检查网络或更换模型后重试。',
      recoverable: true,
    };
  }
  if (code === 'capability_invalid_output') {
    return {
      title: '执行结果待确认',
      message: '操作已经发起，但返回结果格式异常，麓鸣无法确认最终状态。请先查看目标设备或任务记录，确认后再决定是否重试，避免重复执行。',
      recoverable: false,
    };
  }
  if (code === 'capability_execution_unknown') {
    return {
      title: '执行状态待确认',
      message: '操作已经发出，但连接在返回结果前中断，麓鸣无法确认是否已生效。请先查看手机、矩阵任务、素材库或发布记录，避免直接重复执行。',
      recoverable: false,
    };
  }
  if (isProtocolError(data)) {
    return {
      title: '能力暂不可用',
      message: '麓鸣未能匹配到这项能力，任务已保留，可重试或查看运行详情。',
      recoverable: true,
    };
  }
  if (
    code === 'phone_login_required'
    || (
      code === 'phone_publish_semantic_failure'
      && (/未登录|需要登录|请先登录/.test(message) || /not logged in|login required/.test(message))
    )
  ) {
    return {
      title: '抖音需要登录',
      message: '请先在手机上手动登录抖音，完成后重试。麓鸣不会代填账号、密码或验证码。',
      recoverable: true,
    };
  }
  if (error.outcomeIndeterminate === true || data.outcomeIndeterminate === true) {
    return {
      title: '部分结果待确认',
      message: '任务可能已经在部分设备或平台生效。请先检查目标手机、素材库、矩阵任务或发布记录，再决定是否重新执行。',
      recoverable: false,
    };
  }
  if (code.includes('device_offline') || message.includes('device offline')) {
    return {
      title: '设备暂时离线',
      message: '请检查手机连接后重试，当前任务已保留。',
      recoverable: true,
    };
  }
  if (code.includes('matrix') || message.includes('matrix')) {
    const detail = actionableErrorText(data);
    return {
      title: '矩阵任务未完成',
      message: detail || '矩阵任务未能完成，请检查失败设备和手机连接后重试。',
      recoverable: error.recoverable === true || data.recoverable === true,
    };
  }
  if (error.recoverable === true || data.recoverable === true) {
    return {
      title: '任务暂未完成',
      message: actionableErrorText(data) || '当前步骤未完成，任务已保留，可重试或查看运行详情。',
      recoverable: true,
    };
  }
  return {
    title: '任务执行失败',
    message: actionableErrorText(data) || '当前任务未能完成，请查看运行详情。',
    recoverable: false,
  };
}

function isAgentMessage(value: unknown): value is AgentMessage {
  if (!isRecord(value)) return false;
  return value.schema === AGENT_MESSAGE_SCHEMA
    && typeof value.messageId === 'string'
    && typeof value.sessionId === 'string'
    && Array.isArray(value.blocks);
}

function roleValue(value: unknown): AgentMessageRole {
  return value === 'user' || value === 'system' || value === 'tool' ? value : 'assistant';
}

function blockData(data: Record<string, unknown>): Record<string, unknown> {
  const { message: _message, run: _run, sessionId: _sessionId, messageId: _messageId, ...rest } = data;
  return sanitizeDisplayValue(rest) as Record<string, unknown>;
}

function messageIdFor(event: LoomRealtimeEvent, suffix: string): string {
  return stringValue(event.data.messageId)
    || stringValue(event.data.toolCallId)
    || stringValue(event.data.approvalId)
    || (event.type.startsWith('matrix.') && stringValue(event.data.campaignId)
      ? `matrix:${stringValue(event.data.campaignId)}`
      : undefined)
    || `${event.entityId}:${suffix}`;
}

function createMessage(
  messageId: string,
  sessionId: string,
  role: AgentMessageRole,
  status: AgentMessage['status'],
  blocks: AgentMessageBlock[],
  createdAt: string,
): AgentMessage {
  return {
    schema: AGENT_MESSAGE_SCHEMA,
    messageId,
    sessionId,
    role,
    status,
    blocks,
    createdAt,
  };
}

function updateMessage(
  messages: AgentMessage[],
  messageId: string,
  create: () => AgentMessage,
  update: (message: AgentMessage) => AgentMessage,
): AgentMessage[] {
  const index = messages.findIndex((message) => message.messageId === messageId);
  if (index < 0) return [...messages, create()];
  const next = [...messages];
  next[index] = update(messages[index]);
  return next;
}

function toolIdentity(event: LoomRealtimeEvent): { runId: string; toolCallId: string } | null {
  const runId = stringValue(event.data.runId) || event.entityId;
  const toolCallId = stringValue(event.data.toolCallId);
  return runId && toolCallId ? { runId, toolCallId } : null;
}

function toolMessageId(runId: string): string {
  return `tool-run:${runId}`;
}

function toolStatus(value: unknown): ToolLifecycleStatus | undefined {
  return value === 'queued' || value === 'running' || value === 'completed' || value === 'failed'
    ? value
    : undefined;
}

function mergeToolStatus(
  current: ToolLifecycleStatus | undefined,
  incoming: ToolLifecycleStatus,
): ToolLifecycleStatus {
  if (current === 'completed' || current === 'failed') return current;
  if (incoming === 'completed' || incoming === 'failed') return incoming;
  if (current === 'running' && incoming === 'queued') return current;
  return incoming;
}

function messageStatusForTool(status: ToolLifecycleStatus): AgentMessage['status'] {
  if (status === 'completed') return 'completed';
  if (status === 'failed') return 'failed';
  return 'streaming';
}

function messageStatusForToolBlocks(blocks: AgentMessageBlock[]): AgentMessage['status'] {
  const statuses = blocks
    .filter((block) => block.type === 'tool')
    .map((block) => toolStatus(block.data.status));
  if (statuses.includes('failed')) return 'failed';
  if (statuses.some((status) => status === 'queued' || status === 'running')) return 'streaming';
  return 'completed';
}

function upsertToolBlock(
  messages: AgentMessage[],
  event: LoomRealtimeEvent,
  sessionId: string,
  incomingStatus: ToolLifecycleStatus,
): AgentMessage[] {
  const identity = toolIdentity(event);
  if (!identity) {
    return upsertBlock(
      messages,
      { ...event, data: { ...event.data, status: incomingStatus } },
      sessionId,
      'tool',
      messageStatusForTool(incomingStatus),
    );
  }

  const messageId = toolMessageId(identity.runId);
  const data = {
    ...blockData(event.data),
    ...identity,
    status: incomingStatus,
  };
  return updateMessage(
    messages,
    messageId,
    () => createMessage(
      messageId,
      sessionId,
      'tool',
      messageStatusForTool(incomingStatus),
      [{ type: 'tool', data }],
      event.timestamp,
    ),
    (message) => {
      const blockIndex = message.blocks.findIndex((block) => (
        block.type === 'tool'
        && block.data.runId === identity.runId
        && block.data.toolCallId === identity.toolCallId
      ));
      const currentBlock = blockIndex >= 0 ? message.blocks[blockIndex] : undefined;
      const status = mergeToolStatus(toolStatus(currentBlock?.data.status), incomingStatus);
      const nextBlock: AgentMessageBlock = {
        type: 'tool',
        data: { ...currentBlock?.data, ...data, status },
      };
      const blocks = [...message.blocks];
      if (blockIndex < 0) blocks.push(nextBlock);
      else blocks[blockIndex] = nextBlock;
      return { ...message, role: 'tool', status: messageStatusForToolBlocks(blocks), blocks };
    },
  );
}

function removeRejectedToolBlock(
  messages: AgentMessage[],
  event: LoomRealtimeEvent,
): AgentMessage[] {
  const identity = toolIdentity(event);
  if (!identity) return messages;
  const messageId = toolMessageId(identity.runId);
  return messages.flatMap((message) => {
    if (message.messageId !== messageId) return [message];
    const blocks = message.blocks.filter((block) => !(
      block.type === 'tool'
      && block.data.runId === identity.runId
      && block.data.toolCallId === identity.toolCallId
    ));
    if (!blocks.length) return [];
    return [{ ...message, status: messageStatusForToolBlocks(blocks), blocks }];
  });
}

function reconcileTerminalToolRows(
  messages: AgentMessage[],
  event: LoomRealtimeEvent,
  status: Extract<ToolLifecycleStatus, 'completed' | 'failed'>,
): AgentMessage[] {
  const suppliedRun = isRecord(event.data.run) ? event.data.run : undefined;
  const runId = stringValue(suppliedRun?.runId) || stringValue(event.data.runId) || event.entityId;
  const terminalData = blockData(event.data);
  let changed = false;
  const next = messages.map((message) => {
    let messageChanged = false;
    const blocks = message.blocks.map((block) => {
      if (
        block.type !== 'tool'
        || block.data.runId !== runId
        || !stringValue(block.data.toolCallId)
      ) return block;
      const currentStatus = toolStatus(block.data.status);
      if (currentStatus === 'completed' || currentStatus === 'failed') return block;
      messageChanged = true;
      return {
        ...block,
        data: status === 'failed'
          ? { ...block.data, ...terminalData, runId, status }
          : { ...block.data, status },
      };
    });
    if (!messageChanged) return message;
    changed = true;
    return { ...message, status: messageStatusForToolBlocks(blocks), blocks };
  });
  return changed ? next : messages;
}

function hasFailedToolForRun(messages: AgentMessage[], runId: string): boolean {
  return messages.some((message) => message.blocks.some((block) => (
    block.type === 'tool'
    && block.data.runId === runId
    && block.data.status === 'failed'
  )));
}

function moveMessageToEnd(messages: AgentMessage[], messageId: string): AgentMessage[] {
  const index = messages.findIndex((message) => message.messageId === messageId);
  if (index < 0 || index === messages.length - 1) return messages;
  return [...messages.slice(0, index), ...messages.slice(index + 1), messages[index]];
}

function upsertBlock(
  messages: AgentMessage[],
  event: LoomRealtimeEvent,
  sessionId: string,
  type: AgentMessageBlock['type'],
  status: AgentMessage['status'] = 'streaming',
): AgentMessage[] {
  const messageId = messageIdFor(event, type);
  const data = blockData(event.data);
  const nextBlock: AgentMessageBlock = { type, data };
  return updateMessage(
    messages,
    messageId,
    () => createMessage(messageId, sessionId, roleValue(event.data.role), status, [nextBlock], event.timestamp),
    (message) => {
      const blockIndex = message.blocks.findIndex((block) => {
        if (block.type !== type) return false;
        const nextIdentity = stringValue(data.toolCallId) || stringValue(data.approvalId);
        if (!nextIdentity) return true;
        return block.data.toolCallId === nextIdentity || block.data.approvalId === nextIdentity;
      });
      if (blockIndex < 0) return { ...message, status, blocks: [...message.blocks, nextBlock] };
      const blocks = [...message.blocks];
      blocks[blockIndex] = { type, data: { ...blocks[blockIndex].data, ...data } };
      return { ...message, status, blocks };
    },
  );
}

function upsertErrorBlock(
  messages: AgentMessage[],
  event: LoomRealtimeEvent,
  sessionId: string,
): AgentMessage[] {
  const data = blockData(event.data);
  const runId = stringValue(data.runId) || event.entityId;
  if (!runId || !isProtocolError(data)) return upsertBlock(messages, event, sessionId, 'error', 'failed');

  for (let messageIndex = 0; messageIndex < messages.length; messageIndex += 1) {
    const blockIndex = messages[messageIndex].blocks.findIndex((block) => (
      block.type === 'error'
      && block.data.runId === runId
      && isProtocolError(block.data)
    ));
    if (blockIndex < 0) continue;
    const next = [...messages];
    const message = messages[messageIndex];
    const blocks = [...message.blocks];
    const previous = blocks[blockIndex];
    blocks[blockIndex] = {
      type: 'error',
      data: {
        ...previous.data,
        ...data,
        runId,
        recoverable: true,
        occurrences: Number(previous.data.occurrences || 1) + 1,
      },
    };
    next[messageIndex] = { ...message, status: 'failed', blocks };
    return next;
  }

  return upsertBlock(messages, {
    ...event,
    data: {
      ...event.data,
      messageId: `protocol:${runId}`,
      runId,
      recoverable: true,
      occurrences: 1,
    },
  }, sessionId, 'error', 'failed');
}

function mergeDelta(messages: AgentMessage[], event: LoomRealtimeEvent, sessionId: string): AgentMessage[] {
  const messageId = messageIdFor(event, 'message');
  const delta = stringValue(event.data.delta) ?? stringValue(event.data.text) ?? '';
  const runId = stringValue(event.data.runId) || event.entityId;
  return updateMessage(
    messages,
    messageId,
    () => createMessage(messageId, sessionId, roleValue(event.data.role), 'streaming', [
      { type: 'text', data: { text: delta, runId } },
    ], event.timestamp),
    (message) => {
      const textIndex = message.blocks.findIndex((block) => block.type === 'text');
      const blocks = [...message.blocks];
      if (textIndex < 0) blocks.push({ type: 'text', data: { text: delta } });
      else {
        const currentText = stringValue(blocks[textIndex].data.text) ?? '';
        blocks[textIndex] = { type: 'text', data: { ...blocks[textIndex].data, text: currentText + delta, runId } };
      }
      return { ...message, status: 'streaming', blocks };
    },
  );
}

function finishStreamingNarration(messages: AgentMessage[], runId: string): AgentMessage[] {
  let changed = false;
  const next = messages.map((message) => {
    if (message.role !== 'assistant' || message.status !== 'streaming') return message;
    if (!message.blocks.some((block) => block.data.runId === runId)) return message;
    changed = true;
    return {
      ...message,
      status: 'completed' as const,
      blocks: message.blocks.map((block) => (
        block.type === 'text' && block.data.runId === runId
          ? { ...block, data: { ...block.data, preparatory: true } }
          : block
      )),
    };
  });
  return changed ? next : messages;
}

function removePreparatoryNarration(messages: AgentMessage[], runId: string): AgentMessage[] {
  return messages.filter((message) => !(
    message.role === 'assistant'
    && message.blocks.length > 0
    && message.blocks.every((block) => block.type === 'text')
    && message.blocks.some((block) => block.data.runId === runId && block.data.preparatory === true)
  ));
}

function mergeCompletedMessage(messages: AgentMessage[], event: LoomRealtimeEvent, sessionId: string): AgentMessage[] {
  const supplied = event.data.message;
  if (isAgentMessage(supplied)) {
    const merged = updateMessage(messages, supplied.messageId, () => supplied, () => supplied);
    return supplied.role === 'assistant' ? moveMessageToEnd(merged, supplied.messageId) : merged;
  }
  const messageId = messageIdFor(event, 'message');
  const text = stringValue(event.data.text);
  const merged = updateMessage(
    messages,
    messageId,
    () => createMessage(
      messageId,
      sessionId,
      roleValue(event.data.role),
      'completed',
      text ? [{ type: 'text', data: { text } }] : [],
      event.timestamp,
    ),
    (message) => ({
      ...message,
      status: 'completed',
      completedAt: stringValue(event.data.completedAt) || event.timestamp,
      blocks: text ? [{ type: 'text', data: { text } }, ...message.blocks.filter((block) => block.type !== 'text')] : message.blocks,
    }),
  );
  return roleValue(event.data.role) === 'assistant' ? moveMessageToEnd(merged, messageId) : merged;
}

function runStatusFor(type: string): AgentRunStatus | undefined {
  const statuses: Record<string, AgentRunStatus> = {
    'run.queued': 'queued',
    'run.started': 'running',
    'run.running': 'running',
    'run.waiting_approval': 'waiting_approval',
    'run.paused': 'paused',
    'run.resumed': 'running',
    'run.completed': 'completed',
    'run.failed': 'failed',
    'run.cancelled': 'cancelled',
  };
  return statuses[type];
}

function mergeRun(
  runs: Record<string, AgentRun>,
  event: LoomRealtimeEvent,
  sessionId: string,
): Record<string, AgentRun> {
  const supplied = isRecord(event.data.run) ? event.data.run : undefined;
  const runId = stringValue(supplied?.runId) || stringValue(event.data.runId) || event.entityId;
  const status = runStatusFor(event.type)
    || (stringValue(supplied?.status) as AgentRunStatus | undefined);
  if (!status && !supplied) return runs;
  const existing = runs[runId];
  const campaignIds = stringArray(supplied?.campaignIds ?? event.data.campaignIds);
  const errorValue = isRecord(supplied?.error) ? supplied.error : isRecord(event.data.error) ? event.data.error : undefined;
  const next: AgentRun = {
    schema: AGENT_RUN_SCHEMA,
    runId,
    sessionId: stringValue(supplied?.sessionId) || stringValue(event.data.sessionId) || existing?.sessionId || sessionId,
    status: status || existing?.status || 'running',
    campaignIds: campaignIds.length ? campaignIds : existing?.campaignIds || [],
    checkpoint: stringValue(supplied?.checkpoint) || stringValue(event.data.checkpoint) || existing?.checkpoint,
    startedAt: stringValue(supplied?.startedAt) || existing?.startedAt,
    completedAt: stringValue(supplied?.completedAt)
      || (status === 'completed' || status === 'failed' || status === 'cancelled' ? event.timestamp : existing?.completedAt),
    error: errorValue ? {
      code: stringValue(errorValue.code) || 'agent_run_failed',
      message: stringValue(errorValue.message) || '运行失败',
      recoverable: errorValue.recoverable === true,
    } : existing?.error,
  };
  return { ...runs, [runId]: next };
}

function mergeMessages(messages: AgentMessage[], event: LoomRealtimeEvent, sessionId: string): AgentMessage[] {
  switch (event.type) {
    case 'message.delta':
      return mergeDelta(messages, event, sessionId);
    case 'message.completed':
      return mergeCompletedMessage(messages, event, sessionId);
    case 'plan.updated':
      return upsertBlock(messages, event, sessionId, 'plan');
    case 'tool.queued':
      return upsertToolBlock(finishStreamingNarration(messages, stringValue(event.data.runId) || event.entityId), event, sessionId, 'queued');
    case 'tool.started':
      return upsertToolBlock(finishStreamingNarration(messages, stringValue(event.data.runId) || event.entityId), event, sessionId, 'running');
    case 'tool.completed':
      return upsertToolBlock(messages, event, sessionId, 'completed');
    case 'tool.input_rejected':
      return removeRejectedToolBlock(messages, event);
    case 'tool.failed':
      return upsertToolBlock(messages, event, sessionId, 'failed');
    case 'approval.required':
      return upsertBlock(messages, {
        ...event,
        data: isRecord(event.data.approval) ? { ...event.data, ...event.data.approval } : event.data,
      }, sessionId, 'approval');
    case 'approval.resolved':
      return upsertBlock(messages, {
        ...event,
        data: isRecord(event.data.approval) ? { ...event.data, ...event.data.approval } : event.data,
      }, sessionId, 'approval', 'completed');
    case 'matrix.attached':
      return upsertBlock(messages, event, sessionId, 'matrix');
    case 'run.completed':
      return reconcileTerminalToolRows(messages, event, 'completed');
    case 'run.failed': {
      const reconciled = reconcileTerminalToolRows(messages, event, 'failed');
      const suppliedRun = isRecord(event.data.run) ? event.data.run : undefined;
      const runId = stringValue(suppliedRun?.runId) || stringValue(event.data.runId) || event.entityId;
      const withoutPreparatoryNarration = removePreparatoryNarration(reconciled, runId);
      return hasFailedToolForRun(withoutPreparatoryNarration, runId)
        ? withoutPreparatoryNarration
        : upsertErrorBlock(withoutPreparatoryNarration, event, sessionId);
    }
    case 'run.cancelled':
      return reconcileTerminalToolRows(messages, event, 'failed');
    default:
      return event.type.startsWith('matrix.')
        ? upsertBlock(messages, event, sessionId, 'matrix', event.type === 'matrix.completed' ? 'completed' : 'streaming')
        : messages;
  }
}

export function createAgentEventState(messages: AgentMessage[] = []): AgentEventState {
  return { messages: normalizeAgentMessages([...messages]), runs: {}, lastSeq: 0, seenEventIds: [] };
}

export function mergeAgentEvent(
  state: AgentEventState,
  event: LoomRealtimeEvent,
  sessionId: string,
): AgentEventState {
  if (event.seq <= state.lastSeq || state.seenEventIds.includes(event.eventId)) return state;
  const eventSessionId = stringValue(event.data.sessionId)
    || (isRecord(event.data.message) ? stringValue(event.data.message.sessionId) : undefined)
    || (isRecord(event.data.run) ? stringValue(event.data.run.sessionId) : undefined);
  if (eventSessionId && eventSessionId !== sessionId) return state;

  return {
    messages: normalizeAgentMessages(mergeMessages(state.messages, event, sessionId)),
    runs: mergeRun(state.runs, event, sessionId),
    lastSeq: event.seq,
    seenEventIds: [...state.seenEventIds, event.eventId].slice(-EVENT_ID_HISTORY_LIMIT),
  };
}

export function sanitizeDisplayValue(value: unknown, key = ''): unknown {
  if (SECRET_FIELD.test(key)) return '[REDACTED]';
  if (Array.isArray(value)) return value.map((item) => sanitizeDisplayValue(item));
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.entries(value).map(([childKey, childValue]) => [childKey, sanitizeDisplayValue(childValue, childKey)]),
  );
}

export function formatDuration(durationMs?: number): string {
  if (durationMs === undefined) return '进行中';
  if (durationMs < 1000) return `${durationMs} ms`;
  return `${(durationMs / 1000).toFixed(durationMs < 10_000 ? 1 : 0)} s`;
}
