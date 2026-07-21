import React from 'react';
import qrcode from 'qrcode-generator';
import {
  acquisitionApi,
  feishuApi,
  matrixApi,
  parseErrorText,
  type AcquisitionSnapshot,
  type FeishuStatus,
  type MatrixDeviceSummary,
  type MatrixStatusSnapshot,
} from '../../services/api';
import { Button, Input, showConfirm, showToast } from '../common';
import { buildMcpJson, buildOneShotAgentPrompt } from '../agentAccess/agentPrompt';

const EMPTY_SNAPSHOT: AcquisitionSnapshot = {
  schema: 'loom.customer_acquisition.v1',
  contentTasks: [],
  leads: [],
  customers: [],
  drafts: [],
  sop: [],
  logs: [],
  stats: {
    contentTasks: 0,
    leads: 0,
    customers: 0,
    draftsPending: 0,
    approvedDrafts: 0,
    pendingSync: 0,
  },
  outboundPolicy: ['draft_only', 'manual_confirm', 'whitelist', 'frequency_cap', 'audit_log'],
  integrations: {
    feishu: {
      cliInstalled: false,
      connected: false,
      pendingCount: 0,
      auth: { loggedIn: false, botReady: false },
      table: {},
      lastSync: {},
    },
  },
};

const EMPTY_MATRIX_STATUS: MatrixStatusSnapshot = {
  schema: 'loom.matrix.status.v1',
  devices: [],
  summary: {
    total: 0,
    online: 0,
    busy: 0,
    failed: 0,
  },
};

function statusLabel(value?: string): string {
  if (value === 'pending_manual_review') return '待人工确认';
  if (value === 'approved_pending_manual_send') return '已确认待人工触达';
  if (value === 'manual_sent') return '已记录人工触达';
  if (value === 'manual_send_failed') return '人工触达失败';
  if (value === 'contacted') return '已触达';
  if (value === 'replied') return '已回复';
  if (value === 'no_reply') return '暂无回复';
  if (value === 'qualified') return '已筛选';
  if (value === 'needs_follow_up') return '待跟进';
  if (value === 'pending_sync') return '待同步飞书';
  if (value === 'sync_failed') return '同步失败';
  if (value === 'synced') return '已入飞书';
  if (value === 'pending_human_confirm') return '等待人工确认';
  return value || '待处理';
}

function policyLabel(value: string): string {
  if (value === 'draft_only') return '只生成草稿';
  if (value === 'manual_confirm') return '人工确认';
  if (value === 'whitelist') return '白名单';
  if (value === 'frequency_cap') return '频控';
  if (value === 'audit_log') return '日志留痕';
  return value;
}

function feishuStatusLabel(status?: FeishuStatus): string {
  if (!status?.cliInstalled) return '未安装 CLI';
  if (!status?.auth?.loggedIn && !status?.auth?.botReady) return '未登录';
  if (!status?.table?.baseToken || !status?.table?.tableId) return '未绑定表格';
  return status.connected ? '已连接' : '待检查';
}

function formatTime(value?: string): string {
  if (!value) return '暂无';
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function countMatrixDevices(status: MatrixStatusSnapshot) {
  const devices = status.devices || [];
  const summary = status.summary || {};
  const total = summary.total ?? devices.length;
  const online = summary.online ?? devices.filter((device) => device.online).length;
  const busy = summary.busy ?? devices.filter((device) => device.online && Boolean(device.busy || device.currentTaskId)).length;
  const failed = summary.failed ?? devices.filter((device) => (device.failureCount || 0) > 0 || device.streamStatus === 'failed').length;
  return { total, online, busy, failed };
}

function matrixDeviceStatus(device: MatrixDeviceSummary): string {
  if (!device.online) return '离线';
  if ((device.failureCount || 0) > 0 || device.streamStatus === 'failed') return '异常';
  if (device.busy || device.currentTaskId) return '执行中';
  return '在线';
}

type FeishuLoginGuideState = { loginUrl?: string; userCode?: string; qrAscii?: string };

function createQrDataUri(value?: string): string {
  if (!value) return '';
  try {
    const qr = qrcode(0, 'M');
    qr.addData(value);
    qr.make();
    const dataUrl = qr.createDataURL(5, 2);
    return dataUrl.startsWith('data:image/gif;base64') ? dataUrl : '';
  } catch {
    return '';
  }
}

async function copyFeishuLoginUrl(value?: string) {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    showToast('已复制飞书登录链接', 'success');
  } catch {
    showToast('复制失败，请手动复制飞书登录链接', 'error');
  }
}

async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value);
    showToast('已复制 AI 接入提示词', 'success');
  } catch {
    showToast('复制失败，请手动选中文本复制', 'error');
  }
}

export const AcquisitionWorkbenchPage = () => {
  const [snapshot, setSnapshot] = React.useState<AcquisitionSnapshot>(EMPTY_SNAPSHOT);
  const [matrixStatus, setMatrixStatus] = React.useState<MatrixStatusSnapshot>(EMPTY_MATRIX_STATUS);
  const [matrixError, setMatrixError] = React.useState('');
  const [tableUrl, setTableUrl] = React.useState('');
  const [loginGuide, setLoginGuide] = React.useState<FeishuLoginGuideState | null>(null);
  const [feishuBusy, setFeishuBusy] = React.useState('');
  const agentPrompt = React.useMemo(() => buildOneShotAgentPrompt(buildMcpJson()), []);

  const refresh = React.useCallback(async () => {
    const [acquisitionResult, matrixResult] = await Promise.allSettled([
      acquisitionApi.snapshot(),
      matrixApi.status(),
    ]);

    if (acquisitionResult.status === 'fulfilled') {
      setSnapshot(acquisitionResult.value);
    } else {
      showToast(parseErrorText(acquisitionResult.reason) || '读取获客总览失败', 'error');
    }

    if (matrixResult.status === 'fulfilled') {
      setMatrixStatus(matrixResult.value);
      setMatrixError('');
    } else {
      setMatrixError(parseErrorText(matrixResult.reason) || '矩阵状态待刷新');
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const refreshFeishu = async () => {
    setFeishuBusy('status');
    try {
      const feishu = await feishuApi.status();
      setSnapshot((current) => ({ ...current, integrations: { ...(current.integrations || {}), feishu } }));
      showToast('已刷新飞书状态', 'success');
    } catch (error) {
      showToast(parseErrorText(error) || '刷新飞书状态失败', 'error');
    } finally {
      setFeishuBusy('');
    }
  };

  const startFeishuLogin = async () => {
    setFeishuBusy('login');
    try {
      const guide = await feishuApi.login();
      setLoginGuide({ loginUrl: guide.loginUrl || guide.verificationUrl, userCode: guide.userCode, qrAscii: guide.qrAscii });
      showToast('请扫码或打开链接完成飞书登录', 'info');
    } catch (error) {
      showToast(parseErrorText(error) || '启动飞书登录失败', 'error');
    } finally {
      setFeishuBusy('');
    }
  };

  const bindFeishuTable = async () => {
    if (!tableUrl.trim()) {
      showToast('请粘贴飞书多维表格链接', 'info');
      return;
    }
    setFeishuBusy('bind');
    try {
      const result = await feishuApi.bindTable({ url: tableUrl, name: '麓鸣获客线索表' });
      const feishu = result.status || await feishuApi.status();
      setSnapshot((current) => ({ ...current, integrations: { ...(current.integrations || {}), feishu } }));
      showToast('已绑定飞书线索表', 'success');
    } catch (error) {
      showToast(parseErrorText(error) || '绑定飞书线索表失败', 'error');
    } finally {
      setFeishuBusy('');
    }
  };

  const createFeishuTable = async () => {
    setFeishuBusy('create');
    try {
      const preview = await feishuApi.createTable(false);
      const fields = Array.isArray(preview.fields) ? preview.fields.length : 0;
      const ok = await showConfirm({
        title: '新建飞书多维表格',
        message: `将创建并绑定一张新的获客线索表${fields ? `，包含 ${fields} 个字段` : ''}。继续吗？`,
        confirmText: '确认新建',
      });
      if (!ok) return;
      await feishuApi.createTable(true);
      await refreshFeishu();
      showToast('已创建并绑定新的飞书线索表', 'success');
    } catch (error) {
      showToast(parseErrorText(error) || '创建飞书线索表失败，请确认已扫码登录且有多维表格权限', 'error');
    } finally {
      setFeishuBusy('');
    }
  };

  const testFeishuWrite = async () => {
    setFeishuBusy('test');
    try {
      await feishuApi.testWrite();
      await refresh();
      showToast('已提交飞书测试写入', 'success');
    } catch (error) {
      showToast(parseErrorText(error) || '飞书测试写入失败', 'error');
    } finally {
      setFeishuBusy('');
    }
  };

  const retryFeishuSync = async () => {
    setFeishuBusy('retry');
    try {
      await feishuApi.retrySync();
      await refresh();
      showToast('已重试同步本地缓存线索', 'success');
    } catch (error) {
      showToast(parseErrorText(error) || '重试同步失败', 'error');
    } finally {
      setFeishuBusy('');
    }
  };

  const feishu = snapshot.integrations?.feishu;
  const pendingSync = snapshot.stats.pendingSync ?? feishu?.pendingCount ?? 0;
  const matrixCounts = countMatrixDevices(matrixStatus);
  const latestAgentRun = snapshot.agentRuns?.[snapshot.agentRuns.length - 1] || null;
  const latestLead = snapshot.leads[snapshot.leads.length - 1] || null;
  const latestDraft = snapshot.drafts[snapshot.drafts.length - 1] || null;
  const latestCustomer = snapshot.customers[snapshot.customers.length - 1] || null;
  const latestLog = snapshot.logs[snapshot.logs.length - 1] || null;

  return (
    <div data-acquisition-workbench data-ai-executor-console className="h-full overflow-auto overflow-x-hidden bg-[#F5F7FA] text-[#17202A]">
      <div className="mx-auto flex min-h-full w-full max-w-[1180px] flex-col gap-4 px-4 py-4">
        <section
          data-acquisition-overview
          data-acquisition-matrix-overview
          className="rounded-[8px] border border-[#C8D6D9] bg-white p-4 shadow-sm"
        >
          <div className="rounded-[8px] border border-[#10464B] bg-[#062A2C] p-4 text-white shadow-[0_18px_50px_rgba(6,42,44,0.16)]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[11px] font-black tracking-[0.18em] text-[#8AE3D1]">获客总览</div>
                <h1 className="mt-2 text-[28px] font-black leading-9 sm:text-[34px] sm:leading-10">多台手机矩阵获客总控</h1>
                <p className="mt-2 max-w-[820px] break-words text-sm font-semibold leading-6 text-[#CFE9E5]">
                  把手机 Agent、线索判断、AI 跟进草稿、人工确认和飞书沉淀放在同一个执行面。数字来自本机真实状态，没有演示流。
                </p>
              </div>
              <Button variant="quiet" onClick={() => void refresh()} className="w-full !rounded-[8px] !border-[#7BCDC0] !bg-white !text-[#06363A] sm:w-auto">
                刷新总览
              </Button>
            </div>

            <div data-matrix-capability-strip className="mt-4 grid gap-2 md:grid-cols-5">
              <CapabilityStep label="手机矩阵" value={`${matrixCounts.online}/${matrixCounts.total} 在线`} />
              <CapabilityStep label="线索发现" value={`${snapshot.stats.leads} 条线索`} />
              <CapabilityStep label="AI 跟进草稿" value={`${snapshot.stats.draftsPending} 条待确认`} />
              <CapabilityStep label="人工确认" value="外发前必停" />
              <CapabilityStep label="飞书沉淀" value={`${pendingSync} 条待同步`} />
            </div>
          </div>

          <div data-acquisition-stats className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="线索数" value={snapshot.stats.leads} desc={latestLead?.title || '暂无最新线索'} />
            <Metric label="客户数" value={snapshot.stats.customers} desc={latestCustomer?.stage ? statusLabel(latestCustomer.stage) : '暂无客户'} />
            <Metric label="待确认草稿" value={snapshot.stats.draftsPending} desc={latestDraft ? statusLabel(latestDraft.status) : '暂无草稿'} />
            <Metric label="飞书待同步" value={pendingSync} desc={feishuStatusLabel(feishu)} />
            <Metric label="设备总数" value={matrixCounts.total} desc={matrixStatus.updatedAt ? `更新 ${formatTime(matrixStatus.updatedAt)}` : '等待接入'} />
            <Metric label="在线设备" value={matrixCounts.online} desc={matrixError || '可接收矩阵任务'} />
            <Metric label="执行中设备" value={matrixCounts.busy} desc={latestAgentRun?.deviceId || '暂无执行任务'} />
            <Metric label="异常设备" value={matrixCounts.failed} desc={matrixError || '矩阵状态待刷新'} tone={matrixCounts.failed > 0 || matrixError ? 'warn' : 'default'} />
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-[1.25fr_1fr_1fr]">
            <section data-matrix-device-summary className="min-h-[160px] rounded-[8px] border border-[#D5DDE5] bg-[#F8FAFC] p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-black">矩阵设备</h3>
                <StatusPill>{matrixError ? '矩阵状态待刷新' : `${matrixCounts.total} 台设备`}</StatusPill>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {matrixStatus.devices.slice(0, 4).map((device) => (
                  <MatrixDeviceItem key={device.deviceId} device={device} />
                ))}
                {matrixStatus.devices.length === 0 ? <Empty>暂无手机接入，绑定手机后这里会显示真实矩阵状态</Empty> : null}
              </div>
              {matrixStatus.devices.length > 4 ? (
                <div className="mt-2 text-[11px] font-black text-[#0F6B7A]">另有 {matrixStatus.devices.length - 4} 台设备已接入</div>
              ) : null}
            </section>
            <OverviewPanel marker="data-acquisition-lead-pool" title="线索池" empty="暂无线索">
              {latestLead ? (
                <SummaryItem title={latestLead.title} body={latestLead.summary} meta={`${latestLead.platform || 'unknown'} / ${statusLabel(latestLead.syncStatus)}`} />
              ) : null}
            </OverviewPanel>
            <OverviewPanel marker="data-acquisition-draft-review" title="草稿确认" empty="暂无待确认草稿">
              {latestDraft ? (
                <SummaryItem title={statusLabel(latestDraft.status)} body={latestDraft.body} meta="不会自动发送" />
              ) : null}
            </OverviewPanel>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <OverviewPanel marker="data-followup-log-panel data-acquisition-task-log" title="最近日志" empty="暂无日志">
              {latestLog ? (
                <SummaryItem title={latestLog.type || 'event'} body={latestLog.message || ''} meta={formatTime(latestLog.timestamp)} />
              ) : null}
            </OverviewPanel>
            <OverviewPanel marker="data-acquisition-agent-run" title="最近 Agent" empty="等待 AI 接入">
              {latestAgentRun ? (
                <SummaryItem title={statusLabel(latestAgentRun.status)} body={latestAgentRun.action || latestAgentRun.platform || ''} meta={latestAgentRun.deviceId || '未指定设备'} />
              ) : null}
            </OverviewPanel>
          </div>
        </section>

        <section
          data-feishu-bitable-binding
          data-feishu-sync-panel
          data-acquisition-feishu-sync
          className="rounded-[8px] border border-[#D5DDE5] bg-white p-4 shadow-sm"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[11px] font-black tracking-[0.18em] text-[#0F6B7A]">线索沉淀出口</div>
              <h2 className="mt-1 text-xl font-black">飞书多维表格</h2>
              <p className="mt-1 max-w-[780px] break-words text-sm font-semibold leading-6 text-[#647181]">
                绑定后，Codex 写入的线索会同步到飞书多维表格；失败会留在本地队列，方便重试和审计。
              </p>
            </div>
            <StatusPill>飞书同步：{feishuStatusLabel(feishu)}</StatusPill>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <Mini label="飞书 CLI" value={feishu?.cliInstalled ? '已安装' : '未安装'} />
            <Mini label="登录" value={feishu?.auth?.loggedIn ? '用户已登录' : feishu?.auth?.botReady ? 'Bot 可用' : '待扫码'} />
            <Mini label="表格" value={feishu?.table?.name || feishu?.table?.tableId || '未绑定'} />
            <Mini label="最近同步" value={statusLabel(feishu?.lastSync?.syncStatus)} />
            <Mini label="失败原因" value={feishu?.lastSync?.syncError || '无'} />
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="quiet" onClick={() => void refreshFeishu()} disabled={Boolean(feishuBusy)} className="!rounded-[8px]">检查</Button>
            <Button variant="primary" onClick={() => void startFeishuLogin()} disabled={Boolean(feishuBusy)} className="!rounded-[8px]">扫码登录</Button>
            <Button variant="success" onClick={() => void createFeishuTable()} disabled={Boolean(feishuBusy)} className="!rounded-[8px]">新建表</Button>
            <Button variant="quiet" onClick={() => void testFeishuWrite()} disabled={Boolean(feishuBusy)} className="!rounded-[8px]">测试写入</Button>
            <Button variant="quiet" onClick={() => void retryFeishuSync()} disabled={Boolean(feishuBusy)} className="!rounded-[8px]">重试同步</Button>
          </div>

          {loginGuide ? (
            <div data-feishu-login-guide className="mt-4 rounded-[8px] border border-[#BAE6FD] bg-[#F0F9FF] p-3 text-xs font-semibold leading-5 text-[#075985]">
              <FeishuQrPanel guide={loginGuide} />
              <div className="break-all">登录链接：{loginGuide.loginUrl || '请查看飞书 CLI 输出'}</div>
              <div>验证码：{loginGuide.userCode || '无'}</div>
              {loginGuide.qrAscii ? <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap text-[9px] leading-3">{loginGuide.qrAscii}</pre> : null}
            </div>
          ) : null}

          <div className="mt-4 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
            <Input aria-label="飞书多维表格链接" value={tableUrl} onChange={(event) => setTableUrl(event.target.value)} placeholder="粘贴飞书多维表格链接" className="!rounded-[8px]" />
            <Button variant="success" onClick={() => void bindFeishuTable()} disabled={Boolean(feishuBusy)} className="!rounded-[8px]">绑定线索表</Button>
          </div>
        </section>

        <section data-acquisition-agent-prompt className="rounded-[8px] border border-[#D5DDE5] bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[11px] font-black tracking-[0.18em] text-[#0F6B7A]">AI 执行入口</div>
              <h2 className="mt-1 text-xl font-black">AI 接入提示词</h2>
              <p className="mt-1 max-w-[780px] break-words text-sm font-semibold leading-6 text-[#647181]">
                复制给 Codex 或其他 Agent 后，它会读取获客任务，调用手机 Agent，回收线索日志，并把确认后的线索写入飞书。
              </p>
            </div>
            <Button variant="primary" onClick={() => void copyText(agentPrompt)} className="w-full !rounded-[8px] sm:w-auto">
              复制 AI 接入提示词
            </Button>
          </div>

          <details className="mt-4 rounded-[8px] border border-[#E1E7EE] bg-[#F8FAFC] p-3">
            <summary className="cursor-pointer text-sm font-black text-[#1F2937]">展开提示词全文</summary>
            <textarea
              aria-label="AI 接入提示词预览"
              readOnly
              value={agentPrompt}
              rows={12}
              className="mt-3 w-full resize-y rounded-[8px] border border-[#CBD5E1] bg-white p-3 font-mono text-[11px] leading-5 text-[#334155] outline-none"
            />
          </details>
        </section>

        <footer className="flex flex-wrap items-center gap-2 rounded-[8px] border border-[#D8E0E8] bg-white p-3 text-[11px] font-black text-[#647181]">
          {snapshot.outboundPolicy.map((item) => <Badge key={item}>{policyLabel(item)}</Badge>)}
          <span>真实外发必须人工确认；禁止无确认批量私信、评论、加好友、群发或发布。</span>
        </footer>
      </div>
    </div>
  );
};

function FeishuQrPanel({ guide }: { guide: FeishuLoginGuideState }) {
  const qrSrc = React.useMemo(() => createQrDataUri(guide.loginUrl), [guide.loginUrl]);
  return (
    <div className="mb-3 grid gap-3 md:grid-cols-[148px_minmax(0,1fr)]">
      <div data-feishu-login-qr className="flex min-h-[148px] items-center justify-center rounded-[8px] border border-[#B7DBEA] bg-white p-2">
        {qrSrc ? (
          <img src={qrSrc} alt="飞书扫码登录二维码" className="h-[132px] w-[132px]" />
        ) : guide.qrAscii ? (
          <pre className="max-h-[132px] max-w-[132px] overflow-hidden whitespace-pre text-[4px] leading-[4px] text-[#0B4A3E]">{guide.qrAscii}</pre>
        ) : (
          <div className="px-3 text-center text-xs font-black leading-5 text-[#0F6B7A]">等待飞书二维码</div>
        )}
      </div>
      <div className="min-w-0 rounded-[8px] border border-[#B7DBEA] bg-white/70 p-3">
        <div className="text-sm font-black text-[#0F3440]">飞书扫码登录</div>
        <div className="mt-1 text-xs font-semibold leading-5 text-[#48616B]">用飞书 App 扫码，或打开链接后输入验证码。</div>
        <div className="mt-2 rounded-[6px] bg-[#E6F6FD] px-2 py-1.5 text-xs font-black text-[#075985]">
          验证码：{guide.userCode || '无'}
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button variant="quiet" onClick={() => void copyFeishuLoginUrl(guide.loginUrl)} disabled={!guide.loginUrl} className="!rounded-[8px] !px-3 !py-1.5 !text-xs">
            复制登录链接
          </Button>
          {guide.loginUrl ? (
            <a className="rounded-[8px] border border-[#0B4A3E]/25 bg-white px-3 py-1.5 text-xs font-black text-[#0B4A3E] hover:bg-[#ECFDF5]" href={guide.loginUrl} target="_blank" rel="noreferrer">
              打开链接
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, desc, tone = 'default' }: { label: string; value: React.ReactNode; desc: React.ReactNode; tone?: 'default' | 'warn' }) {
  const toneClass = tone === 'warn' ? 'border-[#F4B8B8] bg-[#FFF7F7] text-[#B42318]' : 'border-[#D5DDE5] bg-[#F8FAFC] text-[#0F6B7A]';
  return (
    <div className={`min-w-0 rounded-[8px] border p-3 ${toneClass}`}>
      <div className="text-[11px] font-black text-[#647181]">{label}</div>
      <div className="mt-1 truncate text-xl font-black">{value}</div>
      <div className="mt-1 truncate text-xs font-semibold text-[#647181]">{desc}</div>
    </div>
  );
}

function CapabilityStep({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-[8px] border border-[#1E5559] bg-white/10 p-3">
      <div className="truncate text-sm font-black text-white">{label}</div>
      <div className="mt-1 truncate text-xs font-bold text-[#A9E8DC]">{value}</div>
    </div>
  );
}

function MatrixDeviceItem({ device }: { device: MatrixDeviceSummary }) {
  const status = matrixDeviceStatus(device);
  const statusClass = status === '异常' ? 'text-[#B42318]' : status === '执行中' ? 'text-[#B7791F]' : status === '在线' ? 'text-[#0F6B7A]' : 'text-[#647181]';
  return (
    <div className="min-w-0 rounded-[8px] border border-[#E1E7EE] bg-white p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-black text-[#1F2937]">{device.name || device.deviceId}</div>
          <div className="mt-1 truncate text-[11px] font-bold text-[#647181]">{device.group || device.model || device.deviceId}</div>
        </div>
        <span className={`shrink-0 text-xs font-black ${statusClass}`}>{status}</span>
      </div>
      <div className="mt-2 line-clamp-2 text-xs font-semibold leading-5 text-[#647181]">
        {device.currentScreenSummary || device.lastResult || device.currentTaskId || '等待矩阵任务'}
      </div>
    </div>
  );
}

function OverviewPanel({ marker, title, empty, children }: { marker: string; title: string; empty: string; children: React.ReactNode }) {
  const markerProps = marker.split(/\s+/).filter(Boolean).reduce<Record<string, string>>((acc, key) => {
    acc[key] = '';
    return acc;
  }, {});
  return (
    <section {...markerProps} className="min-h-[160px] rounded-[8px] border border-[#E1E7EE] bg-[#F8FAFC] p-3">
      <h3 className="text-sm font-black">{title}</h3>
      <div className="mt-2">{children || <Empty>{empty}</Empty>}</div>
    </section>
  );
}

function SummaryItem({ title, body, meta }: { title: string; body?: string; meta: string }) {
  return (
    <div className="rounded-[8px] border border-[#E1E7EE] bg-white p-3">
      <div className="truncate text-sm font-black text-[#1F2937]">{title}</div>
      <div className="mt-1 line-clamp-2 text-xs font-semibold leading-5 text-[#647181]">{body || '暂无详情'}</div>
      <div className="mt-2 text-[11px] font-black text-[#0F6B7A]">{meta}</div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-[8px] border border-[#E1E7EE] bg-[#F8FAFC] p-2">
      <div className="text-[11px] font-black text-[#647181]">{label}</div>
      <div className="mt-1 truncate text-xs font-bold text-[#1F2937]">{value}</div>
    </div>
  );
}

function StatusPill({ children }: { children: React.ReactNode }) {
  return <span className="rounded-[8px] border border-[#B6D7DD] bg-[#F2FBFC] px-3 py-2 text-xs font-black text-[#0F6B7A]">{children}</span>;
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="rounded-[6px] border border-[#CBD5E1] bg-white px-2 py-1 text-[11px] font-black text-[#475569]">{children}</span>;
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-[8px] border border-dashed border-[#CBD5E1] p-5 text-center text-sm font-bold text-[#647181]">{children}</div>;
}
