import { realtimeApi } from './api';
import {
  REALTIME_EVENT_SCHEMA,
  type LoomRealtimeEvent,
  type OpenRealtimeStreamOptions,
  type RealtimeConnectionState,
  type RealtimeSequenceGap,
  type RealtimeStreamTopic,
  type StreamTicketRequest,
  type StreamTicketResponse,
} from '../types/realtime';

const DEFAULT_RETRY_DELAY_MS = 500;
const EVENT_ID_DEDUPE_CAPACITY = 4096;
const RFC3339_TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})[Tt](?:[01]\d|2[0-3]):[0-5]\d:(?:[0-5]\d|60)(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;

class StreamRequestAbortedError extends Error {}
class RealtimeSequenceGapError extends Error {}

export interface RealtimeStreamDependencies {
  issueTicket: (request: StreamTicketRequest) => Promise<StreamTicketResponse>;
  streamUrl: (topic: RealtimeStreamTopic) => string;
  fetch: typeof fetch;
  retryDelayMs: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isRfc3339Timestamp(value: string): boolean {
  const match = RFC3339_TIMESTAMP.exec(value);
  if (!match) return false;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const calendarDate = new Date(0);
  calendarDate.setUTCHours(0, 0, 0, 0);
  calendarDate.setUTCFullYear(year, month - 1, day);
  return (
    calendarDate.getUTCFullYear() === year
    && calendarDate.getUTCMonth() === month - 1
    && calendarDate.getUTCDate() === day
  );
}

export function isLoomRealtimeEvent(value: unknown): value is LoomRealtimeEvent {
  if (!isRecord(value) || value.schema !== REALTIME_EVENT_SCHEMA) return false;
  return (
    typeof value.eventId === 'string'
    && value.eventId.length > 0
    && Number.isSafeInteger(value.seq)
    && Number(value.seq) >= 1
    && typeof value.timestamp === 'string'
    && isRfc3339Timestamp(value.timestamp)
    && typeof value.topic === 'string'
    && value.topic.length > 0
    && typeof value.entityId === 'string'
    && value.entityId.length > 0
    && typeof value.type === 'string'
    && value.type.length > 0
    && isRecord(value.data)
  );
}

function eventFromFrame(frame: string): LoomRealtimeEvent | null {
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n');
  if (!data) return null;
  try {
    const value: unknown = JSON.parse(data);
    return isLoomRealtimeEvent(value) ? value : null;
  } catch {
    return null;
  }
}

function streamRequestUrl(
  baseUrl: string,
  afterSeq: number,
  query: OpenRealtimeStreamOptions['query'],
): string {
  const absolute = /^[a-z][a-z\d+.-]*:\/\//i.test(baseUrl);
  const url = new URL(baseUrl, 'http://localhost');
  for (const key of [...url.searchParams.keys()]) {
    if (key.toLowerCase() === 'ticket') url.searchParams.delete(key);
  }
  for (const [key, value] of Object.entries(query ?? {})) {
    if (key.toLowerCase() === 'ticket') continue;
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  url.searchParams.set('afterSeq', String(afterSeq));
  return absolute ? url.toString() : `${url.pathname}${url.search}${url.hash}`;
}

function streamResource(options: OpenRealtimeStreamOptions): string {
  if (options.topic === 'matrix') return 'all';
  const sessionId = options.query?.sessionId;
  if (typeof sessionId !== 'string' || !sessionId.trim()) {
    throw new Error('Realtime stream resource unavailable');
  }
  return sessionId.trim();
}

function resolvedStreamBase(grantedUrl: string | undefined, configuredUrl: string): string {
  if (!grantedUrl) return configuredUrl;
  if (/^[a-z][a-z\d+.-]*:\/\//i.test(grantedUrl)) return grantedUrl;
  if (/^[a-z][a-z\d+.-]*:\/\//i.test(configuredUrl)) {
    return new URL(grantedUrl, configuredUrl).toString();
  }
  return grantedUrl;
}

async function waitForRetry(delayMs: number, signal: AbortSignal): Promise<void> {
  if (delayMs <= 0 || signal.aborted) return;
  await new Promise<void>((resolve) => {
    const finish = () => {
      clearTimeout(timeout);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const timeout = setTimeout(finish, delayMs);
    signal.addEventListener('abort', finish, { once: true });
  });
}

function waitWithAbort<T>(pending: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(new StreamRequestAbortedError());

  return new Promise<T>((resolve, reject) => {
    const cleanup = () => signal.removeEventListener('abort', handleAbort);
    const handleAbort = () => {
      cleanup();
      reject(new StreamRequestAbortedError());
    };

    signal.addEventListener('abort', handleAbort, { once: true });
    pending.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (error: unknown) => {
        cleanup();
        reject(error);
      },
    );
  });
}

async function consumeResponse(
  response: Response,
  signal: AbortSignal,
  committedSeq: () => number,
  replaceCommittedSeq: (seq: number) => void,
  commit: (event: LoomRealtimeEvent) => Promise<void>,
  topic: RealtimeStreamTopic,
  onSequenceGap?: (gap: RealtimeSequenceGap) => number | void | Promise<number | void>,
): Promise<void> {
  if (!response.ok || !response.body) {
    throw new Error(`Realtime stream unavailable (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const consumeFrame = async (frame: string) => {
    const event = eventFromFrame(frame);
    const currentSeq = committedSeq();
    if (!event || event.seq <= currentSeq) return;
    if (event.seq > currentSeq + 1) {
      const recoveredSeq = await onSequenceGap?.({
        topic,
        committedSeq: currentSeq,
        expectedSeq: currentSeq + 1,
        receivedSeq: event.seq,
        eventId: event.eventId,
      });
      if (Number.isSafeInteger(recoveredSeq) && Number(recoveredSeq) >= currentSeq) {
        replaceCommittedSeq(Number(recoveredSeq));
      }
      throw new RealtimeSequenceGapError();
    }
    await commit(event);
  };

  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        await consumeFrame(frame);
        if (signal.aborted) return;
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
    }
    buffer += decoder.decode();
    if (!signal.aborted && buffer.trim()) await consumeFrame(buffer);
  } finally {
    if (!signal.aborted) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

function publicConnectionError(error: unknown): string {
  if (error instanceof RealtimeSequenceGapError) return 'Realtime sequence gap';
  if (error instanceof Error && /^Realtime stream unavailable \(\d{3}\)$/.test(error.message)) {
    return error.message;
  }
  if (error instanceof Error && error.message === 'Realtime stream ticket unavailable') {
    return error.message;
  }
  return 'Realtime connection failed';
}

function notifyConnectionState(
  callback: OpenRealtimeStreamOptions['onConnectionState'],
  state: RealtimeConnectionState,
): void {
  try {
    callback?.(state);
  } catch {
    // Connection observers must not be able to stop event delivery.
  }
}

export async function openRealtimeStream(
  options: OpenRealtimeStreamOptions,
  overrides: Partial<RealtimeStreamDependencies> = {},
): Promise<void> {
  const dependencies: RealtimeStreamDependencies = {
    issueTicket: realtimeApi.issueTicket,
    streamUrl: realtimeApi.eventsStreamUrl,
    fetch: globalThis.fetch.bind(globalThis),
    retryDelayMs: DEFAULT_RETRY_DELAY_MS,
    ...overrides,
  };
  let committedSeq = Math.max(0, Math.trunc(options.afterSeq ?? 0));
  let attempt = 0;
  const seenEventIds = new Set<string>();

  const rememberEventId = (eventId: string) => {
    seenEventIds.add(eventId);
    if (seenEventIds.size <= EVENT_ID_DEDUPE_CAPACITY) return;
    const oldestEventId = seenEventIds.values().next().value;
    if (oldestEventId !== undefined) seenEventIds.delete(oldestEventId);
  };

  while (!options.signal.aborted) {
    attempt += 1;
    notifyConnectionState(options.onConnectionState, {
      status: attempt === 1 ? 'connecting' : 'reconnecting',
      attempt,
    });
    try {
      const grant = await waitWithAbort(
        dependencies.issueTicket({ topic: options.topic, resource: streamResource(options) }),
        options.signal,
      );
      if (options.signal.aborted) break;
      if (!grant.ticket) throw new Error('Realtime stream ticket unavailable');
      const configuredUrl = dependencies.streamUrl(options.topic);
      const url = streamRequestUrl(
        resolvedStreamBase(grant.streamUrl, configuredUrl),
        committedSeq,
        options.query,
      );
      const response = await dependencies.fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
          Authorization: `Bearer ${grant.ticket}`,
        },
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
        referrerPolicy: 'no-referrer',
        signal: options.signal,
      });
      if (!response.ok || !response.body) {
        throw new Error(`Realtime stream unavailable (${response.status})`);
      }
      notifyConnectionState(options.onConnectionState, { status: 'connected', attempt });
      await consumeResponse(
        response,
        options.signal,
        () => committedSeq,
        (seq) => {
          committedSeq = seq;
        },
        async (event) => {
          if (seenEventIds.has(event.eventId)) {
            committedSeq = event.seq;
            return;
          }
          await options.onEvent(event);
          rememberEventId(event.eventId);
          committedSeq = event.seq;
        },
        options.topic,
        options.onSequenceGap,
      );
    } catch (error) {
      if (options.signal.aborted) break;
      notifyConnectionState(options.onConnectionState, {
        status: 'reconnecting',
        attempt,
        error: publicConnectionError(error),
      });
    }
    await waitForRetry(dependencies.retryDelayMs, options.signal);
  }
}
