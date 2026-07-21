import React from 'react';
import { Command } from '@tauri-apps/plugin-shell';
import { RefreshCcw, Save, SquareTerminal, Terminal } from 'lucide-react';
import { Button, Chip, Field, Input, InlineState, Panel, SectionHeader, Select, Tabs, TextArea } from '../components/ui';
import { loadSettingsSnapshot, readConfigValue, saveAuthProfiles, saveDesktopAgentConfig, writeConfigValue } from '../api/adapters';
import { applyLauncherUpdate, checkLauncherUpdate, type LauncherUpdateInfo } from '../api/client';
import { makeCommandOptions, resolvePortableBasePath } from '../api/runtimeCommand';
import { maskSecret } from '../lib/format';
import { useAsync } from '../lib/useAsync';
import { usePreviewStore } from '../store/appStore';

type GatewayForm = {
  baseUrl: string;
  apiKey: string;
  model: string;
};

type ImageForm = {
  baseUrl: string;
  apiKey: string;
  model: string;
};

type VideoForm = {
  providerId: string;
  apiBase: string;
  apiKey: string;
  model: string;
};

const AUTH_PROFILES_PATH = 'data/.openclaw/agents/main/agent/auth-profiles.json';
const IMAGE_CONFIG_PATH = 'imgapi_config.json';
const VIDEO_CONFIG_PATH = 'videoapi_config.json';
const OPENCLAW_CONFIG_PATH = 'data/.openclaw/openclaw.json';
const OPENAI_OAUTH_FALLBACK_MS = '120000';

function normalizeOpenAiProxy(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
}

function openAiProxyEnv(proxy: string): Record<string, string> {
  if (!proxy) return {};
  return {
    OPENCLAW_OAUTH_PROXY: proxy,
    HTTPS_PROXY: proxy,
    HTTP_PROXY: proxy,
    ALL_PROXY: proxy,
    https_proxy: proxy,
    http_proxy: proxy,
    all_proxy: proxy,
  };
}

function withOpenAiOAuthEnv<T extends object>(options: T, proxy: string): T & { env: Record<string, string> } {
  const existingEnv = 'env' in options && options.env && typeof options.env === 'object'
    ? options.env as Record<string, string>
    : {};
  return {
    ...options,
    env: {
      ...existingEnv,
      OPENCLAW_OAUTH_MANUAL_FALLBACK_MS: OPENAI_OAUTH_FALLBACK_MS,
      ...openAiProxyEnv(proxy),
    },
  };
}

export function SettingsPage() {
  const storeSettings = usePreviewStore((state) => state.settings);
  const updateSettings = usePreviewStore((state) => state.updateSettings);
  const pushToast = usePreviewStore((state) => state.pushToast);
  const openAiProxy = normalizeOpenAiProxy(storeSettings.openaiProxy || '');
  const [mode, setMode] = React.useState<'basic' | 'advanced'>('basic');
  const [proxyCheck, setProxyCheck] = React.useState<{ state: 'idle' | 'checking' | 'reachable' | 'unreachable' }>({ state: 'idle' });
  const handleCheckOpenAiProxy = React.useCallback(async () => {
    setProxyCheck({ state: 'checking' });
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);
      try {
        await fetch('https://auth.openai.com', { method: 'HEAD', mode: 'no-cors', signal: controller.signal });
        setProxyCheck({ state: 'reachable' });
      } finally {
        clearTimeout(timer);
      }
    } catch {
      setProxyCheck({ state: 'unreachable' });
    }
  }, []);
  const { data, loading, error, refresh } = useAsync(() => loadSettingsSnapshot(storeSettings), [storeSettings], { cacheKey: "settings" });
  const [launcherUpdate, setLauncherUpdate] = React.useState<LauncherUpdateInfo | null>(null);
  const [launcherUpdateBusy, setLauncherUpdateBusy] = React.useState(false);
  const handleCheckLauncherUpdate = async () => {
    setLauncherUpdateBusy(true);
    try {
      const info = await checkLauncherUpdate();
      setLauncherUpdate(info);
      if (!info.configured) pushToast({ tone: 'warn', title: '未配置更新源', detail: '当前构建未内置启动器更新地址。' });
      else if (info.available) pushToast({ tone: 'ok', title: '发现新版本', detail: `${info.current} → ${info.latest}` });
      else pushToast({ tone: 'ok', title: '已是最新', detail: `当前 ${info.current}` });
    } catch (err) {
      pushToast({ tone: 'danger', title: '检查更新失败', detail: String(err) });
    } finally {
      setLauncherUpdateBusy(false);
    }
  };
  const handleApplyLauncherUpdate = async () => {
    if (!launcherUpdate?.url) return;
    setLauncherUpdateBusy(true);
    try {
      pushToast({ tone: 'ok', title: '正在下载更新', detail: '下载完成后将启动安装包并退出。' });
      await applyLauncherUpdate(launcherUpdate.url, launcherUpdate.sha256);
    } catch (err) {
      pushToast({ tone: 'danger', title: '更新失败', detail: String(err) });
      setLauncherUpdateBusy(false);
    }
  };
  const [authProfiles, setAuthProfiles] = React.useState<any>({});
  const [imageConfig, setImageConfig] = React.useState<any>({});
  const [videoConfig, setVideoConfig] = React.useState<any>({});
  const [openclawConfig, setOpenclawConfig] = React.useState<any>({});
  const [gatewayForm, setGatewayForm] = React.useState<GatewayForm>({ baseUrl: '', apiKey: '', model: 'gpt-4o' });
  const [imageForm, setImageForm] = React.useState<ImageForm>({ baseUrl: '', apiKey: '', model: 'gpt-image-2' });
  const [videoForm, setVideoForm] = React.useState<VideoForm>({ providerId: 'agnes', apiBase: 'https://apihub.agnes-ai.com/v1', apiKey: '', model: 'agnes-video-v2.0' });
  const [onboardRunning, setOnboardRunning] = React.useState(false);
  const [syncingDesktopRpa, setSyncingDesktopRpa] = React.useState(false);
  const [jsonDrafts, setJsonDrafts] = React.useState({
    authProfiles: '{}',
    imageConfig: '{}',
    videoConfig: '{}',
    openclawConfig: '{}',
  });

  // 表单只首次填充:避免后续任意一次 loadConfigs 重跑(如 storeSettings 变化)把用户
  // 正在编辑的网关地址/主模型等内容还原,表现为"打不进字/改了又跳回去"。
  const formsSeededRef = React.useRef(false);

  const loadConfigs = React.useCallback(async () => {
    try {
      const [auth, image, video, openclaw] = await Promise.all([
        readConfigValue(storeSettings, AUTH_PROFILES_PATH, { models: { providers: {} } }),
        readConfigValue(storeSettings, IMAGE_CONFIG_PATH, {}),
        readConfigValue(storeSettings, VIDEO_CONFIG_PATH, {}),
        readConfigValue(storeSettings, OPENCLAW_CONFIG_PATH, {}),
      ]);
      const nextAuth = auth || {};
      const nextImage = image || {};
      const nextVideo = video || {};
      const nextOpenclaw = openclaw || {};
      const gateway = formFromAuthProfiles(nextAuth);
      setAuthProfiles(nextAuth);
      setImageConfig(nextImage);
      setVideoConfig(nextVideo);
      setOpenclawConfig(nextOpenclaw);
      // 仅首次填充可编辑表单/草稿;之后保留用户输入,不被重载冲掉。
      if (!formsSeededRef.current) {
        formsSeededRef.current = true;
        setGatewayForm(gateway);
        setImageForm({
          baseUrl: stringValue(nextImage.baseUrl) || gateway.baseUrl,
          apiKey: stringValue(nextImage.apiKey),
          model: stringValue(nextImage.model) || 'gpt-image-2',
        });
        const loadedVideoBase = stringValue(nextVideo.apiBase) || stringValue(nextVideo.baseUrl) || gateway.baseUrl;
        const loadedVideoModel = stringValue(nextVideo.model);
        const loadedVideoProvider = inferVideoProviderId(nextVideo.providerId, loadedVideoBase, loadedVideoModel);
        setVideoForm({
          providerId: loadedVideoProvider,
          apiBase: loadedVideoBase || videoProviderDefaults(loadedVideoProvider).apiBase,
          apiKey: stringValue(nextVideo.apiKey) || stringValue(nextVideo.dashKey) || stringValue(nextImage.apiKey),
          model: loadedVideoModel || videoProviderDefaults(loadedVideoProvider).model,
        });
        setJsonDrafts({
          authProfiles: formatJson(nextAuth),
          imageConfig: formatJson(nextImage),
          videoConfig: formatJson(nextVideo),
          openclawConfig: formatJson(nextOpenclaw),
        });
      }
    } catch {
      setAuthProfiles({});
      setImageConfig({});
      setVideoConfig({});
      setOpenclawConfig({});
      setJsonDrafts({ authProfiles: '{}', imageConfig: '{}', videoConfig: '{}', openclawConfig: '{}' });
    }
  }, [storeSettings]);

  React.useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  const handleOpenClawOnboard = React.useCallback(async () => {
    if (onboardRunning) return;
    setOnboardRunning(true);
    try {
      const cwd = await resolvePortableBasePath(storeSettings);
      const args = ['scripts/openclaw-auth-terminal.mjs', 'onboard'];
      const options = withOpenAiOAuthEnv(makeCommandOptions(cwd), openAiProxy);
      let result;

      try {
        result = await Command.create('openclaw-onboard-terminal', args, options).execute();
      } catch {
        result = await Command.create('openclaw-onboard-terminal-node-exe', args, options).execute();
      }

      if (result.code === 0) {
        pushToast({
          tone: 'ok',
          title: 'OpenClaw 引导终端已打开',
          detail: 'PowerShell 会自动运行 openclaw onboard，你可以在终端里完整配置 OpenClaw。',
        });
      } else {
        pushToast({
          tone: 'danger',
          title: 'OpenClaw 引导终端启动失败',
          detail: commandResultDetail(result),
        });
      }
    } catch (err) {
      pushToast({ tone: 'danger', title: 'OpenClaw 引导终端启动失败', detail: String(err) });
    } finally {
      setOnboardRunning(false);
    }
  }, [onboardRunning, openAiProxy, pushToast, storeSettings]);


  const handleSaveConfigs = async () => {
    const nextAuth = withPrimaryProvider(authProfiles, gatewayForm);
    const nextImage = {
      ...(imageConfig || {}),
      gatewayMode: (imageConfig || {}).gatewayMode || 'manual',
      baseUrl: imageForm.baseUrl.trim(),
      apiKey: imageForm.apiKey.trim(),
      // Don't persist the 'gpt-image-2' placeholder — keep it empty so the server
      // (license) image model wins, matching how video config behaves.
      model: imageForm.model.trim() === 'gpt-image-2' ? '' : imageForm.model.trim(),
    };
    const nextVideo = {
      ...(videoConfig || {}),
      gatewayMode: (videoConfig || {}).gatewayMode || 'manual',
      providerId: inferVideoProviderId(videoForm.providerId, videoForm.apiBase, videoForm.model),
      apiBase: videoForm.apiBase.trim(),
      apiKey: videoForm.apiKey.trim(),
      model: videoForm.model.trim(),
    };
    const nextOpenclaw = sanitizeOpenClawConfig(openclawConfig);

    try {
      await Promise.all([
        saveAuthProfiles(storeSettings, nextAuth),
        writeConfigValue(storeSettings, IMAGE_CONFIG_PATH, nextImage),
        writeConfigValue(storeSettings, VIDEO_CONFIG_PATH, nextVideo),
        writeConfigValue(storeSettings, OPENCLAW_CONFIG_PATH, nextOpenclaw),
      ]);
      setAuthProfiles(nextAuth);
      setImageConfig(nextImage);
      setVideoConfig(nextVideo);
      setOpenclawConfig(nextOpenclaw);
      setJsonDrafts({
        authProfiles: formatJson(nextAuth),
        imageConfig: formatJson(nextImage),
        videoConfig: formatJson(nextVideo),
        openclawConfig: formatJson(nextOpenclaw),
      });
      pushToast({ tone: 'ok', title: '设置已保存', detail: '网关、图像、视频和启动器配置已写入对应文件。' });
      refresh();
    } catch (err) {
      pushToast({ tone: 'danger', title: '保存失败', detail: String(err) });
    }
  };

  const handleSyncDesktopRpa = async () => {
    const baseUrl = gatewayForm.baseUrl.trim();
    const apiKey = gatewayForm.apiKey.trim();
    const model = gatewayForm.model.trim();
    if (!baseUrl || !apiKey) {
      pushToast({ tone: 'warn', title: '缺少模型网关', detail: '先填写主模型地址和密钥。' });
      return;
    }
    setSyncingDesktopRpa(true);
    try {
      const provider = {
        apiKey,
        baseUrl,
        baseURL: baseUrl,
        model,
      };
      await saveDesktopAgentConfig(storeSettings, {
        provider,
        llm: provider,
        chatProvider: { config: provider },
      });
      pushToast({ tone: 'ok', title: '桌面 RPA 已同步', detail: model ? `${model} · ${baseUrl}` : baseUrl });
    } catch (err) {
      pushToast({ tone: 'danger', title: '同步桌面 RPA 失败', detail: String(err) });
    } finally {
      setSyncingDesktopRpa(false);
    }
  };

  return (
    <div className="page-grid">
      <section className="hero-band">
        <div className="hero-copy">
          <div className="eyebrow">统一设置</div>
          <h1>模型和运行时配置。</h1>
          <p>OpenClaw 引导、主模型、媒体生成和桌面 RPA 同步入口集中维护。</p>
        </div>
        <div className="hero-actions">
          <Button variant="primary" icon={RefreshCcw} onClick={() => { refresh(); loadConfigs(); }}>
            刷新
          </Button>
          <Button variant="secondary" icon={Save} onClick={handleSaveConfigs}>
            保存设置
          </Button>
        </div>
      </section>

      <Panel className="surface-panel surface-panel-wide">
        <Tabs
          value={mode}
          onChange={(value) => setMode(value as 'basic' | 'advanced')}
          items={[
            { key: 'basic', label: '普通模式' },
            { key: 'advanced', label: '高级模式' },
          ]}
        />
        <p className="settings-hint">普通模式只显示主模型接口和一键同步；图像/视频独立接口、OAuth 代理、桌面 RPA、配置文件和原始 JSON 在高级模式里。</p>
      </Panel>

      <section className="content-grid content-grid-settings">
        <Panel className="surface-panel surface-panel-wide">
          <SectionHeader
            eyebrow="统一密钥"
            title={mode === 'basic' ? '主模型密钥' : '模型、图像、视频密钥'}
            action={<Chip tone={gatewayForm.apiKey || imageForm.apiKey || videoForm.apiKey ? 'ok' : 'warn'}>{gatewayForm.apiKey || imageForm.apiKey || videoForm.apiKey ? '已配置' : '缺少密钥'}</Chip>}
          />
          <div className="settings-card-grid">
            <section className="settings-card">
              <div className="settings-card-title">主模型网关</div>
              <Field label="模型地址">
                <Input value={gatewayForm.baseUrl} onChange={(event) => setGatewayForm((state) => ({ ...state, baseUrl: event.target.value }))} placeholder="https://api.example.com/v1" />
              </Field>
              <Field label="模型密钥" hint={maskSecret(gatewayForm.apiKey)}>
                <Input type="password" value={gatewayForm.apiKey} onChange={(event) => setGatewayForm((state) => ({ ...state, apiKey: event.target.value }))} placeholder="示例：sk-..." />
              </Field>
              <Field label="主模型">
                <Input value={gatewayForm.model} onChange={(event) => setGatewayForm((state) => ({ ...state, model: event.target.value }))} placeholder="gpt-4o" />
              </Field>
              <div className="settings-card-actions">
                <Button
                  variant="secondary"
                  icon={SquareTerminal}
                  onClick={handleSyncDesktopRpa}
                  disabled={syncingDesktopRpa || !gatewayForm.baseUrl.trim() || !gatewayForm.apiKey.trim()}
                >
                  {syncingDesktopRpa ? '同步中...' : '同步授权配置'}
                </Button>
              </div>
            </section>

            {mode === 'advanced' ? (
              <section className="settings-card">
                <div className="settings-card-title">OpenClaw 引导终端</div>
                <p className="settings-card-copy">点击后会打开 PowerShell 终端并自动运行 openclaw onboard。模型、OAuth、Provider 和运行时配置都可以在原生 OpenClaw 引导流程里完成。</p>
                <Field label="OpenAI OAuth 代理" hint="用于 auth.openai.com 登录；留空则继承系统代理环境。">
                  <Input
                    value={storeSettings.openaiProxy || ''}
                    onChange={(event) => updateSettings({ openaiProxy: event.target.value })}
                    onBlur={(event) => updateSettings({ openaiProxy: normalizeOpenAiProxy(event.target.value) })}
                    placeholder="http://127.0.0.1:7890"
                  />
                </Field>
                <div className="settings-card-actions">
                  <Button
                    variant="secondary"
                    onClick={handleCheckOpenAiProxy}
                    disabled={proxyCheck.state === 'checking'}
                  >
                    {proxyCheck.state === 'checking' ? '检测中...' : '检测代理'}
                  </Button>
                </div>
                {proxyCheck.state === 'reachable' ? (
                  <InlineState tone="ok" title="无需代理" description="当前网络可以直接访问 auth.openai.com。" />
                ) : null}
                {proxyCheck.state === 'unreachable' ? (
                  <InlineState
                    tone="warn"
                    title="需要填写代理"
                    description={`当前网络无法访问 auth.openai.com，需要填写代理，例如：http://127.0.0.1:7890`}
                  />
                ) : null}
                <div className="settings-card-actions">
                  <Button
                    variant="primary"
                    icon={Terminal}
                    onClick={handleOpenClawOnboard}
                    disabled={onboardRunning}
                    className="settings-card-action"
                  >
                    {onboardRunning ? '正在打开...' : '打开 OpenClaw 配置向导'}
                  </Button>
                </div>
                <p className="settings-hint">将运行 openclaw onboard。</p>
              </section>
            ) : null}

            {mode === 'advanced' ? (
              <section className="settings-card">
                <div className="settings-card-title">图像生成</div>
                <Field label="图像地址">
                  <Input value={imageForm.baseUrl} onChange={(event) => setImageForm((state) => ({ ...state, baseUrl: event.target.value }))} placeholder="https://api.example.com/v1" />
                </Field>
                <Field label="图像密钥" hint={maskSecret(imageForm.apiKey)}>
                  <Input type="password" value={imageForm.apiKey} onChange={(event) => setImageForm((state) => ({ ...state, apiKey: event.target.value }))} placeholder="示例：图像密钥" />
                </Field>
                <Field label="图像模型">
                  <Input value={imageForm.model} onChange={(event) => setImageForm((state) => ({ ...state, model: event.target.value }))} placeholder="gpt-image-2" />
                </Field>
              </section>
            ) : null}

            {mode === 'advanced' ? (
              <section className="settings-card">
                <div className="settings-card-title">视频生成</div>
                <div className="form-grid form-grid-tight">
                  <Field label="服务商">
                    <Select
                      value={videoForm.providerId}
                      onChange={(event) => {
                        const providerId = event.target.value;
                        const defaults = videoProviderDefaults(providerId);
                        setVideoForm((state) => ({
                          ...state,
                          providerId,
                          apiBase: state.apiBase.trim() && state.providerId === providerId ? state.apiBase : defaults.apiBase,
                          model: defaults.model || state.model,
                        }));
                      }}
                    >
                      <option value="agnes">Agnes Video V2.0</option>
                      <option value="dashscope">DashScope / 快乐马</option>
                      <option value="seedance">火山引擎 Seedance</option>
                      <option value="custom">自定义兼容服务</option>
                    </Select>
                  </Field>
                  <Field label="模型">
                    <Input value={videoForm.model} onChange={(event) => setVideoForm((state) => ({ ...state, model: event.target.value }))} placeholder="happyhorse-1.0-t2v" />
                  </Field>
                </div>
                <Field label="视频地址">
                  <Input value={videoForm.apiBase} onChange={(event) => setVideoForm((state) => ({ ...state, apiBase: event.target.value }))} placeholder="https://apihub.agnes-ai.com/v1" />
                </Field>
                <Field label="视频密钥" hint={maskSecret(videoForm.apiKey)}>
                  <Input type="password" value={videoForm.apiKey} onChange={(event) => setVideoForm((state) => ({ ...state, apiKey: event.target.value }))} placeholder="示例：视频密钥" />
                </Field>
              </section>
            ) : null}
          </div>
        </Panel>

        <Panel className="surface-panel">
          <SectionHeader
            eyebrow="启动器更新"
            title="启动器自更新"
            subtitle="检查并安装新版启动器；更新只替换启动器本体，已下载的运行时层保留。"
            action={<Button variant="secondary" icon={RefreshCcw} onClick={handleCheckLauncherUpdate} disabled={launcherUpdateBusy}>检查启动器更新</Button>}
          />
          {launcherUpdate ? (
            <div className="detail-stack">
              <div className="detail-row"><span className="detail-label">当前版本</span><span className="detail-value">{launcherUpdate.current || '未知'}</span></div>
              <div className="detail-row"><span className="detail-label">最新版本</span><span className="detail-value">{launcherUpdate.configured ? launcherUpdate.latest : '未配置更新源'}</span></div>
              {launcherUpdate.notes ? (
                <div className="detail-row"><span className="detail-label">说明</span><span className="detail-value">{launcherUpdate.notes}</span></div>
              ) : null}
              {launcherUpdate.available ? (
                <Button variant="success" onClick={handleApplyLauncherUpdate} disabled={launcherUpdateBusy}>下载并安装 {launcherUpdate.latest}</Button>
              ) : null}
            </div>
          ) : (
            <p className="settings-hint">点击右上角「检查启动器更新」获取最新启动器版本（仅桌面安装版支持）。</p>
          )}
        </Panel>

        {mode === 'advanced' ? (
          <Panel className="surface-panel surface-panel-wide">
            <SectionHeader eyebrow="高级排障" title="配置文件 / 环境变量 / 原始 JSON" subtitle="日常不需要展开；排查和迁移时再查看。" />
            <details className="settings-details">
              <summary>展开高级排障</summary>

              <div className="settings-card-title">本页会写入的配置文件</div>
              <div className="path-list">
                {data?.configPaths.map((item) => (
                  <div key={item.key} className="path-card">
                    <strong>{item.key}</strong>
                    <span>{item.path}</span>
                    <Chip tone={item.writable ? 'ok' : 'warn'}>{item.writable ? '可写' : '只读'}</Chip>
                  </div>
                ))}
              </div>

              <div className="settings-card-title">相关环境变量</div>
              <div className="env-list">
                {data?.env.map((item) => (
                  <div key={item.key} className="env-row">
                    <strong>{item.key}</strong>
                    <span>{item.value}</span>
                    <Chip tone={item.value === '未设置' || item.value.includes('未') ? 'warn' : 'ok'}>{item.note}</Chip>
                  </div>
                ))}
              </div>

              <div className="settings-card-title">原始 JSON 快照</div>
              <div className="form-grid">
                <Field label="模型配置">
                  <TextArea rows={9} value={jsonDrafts.authProfiles} onChange={(event) => {
                    setJsonDrafts((state) => ({ ...state, authProfiles: event.target.value }));
                    const parsed = parseJson(event.target.value, authProfiles);
                    setAuthProfiles(parsed);
                    setGatewayForm(formFromAuthProfiles(parsed));
                  }} />
                </Field>
                <Field label="图像配置">
                  <TextArea rows={9} value={jsonDrafts.imageConfig} onChange={(event) => {
                    setJsonDrafts((state) => ({ ...state, imageConfig: event.target.value }));
                    const parsed = parseJson(event.target.value, imageConfig);
                    setImageConfig(parsed);
                    setImageForm({
                      baseUrl: stringValue(parsed.baseUrl),
                      apiKey: stringValue(parsed.apiKey),
                      model: stringValue(parsed.model) || 'gpt-image-2',
                    });
                  }} />
                </Field>
                <Field label="视频配置">
                  <TextArea rows={9} value={jsonDrafts.videoConfig} onChange={(event) => {
                    setJsonDrafts((state) => ({ ...state, videoConfig: event.target.value }));
                    const parsed = parseJson(event.target.value, videoConfig);
                    setVideoConfig(parsed);
                    setVideoForm({
                      providerId: inferVideoProviderId(parsed.providerId, parsed.apiBase || parsed.baseUrl, parsed.model),
                      apiBase: stringValue(parsed.apiBase) || stringValue(parsed.baseUrl),
                      apiKey: stringValue(parsed.apiKey) || stringValue(parsed.dashKey),
                      model: stringValue(parsed.model) || videoProviderDefaults(parsed.providerId).model,
                    });
                  }} />
                </Field>
                <Field label="OpenClaw 配置">
                  <TextArea rows={9} value={jsonDrafts.openclawConfig} onChange={(event) => {
                    setJsonDrafts((state) => ({ ...state, openclawConfig: event.target.value }));
                    setOpenclawConfig(parseJson(event.target.value, openclawConfig));
                  }} />
                </Field>
              </div>
            </details>
          </Panel>
        ) : null}
      </section>

      {loading ? <Panel className="panel-loading">正在读取设置快照...</Panel> : null}
      {error ? <Panel className="panel-error">{error}</Panel> : null}
    </div>
  );
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function formatJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJson(value: string, fallback: unknown = {}) {
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function cloneRecord(value: any): any {
  return JSON.parse(JSON.stringify(value || {}));
}

function formFromAuthProfiles(value: any): GatewayForm {
  const source = value && typeof value === 'object' ? value : {};
  const providers = source.models?.providers && typeof source.models.providers === 'object'
    ? source.models.providers
    : {};
  const primaryKey = source.models?.primary && providers[source.models.primary]
    ? source.models.primary
    : Object.keys(providers)[0];
  const provider = primaryKey ? providers[primaryKey] || {} : {};
  const models = Array.isArray(provider.models) ? provider.models : [];
  const firstModel = models
    .map((item: any) => typeof item === 'string' ? item : item?.id)
    .find(Boolean);
  return {
    baseUrl: stringValue(provider.baseUrl) || stringValue(provider.url),
    apiKey: stringValue(provider.apiKey),
    model: stringValue(firstModel) || stringValue(provider.model) || 'gpt-4o',
  };
}

function withPrimaryProvider(value: any, form: GatewayForm) {
  const next = cloneRecord(value);
  next.models = next.models || {};
  next.models.providers = next.models.providers || {};
  const primaryKey = next.models.primary && next.models.providers[next.models.primary]
    ? next.models.primary
    : Object.keys(next.models.providers)[0] || 'openclaw_gateway';
  next.models.primary = primaryKey;
  next.models.providers[primaryKey] = {
    ...(next.models.providers[primaryKey] || {}),
    id: primaryKey,
    name: next.models.providers[primaryKey]?.name || 'OpenClaw Gateway',
    baseUrl: form.baseUrl.trim(),
    apiKey: form.apiKey.trim(),
    models: form.model.trim() ? [form.model.trim()] : [],
  };
  return next;
}

function inferVideoProviderId(providerId: unknown, apiBase: unknown, model: unknown): string {
  const id = stringValue(providerId).toLowerCase();
  const base = stringValue(apiBase).toLowerCase();
  const modelId = stringValue(model).toLowerCase();
  if (id === 'agnes' || base.includes('agnes-ai.com') || modelId.startsWith('agnes-video')) return 'agnes';
  if (id === 'seedance' || base.includes('volces.com') || modelId.includes('seedance')) return 'seedance';
  if (id === 'custom') return 'custom';
  return id || 'dashscope';
}

function videoProviderDefaults(providerId: unknown) {
  const id = stringValue(providerId).toLowerCase();
  if (id === 'agnes') return { apiBase: 'https://apihub.agnes-ai.com/v1', model: 'agnes-video-v2.0' };
  if (id === 'seedance') return { apiBase: 'https://ark.cn-beijing.volces.com', model: 'doubao-seedance-2-0-pro-260215' };
  if (id === 'dashscope') return { apiBase: 'https://dashscope.aliyuncs.com/api/v1', model: 'happyhorse-1.0-t2v' };
  return { apiBase: '', model: '' };
}

function sanitizeOpenClawConfig(value: any) {
  const next = cloneRecord(value);
  delete next.launcherPreview;
  return next;
}

function commandResultDetail(result: { code?: number | null; stdout?: string; stderr?: string } | undefined) {
  const detail = [result?.stderr, result?.stdout].filter(Boolean).join('\n').trim();
  return detail || `退出码：${result?.code ?? 'unknown'}`;
}
