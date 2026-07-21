import { useEffect, useMemo, useState } from 'react';
import { matrixApi } from '../../services/api';
import type { AgentRun } from '../../types/agent';
import type { MatrixCampaign, MatrixDeviceTask } from '../../types/matrix';
import type { FeatureNavigationContext } from '../../stores/appStore';
import { showConfirm } from '../common';
import { normalizeMatrixCampaigns, supportedMatrixTaskActions } from '../matrix/matrixViewModel';

interface AgentRunAttachmentProps {
  data: Record<string, unknown>;
  run?: AgentRun;
  busy?: boolean;
  onRunAction: (runId: string, action: 'pause' | 'resume' | 'cancel') => Promise<void>;
  onOpenRunDetails: (runId: string, trigger: HTMLButtonElement) => void;
  onOpenWorkbench: (context: FeatureNavigationContext) => void;
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function number(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    : [];
}

const CANCELLABLE_TASK_STATUSES = new Set<MatrixDeviceTask['status']>([
  'queued',
  'preflight',
  'running',
  'retrying',
  'paused',
]);

const statusLabels: Record<string, string> = {
  queued: '等待执行',
  preflight: '准备中',
  running: '执行中',
  retrying: '重试中',
  waiting_approval: '等待审批',
  paused: '已暂停',
  completed: '已完成',
  failed: '执行失败',
  needs_human: '需要人工处理',
  cancelled: '已取消',
};

export function AgentRunAttachment({
  data,
  run,
  busy,
  onRunAction,
  onOpenRunDetails,
  onOpenWorkbench,
}: AgentRunAttachmentProps) {
  const campaignId = text(data.campaignId) || strings(data.campaignIds)[0] || run?.campaignIds[0];
  const deviceIds = strings(data.deviceIds);
  const deviceId = text(data.deviceId) || deviceIds[0];
  const runId = text(data.runId) || run?.runId;
  const eventStatus = text(data.status);
  const [campaign, setCampaign] = useState<MatrixCampaign | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const refreshCampaign = async () => {
    if (!campaignId) return;
    const snapshot = await matrixApi.status();
    setCampaign(normalizeMatrixCampaigns(snapshot.campaigns).find((item) => item.campaignId === campaignId) || null);
  };

  useEffect(() => {
    let active = true;
    setCampaign(null);
    if (!campaignId) return () => { active = false; };
    void matrixApi.status().then((snapshot) => {
      if (!active) return;
      setCampaign(normalizeMatrixCampaigns(snapshot.campaigns).find((item) => item.campaignId === campaignId) || null);
    }).catch(() => {
      if (active) setCampaign(null);
    });
    return () => { active = false; };
  }, [campaignId, eventStatus]);

  const scopedTasks = useMemo(() => {
    if (!campaign) return [];
    const scopedDeviceIds = new Set(deviceIds.length ? deviceIds : deviceId ? [deviceId] : []);
    return scopedDeviceIds.size
      ? campaign.deviceTasks.filter((task) => scopedDeviceIds.has(task.deviceId))
      : campaign.deviceTasks;
  }, [campaign, deviceId, deviceIds]);
  const pauseTaskIds = scopedTasks.filter((task) => supportedMatrixTaskActions(task.status).pause).map((task) => task.deviceTaskId);
  const resumeTaskIds = scopedTasks.filter((task) => supportedMatrixTaskActions(task.status).resume).map((task) => task.deviceTaskId);
  const canCancel = scopedTasks.some((task) => CANCELLABLE_TASK_STATUSES.has(task.status));
  const status = campaign?.status || text(data.status) || run?.status || 'running';
  const total = campaign ? scopedTasks.length : number(data.total) || number(data.deviceCount);
  const completed = campaign
    ? scopedTasks.filter((task) => task.status === 'completed').length
    : number(data.completed) + number(data.succeeded);
  const failed = campaign
    ? scopedTasks.filter((task) => task.status === 'failed' || task.status === 'needs_human').length
    : number(data.failed);
  const campaignFailures = scopedTasks
    .filter((task) => task.status === 'failed' || task.status === 'needs_human')
    .map((task) => ({
      deviceId: task.deviceId,
      errorCode: task.failureCode,
      message: task.failureReason || '手机任务执行失败，请打开矩阵工作台查看设备状态。',
    }));
  const eventFailures = records(data.failures).map((item) => ({
    deviceId: text(item.deviceId) || '未知设备',
    errorCode: text(item.errorCode),
    message: text(item.message) || '手机任务执行失败，请打开矩阵工作台查看设备状态。',
  }));
  const failures = campaignFailures.length ? campaignFailures : eventFailures;
  const progress = total > 0 ? Math.min(100, Math.round(((completed + failed) / total) * 100)) : status === 'completed' ? 100 : 0;

  const performTaskAction = async (action: 'pause' | 'resume', deviceTaskIds: string[]) => {
    setActionBusy(true);
    try {
      await Promise.all(deviceTaskIds.map((deviceTaskId) => onRunAction(deviceTaskId, action)));
      await refreshCampaign().catch(() => undefined);
    } catch {
      // AgentWorkbenchPage owns user-facing Matrix action errors.
    } finally {
      setActionBusy(false);
    }
  };

  const cancelCampaign = async () => {
    if (!campaignId) return;
    const accepted = await showConfirm({
      title: '取消任务',
      message: '将取消这次矩阵任务中仍在执行的全部设备任务。',
      confirmText: '确认中断',
      tone: 'danger',
    });
    if (!accepted) return;
    setActionBusy(true);
    try {
      await onRunAction(campaignId, 'cancel');
      await refreshCampaign().catch(() => undefined);
    } catch {
      // AgentWorkbenchPage owns user-facing Matrix action errors.
    } finally {
      setActionBusy(false);
    }
  };

  const controlsBusy = busy || actionBusy;

  return (
    <section className="rounded-[8px] border border-accent/25 bg-accent/[0.07] p-4" data-agent-matrix-attachment="true">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-black text-text">矩阵任务</h3>
            <span className="rounded-[5px] border border-accent/25 bg-surface px-1.5 py-0.5 text-[10px] font-bold text-accent">{statusLabels[status] || '执行中'}</span>
          </div>
          <div className="mt-1 text-[11px] text-text-muted">{total > 0 ? `涉及 ${total} 台设备` : '任务已创建'}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {run && runId ? (
            <button
              type="button"
              onClick={(event) => onOpenRunDetails(runId, event.currentTarget)}
              className="rounded-[7px] border border-border bg-surface px-3 py-1.5 text-xs font-bold text-text hover:bg-hover"
            >
              运行详情
            </button>
          ) : null}
          <button
            type="button"
            disabled={!campaignId}
            onClick={() => campaignId && onOpenWorkbench({ campaignId, deviceId, runId, source: 'agent' })}
            className="rounded-[7px] border border-border bg-surface px-3 py-1.5 text-xs font-bold text-text hover:bg-hover disabled:opacity-50"
          >
            打开工作台
          </button>
        </div>
      </div>

      {total > 0 ? (
        <div className="mt-3">
          <div className="mb-1.5 flex justify-between text-[11px] font-semibold text-text-muted">
            <span>{completed} 完成 / {failed} 失败 / {total} 设备</span>
            <span>{progress}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-alt"><div className="h-full bg-accent transition-[width]" style={{ width: `${progress}%` }} /></div>
        </div>
      ) : null}
      {deviceIds.length && total === 0 ? <div className="mt-2 text-[11px] text-text-muted">涉及 {deviceIds.length} 台设备</div> : null}

      {failures.length ? (
        <div data-agent-matrix-failures className="mt-3 border-t border-status-danger/20 pt-3">
          <div className="text-[11px] font-black text-status-danger">失败原因</div>
          <div className="mt-1.5 grid gap-1.5">
            {failures.map((failure, index) => (
              <div key={`${failure.deviceId}-${index}`} className="rounded-[6px] bg-status-danger/8 px-2.5 py-2 text-[11px] leading-4 text-text">
                <span className="font-black">{failure.deviceId}</span>
                {failure.errorCode ? <span className="ml-1 text-text-muted">{failure.errorCode}</span> : null}
                <div className="mt-0.5 text-text-muted">{failure.message}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {campaign && (pauseTaskIds.length > 0 || resumeTaskIds.length > 0 || canCancel) ? (
        <div className="mt-3 flex gap-2 border-t border-border/70 pt-3">
          {pauseTaskIds.length ? <button type="button" disabled={controlsBusy} onClick={() => void performTaskAction('pause', pauseTaskIds)} className="rounded-[7px] border border-border bg-surface px-2.5 py-1 text-xs font-bold text-text-muted disabled:opacity-50">暂停</button> : null}
          {resumeTaskIds.length ? <button type="button" disabled={controlsBusy} onClick={() => void performTaskAction('resume', resumeTaskIds)} className="rounded-[7px] border border-accent/35 bg-accent/10 px-2.5 py-1 text-xs font-bold text-accent disabled:opacity-50">继续</button> : null}
          {canCancel ? <button type="button" disabled={controlsBusy} onClick={() => void cancelCampaign()} className="rounded-[7px] border border-status-danger/25 bg-status-danger/10 px-2.5 py-1 text-xs font-bold text-status-danger disabled:opacity-50">中断</button> : null}
        </div>
      ) : null}
    </section>
  );
}
