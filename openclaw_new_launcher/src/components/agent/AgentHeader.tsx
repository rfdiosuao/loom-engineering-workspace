import type { AgentBootstrapResponse, AgentRun } from '../../types/agent';
import { LoomAgentMark } from '../brand/LoomBrand';
import { userFacingAgentError } from './agentViewModel';

interface AgentHeaderProps {
  bootstrap: AgentBootstrapResponse | null;
  run: AgentRun | null;
  targetCount: number;
  streamStatus: 'idle' | 'connecting' | 'live' | 'reconnecting' | 'error';
}

const streamLabels: Record<AgentHeaderProps['streamStatus'], string> = {
  idle: '未连接',
  connecting: '连接中',
  live: '实时',
  reconnecting: '重连中',
  error: '连接失败',
};

const runStatusLabels: Record<AgentRun['status'], string> = {
  queued: '等待执行',
  running: '执行中',
  waiting_approval: '等待审批',
  paused: '已暂停',
  completed: '已完成',
  failed: '执行失败',
  cancelled: '已取消',
};

export function AgentHeader({
  bootstrap,
  run,
  targetCount,
  streamStatus,
}: AgentHeaderProps) {
  const nativeProfile = bootstrap?.runtimeProfiles.find((profile) => profile.runtimeProfileId === 'loom-native');
  const nativeState = nativeProfile?.available
    ? '模型已就绪'
    : nativeProfile?.error
      ? userFacingAgentError({ error: nativeProfile.error }).title
      : '等待模型账号';
  const availableCapabilities = bootstrap?.capabilities.filter((capability) => capability.available).length || 0;
  const permissionCount = Object.values(bootstrap?.permissions || {}).filter(Boolean).length;
  const executing = run?.status === 'queued' || run?.status === 'running';

  return (
    <header className="flex min-h-[66px] shrink-0 items-center gap-4 border-b border-border bg-surface px-5 py-3" data-agent-header>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <LoomAgentMark className="h-9 w-9" executing={executing} />
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <h1 className="truncate text-base font-semibold text-text">中枢智能体</h1>
            <span className={`h-2 w-2 shrink-0 rounded-full ${streamStatus === 'live' ? 'bg-status-success' : streamStatus === 'error' ? 'bg-status-danger' : 'bg-status-warning'}`} />
            <span className="shrink-0 text-[11px] font-semibold text-text-subtle">{streamLabels[streamStatus]}</span>
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-2 text-[11px] text-text-muted">
            <span className="truncate">麓鸣原生智能体</span>
            <span aria-hidden="true">/</span>
            <span className="truncate">{nativeState}</span>
            <span aria-hidden="true">/</span>
            <span className="shrink-0">{availableCapabilities} 项能力</span>
            {permissionCount > 0 ? <span className="shrink-0">/ {permissionCount} 项授权</span> : null}
          </div>
        </div>
      </div>

      <div className="hidden items-center gap-2 lg:flex" data-agent-run-badges>
        {run ? (
          <span className="rounded-[6px] border border-border bg-surface-alt/60 px-2.5 py-1 text-[11px] font-medium text-text-muted">
            {runStatusLabels[run.status]}
          </span>
        ) : null}
        {targetCount > 0 ? (
          <span className="rounded-[6px] border border-accent/20 bg-accent/10 px-2.5 py-1 text-[11px] font-medium text-accent">
            {targetCount} 个目标
          </span>
        ) : null}
      </div>
    </header>
  );
}
