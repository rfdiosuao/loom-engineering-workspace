import { useEffect, useRef } from 'react';
import type { AgentMessage, AgentRun } from '../../types/agent';
import type { FeatureNavigationContext } from '../../stores/appStore';
import { LoomAgentMark } from '../brand/LoomBrand';
import { shouldShowThinking, thinkingStatusLabel } from './agentViewModel';
import { AgentThinkingIndicator } from './AgentThinkingIndicator';
import { MessageBlockView, ToolExecutionGroup } from './messageBlocks';

interface ConversationStreamProps {
  messages: AgentMessage[];
  runs: Record<string, AgentRun>;
  currentRun: AgentRun | null;
  sending: boolean;
  loading?: boolean;
  busyKey: string | null;
  onRunAction: (runId: string, action: 'pause' | 'resume' | 'cancel') => Promise<void>;
  onOpenRunDetails: (runId: string, trigger: HTMLButtonElement) => void;
  onResolveApproval: (approvalId: string, decision: 'approve' | 'reject') => Promise<void>;
  onOpenWorkbench: (context: FeatureNavigationContext) => void;
}

const roleLabels: Record<AgentMessage['role'], string> = {
  user: '你',
  assistant: 'LOOM',
  system: '系统',
  tool: '执行过程',
};

export function ConversationStream({
  messages,
  runs,
  currentRun,
  sending,
  loading,
  busyKey,
  onRunAction,
  onOpenRunDetails,
  onResolveApproval,
  onOpenWorkbench,
}: ConversationStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const shouldFollowRef = useRef(true);
  const thinking = shouldShowThinking(messages, currentRun, sending);
  const thinkingLabel = thinkingStatusLabel(messages, currentRun);

  useEffect(() => {
    const container = scrollRef.current;
    if (container && shouldFollowRef.current) container.scrollTop = container.scrollHeight;
  }, [messages, thinking]);

  return (
    <div
      ref={scrollRef}
      onScroll={(event) => {
        const element = event.currentTarget;
        shouldFollowRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 120;
      }}
      className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto bg-surface px-3 py-5 sm:px-5 sm:py-6"
      data-agent-conversation-stream
    >
      <div className="mx-auto w-full max-w-[920px]">
        {loading ? <div className="py-10 text-center text-sm text-text-muted">正在读取对话...</div> : null}
        {!loading && messages.length === 0 && !thinking ? (
          <div className="flex min-h-[260px] flex-col items-center justify-center text-center">
            <LoomAgentMark className="h-14 w-14" />
            <div className="mt-4 text-base font-semibold text-text">开始一段新对话</div>
          </div>
        ) : null}
        <div className="grid gap-5">
          {messages.map((message) => {
            const renderedToolRuns = new Set<string>();
            return (
              <article
                key={message.messageId}
                className={`agent-message-enter grid min-w-0 gap-2 ${message.role === 'user' ? 'ml-auto w-fit max-w-[78%] justify-self-end' : 'w-full max-w-full'}`}
                data-agent-message={message.messageId}
                data-message-role={message.role}
              >
                {message.role !== 'tool' ? (
                  <div className={`flex items-center gap-2 text-[10px] font-black uppercase ${message.role === 'user' ? 'justify-end' : ''}`}>
                    <span className={message.role === 'user' ? 'text-accent' : 'text-text-subtle'}>{roleLabels[message.role]}</span>
                    {message.status === 'streaming' ? <span className="agent-message-status-dot h-1.5 w-1.5 rounded-full bg-status-success" title="正在生成" /> : null}
                    {message.status === 'failed' ? <span className="text-status-danger">失败</span> : null}
                  </div>
                ) : null}
                <div className={`grid min-w-0 break-words [overflow-wrap:anywhere] gap-3 ${message.role === 'user' ? 'rounded-[8px] border border-accent/25 bg-accent/10 px-4 py-3' : ''}`}>
                  {message.blocks.map((block, index) => {
                    const isLifecycleTool = block.type === 'tool' && !Array.isArray(block.data.attachments);
                    if (isLifecycleTool) {
                      const runId = typeof block.data.runId === 'string' ? block.data.runId : message.messageId;
                      if (renderedToolRuns.has(runId)) return null;
                      renderedToolRuns.add(runId);
                      const groupedBlocks = message.blocks.filter((candidate) => (
                        candidate.type === 'tool'
                        && !Array.isArray(candidate.data.attachments)
                        && (typeof candidate.data.runId === 'string' ? candidate.data.runId : message.messageId) === runId
                      ));
                      return (
                        <ToolExecutionGroup
                          key={`${message.messageId}-tool-group-${runId}`}
                          blocks={groupedBlocks}
                          run={runs[runId]}
                        />
                      );
                    }
                    return (
                      <MessageBlockView
                        key={`${message.messageId}-${block.type}-${index}`}
                        block={block}
                        runs={runs}
                        busyKey={busyKey}
                        onRunAction={onRunAction}
                        onOpenRunDetails={onOpenRunDetails}
                        onResolveApproval={onResolveApproval}
                        onOpenWorkbench={onOpenWorkbench}
                      />
                    );
                  })}
                </div>
              </article>
            );
          })}
          {thinking ? <AgentThinkingIndicator label={thinkingLabel} /> : null}
        </div>
      </div>
    </div>
  );
}
