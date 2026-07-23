import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { accountApi, agentApi, matrixApi, parseErrorText } from '../../services/api';
import { openRealtimeStream } from '../../services/realtimeStream';
import type {
  AgentBootstrapResponse,
  AgentMessage,
  AgentRun,
  AgentSession,
} from '../../types/agent';
import type { RealtimeSequenceGap } from '../../types/realtime';
import type { FeatureNavigationContext } from '../../stores/appStore';
import { useAppStore } from '../../stores/appStore';
import {
  agentDraftFor,
  agentMessagesFor,
  type AgentDraft,
  useAgentStore,
} from '../../stores/agentStore';
import { showToast } from '../common';
import { AgentComposer } from './AgentComposer';
import { AgentDebugger } from './AgentDebugger';
import { AgentHeader } from './AgentHeader';
import { ConversationSidebar } from './ConversationSidebar';
import { ConversationStream } from './ConversationStream';
import { agentModelUpdateRequest, selectCurrentAgentRun } from './agentViewModel';

type StreamStatus = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'error';

interface ConversationSearchState {
  result: { query: string; sessions: AgentSession[] } | null;
  status: 'idle' | 'loading' | 'error';
  error: string | null;
  errorQuery: string | null;
}

type ConversationSearchAction =
  | { type: 'reset' }
  | { type: 'start' }
  | { type: 'success'; query: string; sessions: AgentSession[] }
  | { type: 'failure'; query: string };

const initialConversationSearchState: ConversationSearchState = {
  result: null,
  status: 'idle',
  error: null,
  errorQuery: null,
};

export function conversationSearchReducer(
  state: ConversationSearchState,
  action: ConversationSearchAction,
): ConversationSearchState {
  if (action.type === 'reset') return initialConversationSearchState;
  if (action.type === 'start') return { ...state, status: 'loading', error: null, errorQuery: null };
  if (action.type === 'failure') {
    return {
      ...state,
      status: 'error',
      error: '搜索失败，请检查网络后重试',
      errorQuery: action.query,
    };
  }
  return {
    result: { query: action.query, sessions: action.sessions },
    status: 'idle',
    error: null,
    errorQuery: null,
  };
}

export function conversationSearchSessions(state: ConversationSearchState, query: string): AgentSession[] {
  return state.result?.query === query.trim() ? state.result.sessions : [];
}

export function conversationSearchError(state: ConversationSearchState, query: string): string | null {
  return state.errorQuery === query.trim() ? state.error : null;
}

export function visibleAgentSessions(
  sessions: AgentSession[],
  searchState: ConversationSearchState,
  query: string,
): AgentSession[] {
  const activeIds = new Set(
    sessions.filter((session) => session.status === 'active').map((session) => session.sessionId),
  );
  const source = query.trim() ? conversationSearchSessions(searchState, query) : sessions;
  return source.filter((session) => session.status === 'active' && activeIds.has(session.sessionId));
}

function localId(): string {
  const id = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}_${Math.random().toString(16).slice(2)}`;
  return `local_agent_${id}`;
}

function clientMessageId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `message_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

interface PendingAgentSubmission {
  clientMessageId: string;
  fingerprint: string;
}

export interface AgentSubmissionCoordinator {
  begin: (sessionId: string, fingerprint: string) => string | null;
  rebindSession: (fromSessionId: string, toSessionId: string) => void;
  settle: (sessionId: string, succeeded: boolean) => void;
}

export function createAgentSubmissionCoordinator(
  createId: () => string = clientMessageId,
): AgentSubmissionCoordinator {
  const pendingBySession = new Map<string, PendingAgentSubmission>();
  let activeSessionId: string | null = null;

  return {
    begin: (sessionId, fingerprint) => {
      if (activeSessionId !== null) return null;
      activeSessionId = sessionId;
      const pending = pendingBySession.get(sessionId);
      if (pending?.fingerprint === fingerprint) return pending.clientMessageId;
      const next = { clientMessageId: createId(), fingerprint };
      pendingBySession.set(sessionId, next);
      return next.clientMessageId;
    },
    rebindSession: (fromSessionId, toSessionId) => {
      if (fromSessionId === toSessionId) return;
      const pending = pendingBySession.get(fromSessionId);
      if (pending) {
        pendingBySession.set(toSessionId, pending);
        pendingBySession.delete(fromSessionId);
      }
      if (activeSessionId === fromSessionId) activeSessionId = toSessionId;
    },
    settle: (sessionId, succeeded) => {
      if (succeeded) pendingBySession.delete(sessionId);
      activeSessionId = null;
    },
  };
}

function agentSubmissionFingerprint(draft: AgentDraft): string {
  return JSON.stringify({
    text: draft.text.trim(),
    attachments: draft.attachments,
    scopeMode: draft.scopeMode,
    scope: draft.scope,
    runtimeProfileId: 'loom-native',
  });
}

interface AgentRealtimeEventLike {
  eventId?: unknown;
  seq?: unknown;
  entityId?: unknown;
  type?: unknown;
  data?: unknown;
}

interface AgentRealtimeSnapshotLike {
  messages: ReadonlyArray<Pick<AgentMessage, 'messageId' | 'status'> | Record<string, unknown>>;
  runs: Record<string, Pick<AgentRun, 'runId' | 'status'> | Record<string, unknown>>;
}

export interface AgentRealtimeCoordinator {
  preserveCursor: (sessionId: string, cursor: number) => void;
  cursorFor: (sessionId: string, storeCursor: number) => number;
  accept: (
    sessionId: string,
    event: AgentRealtimeEventLike,
    snapshot: AgentRealtimeSnapshotLike,
  ) => boolean;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function terminalRunStatus(status: unknown): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled';
}

function shouldApplyAgentRealtimeEvent(
  event: AgentRealtimeEventLike,
  snapshot: AgentRealtimeSnapshotLike,
): boolean {
  const type = stringValue(event.type);
  const data = recordValue(event.data);
  const nestedRun = recordValue(data.run);
  const entityId = stringValue(event.entityId);
  const runId = stringValue(nestedRun.runId) || stringValue(data.runId) || entityId;
  const existingRun = runId ? snapshot.runs[runId] : undefined;

  if (type === 'message.delta') {
    const messageId = stringValue(data.messageId) || (entityId ? `${entityId}:message` : '');
    const existingMessage = messageId
      ? snapshot.messages.find((message) => message.messageId === messageId)
      : undefined;
    if (existingMessage && existingMessage.status !== 'streaming') return false;
    if (existingRun && terminalRunStatus(existingRun.status)) return false;
  }

  if (
    existingRun
    && terminalRunStatus(existingRun.status)
    && (
      type === 'run.queued'
      || type === 'run.started'
      || type === 'run.running'
      || type === 'run.waiting_approval'
      || type === 'run.paused'
      || type === 'run.resumed'
    )
  ) {
    return false;
  }

  return true;
}

export function createAgentRealtimeCoordinator(): AgentRealtimeCoordinator {
  const cursors = new Map<string, number>();
  const preserveCursor = (sessionId: string, cursor: number) => {
    const normalized = Number.isSafeInteger(cursor) ? Math.max(0, cursor) : 0;
    cursors.set(sessionId, Math.max(cursors.get(sessionId) || 0, normalized));
  };

  return {
    preserveCursor,
    cursorFor: (sessionId, storeCursor) => (
      Math.max(cursors.get(sessionId) || 0, Number.isSafeInteger(storeCursor) ? storeCursor : 0)
    ),
    accept: (sessionId, event, snapshot) => {
      const seq = Number(event.seq);
      const currentCursor = cursors.get(sessionId) || 0;
      if (!Number.isSafeInteger(seq) || seq <= currentCursor) return false;
      preserveCursor(sessionId, seq);
      return shouldApplyAgentRealtimeEvent(event, snapshot);
    },
  };
}

export function agentSequenceGapRecoveryCursor(
  gap: Pick<RealtimeSequenceGap, 'committedSeq' | 'receivedSeq'>,
): number {
  return gap.committedSeq;
}

interface ArchivableAgentSession {
  sessionId: string;
  status?: unknown;
  activeRunId?: string;
}

interface ArchivableAgentRun {
  runId?: unknown;
  sessionId?: unknown;
  status?: unknown;
}

interface ArchiveAgentSessionDependencies {
  runs: Record<string, ArchivableAgentRun>;
  cancelRun: (runId: string) => Promise<{ run: ArchivableAgentRun }>;
  archiveRemote: (sessionId: string) => Promise<{ session: ArchivableAgentSession }>;
  upsertRun: (run: ArchivableAgentRun) => void;
  removeSession: (sessionId: string) => void;
}

export async function archiveAgentSession(
  session: ArchivableAgentSession,
  dependencies: ArchiveAgentSessionDependencies,
): Promise<void> {
  const activeRun = (
    session.activeRunId
      ? dependencies.runs[session.activeRunId] || { runId: session.activeRunId, status: 'running' }
      : Object.values(dependencies.runs).find((run) => (
        run.sessionId === session.sessionId && !terminalRunStatus(run.status)
      ))
  );
  const activeRunId = stringValue(activeRun?.runId);
  if (activeRunId && !terminalRunStatus(activeRun?.status)) {
    const response = await dependencies.cancelRun(activeRunId);
    dependencies.upsertRun(response.run);
    if (!terminalRunStatus(response.run.status)) {
      throw new Error('active run cancellation did not reach a terminal state');
    }
  }

  if (!session.sessionId.startsWith('local_agent_')) {
    const response = await dependencies.archiveRemote(session.sessionId);
    if (response.session.status !== 'archived') throw new Error('归档状态未生效');
  }
  dependencies.removeSession(session.sessionId);
}

function errorMessage(reason: unknown, fallback: string): string {
  return parseErrorText(reason) || fallback;
}

function isTerminalRun(run: AgentRun): boolean {
  return run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled';
}

export function afterAgentResumeAccepted(run: AgentRun): AgentRun {
  if (run.status !== 'paused') return run;
  return { ...run, status: 'queued', error: undefined };
}

export function sessionRetryDelayMs(attempt: number): number {
  return Math.min(1000 * (2 ** Math.max(0, attempt - 1)), 8000);
}

export function AgentWorkbenchPage() {
  const sessions = useAgentStore((state) => state.sessions);
  const currentSessionId = useAgentStore((state) => state.currentSessionId);
  const messages = useAgentStore((state) => agentMessagesFor(state, currentSessionId));
  const activeRuns = useAgentStore((state) => state.activeRuns);
  const draft = useAgentStore((state) => agentDraftFor(state, currentSessionId));
  const debuggerOpen = useAgentStore((state) => state.debuggerOpen);
  const openFeature = useAppStore((state) => state.openFeature);

  const [bootstrap, setBootstrap] = useState<AgentBootstrapResponse | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [conversationLoading, setConversationLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [searchState, dispatchSearch] = useReducer(conversationSearchReducer, initialConversationSearchState);
  const [searchRequestVersion, setSearchRequestVersion] = useState(0);
  const [sending, setSending] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>('idle');
  const [traceRefreshToken, setTraceRefreshToken] = useState(0);
  const [debuggerRunId, setDebuggerRunId] = useState<string | null>(null);
  const pendingCreatesRef = useRef(new Map<string, Promise<string>>());
  const submissionCoordinatorRef = useRef<AgentSubmissionCoordinator | null>(null);
  const realtimeCoordinatorRef = useRef<AgentRealtimeCoordinator | null>(null);
  const debuggerReturnFocusRef = useRef<HTMLElement | null>(null);
  if (!submissionCoordinatorRef.current) {
    submissionCoordinatorRef.current = createAgentSubmissionCoordinator();
  }
  if (!realtimeCoordinatorRef.current) {
    realtimeCoordinatorRef.current = createAgentRealtimeCoordinator();
  }

  const currentSession = sessions.find((session) => session.sessionId === currentSessionId) || null;
  const currentRun = useMemo(
    () => selectCurrentAgentRun(currentSessionId, currentSession?.activeRunId, activeRuns),
    [activeRuns, currentSession?.activeRunId, currentSessionId],
  );
  const debuggerRun = debuggerRunId ? activeRuns[debuggerRunId] || null : null;

  useEffect(() => {
    useAgentStore.getState().setDebuggerOpen(false);
    setDebuggerRunId(null);
    debuggerReturnFocusRef.current = null;
  }, [currentSessionId]);

  useEffect(() => {
    let active = true;
    void Promise.allSettled([agentApi.bootstrap(), agentApi.sessions({ limit: 100 })]).then(([bootstrapResult, sessionsResult]) => {
      if (!active) return;
      if (bootstrapResult.status === 'fulfilled') setBootstrap(bootstrapResult.value);
      else showToast(errorMessage(bootstrapResult.reason, '智能体状态读取失败'), 'error');
      if (sessionsResult.status === 'fulfilled') useAgentStore.getState().setSessions(sessionsResult.value.sessions);
      else showToast(errorMessage(sessionsResult.reason, '会话列表读取失败'), 'error');
      setInitialLoading(false);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const normalized = query.trim();
    if (!normalized) {
      dispatchSearch({ type: 'reset' });
      return;
    }
    let active = true;
    dispatchSearch({ type: 'start' });
    const timeout = window.setTimeout(() => {
      void agentApi.sessions({ query: normalized, limit: 100 }).then((response) => {
        if (active) dispatchSearch({ type: 'success', query: normalized, sessions: response.sessions });
      }).catch(() => {
        if (active) dispatchSearch({ type: 'failure', query: normalized });
      });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [query, searchRequestVersion]);

  useEffect(() => {
    if (!currentSessionId || currentSessionId.startsWith('local_agent_')) {
      setConversationLoading(false);
      setStreamStatus('idle');
      return;
    }
    const controller = new AbortController();
    let active = true;
    let lastConnectionError = '';
    let retryTimer: number | undefined;
    const realtimeCoordinator = realtimeCoordinatorRef.current;
    if (!realtimeCoordinator) return;

    const applySessionDetail = (detail: Awaited<ReturnType<typeof agentApi.session>>) => {
      const store = useAgentStore.getState();
      realtimeCoordinator.preserveCursor(
        currentSessionId,
        store.streamCursors[currentSessionId]?.lastSeq || 0,
      );
      store.upsertSession(detail.session);
      store.setMessages(currentSessionId, detail.messages);
      for (const run of detail.runs || []) store.upsertRun(run);
    };

    const loadAndSubscribe = async () => {
      setConversationLoading(true);
      let loadAttempt = 0;
      while (active && !controller.signal.aborted) {
        try {
          const detail = await agentApi.session(currentSessionId, { limit: 200 });
          if (!active) return;
          applySessionDetail(detail);
          break;
        } catch (reason) {
          if (!active || controller.signal.aborted) return;
          loadAttempt += 1;
          setStreamStatus('reconnecting');
          const message = errorMessage(reason, '对话读取失败');
          if (message !== lastConnectionError) {
            lastConnectionError = message;
            showToast(`${message}，正在重试`, 'error');
          }
          await new Promise<void>((resolve) => {
            retryTimer = window.setTimeout(resolve, sessionRetryDelayMs(loadAttempt));
          });
        }
      }
      if (active) setConversationLoading(false);
      if (!active) return;
      setStreamStatus('connecting');
      const afterSeq = realtimeCoordinator.cursorFor(
        currentSessionId,
        useAgentStore.getState().streamCursors[currentSessionId]?.lastSeq || 0,
      );
      await openRealtimeStream({
        topic: 'agent',
        afterSeq,
        signal: controller.signal,
        query: { sessionId: currentSessionId },
        onEvent: (event) => {
          if (!active) return;
          const store = useAgentStore.getState();
          if (realtimeCoordinator.accept(currentSessionId, event, {
            messages: store.messagesBySession[currentSessionId] || [],
            runs: store.activeRuns,
          })) {
            store.mergeRealtimeEvent(currentSessionId, event);
          }
          setStreamStatus('live');
          setTraceRefreshToken((value) => value + 1);
        },
        onSequenceGap: async (gap) => {
          if (active) setStreamStatus('reconnecting');
          realtimeCoordinator.preserveCursor(currentSessionId, gap.committedSeq);
          try {
            const detail = await agentApi.session(currentSessionId, { limit: 200 });
            if (!active) return;
            applySessionDetail(detail);
            return agentSequenceGapRecoveryCursor(gap);
          } catch (reason) {
            if (active) showToast(errorMessage(reason, '实时状态补收失败，正在重试'), 'error');
            return;
          }
        },
        onConnectionState: (state) => {
          if (!active) return;
          setStreamStatus(state.error ? 'error' : state.status === 'connected' ? 'live' : state.status);
          if (state.status === 'connected') lastConnectionError = '';
          if (state.error && state.error !== lastConnectionError) {
            lastConnectionError = state.error;
            showToast(state.error, 'error');
          }
        },
      });
    };
    void loadAndSubscribe();
    return () => {
      active = false;
      controller.abort();
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [currentSessionId]);

  const ensureRemoteSession = useCallback((sessionId: string): Promise<string> => {
    if (!sessionId.startsWith('local_agent_')) return Promise.resolve(sessionId);
    const pending = pendingCreatesRef.current.get(sessionId);
    if (pending) return pending;
    const state = useAgentStore.getState();
    const optimistic = state.sessions.find((session) => session.sessionId === sessionId);
    const request = agentApi.createSession({
      title: optimistic?.title || '新对话',
      runtimeProfileId: 'loom-native',
    }).then(({ session }) => {
      useAgentStore.getState().replaceSession(sessionId, session);
      pendingCreatesRef.current.delete(sessionId);
      return session.sessionId;
    }).catch((reason: unknown) => {
      pendingCreatesRef.current.delete(sessionId);
      throw reason;
    });
    pendingCreatesRef.current.set(sessionId, request);
    return request;
  }, []);

  const createSession = useCallback(() => {
    const now = new Date().toISOString();
    const sessionId = localId();
    const runtimeProfileId = 'loom-native';
    const session: AgentSession = {
      schema: 'loom.agent.session.v1',
      sessionId,
      title: '新对话',
      status: 'active',
      runtimeProfileId,
      createdAt: now,
      updatedAt: now,
    };
    const store = useAgentStore.getState();
    store.upsertSession(session);
    store.setCurrentSession(sessionId);
    store.updateDraft(sessionId, { runtimeProfileId });
    void ensureRemoteSession(sessionId).catch((reason: unknown) => {
      showToast(`${errorMessage(reason, '新对话创建失败')}，草稿已保留`, 'error');
    });
  }, [ensureRemoteSession]);

  const renameSession = async (session: AgentSession, title: string) => {
    try {
      if (session.sessionId.startsWith('local_agent_')) {
        useAgentStore.getState().upsertSession({ ...session, title, updatedAt: new Date().toISOString() });
        return;
      }
      const response = await agentApi.updateSession(session.sessionId, { title });
      useAgentStore.getState().upsertSession(response.session);
    } catch (reason) {
      showToast(errorMessage(reason, '重命名失败'), 'error');
    }
  };

  const archiveSession = async (session: AgentSession) => {
    try {
      const store = useAgentStore.getState();
      await archiveAgentSession(session, {
        runs: store.activeRuns,
        cancelRun: agentApi.cancel,
        archiveRemote: (sessionId) => agentApi.updateSession(sessionId, { status: 'archived' }),
        upsertRun: (run) => useAgentStore.getState().upsertRun(run as AgentRun),
        removeSession: (sessionId) => useAgentStore.getState().purgeSessionState(sessionId),
      });
    } catch (reason) {
      showToast(errorMessage(reason, '归档失败'), 'error');
    }
  };

  const sendMessage = async () => {
    if (!currentSessionId || sending) return;
    const initialDraft = useAgentStore.getState().drafts[currentSessionId] || draft;
    if (!initialDraft.text.trim() && initialDraft.attachments.length === 0) return;
    const submissionCoordinator = submissionCoordinatorRef.current;
    if (!submissionCoordinator) return;
    const submissionId = submissionCoordinator.begin(
      currentSessionId,
      agentSubmissionFingerprint(initialDraft),
    );
    if (!submissionId) return;
    let submissionSessionId = currentSessionId;
    let succeeded = false;
    setSending(true);
    try {
      const nativeProfile = bootstrap?.runtimeProfiles.find((profile) => profile.runtimeProfileId === 'loom-native');
      if (!nativeProfile?.available) {
        throw new Error(nativeProfile?.error?.message || '麓鸣原生智能体尚未就绪，请先登录模型账号');
      }
      const realSessionId = await ensureRemoteSession(currentSessionId);
      submissionCoordinator.rebindSession(submissionSessionId, realSessionId);
      submissionSessionId = realSessionId;
      const currentState = useAgentStore.getState();
      const outgoing = currentState.drafts[realSessionId] || initialDraft;
      const response = await agentApi.sendMessage(realSessionId, {
        clientMessageId: submissionId,
        text: outgoing.text.trim(),
        attachments: outgoing.attachments.map((attachment) => ({ ...attachment })),
        scopeMode: outgoing.scopeMode,
        scope: outgoing.scope,
        runtimeProfileId: 'loom-native',
      });
      const store = useAgentStore.getState();
      store.upsertMessage(response.message);
      store.upsertRun(response.run);
      const session = store.sessions.find((item) => item.sessionId === realSessionId);
      if (session) store.upsertSession({
        ...session,
        activeRunId: response.run.runId,
        lastMessagePreview: outgoing.text.trim().slice(0, 120),
        updatedAt: new Date().toISOString(),
      });
      store.clearDraft(realSessionId);
      setTraceRefreshToken((value) => value + 1);
      succeeded = true;
    } catch (reason) {
      showToast(`${errorMessage(reason, '发送失败')}，草稿已保留`, 'error');
    } finally {
      submissionCoordinator.settle(submissionSessionId, succeeded);
      setSending(false);
    }
  };

  const selectSessionModel = async (modelId?: string) => {
    if (!currentSessionId) return;
    try {
      const realSessionId = await ensureRemoteSession(currentSessionId);
      const response = await agentApi.updateSession(realSessionId, agentModelUpdateRequest(modelId));
      useAgentStore.getState().upsertSession(response.session);
    } catch (reason) {
      showToast(errorMessage(reason, '当前对话模型切换失败'), 'error');
      throw reason;
    }
  };

  const setDefaultModel = async (modelId: string) => {
    try {
      await accountApi.selectModels({ textModel: modelId });
      setBootstrap((current) => current ? { ...current, defaultModelId: modelId } : current);
      showToast('麓鸣默认模型已更新', 'success');
    } catch (reason) {
      showToast(errorMessage(reason, '默认模型设置失败'), 'error');
      throw reason;
    }
  };

  const stopCurrentRun = async () => {
    if (!currentRun || isTerminalRun(currentRun)) return;
    setBusyKey(currentRun.runId);
    try {
      const response = await agentApi.cancel(currentRun.runId);
      useAgentStore.getState().upsertRun(response.run);
      setTraceRefreshToken((value) => value + 1);
    } catch (reason) {
      showToast(errorMessage(reason, '停止任务失败'), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const resumeCurrentRun = async () => {
    if (!currentRun || currentRun.status !== 'paused') return;
    setBusyKey(currentRun.runId);
    try {
      const response = await agentApi.resume(currentRun.runId);
      useAgentStore.getState().upsertRun(afterAgentResumeAccepted(response.run));
      setTraceRefreshToken((value) => value + 1);
    } catch (reason) {
      showToast(errorMessage(reason, '继续任务失败'), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const matrixAction = async (scopeId: string, action: 'pause' | 'resume' | 'cancel') => {
    const actionLabels = { pause: '暂停', resume: '继续', cancel: '中断' } as const;
    setBusyKey(scopeId);
    try {
      if (action === 'pause') await matrixApi.pauseTask(scopeId);
      if (action === 'resume') await matrixApi.resumeTask(scopeId);
      if (action === 'cancel') await matrixApi.cancel(scopeId);
    } catch (reason) {
      showToast(errorMessage(reason, `${actionLabels[action]}操作失败`), 'error');
      throw reason;
    } finally {
      setBusyKey(null);
    }
  };

  const resolveApproval = async (approvalId: string, decision: 'approve' | 'reject') => {
    setBusyKey(approvalId);
    try {
      const response = await agentApi.resolveApproval(approvalId, { decision });
      const store = useAgentStore.getState();
      store.applyResolvedApproval(response.approval);
      if (response.run) store.upsertRun(response.run);
      setTraceRefreshToken((value) => value + 1);
    } catch (reason) {
      showToast(errorMessage(reason, '审批操作失败'), 'error');
    } finally {
      setBusyKey(null);
    }
  };

  const openWorkbench = (context: FeatureNavigationContext) => openFeature('workbench', context);
  const openRunDetails = useCallback((runId: string, trigger: HTMLButtonElement) => {
    if (!activeRuns[runId]) return;
    debuggerReturnFocusRef.current = trigger;
    setDebuggerRunId(runId);
    const store = useAgentStore.getState();
    store.setSelectedTraceNode(null);
    store.setDebuggerOpen(true);
  }, [activeRuns]);
  const closeRunDetails = useCallback(() => {
    useAgentStore.getState().setDebuggerOpen(false);
  }, []);
  const visibleSessions = visibleAgentSessions(sessions, searchState, query);
  const targetCount = draft.scopeMode === 'manual'
    ? draft.scope.deviceIds.length + draft.scope.groups.length + (draft.scope.allOnline ? 1 : 0)
    : 0;
  const runActive = Boolean(currentRun && !isTerminalRun(currentRun));

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-surface" data-agent-workbench>
      <AgentHeader
        bootstrap={bootstrap}
        run={currentRun}
        targetCount={targetCount}
        streamStatus={streamStatus}
      />
      <div className="relative flex min-h-0 min-w-0 flex-1">
        <ConversationSidebar
          sessions={visibleSessions}
          currentSessionId={currentSessionId}
          query={query}
          loading={initialLoading || searchState.status === 'loading'}
          error={conversationSearchError(searchState, query)}
          onQueryChange={setQuery}
          onRetry={() => setSearchRequestVersion((version) => version + 1)}
          onSelect={(sessionId) => useAgentStore.getState().setCurrentSession(sessionId)}
          onNew={createSession}
          onRename={renameSession}
          onArchive={archiveSession}
        />
        <main className="flex min-w-0 flex-1 flex-col bg-surface">
          <ConversationStream
            messages={messages}
            runs={activeRuns}
            currentRun={currentRun}
            sending={sending}
            loading={conversationLoading}
            busyKey={busyKey}
            onRunAction={matrixAction}
            onOpenRunDetails={openRunDetails}
            onResolveApproval={resolveApproval}
            onOpenWorkbench={openWorkbench}
          />
          <AgentComposer
            draft={draft}
            session={currentSession}
            bootstrap={bootstrap}
            disabled={!currentSession || currentSession.status === 'archived'}
            sending={sending}
            running={runActive}
            paused={currentRun?.status === 'paused'}
            controlBusy={Boolean(currentRun && busyKey === currentRun.runId)}
            onChange={(next) => currentSessionId && useAgentStore.getState().updateDraft(currentSessionId, next)}
            onSubmit={() => void sendMessage()}
            onStop={() => void stopCurrentRun()}
            onResume={() => void resumeCurrentRun()}
            onSelectModel={selectSessionModel}
            onSetDefaultModel={setDefaultModel}
            onManageModels={() => openFeature('models')}
          />
        </main>
        <AgentDebugger
          open={debuggerOpen}
          run={debuggerRun}
          refreshToken={traceRefreshToken}
          returnFocusRef={debuggerReturnFocusRef}
          onClose={closeRunDetails}
        />
      </div>
    </div>
  );
}
