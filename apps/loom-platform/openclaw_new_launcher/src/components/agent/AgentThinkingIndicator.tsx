import { LoomAgentMark } from '../brand/LoomBrand';

export function AgentThinkingIndicator({ label = '麓鸣正在思考' }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="flex min-h-[32px] items-center gap-2 text-sm text-text-muted"
      data-agent-thinking
    >
      <LoomAgentMark className="h-6 w-6" executing />
      <span className="font-medium">{label}</span>
      <span className="loom-agent-waveform" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
    </div>
  );
}
