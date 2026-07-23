import 'tsx/esm';

import assert from 'node:assert/strict';
import { readdir, readFile, stat } from 'node:fs/promises';
import { test } from 'node:test';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as agentWorkbench from './AgentWorkbenchPage.tsx';
import { AgentComposer } from './AgentComposer.tsx';
import { ConversationSidebar } from './ConversationSidebar.tsx';
import { AgentMarkdown } from './messageBlocks.tsx';

const agentDirectory = dirname(fileURLToPath(import.meta.url));
const sourcePaths = [
  ...(await readdir(agentDirectory, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name))
    .map((entry) => join(agentDirectory, entry.name)),
  join(agentDirectory, '..', '..', 'stores', 'agentStore.ts'),
  join(agentDirectory, '..', '..', 'stores', 'agentStore.test.ts'),
];

const utf8 = new TextDecoder('utf-8', { fatal: true });
const mojibakeSignatures = [
  '\uFFFD',
  '\u951F\u65A4\u62F7',
  '\u93C2',
  '\u951B',
  '\u9286',
  '\u9225',
].map((value) => JSON.parse(`"${value}"`) as string);

test('all owned Agent frontend sources are strict UTF-8 without mojibake', async () => {
  for (const path of sourcePaths) {
    const source = utf8.decode(await readFile(path));
    for (const signature of mojibakeSignatures) {
      assert.equal(source.includes(signature), false, `${path} contains mojibake signature ${JSON.stringify(signature)}`);
    }
    assert.doesNotMatch(source, /[\u3400-\u9fff]\?(?=["'`}<])/u, `${path} contains a truncated CJK string`);
  }
});

test('every visible Agent button declares a click handler', async () => {
  const componentPaths = sourcePaths.filter((path) => path.endsWith('.tsx') && !path.endsWith('.test.tsx'));
  for (const path of componentPaths) {
    const source = utf8.decode(await readFile(path));
    const buttonTags = source.matchAll(/<button\b([\s\S]*?)>/g);
    for (const match of buttonTags) {
      assert.match(match[1], /\bonClick\s*=/, `${path} has a button without an onClick handler: ${match[0]}`);
    }
  }
});

test('Agent command buttons route to concrete callbacks', async () => {
  const expectedHandlers: Record<string, RegExp[]> = {
    'ConversationSidebar.tsx': [
      /onClick=\{onNew\}/,
      /onClick=\{\(\) => onSelect\(session\.sessionId\)\}/,
      /onClick=\{\(\) => startRename\(session\)\}/,
      /onClick=\{\(\) => void archive\(session\)\}/,
    ],
    'AgentComposer.tsx': [
      /onClick=\{\(\) => onChange\(\{ attachments:/,
      /onClick=\{\(\) => fileInputRef\.current\?\.click\(\)\}/,
      /onClick=\{onResume\}/,
      /onClick=\{onStop\}/,
      /onClick=\{onSubmit\}/,
    ],
    'AgentApprovalCard.tsx': [/onClick=\{\(\) => void approve\(\)\}/, /onResolve\(approvalId, 'reject'\)/],
    'AgentRunAttachment.tsx': [
      /onOpenWorkbench\(\{ campaignId, deviceId, runId, source: 'agent' \}\)/,
      /onOpenRunDetails\(runId,/,
      /onRunAction\(deviceTaskId, action\)/,
      /onRunAction\(campaignId, 'cancel'\)/,
      /await showConfirm/,
    ],
    'AgentDebugger.tsx': [/onClick=\{closeDebugger\}/, /setSelectedTraceNode\(node\.traceId\)/],
  };

  for (const [fileName, handlers] of Object.entries(expectedHandlers)) {
    const source = utf8.decode(await readFile(join(agentDirectory, fileName)));
    for (const handler of handlers) assert.match(source, handler, `${fileName} is missing handler ${handler}`);
  }
});

test('Agent header leaves conversation creation and run details to their contextual controls', async () => {
  const source = utf8.decode(await readFile(join(agentDirectory, 'AgentHeader.tsx')));

  assert.doesNotMatch(source, /<\/?>/);
  assert.doesNotMatch(source, /新对话/);
  assert.doesNotMatch(source, /onToggleDebugger|onNewSession|debuggerOpen/);
  assert.doesNotMatch(source, /run\.runId/);
});

test('ordinary run summaries never render raw run campaign or device identifiers', async () => {
  const attachment = utf8.decode(await readFile(join(agentDirectory, 'AgentRunAttachment.tsx')));

  assert.doesNotMatch(attachment, /data-agent-matrix-attachment=\{campaignId/);
  assert.doesNotMatch(attachment, /\{campaignId \|\| '等待任务编号'\}/);
  assert.doesNotMatch(attachment, /deviceIds\.join/);
  assert.doesNotMatch(attachment, /\$\{campaignId\}/);
  assert.doesNotMatch(attachment, /证据设备/);
  assert.match(attachment, /矩阵任务/);
});

test('thinking feedback is immediate accessible stable and reduced-motion safe', async () => {
  const source = utf8.decode(await readFile(join(agentDirectory, 'AgentThinkingIndicator.tsx')));
  const styles = utf8.decode(await readFile(join(agentDirectory, '..', '..', 'styles', 'index.css')));

  assert.match(source, /role="status"/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /麓鸣正在思考/);
  assert.match(source, /min-h-/);
  assert.match(source, /loom-agent-waveform/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.loom-agent-waveform > span/);
  assert.doesNotMatch(source, /setTimeout|setInterval/);
});

test('long conversations render every message and contain horizontal overflow', async () => {
  const source = utf8.decode(await readFile(join(agentDirectory, 'ConversationStream.tsx')));

  assert.doesNotMatch(source, /contentVisibility|containIntrinsicSize/);
  assert.match(source, /overflow-x-hidden/);
  assert.match(source, /break-words/);
});

test('Agent visual identity uses a bundled brand mark with restrained status motion', async () => {
  const brand = utf8.decode(await readFile(join(agentDirectory, '..', 'brand', 'LoomBrand.tsx')));
  const header = utf8.decode(await readFile(join(agentDirectory, 'AgentHeader.tsx')));
  const stream = utf8.decode(await readFile(join(agentDirectory, 'ConversationStream.tsx')));
  const thinking = utf8.decode(await readFile(join(agentDirectory, 'AgentThinkingIndicator.tsx')));
  const sidebar = utf8.decode(await readFile(join(agentDirectory, 'ConversationSidebar.tsx')));
  const styles = utf8.decode(await readFile(join(agentDirectory, '..', '..', 'styles', 'index.css')));

  assert.match(brand, /export const LoomAgentMark/);
  assert.match(brand, /new URL\('\.\.\/\.\.\/assets\/luming-logo\.svg', import\.meta\.url\)/);
  assert.match(brand, /const LoomBrandImage/);
  assert.match(brand, /onError=\{\(\) => setFailed\(true\)\}/);
  assert.doesNotMatch(brand, /\/loom-motion\/(?:agent-core-v1|luming-wordmark(?:-light|-gold)?)\.png/);
  assert.equal((await stat(join(agentDirectory, '..', '..', 'assets', 'luming-logo.svg'))).isFile(), true);
  assert.match(brand, /data-agent-executing/);

  assert.match(header, /<LoomAgentMark/);
  assert.match(header, /run\?\.status === 'queued' \|\| run\?\.status === 'running'/);
  assert.match(header, /\blg:flex\b/);
  assert.doesNotMatch(header, /\bxl:flex\b|\bAGT\b/);

  assert.match(stream, /<LoomAgentMark/);
  assert.doesNotMatch(stream, /\bAGT\b/);
  assert.match(thinking, /<LoomAgentMark[^>]*executing/);
  assert.match(thinking, /loom-agent-waveform/);
  assert.doesNotMatch(thinking, /animate-(?:bounce|pulse)/);

  assert.match(styles, /@keyframes loom-agent-wave/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /\.loom-agent-mark--executing/);
  assert.match(styles, /\.loom-agent-waveform/);

  assert.match(sidebar, /Search/);
  assert.match(sidebar, /Plus/);
  assert.match(sidebar, /Pencil/);
  assert.match(sidebar, /Archive/);
  assert.doesNotMatch(sidebar, />\s*[+\u2315\u270e\u25a1]\s*</u);
});

test('brand runtime asset routes always resolve to shipped files', async () => {
  const brandDirectory = join(agentDirectory, '..', 'brand');
  const publicDirectory = join(agentDirectory, '..', '..', '..', 'public');
  const files = await readdir(brandDirectory, { withFileTypes: true });

  for (const file of files.filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name))) {
    const source = utf8.decode(await readFile(join(brandDirectory, file.name)));
    const routes = source.matchAll(/['\"](\/loom-motion\/[^'\"]+)['\"]/g);
    for (const route of routes) {
      const assetPath = join(publicDirectory, ...route[1].slice(1).split('/'));
      assert.equal((await stat(assetPath)).isFile(), true, `${file.name} references a missing bundled asset: ${route[1]}`);
    }
  }
});

test('run details use an opaque contextual debugger and return focus on close', async () => {
  const attachment = utf8.decode(await readFile(join(agentDirectory, 'AgentRunAttachment.tsx')));
  const debuggerSource = utf8.decode(await readFile(join(agentDirectory, 'AgentDebugger.tsx')));
  const workbench = utf8.decode(await readFile(join(agentDirectory, 'AgentWorkbenchPage.tsx')));

  assert.match(attachment, /运行详情/);
  assert.match(attachment, /run && runId/);
  assert.match(debuggerSource, /bg-surface(?:\s|\")/);
  assert.doesNotMatch(debuggerSource, /bg-surface-alt\/95/);
  assert.match(debuggerSource, /event\.key === 'Escape'/);
  assert.match(debuggerSource, /returnFocusRef\.current\?\.focus\(\)/);
  assert.match(debuggerSource, /setTrace\(\[\]\)/);
  assert.match(debuggerSource, /wasOpenRef/);
  assert.match(debuggerSource, /if \(open && !wasOpenRef\.current\)/);
  assert.doesNotMatch(debuggerSource, /panelRef\.current\?\.focus\(\);[\s\S]{0,240}\[closeDebugger, open\]/);
  assert.match(workbench, /const closeRunDetails = useCallback/);
  assert.match(workbench, /onClose=\{closeRunDetails\}/);
});

test('ordinary messages show Chinese actions without raw capability and protocol identifiers', async () => {
  const source = utf8.decode(await readFile(join(agentDirectory, 'messageBlocks.tsx')));
  const approval = utf8.decode(await readFile(join(agentDirectory, 'AgentApprovalCard.tsx')));
  const attachment = utf8.decode(await readFile(join(agentDirectory, 'AgentRunAttachment.tsx')));

  assert.match(source, /capabilityActionLabel/);
  assert.match(source, /userFacingAgentError/);
  assert.doesNotMatch(source, /text\(data\.capability\)|text\(data\.tool\)|text\(error\.code/);
  assert.doesNotMatch(source, /safeSummary\(summary\)/);
  assert.match(approval, /capabilityActionLabel/);
  assert.match(approval, /外发操作/);
  assert.match(approval, /已拒绝/);
  assert.doesNotMatch(approval, /JSON\.stringify\(record\(approval\.targets\)\)|uppercase text-status-warning/);
  assert.match(attachment, /running: '执行中'/);
  assert.doesNotMatch(attachment, />\{status\}<\/span>/);
});

test('agent header localizes runtime credential failures instead of exposing backend text', async () => {
  const source = utf8.decode(await readFile(join(agentDirectory, 'AgentHeader.tsx')));

  assert.match(source, /userFacingAgentError/);
  assert.doesNotMatch(source, /nativeProfile\?\.error\?\.message/);
});

test('Agent text messages render safe semantic Markdown instead of raw syntax', () => {
  const markup = renderToStaticMarkup(React.createElement(AgentMarkdown, {
    value: '# 执行结果\n\n- **设备**：phone-1\n- `状态`：在线\n\n| 项目 | 结果 |\n| --- | --- |\n| 截图 | 完成 |\n\n[安全链接](https://example.com) [危险链接](javascript:alert(1)) <script>alert(2)</script>',
  }));

  assert.match(markup, /<h1/);
  assert.match(markup, /<ul/);
  assert.match(markup, /<strong>设备<\/strong>/);
  assert.match(markup, /<table/);
  assert.match(markup, /href="https:\/\/example\.com"/);
  assert.doesNotMatch(markup, /javascript:|<script/);
  assert.doesNotMatch(markup, /\*\*设备\*\*|\| 项目 \|/);
});

test('Agent realtime status is driven by connection callbacks without a success timer', async () => {
  const source = utf8.decode(await readFile(join(agentDirectory, 'AgentWorkbenchPage.tsx')));

  assert.match(source, /onConnectionState\s*:/, 'AgentWorkbenchPage must subscribe to authoritative connection state');
  assert.match(source, /state\.error/, 'AgentWorkbenchPage must surface realtime connection errors');
  assert.doesNotMatch(source, /connectedTimer/, 'AgentWorkbenchPage must not declare the stream live on a timer');
});

test('failed Agent conversation search preserves valid prior results for retry without leaking them to another query', () => {
  type SearchState = {
    result: { query: string; sessions: Array<{ sessionId: string; title: string }> } | null;
    status: 'idle' | 'loading' | 'error';
    error: string | null;
    errorQuery: string | null;
  };
  const searchApi = agentWorkbench as typeof agentWorkbench & {
    conversationSearchReducer?: (state: SearchState, action: { type: string; query?: string }) => SearchState;
    conversationSearchSessions?: (state: SearchState, query: string) => Array<{ sessionId: string; title: string }>;
    conversationSearchError?: (state: SearchState, query: string) => string | null;
  };
  const reduceSearch = searchApi.conversationSearchReducer;
  const visibleSessions = searchApi.conversationSearchSessions;
  const visibleError = searchApi.conversationSearchError;
  assert.equal(typeof reduceSearch, 'function');
  assert.equal(typeof visibleSessions, 'function');
  assert.equal(typeof visibleError, 'function');
  if (!reduceSearch || !visibleSessions || !visibleError) return;

  const previous: SearchState = {
    result: { query: '客户跟进', sessions: [{ sessionId: 'session-1', title: '周一跟进' }] },
    status: 'idle',
    error: null,
    errorQuery: null,
  };
  const failed = reduceSearch(previous, { type: 'failure', query: '客户跟进' });

  assert.equal(failed.status, 'error');
  assert.equal(failed.error, '搜索失败，请检查网络后重试');
  assert.strictEqual(failed.result, previous.result);
  assert.deepEqual(visibleSessions(failed, '客户跟进'), previous.result?.sessions);
  assert.deepEqual(visibleSessions(failed, '另一条查询'), []);
  assert.equal(visibleError(failed, '客户跟进'), '搜索失败，请检查网络后重试');
  assert.equal(visibleError(failed, '另一条查询'), null);

  const retrying = reduceSearch(failed, { type: 'start' });
  assert.equal(retrying.status, 'loading');
  assert.equal(retrying.error, null);
  assert.strictEqual(retrying.result, previous.result);
});

test('archived Agent conversations disappear immediately, including stale search results', () => {
  type SearchState = {
    result: { query: string; sessions: Array<{ sessionId: string; title: string; status: string }> } | null;
    status: 'idle' | 'loading' | 'error';
    error: string | null;
    errorQuery: string | null;
  };
  const sessionApi = agentWorkbench as typeof agentWorkbench & {
    visibleAgentSessions?: (
      sessions: Array<{ sessionId: string; title: string; status: string }>,
      state: SearchState,
      query: string,
    ) => Array<{ sessionId: string }>;
  };
  assert.equal(typeof sessionApi.visibleAgentSessions, 'function');
  if (!sessionApi.visibleAgentSessions) return;

  const active = { sessionId: 'session-active', title: '继续跟进', status: 'active' };
  const archived = { sessionId: 'session-archived', title: '已经归档', status: 'archived' };
  const searchState: SearchState = {
    result: { query: '跟进', sessions: [active, archived] },
    status: 'idle',
    error: null,
    errorQuery: null,
  };

  assert.deepEqual(
    sessionApi.visibleAgentSessions([active], searchState, '跟进').map((session) => session.sessionId),
    ['session-active'],
  );
});

test('Agent conversation sidebar renders a compact actionable search error instead of zero results', () => {
  const markup = renderToStaticMarkup(React.createElement(
    ConversationSidebar as unknown as React.ComponentType<Record<string, unknown>>,
    {
      sessions: [{
        schema: 'loom.agent.session.v1',
        sessionId: 'session-1',
        title: '上次搜索结果',
        status: 'active',
        runtimeProfileId: 'loom-native',
        createdAt: '2026-07-18T00:00:00.000Z',
        updatedAt: '2026-07-18T00:00:00.000Z',
      }],
      currentSessionId: null,
      query: '客户跟进',
      loading: false,
      error: '搜索失败，请检查网络后重试',
      onRetry: () => undefined,
      onQueryChange: () => undefined,
      onSelect: () => undefined,
      onNew: () => undefined,
      onRename: async () => undefined,
      onArchive: async () => undefined,
    },
  ));

  assert.match(markup, /role="alert"/);
  assert.match(markup, /搜索失败，请检查网络后重试/);
  assert.match(markup, />重试</);
  assert.match(markup, /上次搜索结果/);
  assert.doesNotMatch(markup, /没有匹配的对话/);
});

test('initial Agent session loading really retries with bounded backoff', async () => {
  const source = utf8.decode(await readFile(join(agentDirectory, 'AgentWorkbenchPage.tsx')));

  assert.equal(agentWorkbench.sessionRetryDelayMs(1), 1000);
  assert.equal(agentWorkbench.sessionRetryDelayMs(2), 2000);
  assert.equal(agentWorkbench.sessionRetryDelayMs(20), 8000);
  assert.match(source, /while \(active && !controller\.signal\.aborted\)/);
  assert.match(source, /正在重试/);
  assert.doesNotMatch(source, /catch \(reason\) \{[\s\S]{0,260}setStreamStatus\('reconnecting'\);[\s\S]{0,260}\n\s*return;/);
});

test('Agent startup surfaces structured Bridge errors instead of generic fallbacks', async () => {
  const source = utf8.decode(await readFile(join(agentDirectory, 'AgentWorkbenchPage.tsx')));

  assert.match(source, /import \{ accountApi, agentApi, matrixApi, parseErrorText \} from '\.\.\/\.\.\/services\/api';/);
  assert.match(source, /return parseErrorText\(reason\) \|\| fallback;/);
});

test('Matrix attachment controls use Matrix device-task and campaign operations', async () => {
  const attachment = utf8.decode(await readFile(join(agentDirectory, 'AgentRunAttachment.tsx')));
  const workbench = utf8.decode(await readFile(join(agentDirectory, 'AgentWorkbenchPage.tsx')));

  assert.match(attachment, /matrixApi\.status\(\)/, 'attachment controls must use authoritative Matrix campaign status');
  assert.match(workbench, /matrixApi\.pauseTask\(scopeId\)/);
  assert.match(workbench, /matrixApi\.resumeTask\(scopeId\)/);
  assert.match(workbench, /matrixApi\.cancel\(scopeId\)/);
  assert.doesNotMatch(workbench, /agentApi\[action\]/, 'Matrix controls must not dispatch through Agent run actions');
});

test('Agent composer owns model and scope routing without exposing capability plumbing', async () => {
  const composer = utf8.decode(await readFile(join(agentDirectory, 'AgentComposer.tsx')));
  const modelMenu = utf8.decode(await readFile(join(agentDirectory, 'AgentModelMenu.tsx')));
  const scopeMenu = utf8.decode(await readFile(join(agentDirectory, 'AgentScopeMenu.tsx')));
  const workbench = utf8.decode(await readFile(join(agentDirectory, 'AgentWorkbenchPage.tsx')));

  assert.match(composer, /<AgentModelMenu/);
  assert.match(composer, /<AgentScopeMenu/);
  assert.match(composer, /event\.key === 'Enter' && !event\.shiftKey/);
  assert.match(composer, /<Paperclip/);
  assert.match(composer, /<ArrowUp/);
  assert.match(composer, /<Square/);
  assert.doesNotMatch(composer, /capabilityHints|toggleCapability|splitTargets/);
  assert.doesNotMatch(composer, />\s*设备\s*</);
  assert.doesNotMatch(composer, />\s*设备组\s*</);

  assert.match(modelMenu, /设为麓鸣默认模型/);
  assert.match(modelMenu, /管理模型/);
  assert.match(modelMenu, /跟随默认模型/);
  assert.match(modelMenu, /selectModel\(undefined\)/);
  assert.match(modelMenu, /bg-surface/);
  assert.doesNotMatch(modelMenu, /bg-[^\s"']+\/(?:[1-9]\d?)/);

  assert.match(scopeMenu, /matrixApi\.status\(\)/);
  assert.match(scopeMenu, /自动选择/);
  assert.match(scopeMenu, /全部在线设备/);
  assert.match(scopeMenu, /bg-surface/);

  assert.match(workbench, /scopeMode: outgoing\.scopeMode/);
  assert.match(workbench, /scope: outgoing\.scope/);
  assert.match(workbench, /accountApi\.selectModels/);
  assert.match(workbench, /agentApi\.updateSession\([^,]+, agentModelUpdateRequest\(modelId\)\)/);
  assert.doesNotMatch(workbench, /capabilityHints: outgoing|targets: outgoing/);
});

test('a safely paused Agent run exposes resume and cancel controls', () => {
  const markup = renderToStaticMarkup(React.createElement(AgentComposer, {
    draft: {
      text: '',
      attachments: [],
      scopeMode: 'auto',
      scope: { deviceIds: [], groups: [], allOnline: false },
      runtimeProfileId: 'loom-native',
    },
    session: {
      schema: 'loom.agent.session.v1',
      sessionId: 'session-paused',
      title: 'safe pause',
      status: 'active',
      runtimeProfileId: 'loom-native',
      createdAt: '2026-07-23T00:00:00.000Z',
      updatedAt: '2026-07-23T00:00:00.000Z',
    },
    bootstrap: null,
    running: true,
    paused: true,
    onChange: () => undefined,
    onSubmit: () => undefined,
    onStop: () => undefined,
    onResume: () => undefined,
    onSelectModel: async () => undefined,
    onSetDefaultModel: async () => undefined,
    onManageModels: () => undefined,
  }));

  assert.match(markup, /\u4efb\u52a1\u5df2\u5b89\u5168\u6682\u505c/);
  assert.match(markup, /aria-label="\u7ee7\u7eed\u4efb\u52a1"/);
  assert.match(markup, /aria-label="\u4e2d\u65ad\u4efb\u52a1"/);
});

test('accepted Agent resume is reflected as queued before realtime catches up', () => {
  const afterResumeAccepted = (
    agentWorkbench as typeof agentWorkbench & {
      afterAgentResumeAccepted?: (run: {
        status: string;
        error?: unknown;
      }) => { status: string; error?: unknown };
    }
  ).afterAgentResumeAccepted;

  assert.equal(typeof afterResumeAccepted, 'function');
  if (!afterResumeAccepted) return;
  const resumed = afterResumeAccepted({
    status: 'paused',
    error: { code: 'agent_restart_recovery', recoverable: true },
  });

  assert.equal(resumed.status, 'queued');
  assert.equal(resumed.error, undefined);
});

test('Agent submission retries reuse one clientMessageId and same-tick duplicates allocate nothing', () => {
  type SubmissionCoordinator = {
    begin: (sessionId: string, fingerprint: string) => string | null;
    rebindSession: (fromSessionId: string, toSessionId: string) => void;
    settle: (sessionId: string, succeeded: boolean) => void;
  };
  const createCoordinator = (
    agentWorkbench as typeof agentWorkbench & {
      createAgentSubmissionCoordinator?: (createId: () => string) => SubmissionCoordinator;
    }
  ).createAgentSubmissionCoordinator;

  assert.equal(typeof createCoordinator, 'function');
  if (!createCoordinator) return;

  let allocatedIds = 0;
  const coordinator = createCoordinator(() => `client-message-${++allocatedIds}`);
  const firstAttempt = coordinator.begin('local-session', 'same-draft');
  const duplicateAttempt = coordinator.begin('local-session', 'same-draft');

  assert.equal(firstAttempt, 'client-message-1');
  assert.equal(duplicateAttempt, null);
  assert.equal(allocatedIds, 1);

  coordinator.rebindSession('local-session', 'remote-session');
  coordinator.settle('remote-session', false);
  assert.equal(coordinator.begin('remote-session', 'same-draft'), 'client-message-1');
  assert.equal(allocatedIds, 1);

  coordinator.settle('remote-session', true);
  assert.equal(coordinator.begin('remote-session', 'same-draft'), 'client-message-2');
  assert.equal(allocatedIds, 2);
});

test('Agent sequence gaps resume at the committed cursor and apply the missing event before later events', () => {
  type RealtimeCoordinator = {
    preserveCursor: (sessionId: string, cursor: number) => void;
    cursorFor: (sessionId: string, storeCursor: number) => number;
    accept: (
      sessionId: string,
      event: Record<string, unknown>,
      snapshot: { messages: Array<Record<string, unknown>>; runs: Record<string, Record<string, unknown>> },
    ) => boolean;
  };
  const realtimeApi = agentWorkbench as typeof agentWorkbench & {
    createAgentRealtimeCoordinator?: () => RealtimeCoordinator;
    agentSequenceGapRecoveryCursor?: (gap: { committedSeq: number; receivedSeq: number }) => number;
  };

  assert.equal(typeof realtimeApi.createAgentRealtimeCoordinator, 'function');
  assert.equal(typeof realtimeApi.agentSequenceGapRecoveryCursor, 'function');
  if (!realtimeApi.createAgentRealtimeCoordinator || !realtimeApi.agentSequenceGapRecoveryCursor) return;

  const coordinator = realtimeApi.createAgentRealtimeCoordinator();
  coordinator.preserveCursor('session-gap', 4);
  assert.equal(
    realtimeApi.agentSequenceGapRecoveryCursor({ committedSeq: 4, receivedSeq: 6 }),
    4,
  );

  const applied: number[] = [];
  for (const seq of [5, 6]) {
    const event = {
      schema: 'loom.realtime.event.v1',
      eventId: `event-${seq}`,
      seq,
      timestamp: `2026-07-23T00:00:0${seq}.000Z`,
      topic: 'agent',
      entityId: 'run-gap',
      type: seq === 5 ? 'run.started' : 'run.completed',
      data: { runId: 'run-gap', sessionId: 'session-gap' },
    };
    if (coordinator.accept('session-gap', event, { messages: [], runs: {} })) applied.push(seq);
  }

  assert.deepEqual(applied, [5, 6]);
  assert.equal(coordinator.cursorFor('session-gap', 0), 6);
});

test('Agent terminal snapshots reject replayed deltas and run starts while retaining a nonzero replay cursor', () => {
  type RealtimeCoordinator = {
    preserveCursor: (sessionId: string, cursor: number) => void;
    cursorFor: (sessionId: string, storeCursor: number) => number;
    accept: (
      sessionId: string,
      event: Record<string, unknown>,
      snapshot: { messages: Array<Record<string, unknown>>; runs: Record<string, Record<string, unknown>> },
    ) => boolean;
  };
  const createCoordinator = (
    agentWorkbench as typeof agentWorkbench & {
      createAgentRealtimeCoordinator?: () => RealtimeCoordinator;
    }
  ).createAgentRealtimeCoordinator;

  assert.equal(typeof createCoordinator, 'function');
  if (!createCoordinator) return;

  const coordinator = createCoordinator();
  coordinator.preserveCursor('session-terminal', 80);
  const snapshot = {
    messages: [{ messageId: 'message-terminal', status: 'completed' }],
    runs: { 'run-terminal': { runId: 'run-terminal', status: 'completed' } },
  };
  const oldDelta = {
    eventId: 'old-delta',
    seq: 81,
    entityId: 'run-terminal',
    type: 'message.delta',
    data: { messageId: 'message-terminal', runId: 'run-terminal' },
  };
  const oldRunStarted = {
    eventId: 'old-run-started',
    seq: 82,
    entityId: 'run-terminal',
    type: 'run.started',
    data: { runId: 'run-terminal' },
  };

  assert.equal(coordinator.accept('session-terminal', oldDelta, snapshot), false);
  assert.equal(coordinator.accept('session-terminal', oldRunStarted, snapshot), false);
  assert.equal(coordinator.cursorFor('session-terminal', 0), 82);
});

test('archiving an Agent session cancels its active run before archive and then invokes store cleanup', async () => {
  type ArchiveDependencies = {
    runs: Record<string, Record<string, unknown>>;
    cancelRun: (runId: string) => Promise<{ run: Record<string, unknown> }>;
    archiveRemote: (sessionId: string) => Promise<{ session: Record<string, unknown> }>;
    upsertRun: (run: Record<string, unknown>) => void;
    removeSession: (sessionId: string) => void;
  };
  const archive = (
    agentWorkbench as typeof agentWorkbench & {
      archiveAgentSession?: (
        session: Record<string, unknown>,
        dependencies: ArchiveDependencies,
      ) => Promise<void>;
    }
  ).archiveAgentSession;

  assert.equal(typeof archive, 'function');
  if (!archive) return;

  const operations: string[] = [];
  await archive({
    sessionId: 'session-active',
    status: 'active',
    activeRunId: 'run-active',
  }, {
    runs: {
      'run-active': {
        runId: 'run-active',
        sessionId: 'session-active',
        status: 'running',
      },
    },
    cancelRun: async (runId) => {
      operations.push(`cancel:${runId}`);
      return {
        run: {
          runId,
          sessionId: 'session-active',
          status: 'cancelled',
        },
      };
    },
    archiveRemote: async (sessionId) => {
      operations.push(`archive:${sessionId}`);
      return { session: { sessionId, status: 'archived' } };
    },
    upsertRun: (run) => operations.push(`upsert:${String(run.status)}`),
    removeSession: (sessionId) => operations.push(`remove:${sessionId}`),
  });

  assert.deepEqual(operations, [
    'cancel:run-active',
    'upsert:cancelled',
    'archive:session-active',
    'remove:session-active',
  ]);
});

test('archiving refuses to remove an Agent session when active-run cancellation is not terminal', async () => {
  const archive = (
    agentWorkbench as typeof agentWorkbench & {
      archiveAgentSession?: (
        session: Record<string, unknown>,
        dependencies: {
          runs: Record<string, Record<string, unknown>>;
          cancelRun: (runId: string) => Promise<{ run: Record<string, unknown> }>;
          archiveRemote: (sessionId: string) => Promise<{ session: Record<string, unknown> }>;
          upsertRun: (run: Record<string, unknown>) => void;
          removeSession: (sessionId: string) => void;
        },
      ) => Promise<void>;
    }
  ).archiveAgentSession;

  assert.equal(typeof archive, 'function');
  if (!archive) return;

  let archived = false;
  let removed = false;
  await assert.rejects(() => archive({
    sessionId: 'session-still-active',
    status: 'active',
    activeRunId: 'run-still-active',
  }, {
    runs: {
      'run-still-active': {
        runId: 'run-still-active',
        sessionId: 'session-still-active',
        status: 'running',
      },
    },
    cancelRun: async () => ({
      run: {
        runId: 'run-still-active',
        sessionId: 'session-still-active',
        status: 'running',
      },
    }),
    archiveRemote: async (sessionId) => {
      archived = true;
      return { session: { sessionId, status: 'archived' } };
    },
    upsertRun: () => undefined,
    removeSession: () => {
      removed = true;
    },
  }), /active run cancellation did not reach a terminal state/);

  assert.equal(archived, false);
  assert.equal(removed, false);
});
