import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import type { MatrixCampaign, MatrixDeviceSummary, MatrixDeviceTask, MatrixStatusSnapshot } from '../../types/matrix';
import {
  buildDeviceGroups,
  deriveDeviceStatus,
  latestTasksByDevice,
  mergeMatrixSnapshot,
  normalizeMatrixCampaigns,
  resolveMatrixNavigation,
  stableDeviceOrder,
} from './matrixViewModel';
import * as matrixViewModel from './matrixViewModel';
import {
  applyScreenResponse,
  MAX_SCREEN_REQUESTS,
  nextScreenDueAt,
  pollIntervalForDevice,
  resolveScreenRequestOutcome,
  screenFailureBackoffMs,
  selectDueScreenRequests,
  type ScreenScheduleCandidate,
} from './screenScheduler';

const device = (deviceId: string, overrides: Partial<MatrixDeviceSummary> = {}): MatrixDeviceSummary => ({
  deviceId,
  online: true,
  ...overrides,
});

const task = (deviceId: string, status: MatrixDeviceTask['status']): MatrixDeviceTask => ({
  assignmentId: `assignment-${deviceId}`,
  deviceTaskId: `task-${deviceId}`,
  deviceId,
  jobId: null,
  status,
  attempt: 1,
});

const campaign = (campaignId: string, deviceIds: string[]): MatrixCampaign => ({
  schema: 'loom.matrix.campaign.v2',
  campaignId,
  status: 'running',
  concurrency: 2,
  counts: { total: deviceIds.length, queued: 0, running: deviceIds.length, completed: 0, failed: 0, needsHuman: 0 },
  deviceTasks: deviceIds.map((deviceId) => task(deviceId, 'running')),
});

test('stableDeviceOrder preserves known positions and appends new devices deterministically', () => {
  const ordered = stableDeviceOrder(
    [device('phone-c'), device('phone-a'), device('phone-b')],
    ['phone-b', 'phone-a'],
  );

  assert.deepEqual(ordered.map((item) => item.deviceId), ['phone-b', 'phone-a', 'phone-c']);
});

test('buildDeviceGroups includes every declared device group without duplicating devices', () => {
  const groups = buildDeviceGroups([
    device('phone-a', { group: 'group-b', groups: ['group-b', 'group-c'] }),
    device('phone-b', { group: 'group-a' }),
  ]);

  assert.deepEqual(groups.map((group) => [group.id, group.deviceIds]), [
    ['all', ['phone-a', 'phone-b']],
    ['group-a', ['phone-b']],
    ['group-b', ['phone-a']],
    ['group-c', ['phone-a']],
  ]);
});

test('resolveMatrixNavigation selects the linked campaign devices and exact target group', () => {
  const devices = [device('phone-a', { group: 'group-a' }), device('phone-b', { group: 'group-b' })];
  const groups = buildDeviceGroups(devices);

  const result = resolveMatrixNavigation(devices, [campaign('campaign-1', ['phone-a', 'phone-b'])], groups, {
    campaignId: 'campaign-1',
    deviceId: 'phone-b',
  });

  assert.equal(result.campaignFound, true);
  assert.equal(result.focusedId, 'phone-b');
  assert.equal(result.groupId, 'group-b');
  assert.deepEqual(result.selectedIds, ['phone-a', 'phone-b']);
  assert.equal(result.missingDeviceId, undefined);
});

test('resolveMatrixNavigation reports a missing exact target without choosing another phone', () => {
  const devices = [device('phone-a')];

  const result = resolveMatrixNavigation(devices, [campaign('campaign-1', ['phone-a'])], buildDeviceGroups(devices), {
    campaignId: 'campaign-1',
    deviceId: 'phone-offline',
  });

  assert.equal(result.focusedId, undefined);
  assert.equal(result.missingDeviceId, 'phone-offline');
});

test('deriveDeviceStatus gives offline state precedence over stale task data', () => {
  assert.equal(deriveDeviceStatus(device('phone-a', { online: false, busy: true }), task('phone-a', 'running')), 'offline');
});

test('deriveDeviceStatus highlights task failures as errors', () => {
  assert.equal(deriveDeviceStatus(device('phone-a'), task('phone-a', 'failed')), 'error');
});

test('deriveDeviceStatus distinguishes active work, queued work, and idle devices', () => {
  assert.equal(deriveDeviceStatus(device('running'), task('running', 'running')), 'running');
  assert.equal(deriveDeviceStatus(device('waiting'), task('waiting', 'queued')), 'waiting');
  assert.equal(deriveDeviceStatus(device('idle')), 'online_idle');
});

test('mergeMatrixSnapshot merges partial device updates and keeps untouched devices', () => {
  const current: MatrixStatusSnapshot = {
    schema: 'loom.matrix.v1',
    devices: [device('phone-a', { name: 'A', progress: 20 }), device('phone-b', { name: 'B' })],
  };
  const incoming: MatrixStatusSnapshot = {
    schema: 'loom.matrix.v1',
    devices: [device('phone-a', { progress: 80 })],
    updatedAt: '2026-07-16T12:00:00+08:00',
  };

  const merged = mergeMatrixSnapshot(current, incoming);

  assert.deepEqual(merged.devices, [
    device('phone-a', { name: 'A', progress: 80 }),
    device('phone-b', { name: 'B' }),
  ]);
  assert.equal(merged.updatedAt, incoming.updatedAt);
});

test('latestTasksByDevice reads the nested campaign shape returned by the Matrix backend', () => {
  const snapshot: MatrixStatusSnapshot = {
    schema: 'loom.matrix.v1',
    devices: [device('phone-a')],
    campaigns: [{
      campaignId: 'campaign-backend-1',
      status: 'running',
      concurrency: 1,
      missions: [{
        missionId: 'mission-backend-1',
        deviceTasks: [{
          assignmentId: 'assignment-backend-1',
          deviceTaskId: 'task-backend-1',
          deviceId: 'phone-a',
          jobId: null,
          status: 'running',
          attempt: 1,
        }],
      }],
    }],
  };

  assert.equal(latestTasksByDevice(snapshot).get('phone-a')?.deviceTaskId, 'task-backend-1');
});

test('latestTasksByDevice prefers a task from the newest campaign over an older failure', () => {
  const oldCampaign = campaign('campaign-old', ['phone-a']);
  oldCampaign.deviceTasks[0] = { ...oldCampaign.deviceTasks[0], deviceTaskId: 'task-old-failure', status: 'failed' };
  const newCampaign = campaign('campaign-new', ['phone-a']);
  newCampaign.deviceTasks[0] = { ...newCampaign.deviceTasks[0], deviceTaskId: 'task-new-queued', status: 'queued' };
  const snapshot: MatrixStatusSnapshot = {
    schema: 'loom.matrix.v1',
    devices: [device('phone-a')],
    campaigns: [oldCampaign, newCampaign],
  };

  assert.equal(latestTasksByDevice(snapshot).get('phone-a')?.deviceTaskId, 'task-new-queued');
});

test('normalizeMatrixCampaigns preserves per-device failure diagnostics', () => {
  const normalized = normalizeMatrixCampaigns([{
    campaignId: 'campaign-failed',
    status: 'failed',
    missions: [{
      deviceTasks: [{
        assignmentId: 'assignment-failed',
        deviceTaskId: 'task-failed',
        deviceId: 'phone-a',
        jobId: 'job-failed',
        status: 'failed',
        attempt: 1,
        failureCode: 'device_offline',
        failureReason: '手机端离线，请检查 APKClaw 网络连接',
      }],
    }],
  }]);

  assert.equal(normalized[0].deviceTasks[0].failureCode, 'device_offline');
  assert.equal(normalized[0].deviceTasks[0].failureReason, '手机端离线，请检查 APKClaw 网络连接');
});

test('dispatch confirmation fingerprints bind approval to every risk-bearing input', () => {
  const fingerprint = (matrixViewModel as unknown as {
    matrixDispatchFingerprint?: (input: {
      prompt: string;
      templateId: string;
      mode: string;
      profile: string;
      selectedDeviceIds: Iterable<string>;
    }) => string;
  }).matrixDispatchFingerprint;
  assert.equal(typeof fingerprint, 'function');
  if (!fingerprint) return;
  const base = {
    prompt: 'publish approved note',
    templateId: 'publish-note',
    mode: 'full',
    profile: 'deep',
    selectedDeviceIds: new Set(['phone-b', 'phone-a']),
  };
  const approved = fingerprint(base);

  assert.notEqual(fingerprint({ ...base, prompt: 'publish changed note' }), approved);
  assert.notEqual(fingerprint({ ...base, templateId: 'send-message' }), approved);
  assert.notEqual(fingerprint({ ...base, mode: 'safe' }), approved);
  assert.notEqual(fingerprint({ ...base, profile: 'standard' }), approved);
  assert.notEqual(fingerprint({ ...base, selectedDeviceIds: new Set(['phone-a']) }), approved);
  assert.equal(fingerprint({ ...base, selectedDeviceIds: new Set(['phone-a', 'phone-b']) }), approved);
});

test('object-contain coordinates ignore letterbox padding and normalize against visible pixels', () => {
  const normalize = (matrixViewModel as unknown as {
    normalizeObjectContainPoint?: (
      container: { left: number; top: number; width: number; height: number },
      media: { width: number; height: number },
      point: { x: number; y: number },
    ) => { x: number; y: number } | null;
  }).normalizeObjectContainPoint;
  assert.equal(typeof normalize, 'function');
  if (!normalize) return;
  const container = { left: 10, top: 20, width: 200, height: 400 };
  const squareMedia = { width: 1000, height: 1000 };

  assert.equal(normalize(container, squareMedia, { x: 110, y: 70 }), null);
  assert.deepEqual(normalize(container, squareMedia, { x: 110, y: 220 }), { x: 0.5, y: 0.5 });
  assert.equal(normalize(container, squareMedia, { x: 110, y: 370 }), null);
});

test('pause and resume visibility matches backend-supported task transitions', () => {
  const actionsFor = (matrixViewModel as unknown as {
    supportedMatrixTaskActions?: (status: MatrixDeviceTask['status']) => { pause: boolean; resume: boolean };
  }).supportedMatrixTaskActions;
  assert.equal(typeof actionsFor, 'function');
  if (!actionsFor) return;

  assert.deepEqual(actionsFor('queued'), { pause: true, resume: false });
  assert.deepEqual(actionsFor('running'), { pause: true, resume: false });
  assert.deepEqual(actionsFor('paused'), { pause: false, resume: true });
  for (const status of ['preflight', 'retrying', 'needs_human', 'failed', 'completed', 'cancelled'] as const) {
    assert.deepEqual(actionsFor(status), { pause: false, resume: false }, status);
  }
});

test('Matrix realtime gap recovery returns the authoritative snapshot cursor and reports connection state', async () => {
  const source = await readFile(new URL('./useMatrixStream.ts', import.meta.url), 'utf8');

  assert.match(source, /onSequenceGap:[\s\S]*?return loadSnapshot\(\)/);
  assert.match(source, /onConnectionState\s*:/);
  assert.doesNotMatch(source, /onSequenceGap:\s*async\s*\(\)\s*=>\s*\{[^}]*refresh\(\)/);
});

test('Matrix bootstrap presents loading before the first snapshot instead of an empty device wall', async () => {
  const derive = (matrixViewModel as unknown as {
    deriveMatrixStreamPresentation?: (input: {
      enabled: boolean;
      hasSnapshot: boolean;
      syncHealthy: boolean;
      syncError: string;
      transportConnected: boolean;
      transportReconnecting: boolean;
      transportError: string;
    }) => { loading: boolean; connected: boolean; reconnecting: boolean; error: string };
  }).deriveMatrixStreamPresentation;
  assert.equal(typeof derive, 'function');
  if (!derive) return;

  assert.deepEqual(derive({
    enabled: true,
    hasSnapshot: false,
    syncHealthy: false,
    syncError: '',
    transportConnected: false,
    transportReconnecting: false,
    transportError: '',
  }), {
    loading: true,
    connected: false,
    reconnecting: false,
    error: '',
  });

  const workbenchSource = await readFile(new URL('./MatrixWorkbenchPage.tsx', import.meta.url), 'utf8');
  const phoneWallSource = await readFile(new URL('./PhoneWall.tsx', import.meta.url), 'utf8');
  assert.match(workbenchSource, /<PhoneWall[\s\S]*?loading=\{stream\.loading\}/);
  assert.match(phoneWallSource, /loading\s*\?[\s\S]*?正在加载矩阵设备/);
});

test('Matrix sync failures cannot present realtime as connected', () => {
  const derive = (matrixViewModel as unknown as {
    deriveMatrixStreamPresentation?: (input: {
      enabled: boolean;
      hasSnapshot: boolean;
      syncHealthy: boolean;
      syncError: string;
      transportConnected: boolean;
      transportReconnecting: boolean;
      transportError: string;
    }) => { loading: boolean; connected: boolean; reconnecting: boolean; error: string };
  }).deriveMatrixStreamPresentation;
  assert.equal(typeof derive, 'function');
  if (!derive) return;

  assert.deepEqual(derive({
    enabled: true,
    hasSnapshot: true,
    syncHealthy: false,
    syncError: '矩阵状态刷新失败',
    transportConnected: true,
    transportReconnecting: false,
    transportError: '',
  }), {
    loading: false,
    connected: false,
    reconnecting: false,
    error: '矩阵状态刷新失败',
  });
});

test('pollIntervalForDevice uses focus, running, and idle production intervals', () => {
  assert.equal(pollIntervalForDevice('online_idle', false), 4_000);
  assert.equal(pollIntervalForDevice('running', false), 1_500);
  assert.equal(pollIntervalForDevice('waiting', true), 700);
  assert.equal(pollIntervalForDevice('offline', false), null);
});

test('an immediate screen request made during an in-flight poll runs next instead of being overwritten', () => {
  assert.equal(nextScreenDueAt(1_000, 700, true), 0);
  assert.equal(nextScreenDueAt(1_000, 700, false), 1_700);
  assert.equal(nextScreenDueAt(1_000, null, false), Number.POSITIVE_INFINITY);
});

test('failed screen refreshes back off instead of continuously occupying the phone channel', () => {
  assert.equal(screenFailureBackoffMs(0), 0);
  assert.equal(screenFailureBackoffMs(1), 3_000);
  assert.equal(screenFailureBackoffMs(2), 6_000);
  assert.equal(screenFailureBackoffMs(3), 12_000);
  assert.equal(screenFailureBackoffMs(8), 15_000);
});

test('a transient screen refresh error does not disable manual control when a valid frame remains', () => {
  assert.equal(matrixViewModel.canUseMatrixManualControls({
    mode: 'manual',
    leasedDeviceId: 'phone-a',
    deviceId: 'phone-a',
    hasFrame: true,
    screenError: 'temporary timeout',
  }), true);
  assert.equal(matrixViewModel.canUseMatrixManualControls({
    mode: 'manual',
    leasedDeviceId: 'phone-a',
    deviceId: 'phone-a',
    hasFrame: false,
    screenError: 'temporary timeout',
  }), false);
});

test('manual screenshot feedback settles only from the matching refresh generation', () => {
  assert.deepEqual(resolveScreenRequestOutcome(3, undefined), { status: 'pending' });
  assert.deepEqual(resolveScreenRequestOutcome(3, { generation: 2 }), { status: 'pending' });
  assert.deepEqual(resolveScreenRequestOutcome(3, { generation: 3 }), { status: 'success' });
  assert.deepEqual(
    resolveScreenRequestOutcome(3, { generation: 3, error: 'screen unavailable' }),
    { status: 'error', error: 'screen unavailable' },
  );
});

const candidate = (deviceId: string, overrides: Partial<ScreenScheduleCandidate> = {}): ScreenScheduleCandidate => ({
  deviceId,
  status: 'online_idle',
  visible: true,
  focused: false,
  dueAt: 0,
  ...overrides,
});

test('selectDueScreenRequests stops hidden and offscreen polling', () => {
  const result = selectDueScreenRequests([
    candidate('visible'),
    candidate('offscreen', { visible: false }),
  ], new Set(), 10, false);

  assert.deepEqual(result.map((item) => item.deviceId), []);
});

test('selectDueScreenRequests prioritizes focus and excludes in-flight requests', () => {
  const result = selectDueScreenRequests([
    candidate('normal', { dueAt: 1 }),
    candidate('focused', { focused: true, dueAt: 5 }),
    candidate('busy', { focused: true, dueAt: 0 }),
  ], new Set(['busy']), 10, true);

  assert.deepEqual(result.map((item) => item.deviceId), ['focused', 'normal']);
});

test('selectDueScreenRequests never exceeds the global concurrency cap', () => {
  const candidates = Array.from({ length: 30 }, (_, index) => candidate(`phone-${index}`));

  const result = selectDueScreenRequests(candidates, new Set(), 10, true);

  assert.equal(result.length, MAX_SCREEN_REQUESTS);
});

test('applyScreenResponse preserves the current object URL on a hash hit', () => {
  const current = {
    deviceId: 'phone-a',
    url: 'blob:current',
    hash: 'sha256:same',
    capturedAt: '2026-07-16T11:59:00+08:00',
    width: 1080,
    height: 2400,
  };

  const result = applyScreenResponse(current, {
    schema: 'loom.matrix.screen.v1',
    deviceId: 'phone-a',
    screenHash: 'sha256:same',
    capturedAt: '2026-07-16T12:00:00+08:00',
    mime: 'image/jpeg',
    width: 1080,
    height: 2400,
    notModified: true,
  });

  assert.equal(result.frame.url, 'blob:current');
  assert.equal(result.frame.capturedAt, '2026-07-16T12:00:00+08:00');
  assert.equal(result.revokeUrl, undefined);
});

test('applyScreenResponse identifies the replaced object URL for cleanup', () => {
  const result = applyScreenResponse({
    deviceId: 'phone-a',
    url: 'blob:old',
    hash: 'sha256:old',
    capturedAt: 'old',
    width: 1080,
    height: 2400,
  }, {
    schema: 'loom.matrix.screen.v1',
    deviceId: 'phone-a',
    screenHash: 'sha256:new',
    capturedAt: 'new',
    mime: 'image/jpeg',
    width: 1080,
    height: 2400,
    image: 'base64',
    notModified: false,
  }, 'blob:new');

  assert.equal(result.frame.url, 'blob:new');
  assert.equal(result.revokeUrl, 'blob:old');
});
