import { showConfirm } from '../common';
import { capabilityActionLabel } from './agentViewModel';

interface AgentApprovalCardProps {
  data: Record<string, unknown>;
  busy?: boolean;
  onResolve: (approvalId: string, decision: 'approve' | 'reject') => Promise<void>;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value ? value : fallback;
}

const riskLabels: Record<string, string> = {
  outbound: '外发操作',
  critical: '高风险操作',
};

const statusLabels: Record<string, string> = {
  pending: '等待审批',
  approved: '已批准',
  rejected: '已拒绝',
  expired: '已过期',
  consumed: '已执行',
};

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && Boolean(item)) : [];
}

function scopeSummary(value: unknown): string {
  const targets = record(value);
  const deviceIds = stringList(targets.deviceIds);
  const groups = stringList(targets.groups);
  if (deviceIds.length) return `${deviceIds.length} 台设备`;
  if (groups.length) return `${groups.length} 个设备组`;
  if (targets.allOnline === true) return '全部在线设备';
  return '当前任务范围';
}

function displayTime(value: unknown): string {
  const raw = text(value);
  if (!raw) return '';
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? '本次审批有效期内' : date.toLocaleString('zh-CN', { hour12: false });
}

export function AgentApprovalCard({ data, busy, onResolve }: AgentApprovalCardProps) {
  const approval = Object.keys(record(data.approval)).length ? record(data.approval) : data;
  const approvalId = text(approval.approvalId);
  const status = text(approval.status, 'pending');
  const risk = text(approval.risk, 'outbound');
  const pending = status === 'pending';
  const targetSummary = scopeSummary(approval.targets);
  const operationLabel = capabilityActionLabel(approval.capability).replace(/^正在/, '');

  const approve = async () => {
    if (risk === 'critical') {
      const confirmed = await showConfirm({
        title: '确认高风险操作',
        message: `${text(approval.actionSummary, '执行高风险操作')}\n范围：${targetSummary}`,
        confirmText: '确认批准',
        tone: 'danger',
      });
      if (!confirmed) return;
    }
    await onResolve(approvalId, 'approve');
  };

  return (
    <section className="rounded-[8px] border border-status-warning/35 bg-status-warning/10 p-4" data-agent-approval={approvalId}>
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] border border-status-warning/35 bg-surface font-black text-status-warning">!</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-black text-text">需要审批</h3>
            <span className="rounded-[5px] border border-status-warning/30 px-1.5 py-0.5 text-[10px] font-bold text-status-warning">{riskLabels[risk] || '受控操作'}</span>
            {!pending ? <span className="text-[11px] font-bold text-text-muted">{statusLabels[status] || '审批已处理'}</span> : null}
          </div>
          <p className="mt-2 text-sm font-semibold leading-5 text-text">{text(approval.actionSummary, '等待确认的操作')}</p>
          <dl className="mt-2 grid gap-1 text-[11px] leading-5 text-text-muted sm:grid-cols-2">
            <div><dt className="inline font-bold text-text-subtle">操作：</dt><dd className="inline">{operationLabel}</dd></div>
            <div><dt className="inline font-bold text-text-subtle">范围：</dt><dd className="inline">{targetSummary}</dd></div>
            <div className="sm:col-span-2"><dt className="inline font-bold text-text-subtle">原因：</dt><dd className="inline">{text(approval.riskReason, '策略要求人工审批')}</dd></div>
            {approval.expiresAt ? <div className="sm:col-span-2"><dt className="inline font-bold text-text-subtle">有效期：</dt><dd className="inline">{displayTime(approval.expiresAt)}</dd></div> : null}
          </dl>
          {pending ? (
            <div className="mt-3 flex gap-2">
              <button type="button" disabled={busy || !approvalId} onClick={() => void approve()} className="rounded-[7px] border border-accent/40 bg-accent px-3 py-1.5 text-xs font-bold text-accent-ink disabled:opacity-50">批准</button>
              <button type="button" disabled={busy || !approvalId} onClick={() => void onResolve(approvalId, 'reject')} className="rounded-[7px] border border-status-danger/30 bg-status-danger/10 px-3 py-1.5 text-xs font-bold text-status-danger disabled:opacity-50">拒绝</button>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
