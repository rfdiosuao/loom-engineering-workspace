import 'tsx/esm';

import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

import type { AgentSession } from '../types/agent.ts';
import {
  EMPTY_AGENT_DRAFT,
  EMPTY_AGENT_MESSAGES,
  agentDraftFor,
  agentMessagesFor,
  useAgentStore,
} from './agentStore.ts';
import * as agentStoreModule from './agentStore.ts';

function session(sessionId: string): AgentSession {
  return {
    schema: 'loom.agent.session.v1',
    sessionId,
    title: sessionId,
    status: 'active',
    runtimeProfileId: 'default',
    createdAt: '2026-07-16T10:00:00+08:00',
    updatedAt: '2026-07-16T10:00:00+08:00',
  };
}

beforeEach(() => {
  useAgentStore.getState().reset();
});

test('switching sessions preserves independent unsent drafts', () => {
  const store = useAgentStore.getState();
  store.setSessions([session('session_1'), session('session_2')]);
  store.setCurrentSession('session_1');
  store.updateDraft('session_1', {
    text: 'Draft one',
    scopeMode: 'manual',
    scope: { deviceIds: ['P01'], groups: [], allOnline: false },
  });
  store.setCurrentSession('session_2');
  store.updateDraft('session_2', { text: 'Draft two' });

  assert.equal(useAgentStore.getState().drafts.session_1.text, 'Draft one');
  assert.equal(useAgentStore.getState().drafts.session_1.scopeMode, 'manual');
  assert.deepEqual(useAgentStore.getState().drafts.session_1.scope.deviceIds, ['P01']);
  assert.equal(useAgentStore.getState().drafts.session_2.text, 'Draft two');
});

test('empty selectors return stable snapshots for React external-store subscriptions', () => {
  const state = useAgentStore.getState();

  assert.equal(agentMessagesFor(state, null), EMPTY_AGENT_MESSAGES);
  assert.equal(agentMessagesFor(state, 'missing'), EMPTY_AGENT_MESSAGES);
  assert.equal(agentMessagesFor(state, 'missing'), agentMessagesFor(state, 'missing'));
  assert.equal(agentDraftFor(state, null), EMPTY_AGENT_DRAFT);
  assert.equal(agentDraftFor(state, 'missing'), agentDraftFor(state, 'missing'));
});

test('replacing an optimistic session moves its draft and selection to the real session', () => {
  const store = useAgentStore.getState();
  store.upsertSession(session('local_1'));
  store.setCurrentSession('local_1');
  store.updateDraft('local_1', { text: 'Keep this text' });

  store.replaceSession('local_1', session('session_real'));

  const state = useAgentStore.getState();
  assert.equal(state.currentSessionId, 'session_real');
  assert.equal(state.drafts.session_real.text, 'Keep this text');
  assert.equal(state.drafts.local_1, undefined);
});

test('clearing a sent draft restores all composer fields', () => {
  const store = useAgentStore.getState();
  store.updateDraft('session_1', {
    text: 'Send me',
    attachments: [{ name: 'brief.pdf', size: 42, type: 'application/pdf', lastModified: 1 }],
    scopeMode: 'manual',
    scope: { deviceIds: [], groups: ['招聘一组'], allOnline: false },
    runtimeProfileId: 'runtime_1',
  });

  store.clearDraft('session_1');

  assert.deepEqual(useAgentStore.getState().drafts.session_1, EMPTY_AGENT_DRAFT);
});

test('API message acknowledgements upsert in place without resetting the stream cursor', () => {
  const store = useAgentStore.getState();
  const first = {
    schema: 'loom.agent.message.v1' as const,
    messageId: 'message_1',
    sessionId: 'session_1',
    role: 'user' as const,
    status: 'completed' as const,
    blocks: [{ type: 'text' as const, data: { text: 'First' } }],
    createdAt: '2026-07-16T10:00:00+08:00',
  };
  store.setMessages('session_1', [first]);
  store.mergeRealtimeEvent('session_1', {
    schema: 'loom.realtime.event.v1',
    eventId: 'event_1',
    seq: 1,
    timestamp: '2026-07-16T10:00:01+08:00',
    topic: 'agent.run',
    entityId: 'run_1',
    type: 'run.started',
    data: { sessionId: 'session_1', runId: 'run_1' },
  });

  store.upsertMessage({ ...first, blocks: [{ type: 'text', data: { text: 'Updated' } }] });

  const state = useAgentStore.getState();
  assert.equal(state.messagesBySession.session_1.length, 1);
  assert.equal(state.messagesBySession.session_1[0].blocks[0].data.text, 'Updated');
  assert.equal(state.streamCursors.session_1.lastSeq, 1);
});

test('message snapshots and acknowledgements stay in chronological order', () => {
  const store = useAgentStore.getState();
  const later = {
    schema: 'loom.agent.message.v1' as const,
    messageId: 'message_later',
    sessionId: 'session_1',
    role: 'user' as const,
    status: 'completed' as const,
    blocks: [{ type: 'text' as const, data: { text: 'Later' } }],
    createdAt: '2026-07-16T10:00:02+08:00',
  };
  const earlier = {
    ...later,
    messageId: 'message_earlier',
    role: 'assistant' as const,
    blocks: [{ type: 'text' as const, data: { text: 'Earlier' } }],
    createdAt: '2026-07-16T10:00:01+08:00',
  };

  store.setMessages('session_1', [later, earlier]);
  assert.deepEqual(
    useAgentStore.getState().messagesBySession.session_1.map((message) => message.messageId),
    ['message_earlier', 'message_later'],
  );

  store.upsertMessage({ ...later, createdAt: '2026-07-16T10:00:00+08:00' });
  assert.deepEqual(
    useAgentStore.getState().messagesBySession.session_1.map((message) => message.messageId),
    ['message_later', 'message_earlier'],
  );
});

test('terminal realtime events clear the matching session active run', () => {
  for (const status of ['completed', 'failed'] as const) {
    const store = useAgentStore.getState();
    store.reset();
    store.setSessions([{ ...session('session_1'), activeRunId: 'run_1' }]);
    store.upsertRun({
      schema: 'loom.agent.run.v1',
      runId: 'run_1',
      sessionId: 'session_1',
      status: 'running',
      campaignIds: [],
    });

    store.mergeRealtimeEvent('session_1', {
      schema: 'loom.realtime.event.v1',
      eventId: `event_${status}`,
      seq: 1,
      timestamp: '2026-07-16T10:00:01+08:00',
      topic: 'agent.run',
      entityId: 'run_1',
      type: `run.${status}`,
      data: { sessionId: 'session_1', runId: 'run_1' },
    });

    const state = useAgentStore.getState();
    assert.equal(state.activeRuns.run_1.status, status);
    assert.equal(state.sessions[0].activeRunId, undefined);
  }
});

test('send runtime selection follows the current session instead of a stale draft profile', () => {
  const runtimeFor = (agentStoreModule as unknown as {
    agentRuntimeProfileFor?: (
      state: ReturnType<typeof useAgentStore.getState>,
      sessionId: string | null,
      fallback?: string,
    ) => string | undefined;
  }).agentRuntimeProfileFor;
  assert.equal(typeof runtimeFor, 'function');
  if (!runtimeFor) return;
  const store = useAgentStore.getState();
  store.setSessions([{ ...session('session_1'), runtimeProfileId: 'session-runtime' }]);
  store.updateDraft('session_1', { runtimeProfileId: 'stale-draft-runtime' });

  assert.equal(runtimeFor(useAgentStore.getState(), 'session_1', 'fallback-runtime'), 'session-runtime');
});

test('resolved approvals update matching cards in place immediately', () => {
  const store = useAgentStore.getState();
  store.setMessages('session_1', [{
    schema: 'loom.agent.message.v1',
    messageId: 'message_approval',
    sessionId: 'session_1',
    role: 'assistant',
    status: 'streaming',
    blocks: [{
      type: 'approval',
      data: { approvalId: 'approval_1', status: 'pending', actionSummary: 'Send message' },
    }],
    createdAt: '2026-07-16T10:00:00+08:00',
  }]);
  const applyResolvedApproval = (store as unknown as {
    applyResolvedApproval?: (approval: Record<string, unknown>) => void;
  }).applyResolvedApproval;
  assert.equal(typeof applyResolvedApproval, 'function');
  if (!applyResolvedApproval) return;

  applyResolvedApproval({ approvalId: 'approval_1', status: 'rejected', decision: 'rejected' });

  const state = useAgentStore.getState();
  assert.equal(state.messagesBySession.session_1[0].status, 'completed');
  assert.deepEqual(state.messagesBySession.session_1[0].blocks[0].data, {
    approvalId: 'approval_1',
    status: 'rejected',
    actionSummary: 'Send message',
    decision: 'rejected',
  });
});
