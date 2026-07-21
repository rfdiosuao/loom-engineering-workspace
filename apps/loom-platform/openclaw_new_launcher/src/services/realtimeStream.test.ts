import 'tsx/esm';

import assert from 'node:assert/strict';
import { test } from 'node:test';

import type {
  LoomRealtimeEvent,
  RealtimeSequenceGap,
  StreamTicketRequest,
} from '../types/realtime.ts';

const { isLoomRealtimeEvent, openRealtimeStream } = await import('./realtimeStream.ts');

const encoder = new TextEncoder();

function event(overrides: Partial<LoomRealtimeEvent> = {}): LoomRealtimeEvent {
  return {
    schema: 'loom.realtime.event.v1',
    eventId: 'evt_1',
    seq: 1,
    timestamp: '2026-07-15T14:30:00+08:00',
    topic: 'matrix.assignment',
    entityId: 'dt_1',
    type: 'matrix.assignment.progress',
    data: { progress: 10 },
    ...overrides,
  };
}

function streamResponse(chunks: string[]): Response {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  });
}

function frame(payload: unknown, newline = '\n'): string {
  return `event: message${newline}data: ${JSON.stringify(payload)}${newline}${newline}`;
}

test('realtime event validation requires seq to start at one', () => {
  assert.equal(isLoomRealtimeEvent(event({ seq: 1 })), true);
  assert.equal(isLoomRealtimeEvent(event({ seq: 0 })), false);
});

test('realtime event validation requires non-empty identifiers and RFC3339 timestamps', () => {
  assert.equal(isLoomRealtimeEvent(event({ timestamp: '2026-07-15T06:30:00Z' })), true);
  assert.equal(isLoomRealtimeEvent(event({ timestamp: '2026-07-15t06:30:00.123z' })), true);

  for (const value of [
    event({ topic: '' }),
    event({ entityId: '' }),
    event({ type: '' }),
    event({ timestamp: 'not-a-date' }),
    event({ timestamp: '2026-07-15 14:30:00+08:00' }),
    event({ timestamp: '2026-07-15T14:30:00' }),
    event({ timestamp: '2026-02-30T14:30:00+08:00' }),
  ]) {
    assert.equal(isLoomRealtimeEvent(value), false);
  }
});

test('parses split SSE frames, rejects other schemas, and ignores committed sequences', async () => {
  const controller = new AbortController();
  const accepted: LoomRealtimeEvent[] = [];
  const valid = frame(event());
  let ticketCount = 0;

  await openRealtimeStream({
    topic: 'matrix',
    signal: controller.signal,
    onEvent: (value) => {
      accepted.push(value);
    },
  }, {
    issueTicket: async () => {
      ticketCount += 1;
      if (ticketCount === 2) controller.abort();
      return { ticket: `ticket_${ticketCount}`, expiresAt: '2026-07-15T14:30:30+08:00' };
    },
    streamUrl: () => 'http://127.0.0.1:1234/api/matrix/events/stream',
    fetch: async () => streamResponse([
      valid.slice(0, 17),
      valid.slice(17)
        + frame({ ...event({ eventId: 'evt_wrong' }), schema: 'other.v1' }, '\r\n')
        + frame(event({ eventId: 'evt_same_seq' })),
    ]),
    retryDelayMs: 0,
  });

  assert.deepEqual(accepted.map((value) => value.eventId), ['evt_1']);
  assert.equal(ticketCount, 2);
});

test('reconnects with a fresh ticket and the last committed sequence', async () => {
  const controller = new AbortController();
  const urls: string[] = [];
  const authorizations: Array<string | null> = [];
  const ticketTopics: StreamTicketRequest[] = [];
  const accepted: number[] = [];
  let ticketCount = 0;

  await openRealtimeStream({
    topic: 'matrix',
    afterSeq: 2,
    signal: controller.signal,
    query: { campaignId: 'cmp_1' },
    onEvent: (value) => {
      accepted.push(value.seq);
      if (value.seq === 4) controller.abort();
    },
  }, {
    issueTicket: async (request) => {
      ticketTopics.push(request);
      ticketCount += 1;
      return { ticket: `ticket_${ticketCount}`, expiresAt: '2026-07-15T14:30:30+08:00' };
    },
    streamUrl: () => 'http://127.0.0.1:1234/api/matrix/events/stream',
    fetch: async (input, init) => {
      const url = String(input);
      urls.push(url);
      authorizations.push(new Headers(init?.headers).get('Authorization'));
      if (urls.length === 1) return streamResponse([frame(event({ eventId: 'evt_3', seq: 3 }))]);
      return streamResponse([
        frame(event({ eventId: 'evt_3_replay', seq: 3 })),
        frame(event({ eventId: 'evt_4', seq: 4 })),
      ]);
    },
    retryDelayMs: 0,
  });

  assert.deepEqual(ticketTopics, [
    { topic: 'matrix', resource: 'all' },
    { topic: 'matrix', resource: 'all' },
  ]);
  assert.deepEqual(accepted, [3, 4]);
  assert.equal(new URL(urls[0]).searchParams.has('ticket'), false);
  assert.match(urls[0], /afterSeq=2/);
  assert.match(urls[0], /campaignId=cmp_1/);
  assert.equal(new URL(urls[1]).searchParams.has('ticket'), false);
  assert.match(urls[1], /afterSeq=3/);
  assert.deepEqual(authorizations, ['Bearer ticket_1', 'Bearer ticket_2']);
});

test('deduplicates an eventId at a new sequence and still acknowledges its sequence', async () => {
  const controller = new AbortController();
  const accepted: Array<{ eventId: string; seq: number }> = [];
  const gaps: RealtimeSequenceGap[] = [];

  await openRealtimeStream({
    topic: 'matrix',
    signal: controller.signal,
    onEvent: (value) => {
      accepted.push({ eventId: value.eventId, seq: value.seq });
      if (value.seq === 3) controller.abort();
    },
    onSequenceGap: (gap) => {
      gaps.push(gap);
      controller.abort();
    },
  }, {
    issueTicket: async () => ({
      ticket: 'ticket_1',
      expiresAt: '2026-07-15T14:30:30+08:00',
    }),
    streamUrl: () => 'http://127.0.0.1:1234/api/matrix/events/stream',
    fetch: async () => streamResponse([
      frame(event({ eventId: 'evt_shared', seq: 1 })),
      frame(event({ eventId: 'evt_shared', seq: 2 })),
      frame(event({ eventId: 'evt_next', seq: 3 })),
    ]),
    retryDelayMs: 0,
  });

  assert.deepEqual(accepted, [
    { eventId: 'evt_shared', seq: 1 },
    { eventId: 'evt_next', seq: 3 },
  ]);
  assert.deepEqual(gaps, []);
});

test('retains exactly the most recent 4096 eventIds for deduplication', async () => {
  const controller = new AbortController();
  let acceptedCount = 0;
  const frames = Array.from({ length: 4096 }, (_, index) => (
    frame(event({ eventId: `evt_${index + 1}`, seq: index + 1 }))
  ));
  frames.push(frame(event({ eventId: 'evt_1', seq: 4097 })));
  frames.push(frame(event({ eventId: 'evt_4098', seq: 4098 })));
  frames.push(frame(event({ eventId: 'evt_1', seq: 4099 })));

  await openRealtimeStream({
    topic: 'matrix',
    signal: controller.signal,
    onEvent: (value) => {
      acceptedCount += 1;
      if (value.seq === 4099) controller.abort();
    },
  }, {
    issueTicket: async () => ({
      ticket: 'ticket_1',
      expiresAt: '2026-07-15T14:30:30+08:00',
    }),
    streamUrl: () => 'http://127.0.0.1:1234/api/matrix/events/stream',
    fetch: async () => streamResponse(frames),
    retryDelayMs: 0,
  });

  assert.equal(acceptedCount, 4098);
});

test('signals a sequence gap and reconnects from the last committed sequence', async () => {
  const controller = new AbortController();
  const accepted: number[] = [];
  const gaps: RealtimeSequenceGap[] = [];
  const afterSequences: string[] = [];
  let fetchCount = 0;

  await openRealtimeStream({
    topic: 'matrix',
    afterSeq: 2,
    signal: controller.signal,
    onEvent: (value) => {
      accepted.push(value.seq);
      if (value.seq === 5) controller.abort();
    },
    onSequenceGap: (gap) => {
      gaps.push(gap);
    },
  }, {
    issueTicket: async () => ({
      ticket: `ticket_${fetchCount + 1}`,
      expiresAt: '2026-07-15T14:30:30+08:00',
    }),
    streamUrl: () => 'http://127.0.0.1:1234/api/matrix/events/stream',
    fetch: async (input) => {
      fetchCount += 1;
      afterSequences.push(new URL(String(input)).searchParams.get('afterSeq') ?? '');
      if (fetchCount === 1) {
        return streamResponse([
          frame(event({ eventId: 'evt_3', seq: 3 })),
          frame(event({ eventId: 'evt_5_early', seq: 5 })),
        ]);
      }
      return streamResponse([
        frame(event({ eventId: 'evt_4', seq: 4 })),
        frame(event({ eventId: 'evt_5', seq: 5 })),
      ]);
    },
    retryDelayMs: 0,
  });

  assert.deepEqual(accepted, [3, 4, 5]);
  assert.deepEqual(afterSequences, ['2', '3']);
  assert.deepEqual(gaps, [{
    topic: 'matrix',
    committedSeq: 3,
    expectedSeq: 4,
    receivedSeq: 5,
    eventId: 'evt_5_early',
  }]);
});

test('uses the authoritative recovery cursor after a persistent sequence gap', async () => {
  const controller = new AbortController();
  const afterSequences: string[] = [];
  const accepted: number[] = [];
  let fetchCount = 0;

  await openRealtimeStream({
    topic: 'matrix',
    afterSeq: 2,
    signal: controller.signal,
    onEvent: (value) => {
      accepted.push(value.seq);
      controller.abort();
    },
    onSequenceGap: () => 5,
  }, {
    issueTicket: async () => ({
      ticket: `ticket_${fetchCount + 1}`,
      expiresAt: '2026-07-15T14:30:30+08:00',
    }),
    streamUrl: () => 'http://127.0.0.1:1234/api/matrix/events/stream',
    fetch: async (input) => {
      fetchCount += 1;
      afterSequences.push(new URL(String(input)).searchParams.get('afterSeq') ?? '');
      if (fetchCount === 1) {
        return streamResponse([frame(event({ eventId: 'evt_5_early', seq: 5 }))]);
      }
      return streamResponse([frame(event({ eventId: 'evt_6', seq: 6 }))]);
    },
    retryDelayMs: 0,
  });

  assert.deepEqual(afterSequences, ['2', '5']);
  assert.deepEqual(accepted, [6]);
});

test('reports reconnecting and connected states instead of hiding stream failures', async () => {
  const controller = new AbortController();
  const states: Array<{ status: string; attempt: number; error?: string }> = [];
  let fetchCount = 0;

  await openRealtimeStream({
    topic: 'agent',
    signal: controller.signal,
    query: { sessionId: 'session_1' },
    onConnectionState: (state) => states.push(state),
    onEvent: () => controller.abort(),
  }, {
    issueTicket: async () => ({
      ticket: `ticket_${fetchCount + 1}`,
      expiresAt: '2026-07-15T14:30:30+08:00',
    }),
    streamUrl: () => 'http://127.0.0.1:1234/api/agent/events/stream',
    fetch: async () => {
      fetchCount += 1;
      if (fetchCount === 1) return new Response(null, { status: 503 });
      return streamResponse([frame(event({ topic: 'agent.run', entityId: 'run_1' }))]);
    },
    retryDelayMs: 0,
  });

  assert.equal(states[0]?.status, 'connecting');
  assert.equal(states.some((state) => state.status === 'reconnecting' && state.error?.includes('503')), true);
  assert.equal(states[states.length - 1]?.status, 'connected');
});

test('aborts while a stream ticket request is still pending', async () => {
  const controller = new AbortController();
  let ticketRequestStarted: (() => void) | undefined;
  const started = new Promise<void>((resolve) => {
    ticketRequestStarted = resolve;
  });

  const opening = openRealtimeStream({
    topic: 'agent',
    signal: controller.signal,
    query: { sessionId: 'session_1' },
    onEvent: () => undefined,
  }, {
    issueTicket: () => {
      ticketRequestStarted?.();
      return new Promise(() => undefined);
    },
    streamUrl: () => 'http://127.0.0.1:1234/api/agent/events/stream',
    fetch: async () => {
      throw new Error('fetch must not run after abort');
    },
    retryDelayMs: 0,
  });

  await started;
  controller.abort();
  await Promise.race([
    opening,
    new Promise<never>((_, reject) => {
      setTimeout(() => reject(new Error('openRealtimeStream did not observe abort')), 100);
    }),
  ]);
});

test('does not commit an event until its callback succeeds', async () => {
  const controller = new AbortController();
  const afterSequences: string[] = [];
  let callbackCount = 0;
  let ticketCount = 0;

  await openRealtimeStream({
    topic: 'agent',
    afterSeq: 6,
    signal: controller.signal,
    query: { sessionId: 'session_1' },
    onEvent: () => {
      callbackCount += 1;
      if (callbackCount === 1) throw new Error('store update failed');
      controller.abort();
    },
  }, {
    issueTicket: async () => {
      ticketCount += 1;
      return { ticket: `ticket_${ticketCount}`, expiresAt: '2026-07-15T14:30:30+08:00' };
    },
    streamUrl: () => 'http://127.0.0.1:1234/api/agent/events/stream',
    fetch: async (input) => {
      const url = new URL(String(input));
      afterSequences.push(url.searchParams.get('afterSeq') ?? '');
      return streamResponse([frame(event({ eventId: 'evt_7', seq: 7, topic: 'agent.run', entityId: 'run_1' }))]);
    },
    retryDelayMs: 0,
  });

  assert.equal(ticketCount, 2);
  assert.equal(callbackCount, 2);
  assert.deepEqual(afterSequences, ['6', '6']);
});

test('uses the ticket only in the direct stream authorization header and never sends a bridge token', async () => {
  const controller = new AbortController();
  let requestHeaders: HeadersInit | undefined;
  let requestUrl = '';
  let ticketCount = 0;

  await openRealtimeStream({
    topic: 'matrix',
    afterSeq: 3,
    signal: controller.signal,
    query: { ticket: 'caller_override', afterSeq: 999 },
    onEvent: () => controller.abort(),
  }, {
    issueTicket: async () => {
      ticketCount += 1;
      if (ticketCount === 2) controller.abort();
      return { ticket: 'short_lived_ticket', expiresAt: '2026-07-15T14:30:30+08:00' };
    },
    streamUrl: () => 'http://127.0.0.1:1234/api/matrix/events/stream',
    fetch: async (input, init) => {
      requestUrl = String(input);
      requestHeaders = init?.headers;
      return streamResponse([frame(event({ seq: 4 }))]);
    },
    retryDelayMs: 0,
  });

  const headers = new Headers(requestHeaders);
  assert.equal(headers.get('X-Bridge-Token'), null);
  assert.equal(headers.get('Authorization'), 'Bearer short_lived_ticket');
  assert.equal(new URL(requestUrl).searchParams.has('ticket'), false);
  assert.equal(new URL(requestUrl).searchParams.get('afterSeq'), '3');
});

test('resolves a relative granted stream path against the configured Bridge origin', async () => {
  const controller = new AbortController();
  let requestUrl = '';

  await openRealtimeStream({
    topic: 'agent',
    signal: controller.signal,
    query: { sessionId: 'session_1' },
    onEvent: () => controller.abort(),
  }, {
    issueTicket: async () => ({
      ticket: 'ticket_relative',
      expiresAt: '2026-07-15T14:30:30+08:00',
      streamUrl: '/api/agent/events/stream?ticket=must_not_leak',
    }),
    streamUrl: () => 'http://127.0.0.1:24680/api/agent/events/stream',
    fetch: async (input) => {
      requestUrl = String(input);
      return streamResponse([frame(event({ topic: 'agent.run', entityId: 'run_1' }))]);
    },
    retryDelayMs: 0,
  });

  assert.equal(new URL(requestUrl).origin, 'http://127.0.0.1:24680');
  assert.equal(new URL(requestUrl).pathname, '/api/agent/events/stream');
  assert.equal(new URL(requestUrl).searchParams.has('ticket'), false);
});
