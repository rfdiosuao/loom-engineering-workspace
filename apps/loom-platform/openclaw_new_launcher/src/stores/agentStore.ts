import { create } from 'zustand';
import type { AgentApproval, AgentMessage, AgentRun, AgentScope, AgentSession } from '../types/agent';
import type { LoomRealtimeEvent } from '../types/realtime';
import { mergeAgentEvent, normalizeAgentMessages } from '../components/agent/agentViewModel';

export interface AgentAttachmentMetadata {
  name: string;
  size: number;
  type: string;
  lastModified: number;
  content?: string;
  truncated?: boolean;
  contentTruncated?: boolean;
}

export interface AgentDraft {
  text: string;
  attachments: AgentAttachmentMetadata[];
  scopeMode: 'auto' | 'manual';
  scope: AgentScope;
  runtimeProfileId?: string;
}

export const EMPTY_AGENT_DRAFT: AgentDraft = {
  text: '',
  attachments: [],
  scopeMode: 'auto',
  scope: { deviceIds: [], groups: [], allOnline: false },
  runtimeProfileId: undefined,
};

export const EMPTY_AGENT_MESSAGES: AgentMessage[] = [];

interface StreamCursor {
  lastSeq: number;
  seenEventIds: string[];
}

interface AgentState {
  sessions: AgentSession[];
  currentSessionId: string | null;
  messagesBySession: Record<string, AgentMessage[]>;
  activeRuns: Record<string, AgentRun>;
  streamCursors: Record<string, StreamCursor>;
  drafts: Record<string, AgentDraft>;
  debuggerOpen: boolean;
  selectedTraceNodeId: string | null;
  setSessions: (sessions: AgentSession[]) => void;
  upsertSession: (session: AgentSession) => void;
  replaceSession: (optimisticId: string, session: AgentSession) => void;
  removeSession: (sessionId: string) => void;
  setCurrentSession: (sessionId: string | null) => void;
  setMessages: (sessionId: string, messages: AgentMessage[]) => void;
  upsertMessage: (message: AgentMessage) => void;
  upsertRun: (run: AgentRun) => void;
  applyResolvedApproval: (approval: Pick<AgentApproval, 'approvalId' | 'status'> & Partial<AgentApproval>) => void;
  mergeRealtimeEvent: (sessionId: string, event: LoomRealtimeEvent) => void;
  updateDraft: (sessionId: string, draft: Partial<AgentDraft>) => void;
  clearDraft: (sessionId: string) => void;
  setDebuggerOpen: (open: boolean) => void;
  setSelectedTraceNode: (traceId: string | null) => void;
  reset: () => void;
}

function emptyDraft(): AgentDraft {
  return {
    text: '',
    attachments: [],
    scopeMode: 'auto',
    scope: { deviceIds: [], groups: [], allOnline: false },
    runtimeProfileId: undefined,
  };
}

const initialState = {
  sessions: [] as AgentSession[],
  currentSessionId: null as string | null,
  messagesBySession: {} as Record<string, AgentMessage[]>,
  activeRuns: {} as Record<string, AgentRun>,
  streamCursors: {} as Record<string, StreamCursor>,
  drafts: {} as Record<string, AgentDraft>,
  debuggerOpen: false,
  selectedTraceNodeId: null as string | null,
};

function clearTerminalActiveRuns(
  sessions: AgentSession[],
  runs: Record<string, AgentRun>,
): AgentSession[] {
  let changed = false;
  const next = sessions.map((session) => {
    const run = session.activeRunId ? runs[session.activeRunId] : undefined;
    if (!run || (run.status !== 'completed' && run.status !== 'failed' && run.status !== 'cancelled')) {
      return session;
    }
    changed = true;
    return { ...session, activeRunId: undefined };
  });
  return changed ? next : sessions;
}

export const useAgentStore = create<AgentState>((set) => ({
  ...initialState,
  setSessions: (sessions) => set((state) => ({
    sessions,
    currentSessionId: state.currentSessionId && sessions.some((session) => session.sessionId === state.currentSessionId)
      ? state.currentSessionId
      : sessions.find((session) => session.status === 'active')?.sessionId || null,
  })),
  upsertSession: (session) => set((state) => {
    const index = state.sessions.findIndex((item) => item.sessionId === session.sessionId);
    if (index < 0) return { sessions: [session, ...state.sessions] };
    const sessions = [...state.sessions];
    sessions[index] = session;
    return { sessions };
  }),
  replaceSession: (optimisticId, session) => set((state) => {
    const sessions = state.sessions.map((item) => item.sessionId === optimisticId ? session : item);
    const drafts = { ...state.drafts };
    if (drafts[optimisticId]) {
      drafts[session.sessionId] = drafts[optimisticId];
      delete drafts[optimisticId];
    }
    const messagesBySession = { ...state.messagesBySession };
    if (messagesBySession[optimisticId]) {
      messagesBySession[session.sessionId] = messagesBySession[optimisticId];
      delete messagesBySession[optimisticId];
    }
    return {
      sessions,
      drafts,
      messagesBySession,
      currentSessionId: state.currentSessionId === optimisticId ? session.sessionId : state.currentSessionId,
    };
  }),
  removeSession: (sessionId) => set((state) => {
    const sessions = state.sessions.filter((session) => session.sessionId !== sessionId);
    return {
      sessions,
      currentSessionId: state.currentSessionId === sessionId
        ? sessions.find((session) => session.status === 'active')?.sessionId || null
        : state.currentSessionId,
    };
  }),
  setCurrentSession: (currentSessionId) => set({ currentSessionId, selectedTraceNodeId: null }),
  setMessages: (sessionId, messages) => set((state) => ({
    messagesBySession: { ...state.messagesBySession, [sessionId]: normalizeAgentMessages([...messages]) },
    streamCursors: { ...state.streamCursors, [sessionId]: { lastSeq: 0, seenEventIds: [] } },
  })),
  upsertMessage: (message) => set((state) => {
    const messages = state.messagesBySession[message.sessionId] || [];
    const index = messages.findIndex((item) => item.messageId === message.messageId);
    if (index < 0) {
      return {
        messagesBySession: {
          ...state.messagesBySession,
          [message.sessionId]: normalizeAgentMessages([...messages, message]),
        },
      };
    }
    const next = [...messages];
    next[index] = message;
    return {
      messagesBySession: {
        ...state.messagesBySession,
        [message.sessionId]: normalizeAgentMessages(next),
      },
    };
  }),
  upsertRun: (run) => set((state) => {
    const activeRuns = { ...state.activeRuns, [run.runId]: run };
    return {
      activeRuns,
      sessions: clearTerminalActiveRuns(state.sessions, activeRuns),
    };
  }),
  applyResolvedApproval: (approval) => set((state) => ({
    messagesBySession: Object.fromEntries(Object.entries(state.messagesBySession).map(([sessionId, messages]) => [
      sessionId,
      messages.map((message) => {
        let matched = false;
        const blocks = message.blocks.map((block) => {
          if (block.type !== 'approval') return block;
          const nested = block.data.approval && typeof block.data.approval === 'object' && !Array.isArray(block.data.approval)
            ? block.data.approval as Record<string, unknown>
            : null;
          const approvalId = String(nested?.approvalId || block.data.approvalId || '');
          if (approvalId !== approval.approvalId) return block;
          matched = true;
          return nested
            ? { ...block, data: { ...block.data, approval: { ...nested, ...approval } } }
            : { ...block, data: { ...block.data, ...approval } };
        });
        return matched ? { ...message, status: 'completed' as const, blocks } : message;
      }),
    ])),
  })),
  mergeRealtimeEvent: (sessionId, event) => set((state) => {
    const cursor = state.streamCursors[sessionId] || { lastSeq: 0, seenEventIds: [] };
    const merged = mergeAgentEvent({
      messages: state.messagesBySession[sessionId] || [],
      runs: state.activeRuns,
      lastSeq: cursor.lastSeq,
      seenEventIds: cursor.seenEventIds,
    }, event, sessionId);
    if (merged.lastSeq === cursor.lastSeq) return state;
    return {
      messagesBySession: { ...state.messagesBySession, [sessionId]: merged.messages },
      activeRuns: merged.runs,
      sessions: clearTerminalActiveRuns(state.sessions, merged.runs),
      streamCursors: {
        ...state.streamCursors,
        [sessionId]: { lastSeq: merged.lastSeq, seenEventIds: merged.seenEventIds },
      },
    };
  }),
  updateDraft: (sessionId, draft) => set((state) => {
    const current = state.drafts[sessionId] || emptyDraft();
    return {
      drafts: {
        ...state.drafts,
        [sessionId]: {
          ...current,
          ...draft,
          scope: draft.scope ? { ...current.scope, ...draft.scope } : current.scope,
        },
      },
    };
  }),
  clearDraft: (sessionId) => set((state) => ({
    drafts: { ...state.drafts, [sessionId]: emptyDraft() },
  })),
  setDebuggerOpen: (debuggerOpen) => set({ debuggerOpen }),
  setSelectedTraceNode: (selectedTraceNodeId) => set({ selectedTraceNodeId }),
  reset: () => set({
    sessions: [],
    currentSessionId: null,
    messagesBySession: {},
    activeRuns: {},
    streamCursors: {},
    drafts: {},
    debuggerOpen: false,
    selectedTraceNodeId: null,
  }),
}));

export function agentDraftFor(state: Pick<AgentState, 'drafts'>, sessionId: string | null): AgentDraft {
  return sessionId ? state.drafts[sessionId] || EMPTY_AGENT_DRAFT : EMPTY_AGENT_DRAFT;
}

export function agentMessagesFor(
  state: Pick<AgentState, 'messagesBySession'>,
  sessionId: string | null,
): AgentMessage[] {
  return sessionId ? state.messagesBySession[sessionId] || EMPTY_AGENT_MESSAGES : EMPTY_AGENT_MESSAGES;
}

export function agentRuntimeProfileFor(
  state: Pick<AgentState, 'sessions'>,
  sessionId: string | null,
  fallback?: string,
): string | undefined {
  const runtimeProfileId = sessionId
    ? state.sessions.find((session) => session.sessionId === sessionId)?.runtimeProfileId.trim()
    : '';
  return runtimeProfileId || fallback;
}
