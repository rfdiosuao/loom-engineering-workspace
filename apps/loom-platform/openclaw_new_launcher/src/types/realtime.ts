export const REALTIME_EVENT_SCHEMA = 'loom.realtime.event.v1' as const;

export type RealtimeStreamTopic = 'agent' | 'matrix';

export interface LoomRealtimeEvent<TData extends Record<string, unknown> = Record<string, unknown>> {
  schema: typeof REALTIME_EVENT_SCHEMA;
  eventId: string;
  seq: number;
  timestamp: string;
  topic: string;
  entityId: string;
  type: string;
  data: TData;
}

export interface StreamTicketRequest {
  topic: RealtimeStreamTopic;
  resource: string;
}

export interface StreamTicketResponse {
  ticket: string;
  expiresAt: string;
  streamUrl?: string;
}

export type RealtimeQueryValue = string | number | boolean | null | undefined;

export interface RealtimeSequenceGap {
  topic: RealtimeStreamTopic;
  committedSeq: number;
  expectedSeq: number;
  receivedSeq: number;
  eventId: string;
}

export type RealtimeConnectionStatus = 'connecting' | 'connected' | 'reconnecting';

export interface RealtimeConnectionState {
  status: RealtimeConnectionStatus;
  attempt: number;
  error?: string;
}

export interface OpenRealtimeStreamOptions {
  topic: RealtimeStreamTopic;
  afterSeq?: number;
  signal: AbortSignal;
  query?: Record<string, RealtimeQueryValue>;
  onEvent: (event: LoomRealtimeEvent) => void | Promise<void>;
  onSequenceGap?: (gap: RealtimeSequenceGap) => number | void | Promise<number | void>;
  onConnectionState?: (state: RealtimeConnectionState) => void;
}
