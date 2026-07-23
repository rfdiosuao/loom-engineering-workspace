import 'tsx/esm';

import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import type { AgentMessage } from '../../types/agent.ts';
import type { LoomRealtimeEvent } from '../../types/realtime.ts';
import {
  createAgentEventState,
  mergeAgentEvent,
  sanitizeDisplayValue,
} from './agentViewModel.ts';
import * as agentViewModel from './agentViewModel.ts';
import { MessageBlockView, ToolExecutionGroup } from './messageBlocks.tsx';

const SESSION_ID = 'session_1';

function event(
  seq: number,
  type: string,
  data: Record<string, unknown>,
  eventId = `event_${seq}`,
): LoomRealtimeEvent {
  return {
    schema: 'loom.realtime.event.v1',
    eventId,
    seq,
    timestamp: '2026-07-16T10:00:00+08:00',
    topic: 'agent.run',
    entityId: typeof data.runId === 'string' ? data.runId : 'run_1',
    type,
    data,
  };
}

function message(messageId: string, text: string, status: AgentMessage['status']): AgentMessage {
  return {
    schema: 'loom.agent.message.v1',
    messageId,
    sessionId: SESSION_ID,
    role: 'assistant',
    status,
    blocks: [{ type: 'text', data: { text } }],
    createdAt: '2026-07-16T10:00:00+08:00',
  };
}

test('thinking follows the active run phase without competing with streaming replies or active tools', () => {
  const shouldShowThinking = (agentViewModel as typeof agentViewModel & {
    shouldShowThinking?: (
      messages: AgentMessage[],
      run: {
        schema: 'loom.agent.run.v1';
        runId: string;
        sessionId: string;
        status: 'queued' | 'running' | 'failed' | 'cancelled' | 'completed' | 'paused';
        campaignIds: string[];
      } | null,
      sending: boolean,
    ) => boolean;
  }).shouldShowThinking;
  assert.equal(typeof shouldShowThinking, 'function');

  const userMessage = { ...message('message_user', '开始任务', 'completed'), role: 'user' as const };
  const assistantDelta = message('message_assistant', '正在处理', 'streaming');
  const run = (status: 'queued' | 'running' | 'failed' | 'cancelled' | 'completed' | 'paused') => ({
    schema: 'loom.agent.run.v1' as const,
    runId: 'run_1',
    sessionId: SESSION_ID,
    status,
    campaignIds: [],
  });

  assert.equal(shouldShowThinking?.([userMessage], null, true), true);
  assert.equal(shouldShowThinking?.([], null, true), true);
  assert.equal(shouldShowThinking?.([assistantDelta, userMessage], null, true), true);
  assert.equal(shouldShowThinking?.([userMessage, assistantDelta], null, true), false);
  assert.equal(shouldShowThinking?.([userMessage], run('queued'), false), true);
  assert.equal(shouldShowThinking?.([userMessage, assistantDelta], run('running'), false), false);
  assert.equal(shouldShowThinking?.([userMessage, assistantDelta], run('running'), true), false);
  assert.equal(shouldShowThinking?.([userMessage], run('failed'), true), false);
  assert.equal(shouldShowThinking?.([userMessage], run('cancelled'), true), false);
  assert.equal(shouldShowThinking?.([userMessage], run('completed'), true), false);
  assert.equal(shouldShowThinking?.([userMessage], run('paused'), true), false);

  const acknowledgedUser = { ...userMessage, createdAt: '2026-07-16T10:00:00+08:00' };
  const earlyAssistant = { ...assistantDelta, createdAt: '2026-07-16T10:00:01+08:00' };
  assert.equal(shouldShowThinking?.([earlyAssistant, acknowledgedUser], run('queued'), false), false);

  const runningTool: AgentMessage = {
    schema: 'loom.agent.message.v1',
    messageId: 'tool-run:run_1',
    sessionId: SESSION_ID,
    role: 'tool',
    status: 'streaming',
    blocks: [{ type: 'tool', data: { runId: 'run_1', toolCallId: 'tool_1', status: 'running' } }],
    createdAt: '2026-07-16T10:00:02+08:00',
  };
  const completedTool: AgentMessage = {
    ...runningTool,
    status: 'completed',
    blocks: [{ type: 'tool', data: { runId: 'run_1', toolCallId: 'tool_1', status: 'completed' } }],
  };
  const finalAssistant = { ...assistantDelta, messageId: 'message_final', status: 'completed' as const, createdAt: '2026-07-16T10:00:03+08:00' };

  assert.equal(shouldShowThinking?.([userMessage, runningTool], run('running'), false), false);
  assert.equal(shouldShowThinking?.([userMessage, completedTool], run('running'), false), true);
  assert.equal(shouldShowThinking?.([userMessage, completedTool, assistantDelta], run('running'), false), false);
  assert.equal(shouldShowThinking?.([userMessage, completedTool, finalAssistant], run('running'), false), false);
});

test('model selection distinguishes the account default from a session override', () => {
  const viewModel = agentViewModel as typeof agentViewModel & {
    agentModelSelectionState?: (
      sessionModelId: string | undefined,
      defaultModelId: string | undefined,
      models: Array<{ modelId: string; name: string; available: boolean }>,
    ) => {
      usesAccountDefault: boolean;
      effectiveModelId: string;
      effectiveModelName: string;
    };
    agentModelUpdateRequest?: (modelId?: string) => { modelId?: string };
  };
  assert.equal(typeof viewModel.agentModelSelectionState, 'function');
  assert.equal(typeof viewModel.agentModelUpdateRequest, 'function');

  const models = [
    { modelId: 'glm-5', name: 'GLM-5', available: true },
    { modelId: 'qwen3.7-plus', name: 'Qwen 3.7 Plus', available: true },
  ];
  assert.deepEqual(viewModel.agentModelSelectionState?.(undefined, 'glm-5', models), {
    usesAccountDefault: true,
    effectiveModelId: 'glm-5',
    effectiveModelName: 'GLM-5',
  });
  assert.deepEqual(viewModel.agentModelSelectionState?.('qwen3.7-plus', 'glm-5', models), {
    usesAccountDefault: false,
    effectiveModelId: 'qwen3.7-plus',
    effectiveModelName: 'Qwen 3.7 Plus',
  });
  assert.deepEqual(viewModel.agentModelUpdateRequest?.(undefined), { modelId: '' });
  assert.deepEqual(viewModel.agentModelUpdateRequest?.('qwen3.7-plus'), { modelId: 'qwen3.7-plus' });
});

test('tool summaries use capability-specific copy for every lifecycle state', () => {
  const viewModel = agentViewModel as typeof agentViewModel & {
    capabilityActionLabel?: (capability: unknown, status?: string) => string;
    userFacingAgentError?: (data: Record<string, unknown>) => {
      title: string;
      message: string;
      recoverable: boolean;
    };
  };
  assert.equal(typeof viewModel.capabilityActionLabel, 'function');
  assert.equal(typeof viewModel.userFacingAgentError, 'function');

  assert.equal(viewModel.capabilityActionLabel?.('loom.media.image.generate', 'queued'), '等待生成图片');
  assert.equal(viewModel.capabilityActionLabel?.('loom.media.image.generate', 'running'), '正在生成图片');
  assert.equal(viewModel.capabilityActionLabel?.('loom.media.image.generate', 'completed'), '图片已生成');
  assert.equal(viewModel.capabilityActionLabel?.('loom.media.image.generate', 'failed'), '图片生成未完成');
  assert.equal(viewModel.capabilityActionLabel?.('loom.media.video.generate', 'completed'), '视频任务已提交');
  assert.equal(viewModel.capabilityActionLabel?.('loom.phone.read', 'failed'), '手机屏幕读取未完成');
  assert.equal(viewModel.capabilityActionLabel?.('loom.cli.phone.status', 'completed'), '手机连接已检查');
  assert.equal(viewModel.capabilityActionLabel?.('loom.matrix.dispatch', 'completed'), '矩阵任务已分发');
  assert.equal(viewModel.capabilityActionLabel?.('loom.cli.acquisition.agent-run', 'completed'), '获客任务已启动');
  assert.equal(viewModel.capabilityActionLabel?.('vendor_unknown_tool', 'completed'), '麓鸣能力调用完成');
});

test('ordinary errors are Chinese and hide protocol identifiers', () => {
  const viewModel = agentViewModel as typeof agentViewModel & {
    userFacingAgentError?: (data: Record<string, unknown>) => {
      title: string;
      message: string;
      recoverable: boolean;
    };
  };
  assert.equal(typeof viewModel.userFacingAgentError, 'function');

  const summary = viewModel.userFacingAgentError?.({
    code: 'capability_not_found',
    message: 'Unknown capability: loom_mcp_loom_loom_status',
    recoverable: false,
  });
  assert.deepEqual(summary, {
    title: '能力暂不可用',
    message: '麓鸣未能匹配到这项能力，任务已保留，可重试或查看运行详情。',
    recoverable: true,
  });
  assert.doesNotMatch(JSON.stringify(summary), /capability_not_found|loom_mcp|Unknown capability/);
});

test('missing phone request scope is localized without leaking the policy code', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'phone_target_scope_required',
      message: "phone_target_scope_required: Phone target must be selected in this run's request scope.",
      recoverable: true,
    },
  });

  assert.equal(summary.title, '请选择目标手机');
  assert.match(summary.message, /自动选择|目标手机/);
  assert.doesNotMatch(JSON.stringify(summary), /phone_target_scope_required|request scope/i);
});

test('missing critical target is localized without leaking the policy code', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'critical_target_required',
      message: 'Critical actions require an explicit target.',
      recoverable: true,
    },
  });

  assert.equal(summary.title, '请明确操作对象');
  assert.match(summary.message, /设备|目标/);
  assert.doesNotMatch(JSON.stringify(summary), /critical_target_required|explicit target|critical actions/i);
});

test('matrix scope failures explain which target must be selected', () => {
  const target = agentViewModel.userFacingAgentError({
    error: {
      code: 'matrix_target_scope_required',
      message: 'Matrix dispatch requires an explicit target selected for this run.',
      recoverable: true,
    },
  });
  const campaign = agentViewModel.userFacingAgentError({
    error: {
      code: 'matrix_campaign_scope_required',
      message: 'Matrix cancel and retry require a campaign bound to this run.',
      recoverable: true,
    },
  });
  const mismatch = agentViewModel.userFacingAgentError({
    error: {
      code: 'matrix_campaign_scope_violation',
      message: "Matrix campaign is outside this run's requested campaign scope.",
      recoverable: true,
    },
  });

  assert.equal(target.title, '请选择矩阵目标');
  assert.match(target.message, /手机|设备组|全部在线/);
  assert.equal(campaign.title, '请选择对应矩阵任务');
  assert.match(campaign.message, /原会话|任务/);
  assert.equal(mismatch.title, '矩阵任务不匹配');
  assert.match(mismatch.message, /当前会话|对应任务/);
  assert.doesNotMatch(
    JSON.stringify([target, campaign, mismatch]),
    /matrix_(target|campaign)_scope|explicit target|campaign bound|requested campaign scope/i,
  );
});

test('missing media and disconnected capabilities have actionable Chinese guidance', () => {
  const unavailable = agentViewModel.userFacingAgentError({
    error: {
      code: 'capability_unavailable',
      message: 'Capability is not connected: loom.media.generate_image',
      recoverable: true,
    },
  });
  const missing = agentViewModel.userFacingAgentError({
    error: {
      code: 'publish_media_missing',
      message: 'No generated media was attached to the publish request.',
      recoverable: true,
    },
  });

  assert.equal(unavailable.title, '能力尚未就绪');
  assert.match(unavailable.message, /安装|配置|运行状态/);
  assert.equal(missing.title, '找不到可用素材');
  assert.match(missing.message, /生成|素材库/);
  assert.doesNotMatch(
    JSON.stringify([unavailable, missing]),
    /capability_unavailable|not connected|publish_media_missing|attached/i,
  );
});

test('indeterminate execution timeouts never expose an immediate retry action', () => {
  for (const code of [
    'phone_task_timeout',
    'media_job_timeout',
    'media_transfer_timeout',
    'publish_job_timeout',
    'capability_timeout_indeterminate',
  ]) {
    const summary = agentViewModel.userFacingAgentError({
      error: {
        code,
        message: `${code}: operation exceeded its execution window`,
        recoverable: false,
      },
    });

    assert.equal(summary.title, '执行状态待确认');
    assert.match(summary.message, /可能仍在执行/);
    assert.match(summary.message, /避免重复执行/);
    assert.equal(summary.recoverable, false);
    assert.doesNotMatch(JSON.stringify(summary), /timeout|execution window/i);
  }
});

test('pre-execution capability timeout remains safely retryable', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'capability_timeout',
      message: 'Capability timed out before starting.',
      recoverable: true,
    },
  });

  assert.deepEqual(summary, {
    title: '能力等待超时',
    message: '这项能力没有在时间限制内开始执行，本轮没有产生新的操作。请稍后重试；若持续出现，请检查系统负载。',
    recoverable: true,
  });
  assert.doesNotMatch(JSON.stringify(summary), /capability_timeout|timed out/i);
});

test('tool loop guards explain why autonomous execution stopped', () => {
  for (const code of ['agent_repeated_tool_call', 'agent_tool_loop_limit']) {
    const summary = agentViewModel.userFacingAgentError({
      error: {
        code,
        message: 'Agent exceeded the maximum number of tool rounds.',
        recoverable: true,
      },
    });

    assert.equal(summary.title, '已停止重复调用');
    assert.match(summary.message, /没有新证据|调整任务/);
    assert.doesNotMatch(JSON.stringify(summary), /agent_|tool rounds|maximum/i);
  }
});

test('restart recovery never encourages replaying an uncertain side effect', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'agent_restart_inflight_unknown',
      message: 'A tool was in flight when the app stopped; it will not be repeated automatically.',
      recoverable: true,
      outcomeIndeterminate: true,
    },
  });

  assert.equal(summary.title, '执行状态待确认');
  assert.match(summary.message, /重启|关闭/);
  assert.match(summary.message, /避免重复执行/);
  assert.equal(summary.recoverable, false);
  assert.doesNotMatch(JSON.stringify(summary), /agent_restart|in flight|repeated automatically/i);
});

test('service worker crash during a tool never encourages replaying the side effect', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'agent_service_inflight_unknown',
      message: 'simulated service worker crash',
      recoverable: true,
      outcomeIndeterminate: true,
      executionMayContinue: true,
    },
  });

  assert.equal(summary.title, '执行状态待确认');
  assert.match(summary.message, /服务异常/);
  assert.match(summary.message, /避免重复执行/);
  assert.equal(summary.recoverable, false);
  assert.doesNotMatch(JSON.stringify(summary), /agent_service|worker crash|simulated/i);
});

test('post-execution persistence failure warns against duplicate side effects', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'agent_tool_result_persistence_failed',
      message: 'internal persistence error',
      recoverable: true,
    },
  });

  assert.deepEqual(summary, {
    title: '执行结果未能保存',
    message: '工具已经执行，但麓鸣未能可靠保存结果。请先检查手机、矩阵任务、素材库或发布记录，确认实际状态后再决定是否重试。',
    recoverable: false,
  });
  assert.doesNotMatch(JSON.stringify(summary), /agent_tool|persistence|internal/i);
});

test('approval state failures are localized without exposing policy protocol text', () => {
  const rejected = agentViewModel.userFacingAgentError({
    error: {
      code: 'approval_rejected',
      message: 'Approval did not authorize the pending tool call.',
      recoverable: true,
    },
  });
  const conflict = agentViewModel.userFacingAgentError({
    error: {
      code: 'approval_conflict',
      message: 'Approval was resolved by another request.',
      recoverable: true,
    },
  });

  assert.equal(rejected.title, '操作未获授权');
  assert.match(rejected.message, /未执行|重新发起/);
  assert.equal(conflict.title, '审批状态已变化');
  assert.match(conflict.message, /刷新|最新状态/);
  assert.doesNotMatch(
    JSON.stringify([rejected, conflict]),
    /approval_|pending tool|resolved by another/i,
  );
});

test('missing or unavailable phone targets ask for a fresh device selection', () => {
  for (const code of ['phone_target_not_found', 'phone_target_unavailable']) {
    const summary = agentViewModel.userFacingAgentError({
      error: {
        code,
        message: `${code}: configured phone is no longer available`,
        recoverable: true,
      },
    });

    assert.equal(summary.title, '目标手机不可用');
    assert.match(summary.message, /刷新|在线手机/);
    assert.doesNotMatch(JSON.stringify(summary), /phone_target|configured phone/i);
  }
});

test('invalid tool output warns against blindly retrying a completed side effect', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'capability_invalid_output',
      message: 'output.receiptId is required',
      recoverable: false,
      outcomeIndeterminate: true,
    },
  });

  assert.deepEqual(summary, {
    title: '执行结果待确认',
    message: '操作已经发起，但返回结果格式异常，麓鸣无法确认最终状态。请先查看目标设备或任务记录，确认后再决定是否重试，避免重复执行。',
    recoverable: false,
  });
  assert.doesNotMatch(JSON.stringify(summary), /capability_invalid_output|output\.receiptId|required/i);
});

test('oversized runtime output explains that no new tool was executed', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'agent_runtime_output_too_large',
      message: 'Agent runtime output exceeded 2 MB.',
      recoverable: false,
    },
  });

  assert.equal(summary.title, '智能体输出过多');
  assert.match(summary.message, /尚未继续执行新的工具/);
  assert.equal(summary.recoverable, true);
  assert.doesNotMatch(JSON.stringify(summary), /agent_runtime|exceeded|2 MB/i);
});

test('invalid model protocol is localized as a safe pre-tool failure', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'AGENT_MODEL_PROTOCOL_INVALID',
      message: 'Managed gateway tool arguments were malformed JSON.',
      recoverable: false,
    },
  });

  assert.equal(summary.title, '模型响应格式异常');
  assert.match(summary.message, /未继续执行新的工具/);
  assert.equal(summary.recoverable, true);
  assert.doesNotMatch(JSON.stringify(summary), /protocol|malformed|gateway/i);
});

test('runtime event persistence failure reports child termination and diagnostics', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'agent_runtime_event_failed',
      message: 'Agent runtime progress could not be persisted.',
      recoverable: true,
    },
  });

  assert.equal(summary.title, '运行记录写入失败');
  assert.match(summary.message, /停止智能体子进程/);
  assert.match(summary.message, /环境诊断/);
  assert.doesNotMatch(JSON.stringify(summary), /agent_runtime|persisted/i);
});

test('runtime timeout is localized without exposing the adapter protocol', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'agent_runtime_timeout',
      message: 'Agent runtime exceeded its time limit.',
      recoverable: true,
    },
  });

  assert.equal(summary.title, '模型响应超时');
  assert.match(summary.message, /停止等待/);
  assert.doesNotMatch(JSON.stringify(summary), /agent_runtime|time limit/i);
});

test('phone publish login failures show the actionable manual handoff', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'phone_publish_semantic_failure',
      message: '任务无法完成：抖音当前未登录，发布功能需要登录。',
      recoverable: true,
    },
  });

  assert.deepEqual(summary, {
    title: '抖音需要登录',
    message: '请先在手机上手动登录抖音，完成后重试。麓鸣不会代填账号、密码或验证码。',
    recoverable: true,
  });
});

test('matrix failures expose the sanitized backend reason instead of a generic failure', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'matrix_dispatch_failed',
      message: 'phone-a：手机端离线，请检查 APKClaw 网络连接',
      recoverable: true,
    },
  });

  assert.deepEqual(summary, {
    title: '矩阵任务未完成',
    message: 'phone-a：手机端离线，请检查 APKClaw 网络连接',
    recoverable: true,
  });
});

test('ordinary tool failures preserve the actionable backend reason', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'phone_task_failed',
      message: '手机端无障碍服务未启动，请在 APKClaw 设置中开启无障碍权限。',
      recoverable: true,
    },
  });

  assert.deepEqual(summary, {
    title: '任务暂未完成',
    message: '手机端无障碍服务未启动，请在 APKClaw 设置中开启无障碍权限。',
    recoverable: true,
  });
});

test('invalid publish input is translated into actionable Chinese guidance', () => {
  const summary = agentViewModel.userFacingAgentError({
    error: {
      code: 'capability_invalid_input',
      message: 'input.title is required',
      recoverable: true,
    },
  });

  assert.deepEqual(summary, {
    title: '发布信息不完整',
    message: '缺少发布标题。麓鸣会根据正文自动补全；若仍失败，请在任务中明确写出标题。',
    recoverable: true,
  });
});

test('managed model credential failures direct the user to the model account', () => {
  const relogin = agentViewModel.userFacingAgentError({
    error: {
      code: 'AGENT_ACCOUNT_RELOGIN_REQUIRED',
      message: 'Managed model account must be signed in again.',
      recoverable: true,
    },
  });
  const refresh = agentViewModel.userFacingAgentError({
    error: {
      code: 'AGENT_MODEL_CREDENTIAL_REFRESH_FAILED',
      message: 'Managed model credentials could not be refreshed.',
      recoverable: true,
    },
  });

  assert.deepEqual(relogin, {
    title: '模型账号需要重新登录',
    message: '当前模型凭据无法升级，请打开“模型账号”重新登录后再重试。',
    recoverable: true,
  });
  assert.deepEqual(refresh, {
    title: '模型账号暂不可用',
    message: '模型凭据刷新失败，请检查网络；若持续出现，请重新登录模型账号。',
    recoverable: true,
  });
});

test('duplicate protocol errors for one run collapse into one recoverable message', () => {
  const events = [
    event(1, 'tool.failed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'message_tool',
      toolCallId: 'tool_1',
      capability: 'loom_mcp_loom_loom_status',
      code: 'capability_not_found',
      message: 'Unknown capability: loom_mcp_loom_loom_status',
      recoverable: false,
    }),
    event(2, 'run.failed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      code: 'capability_not_found',
      message: 'Unknown capability: loom_mcp_loom_loom_status',
      recoverable: false,
      error: {
        code: 'capability_not_found',
        message: 'Unknown capability: loom_mcp_loom_loom_status',
        recoverable: false,
      },
    }),
  ];
  const state = events.reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );
  const toolBlocks = state.messages.flatMap((item) => item.blocks.filter((block) => block.type === 'tool'));
  const errors = state.messages.flatMap((item) => item.blocks.filter((block) => block.type === 'error'));

  assert.equal(toolBlocks.length, 1);
  assert.equal(toolBlocks[0].data.status, 'failed');
  assert.equal(toolBlocks[0].data.code, 'capability_not_found');
  assert.equal(errors.length, 0);
});

test('a run without a failed tool still receives one actionable run error', () => {
  const state = mergeAgentEvent(createAgentEventState(), event(1, 'run.failed', {
    sessionId: SESSION_ID,
    runId: 'run_1',
    error: { code: 'runtime_unavailable', message: 'runtime unavailable', recoverable: true },
  }), SESSION_ID);

  const errors = state.messages.flatMap((item) => item.blocks.filter((block) => block.type === 'error'));
  assert.equal(errors.length, 1);
  assert.equal(errors[0].data.runId, 'run_1');
});

test('tool lifecycle follows run and call identity when producer message IDs change', () => {
  let state = createAgentEventState();
  state = mergeAgentEvent(state, event(1, 'tool.queued', {
    sessionId: SESSION_ID,
    runId: 'run_1',
    messageId: 'producer_message_queued',
    toolCallId: 'tool_1',
    capability: 'loom.phone.read',
  }), SESSION_ID);
  assert.equal(state.messages[0].blocks[0].data.status, 'queued');

  state = mergeAgentEvent(state, event(2, 'tool.started', {
    sessionId: SESSION_ID,
    runId: 'run_1',
    messageId: 'producer_message_started',
    toolCallId: 'tool_1',
    capability: 'loom.phone.read',
  }), SESSION_ID);
  assert.equal(state.messages[0].blocks[0].data.status, 'running');

  state = mergeAgentEvent(state, event(3, 'tool.completed', {
    sessionId: SESSION_ID,
    runId: 'run_1',
    messageId: 'producer_message_completed',
    toolCallId: 'tool_1',
    capability: 'loom.phone.read',
  }), SESSION_ID);
  const toolMessages = state.messages.filter((item) => item.blocks.some((block) => block.type === 'tool'));

  assert.equal(toolMessages.length, 1);
  assert.equal(toolMessages[0].blocks[0].data.runId, 'run_1');
  assert.equal(toolMessages[0].blocks[0].data.toolCallId, 'tool_1');
  assert.equal(toolMessages[0].blocks[0].data.status, 'completed');
});

test('consecutive tool calls in one run share a single ordered execution message', () => {
  const state = [
    event(1, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'tool_1',
      capability: 'loom.media.image.generate',
    }),
    event(2, 'tool.completed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'tool_1',
      capability: 'loom.media.image.generate',
    }),
    event(3, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'tool_2',
      capability: 'loom.phone.control',
    }),
  ].reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );

  const toolMessages = state.messages.filter((item) => item.role === 'tool');
  assert.equal(toolMessages.length, 1);
  assert.equal(toolMessages[0].messageId, 'tool-run:run_1');
  assert.deepEqual(toolMessages[0].blocks.map((block) => block.data.toolCallId), ['tool_1', 'tool_2']);
  assert.deepEqual(toolMessages[0].blocks.map((block) => block.data.status), ['completed', 'running']);
});

test('starting a tool closes the matching streamed preamble instead of leaving a reply spinner behind', () => {
  const state = [
    event(1, 'message.delta', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'message_preamble',
      role: 'assistant',
      delta: '我先检查手机状态。',
    }),
    event(2, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'tool_1',
      capability: 'loom.cli.phone.status',
    }),
  ].reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );

  const preamble = state.messages.find((item) => item.messageId === 'message_preamble');
  assert.equal(preamble?.status, 'completed');
  assert.equal(preamble?.blocks[0].data.runId, 'run_1');
});

test('a rejected hidden repair attempt does not become a second failed tool row', () => {
  const state = [
    event(1, 'tool.queued', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'repair_1',
      capability: 'loom.phone.publish',
    }),
    event(2, 'tool.input_rejected', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'repair_1',
      capability: 'loom.phone.publish',
      status: 'repairing',
    }),
    event(3, 'tool.queued', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'repair_2',
      capability: 'loom.phone.publish',
    }),
    event(4, 'tool.failed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'repair_2',
      capability: 'loom.phone.publish',
      error: { code: 'capability_invalid_input', message: 'input.title is required' },
    }),
    event(5, 'run.failed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      error: { code: 'capability_invalid_input', message: 'input.title is required' },
    }),
  ].reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );

  const tools = state.messages.flatMap((item) => item.blocks.filter((block) => block.type === 'tool'));
  assert.deepEqual(tools.map((block) => block.data.toolCallId), ['repair_2']);
});

test('a failed run removes preparatory narration that never became a result', () => {
  const state = [
    event(1, 'message.delta', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'message_preamble',
      role: 'assistant',
      delta: '图片已经生成，现在将发布到手机。',
    }),
    event(2, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'publish_1',
      capability: 'loom.phone.publish',
    }),
    event(3, 'tool.failed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'publish_1',
      capability: 'loom.phone.publish',
      error: { code: 'phone_task_failed', message: 'publish failed' },
    }),
    event(4, 'run.failed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      error: { code: 'phone_task_failed', message: 'publish failed' },
    }),
  ].reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );

  assert.equal(state.messages.some((item) => item.messageId === 'message_preamble'), false);
});

test('a failed run keeps a persisted completed assistant result', () => {
  const persisted = {
    schema: 'loom.agent.message.v1',
    messageId: 'message_final',
    sessionId: SESSION_ID,
    role: 'assistant' as const,
    status: 'completed' as const,
    blocks: [{ type: 'text' as const, data: { text: '图片已生成并保存。' } }],
    createdAt: '2026-07-21T00:00:00.000Z',
    completedAt: '2026-07-21T00:00:01.000Z',
  };
  const state = [
    event(1, 'message.delta', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'message_preamble',
      role: 'assistant',
      delta: '正在执行后续操作。',
    }),
    event(2, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'publish_1',
      capability: 'loom.phone.publish',
    }),
    event(3, 'message.completed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      message: persisted,
    }),
    event(4, 'tool.failed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'publish_1',
      capability: 'loom.phone.publish',
      error: { code: 'phone_task_failed', message: 'publish failed' },
    }),
    event(5, 'run.failed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      error: { code: 'phone_task_failed', message: 'publish failed' },
    }),
  ].reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );

  assert.equal(state.messages.some((item) => item.messageId === 'message_preamble'), false);
  assert.equal(state.messages.some((item) => item.messageId === 'message_final'), true);
});

test('tool execution group is compact after success and stays expanded with inline failure guidance', () => {
  const running = renderToStaticMarkup(React.createElement(ToolExecutionGroup, {
    blocks: [{
      type: 'tool',
      data: { runId: 'run_0', toolCallId: 'tool_0', capability: 'loom.media.image.generate', status: 'running' },
    }],
    run: { schema: 'loom.agent.run.v1', runId: 'run_0', sessionId: SESSION_ID, status: 'running', campaignIds: [] },
  }));
  assert.match(running, />正在执行</);
  assert.doesNotMatch(running, /0\/1/);

  const successful = renderToStaticMarkup(React.createElement(ToolExecutionGroup, {
    blocks: [
      { type: 'tool', data: { runId: 'run_1', toolCallId: 'tool_1', capability: 'loom.media.image.generate', status: 'completed' } },
      { type: 'tool', data: { runId: 'run_1', toolCallId: 'tool_2', capability: 'loom.phone.control', status: 'completed' } },
    ],
    run: { schema: 'loom.agent.run.v1', runId: 'run_1', sessionId: SESSION_ID, status: 'completed', campaignIds: [] },
  }));
  assert.match(successful, /data-agent-tool-group/);
  assert.match(successful, /已完成 2 步/);
  assert.match(successful, /data-expanded="false"/);

  const failed = renderToStaticMarkup(React.createElement(ToolExecutionGroup, {
    blocks: [{
      type: 'tool',
      data: {
        runId: 'run_2',
        toolCallId: 'tool_3',
        capability: 'loom.phone.control',
        status: 'failed',
        code: 'device_offline',
        message: 'Device offline',
        recoverable: true,
      },
    }],
    run: { schema: 'loom.agent.run.v1', runId: 'run_2', sessionId: SESSION_ID, status: 'failed', campaignIds: [] },
  }));
  assert.match(failed, /data-expanded="true"/);
  assert.match(failed, /设备暂时离线/);
  assert.match(failed, /请检查手机连接后重试/);
  assert.equal((failed.match(/data-agent-tool-action/g) || []).length, 1);
});

test('repeated calls to the same capability collapse into one visible execution row', () => {
  const markup = renderToStaticMarkup(React.createElement(ToolExecutionGroup, {
    blocks: [
      { type: 'tool', data: { runId: 'run_1', toolCallId: 'tool_1', capability: 'loom.cli.phone.status', status: 'completed' } },
      { type: 'tool', data: { runId: 'run_1', toolCallId: 'tool_2', capability: 'loom.cli.phone.status', status: 'completed' } },
    ],
    run: { schema: 'loom.agent.run.v1', runId: 'run_1', sessionId: SESSION_ID, status: 'completed', campaignIds: [] },
  }));

  assert.equal((markup.match(/data-agent-tool-action/g) || []).length, 1);
  assert.match(markup, /2 次/);
});

test('terminal tool status never regresses to a later nonterminal update', () => {
  const state = [
    event(1, 'tool.completed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'tool_1',
    }),
    event(2, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      toolCallId: 'tool_1',
    }),
  ].reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );

  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].blocks[0].data.status, 'completed');
  assert.equal(state.messages[0].status, 'completed');
});

test('the same tool call ID remains distinct across runs', () => {
  const state = [
    event(1, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'producer_message_shared',
      toolCallId: 'shared_call',
    }),
    event(2, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_2',
      messageId: 'producer_message_shared',
      toolCallId: 'shared_call',
    }),
  ].reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );
  const tools = state.messages.flatMap((item) => item.blocks.filter((block) => block.type === 'tool'));

  assert.equal(tools.length, 2);
  assert.deepEqual(tools.map((block) => block.data.runId), ['run_1', 'run_2']);
});

test('terminal run events reconcile only their nonterminal tool rows', () => {
  for (const [terminalEvent, expectedStatus] of [
    ['run.completed', 'completed'],
    ['run.failed', 'failed'],
    ['run.cancelled', 'failed'],
  ] as const) {
    const state = [
      event(1, 'tool.started', { sessionId: SESSION_ID, runId: 'run_1', toolCallId: 'shared_call' }),
      event(2, 'tool.started', { sessionId: SESSION_ID, runId: 'run_2', toolCallId: 'shared_call' }),
      event(3, terminalEvent, { sessionId: SESSION_ID, runId: 'run_1' }),
    ].reduce(
      (current, item) => mergeAgentEvent(current, item, SESSION_ID),
      createAgentEventState(),
    );
    const tools = state.messages.flatMap((item) => item.blocks.filter((block) => block.type === 'tool'));

    assert.equal(tools.find((block) => block.data.runId === 'run_1')?.data.status, expectedStatus);
    assert.equal(tools.find((block) => block.data.runId === 'run_2')?.data.status, 'running');
  }
});

test('approval cards remain independent from their related tool lifecycle', () => {
  const state = [
    event(1, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'producer_message_shared',
      toolCallId: 'tool_1',
    }),
    event(2, 'approval.required', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'producer_message_shared',
      approval: { approvalId: 'approval_1', toolCallId: 'tool_1', status: 'pending' },
    }),
    event(3, 'tool.completed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'producer_message_completed',
      toolCallId: 'tool_1',
    }),
    event(4, 'approval.resolved', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'producer_message_shared',
      approval: { approvalId: 'approval_1', toolCallId: 'tool_1', status: 'approved' },
    }),
  ].reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );
  const tools = state.messages.flatMap((item) => item.blocks.filter((block) => block.type === 'tool'));
  const approvals = state.messages.flatMap((item) => item.blocks.filter((block) => block.type === 'approval'));

  assert.equal(tools.length, 1);
  assert.equal(tools[0].data.status, 'completed');
  assert.equal(approvals.length, 1);
  assert.equal(approvals[0].data.status, 'approved');
});

test('attachment blocks render as attachments rather than running tool calls', () => {
  const markup = renderToStaticMarkup(React.createElement(MessageBlockView, {
    block: {
      type: 'tool',
      data: {
        name: 'attachments',
        attachments: [
          { name: 'poster.png', path: 'D:/LOOM/data/generated-images/poster.png', mime: 'image/png', kind: 'image' },
          { name: 'clip.mp4', path: 'D:/LOOM/data/videos/clip.mp4', mime: 'video/mp4', kind: 'video' },
        ],
        phoneTransfer: { status: 'succeeded', message: '已传送到手机相册' },
      },
    },
    runs: {},
    busyKey: null,
    onRunAction: async () => {},
    onOpenRunDetails: () => {},
    onResolveApproval: async () => {},
    onOpenWorkbench: () => {},
  }));

  assert.match(markup, /data-agent-attachments/);
  assert.match(markup, /poster\.png/);
  assert.match(markup, /clip\.mp4/);
  assert.match(markup, /<img/);
  assert.match(markup, /<video/);
  assert.match(markup, /已传送到手机相册/);
  assert.doesNotMatch(markup, /data-agent-tool-action|进行中/);
});

test('historical replay moves the final assistant reply after its tool lifecycle', () => {
  const userMessage = { ...message('message_user', '开始任务', 'completed'), role: 'user' as const };
  const finalMessage = message('message_final', '任务完成', 'completed');
  const state = [
    event(1, 'tool.started', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'producer_tool_started',
      toolCallId: 'tool_1',
    }),
    event(2, 'tool.completed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      messageId: 'producer_tool_completed',
      toolCallId: 'tool_1',
    }),
    event(3, 'message.completed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      message: finalMessage,
    }),
  ].reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState([userMessage, finalMessage]),
  );

  assert.deepEqual(state.messages.map((item) => item.messageId), [
    'message_user',
    'tool-run:run_1',
    'message_final',
  ]);
});

test('current run selection does not revive an older nonterminal run after replay completes', () => {
  const selectCurrentAgentRun = (agentViewModel as typeof agentViewModel & {
    selectCurrentAgentRun?: (
      sessionId: string | null,
      activeRunId: string | undefined,
      runs: Record<string, {
        schema: 'loom.agent.run.v1';
        runId: string;
        sessionId: string;
        status: 'running' | 'completed';
        campaignIds: string[];
        startedAt?: string;
        completedAt?: string;
      }>,
    ) => { runId: string } | null;
  }).selectCurrentAgentRun;
  assert.equal(typeof selectCurrentAgentRun, 'function');

  const selected = selectCurrentAgentRun?.(SESSION_ID, undefined, {
    run_old: {
      schema: 'loom.agent.run.v1',
      runId: 'run_old',
      sessionId: SESSION_ID,
      status: 'running',
      campaignIds: [],
      startedAt: '2026-07-16T09:00:00+08:00',
    },
    run_latest: {
      schema: 'loom.agent.run.v1',
      runId: 'run_latest',
      sessionId: SESSION_ID,
      status: 'completed',
      campaignIds: [],
      startedAt: '2026-07-16T10:00:00+08:00',
      completedAt: '2026-07-16T10:01:00+08:00',
    },
  });

  assert.equal(selected?.runId, 'run_latest');
});

test('stream deltas dedupe by event ID and sequence', () => {
  let state = createAgentEventState();
  state = mergeAgentEvent(state, event(1, 'message.delta', {
    sessionId: SESSION_ID,
    messageId: 'message_1',
    delta: 'Hello',
  }), SESSION_ID);
  state = mergeAgentEvent(state, event(1, 'message.delta', {
    sessionId: SESSION_ID,
    messageId: 'message_1',
    delta: 'Hello',
  }), SESSION_ID);
  state = mergeAgentEvent(state, event(2, 'message.delta', {
    sessionId: SESSION_ID,
    messageId: 'message_1',
    delta: ' world',
  }, 'event_1'), SESSION_ID);

  assert.equal(state.messages[0].blocks[0].data.text, 'Hello');
  assert.equal(state.lastSeq, 1);
  assert.deepEqual(state.seenEventIds, ['event_1']);
});

test('late replay events recover chronological message history', () => {
  const initial = createAgentEventState([
    message('message_1', 'First', 'completed'),
    message('message_2', 'Second', 'completed'),
  ]);

  const state = mergeAgentEvent(initial, event(3, 'message.completed', {
    sessionId: SESSION_ID,
    message: {
      ...message('message_3', 'Late arrival', 'completed'),
      createdAt: '2026-07-15T09:00:00+08:00',
    },
  }), SESSION_ID);

  assert.deepEqual(state.messages.map((item) => item.messageId), [
    'message_3',
    'message_1',
    'message_2',
  ]);
});

test('unified events project plans tools approvals matrix evidence errors and run state', () => {
  const events = [
    event(1, 'plan.updated', { sessionId: SESSION_ID, messageId: 'message_plan', steps: ['Inspect', 'Act'] }),
    event(2, 'tool.started', { sessionId: SESSION_ID, messageId: 'message_tool', toolCallId: 'tool_1', capability: 'loom.matrix.dispatch' }),
    event(3, 'approval.required', { sessionId: SESSION_ID, messageId: 'message_approval', approval: { approvalId: 'approval_1', status: 'pending' } }),
    event(4, 'matrix.attached', { sessionId: SESSION_ID, messageId: 'message_matrix', campaignId: 'campaign_1', deviceId: 'P01' }),
    event(5, 'tool.failed', { sessionId: SESSION_ID, messageId: 'message_tool', toolCallId: 'tool_1', code: 'device_offline', message: 'Device offline', recoverable: true }),
    event(6, 'run.paused', { sessionId: SESSION_ID, runId: 'run_1', campaignIds: ['campaign_1'] }),
  ];

  const state = events.reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );

  assert.deepEqual(state.messages.flatMap((item) => item.blocks.map((block) => block.type)), [
    'plan',
    'tool',
    'approval',
    'matrix',
  ]);
  assert.equal(state.runs.run_1.status, 'paused');
  assert.deepEqual(state.runs.run_1.campaignIds, ['campaign_1']);
});

test('matrix progress updates the original attachment instead of appending duplicate cards', () => {
  const events = [
    event(1, 'matrix.attached', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      campaignId: 'campaign_1',
      status: 'running',
      total: 2,
      completed: 0,
      failed: 0,
    }),
    event(2, 'matrix.progress', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      campaignId: 'campaign_1',
      status: 'running',
      total: 2,
      completed: 1,
      failed: 0,
    }),
    event(3, 'matrix.completed', {
      sessionId: SESSION_ID,
      runId: 'run_1',
      campaignId: 'campaign_1',
      status: 'completed',
      total: 2,
      completed: 2,
      failed: 0,
    }),
  ];
  const state = events.reduce(
    (current, item) => mergeAgentEvent(current, item, SESSION_ID),
    createAgentEventState(),
  );

  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].messageId, 'matrix:campaign_1');
  assert.equal(state.messages[0].blocks[0].data.status, 'completed');
  assert.equal(state.messages[0].blocks[0].data.completed, 2);
});

test('debug display values recursively redact secret-bearing fields', () => {
  const safe = sanitizeDisplayValue({
    runtimeProfileId: 'default',
    tokenEstimate: 2048,
    nested: {
      apiKey: 'sk-secret',
      token: 'credential-token',
      authorization: 'Bearer secret',
      detail: 'safe summary',
    },
  }) as Record<string, unknown>;

  assert.deepEqual(safe, {
    runtimeProfileId: 'default',
    tokenEstimate: 2048,
    nested: {
      apiKey: '[REDACTED]',
      token: '[REDACTED]',
      authorization: '[REDACTED]',
      detail: 'safe summary',
    },
  });
});
