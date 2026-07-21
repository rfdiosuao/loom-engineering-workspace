import React from 'react';
import { Download, RefreshCcw, Wrench, X } from 'lucide-react';
import { Button, Chip, EmptyState, InlineState, Modal, Panel, SectionHeader, StatTile } from '../components/ui';
import { exportDiagnostics, loadDiagnosticsSnapshot, repairDiagnostics } from '../api/adapters';
import { useAsync } from '../lib/useAsync';
import { shortenPaths } from '../lib/format';
import { usePreviewStore } from '../store/appStore';
import { CodeBlock } from '../components/ui';

export function DiagnosticsPage() {
  const settings = usePreviewStore((state) => state.settings);
  const pushToast = usePreviewStore((state) => state.pushToast);
  const { data, loading, error, refresh } = useAsync(() => loadDiagnosticsSnapshot(settings), [settings], { cacheKey: "diagnostics", ttlMs: 60000 });
  const [busy, setBusy] = React.useState(false);
  const [confirmRepair, setConfirmRepair] = React.useState(false);

  const repairableChecks = (data?.checks || []).filter((check) => check.status !== 'ok');

  const runRepair = async () => {
    setConfirmRepair(false);
    setBusy(true);
    try {
      const result = await repairDiagnostics(settings);
      pushToast({ tone: 'ok', title: '修复完成', detail: `已执行 ${result.data?.actions?.length || 0} 个动作` });
      refresh();
    } catch (err) {
      pushToast({ tone: 'danger', title: '修复失败', detail: String(err) });
    } finally {
      setBusy(false);
    }
  };

  const handleRepair = () => {
    setConfirmRepair(true);
  };

  const handleExport = async () => {
    setBusy(true);
    try {
      const result = await exportDiagnostics(settings);
      pushToast({ tone: 'ok', title: '诊断包已导出', detail: result.data?.filename || '导出完成' });
    } catch (err) {
      pushToast({ tone: 'danger', title: '导出失败', detail: String(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page-grid">
      <section className="hero-band">
        <div className="hero-copy">
          <div className="eyebrow">环境检测</div>
          <h1>检查启动器是否可以正常运行</h1>
          <p>看看现在能不能正常使用，发现问题给你一键修复。</p>
        </div>
        <div className="hero-actions">
          <Button variant="primary" icon={RefreshCcw} onClick={refresh}>刷新</Button>
          <Button variant="secondary" icon={Wrench} onClick={handleRepair} disabled={busy}>修复</Button>
          <Button variant="secondary" icon={Download} onClick={handleExport} disabled={busy}>导出</Button>
        </div>
      </section>

      <section className="stats-grid">
        <StatTile label="状态" value={toCnStatus(data?.summary.status || 'warn')} hint={`${data?.summary.ok ?? 0}/${data?.summary.total ?? 0} 项检测`} tone={data?.summary.status === 'ok' ? 'ok' : data?.summary.status === 'warn' ? 'warn' : 'danger'} />
        <StatTile label="警告" value={data?.summary.warnings ?? 0} tone="warn" />
        <StatTile label="失败" value={data?.summary.failed ?? 0} tone={data?.summary.failed ? 'danger' : 'ok'} />
        <StatTile label="可修复" value={data?.repairAvailable ? '是' : '否'} tone={data?.repairAvailable ? 'ok' : 'warn'} />
      </section>

      {loading ? (
        <Panel className="panel-loading">正在读取诊断信息...</Panel>
      ) : error ? (
        <Panel className="panel-error"><InlineState tone="danger" title="诊断信息读取失败" description={error} /></Panel>
      ) : data ? (
        <section className="content-grid content-grid-diagnostics">
          <Panel className="surface-panel">
            <SectionHeader eyebrow="检测项" title="健康报告" subtitle="每一项直接映射诊断报告里的状态、消息和详情。" />
            <div className="check-list">
              {data.checks.map((check) => (
                <div key={check.id} className={`check-row check-row-${check.status}`}>
                  <div className="check-head">
                    <strong>{check.label}</strong>
                    <Chip tone={check.status === 'ok' ? 'ok' : check.status === 'warn' ? 'warn' : 'danger'}>{toCnStatus(check.status)}</Chip>
                  </div>
                  <div className="check-message">{shortenPaths(check.message)}</div>
                  {check.detail ? <div className="check-detail" title={check.detail}>{shortenPaths(check.detail)}</div> : null}
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="surface-panel">
            <SectionHeader eyebrow="运行时" title="启动上下文" subtitle="这些字段对应后端诊断返回值。" />
            <div className="detail-stack">
              <div className="detail-row"><span className="detail-label">根路径</span><span className="detail-value" title={data.basePath}>{shortenPaths(data.basePath)}</span></div>
              <div className="detail-row"><span className="detail-label">服务运行</span><span className="detail-value">{data.serviceRunning ? '是' : '否'}</span></div>
              <div className="detail-row"><span className="detail-label">PID</span><span className="detail-value">{data.servicePid ?? '未知'}</span></div>
              <div className="detail-row"><span className="detail-label">启动状态</span><span className="detail-value">{data.startupState}</span></div>
              <div className="detail-row"><span className="detail-label">启动错误</span><span className="detail-value">{data.startupError || '无'}</span></div>
            </div>
          </Panel>

          <Panel className="surface-panel">
            <SectionHeader eyebrow="产物" title="导出与修复记录" subtitle="保留可追踪的诊断产物，方便内测用户反馈。" />
            <div className="detail-stack">
              <div className="detail-row"><span className="detail-label">快照路径</span><span className="detail-value" title={data.startupSnapshotPath}>{shortenPaths(data.startupSnapshotPath) || '暂无'}</span></div>
              <div className="detail-row"><span className="detail-label">已耗时</span><span className="detail-value">{data.startupElapsedSec}s</span></div>
              <div className="detail-row"><span className="detail-label">超时</span><span className="detail-value">{data.startupTimeoutSec}s</span></div>
            </div>
            <CodeBlock text={JSON.stringify(data.summary, null, 2)} maxHeight={220} />
          </Panel>

          <Panel className="surface-panel">
            <SectionHeader eyebrow="导出" title="修复结果" subtitle="适配层会返回修复动作列表和更新后的诊断对象。" />
            {busy ? <div className="panel-loading-inline">处理中...</div> : <EmptyState title="当前没有任务" description="使用上方按钮触发修复或导出。" />}
          </Panel>
        </section>
      ) : null}

      <Modal
        open={confirmRepair}
        title="确认修复"
        subtitle="修复会执行以下操作"
        onClose={() => setConfirmRepair(false)}
        actions={
          <>
            <Button variant="secondary" icon={X} onClick={() => setConfirmRepair(false)}>取消</Button>
            <Button variant="primary" icon={Wrench} onClick={runRepair} disabled={busy}>确认修复</Button>
          </>
        }
      >
        {repairableChecks.length ? (
          <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {repairableChecks.map((check) => (
              <li key={check.id}>
                <strong>{check.label}</strong>
                <span style={{ marginLeft: 6, opacity: 0.8 }}>{shortenPaths(check.message)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p>未发现需要修复的项目，仍会执行一次标准修复流程。</p>
        )}
        <p style={{ marginTop: 12, opacity: 0.75 }}>不会删除你的数据或已生成的文件。</p>
      </Modal>
    </div>
  );
}

function toCnStatus(value: string) {
  const map: Record<string, string> = {
    ok: '正常',
    warn: '警告',
    fail: '失败',
  };
  return map[String(value || '').toLowerCase()] || value;
}

