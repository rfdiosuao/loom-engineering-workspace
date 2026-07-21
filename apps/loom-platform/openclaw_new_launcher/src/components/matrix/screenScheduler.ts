import type { MatrixScreen } from '../../types/matrix';
import type { MatrixDeviceStatus } from './matrixViewModel';

export const MAX_SCREEN_REQUESTS = 12;
const MAX_SCREEN_FAILURE_BACKOFF_MS = 15_000;

export interface ScreenScheduleCandidate {
  deviceId: string;
  status: MatrixDeviceStatus;
  visible: boolean;
  focused: boolean;
  dueAt: number;
}

export interface MatrixScreenFrame {
  deviceId: string;
  url: string;
  hash: string;
  capturedAt: string;
  width: number;
  height: number;
}

export function applyScreenResponse(
  current: MatrixScreenFrame | undefined,
  response: MatrixScreen,
  nextUrl?: string,
): { frame: MatrixScreenFrame; revokeUrl?: string } {
  const url = response.notModified ? current?.url : nextUrl;
  if (!url) throw new Error('截图响应缺少可显示的图片');
  return {
    frame: {
      deviceId: response.deviceId,
      url,
      hash: response.screenHash,
      capturedAt: response.capturedAt,
      width: response.width,
      height: response.height,
    },
    revokeUrl: !response.notModified && current?.url !== nextUrl ? current?.url : undefined,
  };
}

export function pollIntervalForDevice(status: MatrixDeviceStatus, focused: boolean): number | null {
  if (status === 'offline') return null;
  if (focused) return 700;
  if (status === 'running') return 1_500;
  return 4_000;
}

export function screenFailureBackoffMs(failureCount: number): number {
  if (failureCount <= 0) return 0;
  return Math.min(MAX_SCREEN_FAILURE_BACKOFF_MS, 3_000 * (2 ** (failureCount - 1)));
}

export interface ScreenRequestOutcome {
  generation: number;
  error?: string;
}

export function resolveScreenRequestOutcome(
  requestedGeneration: number,
  outcome: ScreenRequestOutcome | undefined,
): { status: 'pending' } | { status: 'success' } | { status: 'error'; error: string } {
  if (!outcome || outcome.generation < requestedGeneration) return { status: 'pending' };
  if (outcome.error) return { status: 'error', error: outcome.error };
  return { status: 'success' };
}

export function nextScreenDueAt(
  now: number,
  interval: number | null,
  immediateRequestPending: boolean,
  minimumDelayMs = 0,
): number {
  if (immediateRequestPending) return 0;
  return interval === null ? Number.POSITIVE_INFINITY : now + Math.max(interval, minimumDelayMs);
}

export function selectDueScreenRequests(
  candidates: ScreenScheduleCandidate[],
  inFlight: ReadonlySet<string>,
  now: number,
  pageVisible: boolean,
): ScreenScheduleCandidate[] {
  if (!pageVisible) return [];
  const remaining = Math.max(0, MAX_SCREEN_REQUESTS - inFlight.size);
  return candidates
    .filter((candidate) => (
      candidate.visible
      && candidate.status !== 'offline'
      && candidate.dueAt <= now
      && !inFlight.has(candidate.deviceId)
    ))
    .sort((left, right) => Number(right.focused) - Number(left.focused) || left.dueAt - right.dueAt || left.deviceId.localeCompare(right.deviceId))
    .slice(0, remaining);
}
