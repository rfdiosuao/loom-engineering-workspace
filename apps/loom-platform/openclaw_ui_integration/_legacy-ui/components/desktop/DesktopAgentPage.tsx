import React from 'react';
import { Button, Input, Select, showToast } from '../common';
import { desktopAgentApi, type DesktopAgentConfig, type DesktopAgentStatus } from '../../services/api';
import { useLogStore } from '../../stores/logStore';

const defaultConfig: DesktopAgentConfig = {
  enabled: false,
  agentDir: '',
  port: 21900,
  appType: 'weixin',
  autoStartHttpApi: true,
  policy: {
    allowScreenshot: true,
    allowClick: false,
    allowType: false,
    allowWechatSend: false,
    requireConfirmForClick: true,
    requireConfirmForType: true,
    requireConfirmForSend: true,
    blockedWindowKeywords: ['支付', '付款', '密码', '授权', '登录'],
  },
  capture: {
    format: 'jpeg',
    quality: 82,
    maxWidth: 1600,
  },
  action: {
    clickDelayMs: 120,
    typeDelayMs: 20,
    timeoutMs: 30000,
  },
  wechat: {
    sendMode: 'draft_only',
    detectUnreadMode: 'hybrid',
  },
};

function mergeConfig(config?: Partial<DesktopAgentConfig>): DesktopAgentConfig {
  return {
    ...defaultConfig,
    ...config,
    policy: { ...defaultConfig.policy!, ...(config?.policy || {}) },
    capture: { ...defaultConfig.capture!, ...(config?.capture || {}) },
    action: { ...defaultConfig.action!, ...(config?.action || {}) },
    wechat: { ...defaultConfig.wechat!, ...(config?.wechat || {}) },
  };
}

function statusTone(status: DesktopAgentStatus | null): { label: string; className: string } {
  if (status?.apiReady) return { label: 'API 就绪', className: 'text-status-success border-status-success/30 bg-status-success/10' };
  if (status?.running) return { label: '进程运行中', className: 'text-status-warning border-status-warning/30 bg-status-warning/10' };
  if (status?.present) return { label: '已发现', className: 'text-accent border-accent/30 bg-accent/10' };
  return { label: '未配置', className: 'text-text-muted border-border bg-surface-alt/70' };
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-4 rounded-xl border border-border bg-surface/55 px-3 py-2">
      <span className="text-sm font-bold text-text">{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

export const DesktopAgentPage: React.FC = () => {
  const appendLog = useLogStore((s) => s.append);
  const [status, setStatus] = React.useState<DesktopAgentStatus | null>(null);
  const [config, setConfig] = React.useState<DesktopAgentConfig>(defaultConfig);
  const [busy, setBusy] = React.useState(false);
  const [screenshot, setScreenshot] = React.useState('');

  const refresh = React.useCallback(async () => {
    const next = await desktopAgentApi.status();
    setStatus(next);
    setConfig(mergeConfig(next.config));
  }, []);

  React.useEffect(() => {
    refresh().catch((error) => showToast(`读取桌面 Agent 状态失败：${error?.error || error}`, 'error'));
  }, [refresh]);

  const updatePolicy = (patch: Partial<NonNullable<DesktopAgentConfig['policy']>>) => {
    setConfig((prev) => ({ ...prev, policy: { ...prev.policy!, ...patch } }));
  };

  const updateCapture = (patch: Partial<NonNullable<DesktopAgentConfig['capture']>>) => {
    setConfig((prev) => ({ ...prev, capture: { ...prev.capture!, ...patch } }));
  };

  const updateAction = (patch: Partial<NonNullable<DesktopAgentConfig['action']>>) => {
    setConfig((prev) => ({ ...prev, action: { ...prev.action!, ...patch } }));
  };

  const updateWechat = (patch: Partial<NonNullable<DesktopAgentConfig['wechat']>>) => {
    setConfig((prev) => ({ ...prev, wechat: { ...prev.wechat!, ...patch } }));
  };

  const run = async (label: string, action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      const result = await action();
      appendLog(`[桌面 Agent] ${label} 完成\n`);
      await refresh();
      return result;
    } catch (error: any) {
      const message = error?.error || error;
      appendLog(`[桌面 Agent] ${label} 失败：${message}\n`);
      showToast(`${label}失败：${message}`, 'error');
      return null;
    } finally {
      setBusy(false);
    }
  };

  const saveConfig = async () => {
    await run('保存配置', async () => {
      const result = await desktopAgentApi.config(config);
      setConfig(mergeConfig(result.config));
      showToast('桌面 Agent 配置已保存', 'success');
      return result;
    });
  };

  const captureScreenshot = async () => {
    const result = await run('截图测试', () => desktopAgentApi.screenshot());
    const shot = (result as any)?.screenshot;
    if (shot) {
      setScreenshot(shot);
      showToast('桌面截图成功', 'success');
    }
  };

  const tone = statusTone(status);
  const screenshotSrc = screenshot && !screenshot.startsWith('data:') ? `data:image/png;base64,${screenshot}` : screenshot;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-transparent">
      <header className="shrink-0 border-b border-border bg-surface px-8 py-7">
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-[0.32em] text-accent">LUMINODE</div>
            <h1 className="mt-2 text-2xl font-black text-text">lumi 桌面控制台</h1>
            <p className="mt-1 text-sm text-text-muted">启动器托管 Luminode 桌面代理，统一保管 token、策略和 Bridge 调用。</p>
          </div>
          <span className={`rounded-full border px-3 py-1.5 text-xs font-black ${tone.className}`}>{tone.label}</span>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 gap-5 overflow-auto p-8 xl:grid-cols-[430px_minmax(0,1fr)]">
        <section className="space-y-4">
          <div className="rounded-2xl border border-border bg-surface-alt/60 p-5">
            <h2 className="text-sm font-black text-text">连接配置</h2>
            <div className="mt-4 space-y-4">
              <label className="block">
                <span className="mb-1 block text-xs font-bold text-text-muted">Luminode 目录</span>
                <Input
                  value={config.agentDir}
                  placeholder="留空时自动查找内置 agents/luminode-desktop"
                  onChange={(event) => setConfig((prev) => ({ ...prev, agentDir: event.target.value }))}
                />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="mb-1 block text-xs font-bold text-text-muted">本地端口</span>
                  <Input
                    type="number"
                    value={config.port}
                    onChange={(event) => setConfig((prev) => ({ ...prev, port: Number(event.target.value || 21900) }))}
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-bold text-text-muted">目标应用</span>
                  <Select className="w-full" value={config.appType} onChange={(event) => setConfig((prev) => ({ ...prev, appType: event.target.value }))}>
                    <option value="weixin">微信</option>
                    <option value="wework">企业微信</option>
                  </Select>
                </label>
              </div>
              <Toggle label="自动启动本地 HTTP API" checked={config.autoStartHttpApi} onChange={(value) => setConfig((prev) => ({ ...prev, autoStartHttpApi: value }))} />
              <Button variant="primary" className="w-full" onClick={saveConfig} disabled={busy}>
                保存配置
              </Button>
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-surface-alt/60 p-5">
            <h2 className="text-sm font-black text-text">安全策略</h2>
            <div className="mt-4 space-y-2">
              <Toggle label="允许截图" checked={!!config.policy?.allowScreenshot} onChange={(value) => updatePolicy({ allowScreenshot: value })} />
              <Toggle label="允许点击" checked={!!config.policy?.allowClick} onChange={(value) => updatePolicy({ allowClick: value })} />
              <Toggle label="点击需要确认" checked={!!config.policy?.requireConfirmForClick} onChange={(value) => updatePolicy({ requireConfirmForClick: value })} />
              <Toggle label="允许输入" checked={!!config.policy?.allowType} onChange={(value) => updatePolicy({ allowType: value })} />
              <Toggle label="输入需要确认" checked={!!config.policy?.requireConfirmForType} onChange={(value) => updatePolicy({ requireConfirmForType: value })} />
              <Toggle label="允许自动发送微信" checked={!!config.policy?.allowWechatSend} onChange={(value) => updatePolicy({ allowWechatSend: value })} />
              <Toggle label="发送需要确认" checked={!!config.policy?.requireConfirmForSend} onChange={(value) => updatePolicy({ requireConfirmForSend: value })} />
              <label className="block pt-2">
                <span className="mb-1 block text-xs font-bold text-text-muted">敏感关键词</span>
                <Input
                  value={(config.policy?.blockedWindowKeywords || []).join('、')}
                  onChange={(event) => updatePolicy({ blockedWindowKeywords: event.target.value.split(/[、,，\s]+/).filter(Boolean) })}
                />
              </label>
            </div>
          </div>
        </section>

        <section className="space-y-4">
          <div className="rounded-2xl border border-border bg-surface-alt/60 p-5">
            <h2 className="text-sm font-black text-text">执行参数</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <label className="block">
                <span className="mb-1 block text-xs font-bold text-text-muted">截图质量</span>
                <Input type="number" value={config.capture?.quality || 82} onChange={(event) => updateCapture({ quality: Number(event.target.value || 82) })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-bold text-text-muted">截图最大宽度</span>
                <Input type="number" value={config.capture?.maxWidth || 1600} onChange={(event) => updateCapture({ maxWidth: Number(event.target.value || 1600) })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-bold text-text-muted">截图格式</span>
                <Select className="w-full" value={config.capture?.format || 'jpeg'} onChange={(event) => updateCapture({ format: event.target.value })}>
                  <option value="jpeg">JPEG</option>
                  <option value="png">PNG</option>
                </Select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-bold text-text-muted">点击延迟 ms</span>
                <Input type="number" value={config.action?.clickDelayMs || 120} onChange={(event) => updateAction({ clickDelayMs: Number(event.target.value || 120) })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-bold text-text-muted">输入延迟 ms</span>
                <Input type="number" value={config.action?.typeDelayMs || 20} onChange={(event) => updateAction({ typeDelayMs: Number(event.target.value || 20) })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-bold text-text-muted">动作超时 ms</span>
                <Input type="number" value={config.action?.timeoutMs || 30000} onChange={(event) => updateAction({ timeoutMs: Number(event.target.value || 30000) })} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-bold text-text-muted">微信发送模式</span>
                <Select className="w-full" value={config.wechat?.sendMode || 'draft_only'} onChange={(event) => updateWechat({ sendMode: event.target.value })}>
                  <option value="draft_only">只允许草稿</option>
                  <option value="paste_only">只粘贴不发送</option>
                  <option value="auto_enter">允许回车发送</option>
                </Select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-bold text-text-muted">未读检测</span>
                <Select className="w-full" value={config.wechat?.detectUnreadMode || 'hybrid'} onChange={(event) => updateWechat({ detectUnreadMode: event.target.value })}>
                  <option value="hybrid">混合</option>
                  <option value="vision">视觉</option>
                  <option value="pixel">像素</option>
                </Select>
              </label>
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-surface-alt/60 p-5">
            <div className="flex items-center justify-between gap-4">
              <h2 className="text-sm font-black text-text">运行状态</h2>
              <Button variant="quiet" onClick={refresh} disabled={busy}>刷新</Button>
            </div>
            <div className="mt-4 grid gap-2 text-sm text-text-muted md:grid-cols-2">
              <div>目录：{status?.config.resolvedAgentDir || '未找到'}</div>
              <div>进程：{status?.running ? `PID ${status.pid}` : '未运行'}</div>
              <div>API：{status?.apiReady ? `127.0.0.1:${status.config.port}` : '未就绪'}</div>
              <div>Token：{status?.config.tokenPreview || '未生成'}</div>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Button variant="success" onClick={() => run('启动桌面代理', () => desktopAgentApi.start())} disabled={busy || status?.running}>启动</Button>
              <Button variant="danger" onClick={() => run('停止桌面代理', () => desktopAgentApi.stop())} disabled={busy || !status?.running}>停止</Button>
              <Button variant="quiet" onClick={() => run('健康检查', () => desktopAgentApi.health())} disabled={busy}>健康检查</Button>
              <Button variant="quiet" onClick={captureScreenshot} disabled={busy || !status?.apiReady}>截图测试</Button>
            </div>
          </div>

          <div className="min-h-[300px] overflow-hidden rounded-2xl border border-border bg-black/20">
            {screenshotSrc ? (
              <img src={screenshotSrc} alt="Desktop screenshot" className="h-full max-h-[560px] w-full object-contain" />
            ) : (
              <div className="flex h-[300px] items-center justify-center text-sm text-text-subtle">截图测试后会显示桌面画面</div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
};
