import React from 'react';
import { BusyOverlay, Button, Input, Select, showConfirm, showToast } from '../common';
import { loomClient } from '../../services/loomClient';
import { loomErrorText } from '../../services/loomErrors';
import type { AccountSnapshot, WireSnapshot } from '../../services/loomContracts';
import { useAppStore } from '../../stores/appStore';
import { accountCacheUsable, loadCachedAccount, saveCachedAccount } from '../../services/startupCache';
import { APP_DISPLAY_NAME } from '../../version';

type SourceMode = 'off' | 'managed' | 'custom';

type CustomProviderOption = {
  id: string;
  label: string;
  baseUrl: string;
};

const CUSTOM_PROVIDER_OPTIONS: CustomProviderOption[] = [
  { id: 'custom', label: '自定义...', baseUrl: '' },
  { id: 'openai', label: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
  { id: 'anthropic', label: 'Anthropic', baseUrl: 'https://api.anthropic.com/v1' },
  { id: 'gemini', label: 'Google Gemini', baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai' },
  { id: 'openrouter', label: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
  { id: 'deepseek', label: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1' },
  { id: 'moonshot', label: 'Moonshot - Kimi', baseUrl: 'https://api.moonshot.cn/v1' },
];

function providerOptionById(id: string): CustomProviderOption {
  return CUSTOM_PROVIDER_OPTIONS.find((option) => option.id === id) || CUSTOM_PROVIDER_OPTIONS[0];
}

function providerIdForName(name?: string): string {
  const normalized = (name || '').trim().toLowerCase();
  if (!normalized) return 'custom';
  return CUSTOM_PROVIDER_OPTIONS.find((option) => option.label.toLowerCase() === normalized)?.id || 'custom';
}

function firstChoice(values?: string[], preferred?: string): string {
  if (preferred && values?.includes(preferred)) return preferred;
  return values?.[0] || '';
}

const DEFAULT_PHONE_MODEL = 'qwen3.7-plus';
const PHONE_MODEL_IDS = new Set(['agnes-2.0-flash']);
const IMAGE_MODEL_MARKERS = ['image', 'dall-e', 'gpt-image', 'flux', 'midjourney', 'mj-', 'stable-diffusion', 'sd-', 'imagen', 'seedream'];
const VIDEO_MODEL_MARKERS = ['video', 'veo', 'sora', 'seedance', 'kling', 'wan', 'hailuo', 'runway', 'pika', 'luma', 'happyhorse'];

function looksLikeNonTextModel(model?: string): boolean {
  const value = (model || '').trim().toLowerCase();
  if (!value) return false;
  if (PHONE_MODEL_IDS.has(value)) return true;
  return IMAGE_MODEL_MARKERS.some((marker) => value.includes(marker)) || VIDEO_MODEL_MARKERS.some((marker) => value.includes(marker));
}

function textModelValues(values?: string[]): string[] {
  return (values || []).filter((model) => !looksLikeNonTextModel(model));
}

function firstTextChoice(values?: string[], preferred?: string): string {
  const safeValues = textModelValues(values);
  if (preferred && !looksLikeNonTextModel(preferred) && safeValues.includes(preferred)) return preferred;
  return safeValues[0] || '';
}

function mergeModelOptions(values?: string[], ...extras: Array<string | undefined>): string[] {
  const result: string[] = [];
  [...(values || []), ...extras].forEach((model) => {
    const value = model?.trim() || '';
    if (value && !result.includes(value)) result.push(value);
  });
  return result;
}

function compactValues(...values: Array<string | undefined>): string[] {
  return values.map((value) => value?.trim() || '').filter(Boolean);
}

function managedTextModelValues(account?: AccountSnapshot | null): string[] {
  const values = textModelValues(account?.models?.text);
  if (!account?.loggedIn) return values;
  const selected = account.selectedModels?.text;
  if (selected && !looksLikeNonTextModel(selected) && values.includes(selected)) {
    return mergeModelOptions(values, selected).filter((model) => !looksLikeNonTextModel(model));
  }
  return values;
}

const ModelSelect: React.FC<{
  label: string;
  value: string;
  values?: string[];
  disabled?: boolean;
  onChange: (value: string) => void;
}> = ({ label, value, values = [], disabled, onChange }) => (
  <label className="block">
    <div className="mb-2 text-xs font-bold text-text-muted">{label}</div>
    <Select aria-label={label} className="w-full" value={value} disabled={disabled || values.length === 0} onChange={(event) => onChange(event.target.value)}>
      {values.length === 0 ? <option value="">暂无可用模型</option> : null}
      {values.map((model) => <option key={model} value={model}>{model}</option>)}
    </Select>
  </label>
);

export const ModelsPage: React.FC = () => {
  const cachedAccountRef = React.useRef<AccountSnapshot | null>(loadCachedAccount());
  const [account, setAccount] = React.useState<AccountSnapshot | null>(cachedAccountRef.current);
  const [loading, setLoading] = React.useState(!accountCacheUsable(cachedAccountRef.current));
  const [busy, setBusy] = React.useState(false);
  const [usingCachedAccount, setUsingCachedAccount] = React.useState(accountCacheUsable(cachedAccountRef.current));
  const [textModel, setTextModel] = React.useState('');
  const [imageModel, setImageModel] = React.useState('');
  const [videoModel, setVideoModel] = React.useState('');
  const [sourceMode, setSourceMode] = React.useState<SourceMode>('managed');
  const [customProvider, setCustomProvider] = React.useState('OpenAI 兼容');
  const [customProviderId, setCustomProviderId] = React.useState('custom');
  const [customBaseUrl, setCustomBaseUrl] = React.useState('');
  const [customApiKey, setCustomApiKey] = React.useState('');
  const [customTextModel, setCustomTextModel] = React.useState('');
  const [customImageModel, setCustomImageModel] = React.useState('');
  const [customPhoneModel, setCustomPhoneModel] = React.useState('');
  const [customVideoModel, setCustomVideoModel] = React.useState('');
  const setCurrentPage = useAppStore((state) => state.setCurrentPage);

  const applyAccount = React.useCallback((next: AccountSnapshot | null, options: { cached?: boolean; persist?: boolean } = {}) => {
    setAccount(next);
    setTextModel(firstTextChoice(managedTextModelValues(next), next?.selectedModels?.text));
    setImageModel(firstChoice(next?.models?.image, next?.selectedModels?.image));
    setVideoModel(firstChoice(next?.models?.video, next?.selectedModels?.videoDraft));
    setUsingCachedAccount(Boolean(options.cached || next?.offline || next?.stale));
    if (options.persist && accountCacheUsable(next)) {
      saveCachedAccount(next);
      cachedAccountRef.current = loadCachedAccount();
    }
  }, []);

  const applyWireSnapshot = React.useCallback((wire?: WireSnapshot | null) => {
    if (!wire?.ok) return;
    if (wire.managedBy === 'custom_provider') {
      setSourceMode('custom');
      const provider = wire.provider || 'OpenAI 兼容';
      setCustomProvider(provider);
      setCustomProviderId(providerIdForName(provider));
      setCustomBaseUrl(wire.baseUrl || '');
      setCustomTextModel(wire.models?.text || '');
      setCustomImageModel(wire.models?.image || '');
      setCustomPhoneModel(wire.models?.phone && wire.models.phone !== DEFAULT_PHONE_MODEL ? wire.models.phone : '');
      setCustomVideoModel(wire.models?.video || '');
      return;
    }
    if (wire.managedBy === 'heang_account' || wire.managedBy === 'newapi_account') {
      setSourceMode('managed');
      if (wire.models?.text && !looksLikeNonTextModel(wire.models.text)) setTextModel(wire.models.text);
      if (wire.models?.image) setImageModel(wire.models.image);
      if (wire.models?.video) setVideoModel(wire.models.video);
    }
  }, []);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const resp = await loomClient.account.current();
      const next = resp.account || null;
      if (accountCacheUsable(next)) {
        applyAccount(next, { persist: true });
      } else {
        const cached = loadCachedAccount() || cachedAccountRef.current;
        if (accountCacheUsable(cached)) applyAccount(cached, { cached: true });
        else applyAccount(next);
      }
    } catch (error: any) {
      const cached = loadCachedAccount() || cachedAccountRef.current;
      if (accountCacheUsable(cached)) {
        applyAccount(cached, { cached: true });
      } else {
        showToast(loomErrorText(error, '读取模型失败'), 'error');
      }
    }
    try {
      const wireResp = await loomClient.wire.current();
      applyWireSnapshot(wireResp.wire);
    } catch {
      // Account snapshot is enough for offline browsing; wire status refreshes when Bridge is back.
    }
    setLoading(false);
  }, [applyAccount, applyWireSnapshot]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const syncModels = async () => {
    if (usingCachedAccount) {
      showToast('当前只是离线账号快照，请重新登录后再同步模型。', 'info');
      setCurrentPage('license');
      return;
    }
    setBusy(true);
    try {
      const resp = await loomClient.account.sync();
      applyAccount(resp.account || null, { persist: true });
      showToast('模型已同步', 'success');
    } catch (error: any) {
      showToast(loomErrorText(error, '同步失败'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const saveSelection = async () => {
    if (usingCachedAccount) {
      showToast('当前只是离线账号快照，请重新登录后再保存模型选择。', 'info');
      setCurrentPage('license');
      return;
    }
    setBusy(true);
    try {
      const resp = await loomClient.account.selectModels({ textModel, imageModel, videoModel });
      applyAccount(resp.account || null, { persist: true });
      showToast('模型选择已保存', 'success');
    } catch (error: any) {
      showToast(loomErrorText(error, '保存失败'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const applyCustomProvider = async () => {
    if (!customBaseUrl.trim() || !customApiKey.trim() || !customTextModel.trim()) {
      showToast('请填写 Provider URL、API Key 和默认文本模型', 'error');
      return;
    }
    setBusy(true);
    try {
      const providerName = customProviderId === 'custom'
        ? customProvider.trim()
        : providerOptionById(customProviderId).label;
      const resp = await loomClient.wire.custom({
        provider: providerName || '自定义...',
        baseUrl: customBaseUrl.trim(),
        apiKey: customApiKey.trim(),
        textModel: customTextModel.trim(),
        imageModel: customImageModel.trim(),
        phoneModel: customPhoneModel.trim(),
        videoModel: customVideoModel.trim(),
      });
      applyWireSnapshot(resp.wire);
      setCustomApiKey('');
      showToast('第三方模型配置已应用', 'success');
    } catch (error: any) {
      showToast(loomErrorText(error, '应用第三方配置失败'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const disableModelSource = async () => {
    const confirmed = await showConfirm({
      title: '关闭 LOOM 模型来源',
      message: '这会把 LOOM 管理的运行时模型配置回滚到上一份可用配置。继续吗？',
      confirmText: '关闭并回滚',
      tone: 'danger',
    });
    if (!confirmed) return;
    setBusy(true);
    try {
      await loomClient.wire.rollback();
      setSourceMode('off');
      showToast('LOOM 模型来源已关闭，并已回滚到上一份可用配置', 'success');
    } catch (error: any) {
      showToast(loomErrorText(error, '没有可回滚的模型配置'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const loggedIn = Boolean(account?.loggedIn);
  const managedWritable = loggedIn && !usingCachedAccount;
  const managedTextModels = managedTextModelValues(account);
  const managedImageModels = mergeModelOptions(account?.models?.image);
  const managedVideoModels = mergeModelOptions(account?.models?.video);
  const missingManagedTextModel = sourceMode === 'managed' && loggedIn && !usingCachedAccount && managedTextModels.length === 0;
  const managedSaveEnabled = managedWritable && !missingManagedTextModel;
  const textCount = sourceMode === 'custom' ? compactValues(customTextModel).length : managedTextModels.length;
  const imageCount = sourceMode === 'custom' ? compactValues(customImageModel).length : managedImageModels.length;
  const videoCount = sourceMode === 'custom' ? compactValues(customVideoModel).length : managedVideoModels.length;
  const summaryTextModels = sourceMode === 'custom' ? compactValues(customTextModel) : managedTextModels;
  const summaryImageModels = sourceMode === 'custom' ? compactValues(customImageModel) : managedImageModels;
  const summaryVideoModels = sourceMode === 'custom' ? compactValues(customVideoModel) : managedVideoModels;
  const selectCustomProvider = (providerId: string) => {
    const option = providerOptionById(providerId);
    setCustomProviderId(providerId);
    setCustomProvider(option.label);
    if (option.baseUrl) setCustomBaseUrl(option.baseUrl);
  };

  const busyOverlayTitle = loading ? '正在读取模型' : sourceMode === 'custom' ? '正在应用第三方配置' : '正在同步模型';

  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface">
      <BusyOverlay active={loading || busy} title={busyOverlayTitle} detail={`${APP_DISPLAY_NAME} 正在读取或写入模型配置。`} />
      <header className="shrink-0 border-b border-border/70 bg-surface px-8 py-7">
        <div className="flex items-end justify-between gap-6">
          <div>
            <div className="text-[11px] font-bold tracking-[0.42em] text-accent">模型</div>
            <h1 className="mt-2 text-[30px] font-black leading-tight text-text">模型选择</h1>
          </div>
          <div className="flex items-center gap-3">
            <span className="rounded-full border border-border/70 bg-surface-alt/50 px-3 py-2 text-xs font-bold text-text">
              {loggedIn ? `文本 ${textCount} / 图像 ${imageCount} / 视频 ${videoCount}` : '未登录'}
            </span>
            <Button variant="quiet" onClick={refresh} disabled={loading || busy}>刷新</Button>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-7">
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className="rounded-[20px] border border-border/80 bg-surface-alt/30 p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-black text-text">模型来源</h2>
                <p className="mt-1 text-sm text-text-muted">托管账号可一键配置，也可以接入自己的第三方 OpenAI 兼容接口。</p>
              </div>
              <div className="flex rounded-[14px] border border-border/80 bg-surface/35 p-1">
                <SourceModeButton active={sourceMode === 'off'} onClick={() => void disableModelSource()}>关闭</SourceModeButton>
                <SourceModeButton active={sourceMode === 'managed'} onClick={() => setSourceMode('managed')}>一键配置</SourceModeButton>
                <SourceModeButton active={sourceMode === 'custom'} onClick={() => setSourceMode('custom')}>自定义</SourceModeButton>
              </div>
            </div>

            {sourceMode === 'off' ? (
              <div className="mt-6 rounded-[16px] border border-border/70 bg-surface/35 p-5 text-sm leading-6 text-text-muted">
                LOOM 模型来源已关闭。运行时配置已回滚到上一份可用配置，之后不会继续由 LOOM 覆盖。
              </div>
            ) : sourceMode === 'custom' ? (
              <div data-model-custom-provider-card className="mt-6 rounded-[18px] border border-accent/20 bg-accent/[0.04] p-5">
                <div className="rounded-[14px] border border-status-danger/20 bg-status-danger/10 px-4 py-3 text-sm font-bold text-status-danger">
                  使用陌生的第三方 API Key 需谨慎。
                </div>
                <div className="mt-5 grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
                  <label className="block">
                    <div className="mb-2 text-xs font-bold text-text-muted">Provider</div>
                    <Select
                      data-model-custom-provider-select
                      className="w-full"
                      value={customProviderId}
                      onChange={(event) => selectCustomProvider(event.target.value)}
                    >
                      {CUSTOM_PROVIDER_OPTIONS.map((option) => (
                        <option key={option.id} value={option.id}>{option.label}</option>
                      ))}
                    </Select>
                  </label>
                  <label className="block">
                    <div className="mb-2 text-xs font-bold text-text-muted">默认文本模型</div>
                    <Input value={customTextModel} onChange={(event) => setCustomTextModel(event.target.value)} placeholder="例如 qwen3.7-plus、gpt-4o" />
                  </label>
                  {customProviderId === 'custom' ? (
                    <label className="block md:col-span-2">
                      <div className="mb-2 text-xs font-bold text-text-muted">Provider 名称</div>
                      <Input value={customProvider} onChange={(event) => setCustomProvider(event.target.value)} placeholder="自定义..." />
                    </label>
                  ) : null}
                  <label className="block md:col-span-2">
                    <div className="mb-2 text-xs font-bold text-text-muted">自定义 URL</div>
                    <Input value={customBaseUrl} onChange={(event) => setCustomBaseUrl(event.target.value)} placeholder="https://example.com/v1" />
                  </label>
                  <label className="block md:col-span-2">
                    <div className="mb-2 flex items-center justify-between gap-3 text-xs font-bold text-text-muted">
                      <span>API Key</span>
                      <span className="text-accent">仅保存在本机</span>
                    </div>
                    <Input type="password" value={customApiKey} onChange={(event) => setCustomApiKey(event.target.value)} placeholder="仅保存在本机" autoComplete="off" />
                  </label>
                  <label className="block">
                    <div className="mb-2 text-xs font-bold text-text-muted">图像模型</div>
                    <Input value={customImageModel} onChange={(event) => setCustomImageModel(event.target.value)} placeholder="可选，例如 gpt-image-1" />
                  </label>
                  <label className="block">
                    <div className="mb-2 text-xs font-bold text-text-muted">手机模型</div>
                    <Input data-custom-phone-model-input value={customPhoneModel} onChange={(event) => setCustomPhoneModel(event.target.value)} placeholder="可选，留空使用手机默认模型" />
                  </label>
                  <label className="block md:col-span-2">
                    <div className="mb-2 text-xs font-bold text-text-muted">视频模型草案</div>
                    <Input value={customVideoModel} onChange={(event) => setCustomVideoModel(event.target.value)} placeholder="可选，仅保存草案，不切换视频 provider" />
                  </label>
                </div>
                <div className="mt-5 flex flex-wrap items-center gap-3">
                  <Button variant="primary" onClick={applyCustomProvider} disabled={busy || loading}>
                    {busy ? '处理中...' : '应用第三方配置'}
                  </Button>
                  <span className="text-xs font-bold text-text-muted">粘贴上游平台生成的密钥；不会上传，不写入日志。</span>
                </div>
              </div>
            ) : !loggedIn ? (
              <div className="mt-6 rounded-[16px] border border-border/80 bg-surface/35 p-5">
                <h3 className="text-base font-black text-text">需要登录模型账号</h3>
                <p className="mt-2 text-sm leading-6 text-text-muted">登录后可一键同步文本、图像和手机模型。视频模型只作为草案展示，不会自动切换视频通道。</p>
                <Button className="mt-5" variant="primary" onClick={() => setCurrentPage('license')}>前往登录</Button>
              </div>
            ) : (
              <div className="mt-6 grid gap-5">
                {missingManagedTextModel ? (
                  <div className="rounded-[16px] border border-status-danger/30 bg-status-danger/10 p-4 text-sm leading-6 text-status-danger">
                    当前模型账号没有可用文本模型。请在模型服务中生成包含文本模型的专用 Key，或切到自定义 API Key。
                  </div>
                ) : null}
                <ModelSelect label="默认文本模型" value={textModel} values={managedTextModels} disabled={busy} onChange={setTextModel} />
                <ModelSelect label="默认图像模型" value={imageModel} values={managedImageModels} disabled={busy} onChange={setImageModel} />
                <ModelSelect label="视频模型草案" value={videoModel} values={managedVideoModels} disabled={busy} onChange={setVideoModel} />
                <div className="flex flex-wrap gap-3">
                  <Button variant="primary" onClick={saveSelection} disabled={busy || loading || !managedSaveEnabled}>{busy ? '处理中...' : '保存选择'}</Button>
                  <Button variant="quiet" onClick={syncModels} disabled={busy || loading || !managedWritable}>同步模型</Button>
                </div>
                <div className="rounded-[16px] border border-status-warning/30 bg-status-warning/10 p-4 text-sm text-status-warning">
                  视频模型仅保存为草案选择，不会写入视频 provider 或 API Key 配置。
                </div>
              </div>
            )}
          </section>

          <aside className="space-y-4">
            <SummaryPanel title="文本" values={summaryTextModels} selected={sourceMode === 'custom' ? customTextModel : textModel} />
            <SummaryPanel title="图像" values={summaryImageModels} selected={sourceMode === 'custom' ? customImageModel : imageModel} />
            <SummaryPanel title="视频" values={summaryVideoModels} selected={sourceMode === 'custom' ? customVideoModel : videoModel} />
          </aside>
        </div>
      </div>
    </div>
  );
};

const SourceModeButton: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }> = ({ active, className = '', ...props }) => (
  <button
    type="button"
    className={`rounded-[11px] px-4 py-2 text-sm font-black transition ${
      active ? 'bg-accent text-accent-ink shadow-[0_10px_22px_rgba(8,60,49,0.18)]' : 'text-text-muted hover:bg-hover hover:text-text'
    } ${className}`}
    {...props}
  />
);

const SummaryPanel: React.FC<{ title: string; values?: string[]; selected: string }> = ({ title, values = [], selected }) => (
  <div className="rounded-[20px] border border-border/80 bg-surface-alt/30 p-5">
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-base font-black text-text">{title}</h2>
      <span className="rounded-full border border-border/70 bg-surface/35 px-3 py-1 text-xs font-bold text-text-muted">{values.length}</span>
    </div>
    <div className="mt-3 truncate text-sm font-bold text-text" title={selected || '暂无'}>{selected || '暂无'}</div>
    <div className="mt-3 space-y-1">
      {values.slice(0, 6).map((model) => <div key={model} className="truncate text-xs text-text-muted" title={model}>{model}</div>)}
    </div>
  </div>
);
