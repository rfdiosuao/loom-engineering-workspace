import 'tsx/esm';

import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { AgentApproval, AgentMessageBlock } from '../types/agent.ts';
import type {
  LegacyMatrixDispatchRequest,
  MatrixDispatchRequest,
  MatrixDeviceAssignment,
  MatrixDeviceLease,
  MatrixDeviceTask,
  MatrixScreen,
} from '../types/matrix.ts';
import type {
  LogClearResponse,
  LogRequest,
  LogResponse,
  MatrixEmergencyStopRequest,
  MatrixEmergencyStopResponse,
} from './api.ts';
import { parseApiErrorPayload, resolveUpdateDisposition } from './api.ts';
import {
  clearCachedComponentSnapshot,
  loadCachedComponentSnapshot,
  saveCachedComponentSnapshot,
} from './componentStatusCache.ts';

test('component status cache survives page remounts until the user explicitly refreshes it', () => {
  const values = new Map<string, string>();
  const originalWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    writable: true,
    value: {
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
      },
    },
  });

  try {
    const snapshot = {
      manifest: null,
      components: [{
        id: 'codex-desktop',
        name: 'Codex',
        version: '1.0.0',
        status: 'ready',
        platform: 'windows',
        arch: 'x64',
        type: 'installer',
        size: 1,
        installPath: 'C:/Codex',
        category: 'agent',
        urls: [],
      }],
    };

    assert.equal(loadCachedComponentSnapshot(), null);
    assert.equal(saveCachedComponentSnapshot(snapshot), snapshot);
    assert.deepEqual(loadCachedComponentSnapshot(), snapshot);
    clearCachedComponentSnapshot();
    assert.equal(loadCachedComponentSnapshot(), null);
  } finally {
    if (originalWindow === undefined) Reflect.deleteProperty(globalThis, 'window');
    else Object.defineProperty(globalThis, 'window', { configurable: true, writable: true, value: originalWindow });
  }
});

test('structured Bridge errors retain update recovery metadata', () => {
  const parsed = parseApiErrorPayload(
    '[500] {"error":"网络连接中断","errorCode":"network_interrupted","retryable":true,"remediation":["重试"]}',
  );

  assert.deepEqual(parsed, {
    error: '网络连接中断',
    errorCode: 'network_interrupted',
    retryable: true,
    remediation: ['重试'],
  });
});

test('update result disposition never treats an empty installer path as a completed install', () => {
  assert.equal(resolveUpdateDisposition({ success: true, outcome: 'ready', installer_path: 'C:/cache/setup.exe' }), 'prepare_install');
  assert.equal(resolveUpdateDisposition({ success: true, outcome: 'already_current', installer_path: '' }), 'already_current');
  assert.throws(
    () => resolveUpdateDisposition({ success: true, outcome: 'ready', installer_path: '' }),
    /installer path/i,
  );
});

test('agent message and approval values match the Hub schemas', () => {
  const errorBlock: AgentMessageBlock = {
    type: 'error',
    data: { code: 'runtime_failed', message: 'Runtime failed.' },
  };
  const approval: AgentApproval = {
    schema: 'loom.agent.approval.v1',
    approvalId: 'approval_1',
    sessionId: 'session_1',
    runId: 'run_1',
    toolCallId: 'tool_call_1',
    capability: 'loom.phone.publish',
    inputHash: 'sha256:' + '0'.repeat(64),
    actionSummary: 'Publish one post',
    targets: { deviceIds: ['P01'] },
    inputSummary: { platform: 'douyin' },
    risk: 'outbound',
    riskReason: 'External write',
    status: 'consumed',
    requestedAt: '2026-07-15T14:30:00+08:00',
    expiresAt: '2026-07-15T14:35:00+08:00',
    decision: 'approved',
    decidedBy: 'operator_1',
    decidedAt: '2026-07-15T14:31:00+08:00',
    consumedAt: '2026-07-15T14:31:01+08:00',
  };

  assert.equal(errorBlock.type, 'error');
  assert.equal(approval.status, 'consumed');
});

test('unsupported Agent message evidence blocks are rejected by the type contract', () => {
  const unsupportedEvidence: AgentMessageBlock = {
    // @ts-expect-error evidence is not an AgentMessage block schema type.
    type: 'evidence',
    evidenceId: 'evidence_1',
    reference: 'local://evidence/1',
  };

  assert.equal(unsupportedEvidence.type, 'evidence');
});

test('Matrix assignments require input timeout and retry budget', () => {
  const assignment: MatrixDeviceAssignment = {
    assignmentId: 'assignment_1',
    deviceId: 'P01',
    prompt: 'Read the current screen.',
    input: {},
    timeoutSec: 30,
    retryBudget: 0,
  };

  // @ts-expect-error Hub schema requires input on every assignment.
  const missingInput: MatrixDeviceAssignment = {
    assignmentId: 'assignment_2',
    deviceId: 'P02',
    prompt: 'Read the current screen.',
    timeoutSec: 30,
    retryBudget: 0,
  };

  assert.equal(assignment.input.campaignId, undefined);
  assert.equal(missingInput.deviceId, 'P02');
});

test('Matrix emergency stop requires one explicit scope and returns authoritative counts', () => {
  const requests: MatrixEmergencyStopRequest[] = [
    { all: true },
    { campaignId: 'campaign_1' },
    { deviceIds: ['P01'] },
    { deviceTaskIds: ['task_1'] },
  ];
  // @ts-expect-error Empty emergency-stop requests are unsafe.
  const empty: MatrixEmergencyStopRequest = {};
  // @ts-expect-error Emergency-stop scopes are mutually exclusive.
  const mixed: MatrixEmergencyStopRequest = { all: true, deviceIds: ['P01'] };
  const response: MatrixEmergencyStopResponse = {
    schema: 'loom.matrix.emergency_stop.v1',
    cancelled: true,
    scope: 'devices',
    matchedCampaignIds: ['campaign_1'],
    campaignIds: ['campaign_1'],
    cancelledJobIds: ['job_1'],
    cancelledCount: 1,
    affectedTaskCount: 1,
    affectedDeviceCount: 1,
    affected: [{
      campaignId: 'campaign_1',
      missionId: 'mission_1',
      assignmentId: 'assignment_1',
      deviceTaskId: 'task_1',
      deviceId: 'P01',
      previousStatus: 'running',
      status: 'cancelled',
    }],
  };

  assert.equal(requests.length, 4);
  assert.equal(response.affectedTaskCount, 1);
  assert.equal(Object.keys(empty).length, 0);
  assert.equal(mixed.all, true);
});

test('Matrix lease screen and device task types reject schema drift', () => {
  const lease: MatrixDeviceLease = {
    schema: 'loom.matrix.device_lease.v1',
    leaseId: 'lease_1',
    deviceId: 'P01',
    holderType: 'human',
    holderId: 'operator_1',
    mode: 'control',
    expiresAt: '2026-07-15T14:30:30+08:00',
  };
  const screen: MatrixScreen = {
    schema: 'loom.matrix.screen.v1',
    deviceId: 'P01',
    capturedAt: '2026-07-15T14:30:00+08:00',
    screenHash: 'sha256:fixture',
    mime: 'image/webp',
    width: 1080,
    height: 2400,
    notModified: true,
  };
  const task: MatrixDeviceTask = {
    assignmentId: 'assignment_1',
    deviceTaskId: 'device_task_1',
    deviceId: 'P01',
    jobId: null,
    status: 'queued',
    attempt: 0,
    // @ts-expect-error progress is event data, not a matrix-campaign deviceTask field.
    progress: 0,
  };

  assert.equal(lease.holderType, 'human');
  assert.equal(screen.notModified, true);
  assert.equal(task.deviceTaskId, 'device_task_1');
});

test('legacy Matrix dispatch accepts top-level deviceIds and non-prompt forms', () => {
  const requests: LegacyMatrixDispatchRequest[] = [
    { deviceIds: ['P01'], action: 'home' },
    { target: { deviceIds: ['P02'] }, template: 'read-screen' },
    { target: { groups: ['lab'] }, templateId: 'screen_read_v1' },
    { target: { allOnline: true }, prompt: 'Read every selected screen.' },
  ];

  assert.equal(requests.length, 4);
});

test('legacy Matrix dispatch requires exactly one target selector at compile time', () => {
  // @ts-expect-error A legacy dispatch must select a target.
  const missingTarget: LegacyMatrixDispatchRequest = { prompt: 'Read screen.' };
  // @ts-expect-error Device and group selectors are mutually exclusive.
  const mixedNestedTarget: LegacyMatrixDispatchRequest = { prompt: 'Read screen.', target: { deviceIds: ['P01'], groups: ['lab'] } };
  // @ts-expect-error Top-level compatibility and nested target forms cannot be mixed.
  const mixedTargetForms: LegacyMatrixDispatchRequest = {
    prompt: 'Read screen.',
    deviceIds: ['P01'],
    target: { allOnline: true },
  };

  assert.equal(missingTarget.prompt, 'Read screen.');
  assert.equal(mixedNestedTarget.prompt, 'Read screen.');
  assert.equal(mixedTargetForms.prompt, 'Read screen.');
});

test('canonical Matrix dispatch and log tail metadata retain required fields', () => {
  const dispatch: MatrixDispatchRequest = {
    schema: 'loom.matrix.dispatch.v2',
    campaignId: 'campaign_1',
    concurrency: 1,
    deviceAssignments: [{
      assignmentId: 'assignment_1',
      deviceId: 'P02',
      prompt: 'Read only P02.',
      input: { candidateId: 'candidate_1' },
      timeoutSec: 180,
      retryBudget: 1,
    }],
  };
  const request: LogRequest = { offset: 4, generation: 'generation-1' };
  const log: LogResponse = {
    log: 'tail',
    offset: 4,
    generation: 'generation-1',
    total: 4,
    reset: false,
    totalBytes: 700_000,
    windowStartBytes: 699_996,
    windowBytes: 4,
    omittedBytes: 699_996,
    truncated: true,
  };
  const cleared: LogClearResponse = { status: 'cleared', generation: 'generation-2' };

  assert.equal(dispatch.deviceAssignments[0].deviceId, 'P02');
  assert.equal(request.generation, log.generation);
  assert.notEqual(cleared.generation, log.generation);
  assert.equal(log.windowStartBytes, 699_996);
  assert.equal(log.omittedBytes, 699_996);
});
