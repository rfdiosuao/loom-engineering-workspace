import React from 'react';
import * as QRCode from 'qrcode';
import { Command, type Child, type TerminatedPayload } from '@tauri-apps/plugin-shell';
import { Link2, MessageCircleMore, PlayCircle, QrCode, RefreshCcw, RotateCcw, Save, Square, Webhook } from 'lucide-react';
import {
  Button,
  Chip,
  EmptyState,
  Field,
  InlineState,
  Input,
  Panel,
  SectionHeader,
  Select,
  StatTile,
  TextArea,
  Toggle,
  cx,
} from '../components/ui';
import { loadDesktopSnapshot, loadSettingsSnapshot, readConfigValue, writeConfigValue } from '../api/adapters';
import { makeCommandOptions, normalizeCommandOutput, resolvePortableBasePath } from '../api/runtimeCommand';
import { formatDateTime, maskSecret } from '../lib/format';
import { useAsync } from '../lib/useAsync';
import { usePreviewStore } from '../store/appStore';

type PlatformKey = 'feishu' | 'wecom' | 'wechat' | 'dingtalk' | 'slack' | 'webhook';
type ChannelMode = 'push' | 'reply' | 'relay';
type DeliveryTarget = 'service' | 'desktop' | 'phone';
type MessageMode = 'text' | 'markdown' | 'card';
type ScanPlatformKey = Extract<PlatformKey, 'feishu' | 'wechat' | 'dingtalk'>;
type FieldKey =
  | 'channelMode'
  | 'endpoint'
  | 'webhookUrl'
  | 'callbackUrl'
  | 'appId'
  | 'appSecret'
  | 'token'
  | 'messageMode'
  | 'deliveryTarget'
  | 'notes';

interface IntegrationDraft {
  enabled: boolean;
  channelMode: ChannelMode;
  endpoint: string;
  webhookUrl: string;
  callbackUrl: string;
  appId: string;
  appSecret: string;
  token: string;
  messageMode: MessageMode;
  deliveryTarget: DeliveryTarget;
  notes: string;
}

interface IntegrationConfig {
  selectedId: PlatformKey;
  updatedAt: string;
  platforms: Record<PlatformKey, IntegrationDraft>;
}

const INTEGRATIONS_CONFIG_PATH = 'data/.openclaw/launcher/platform-integrations.json';
const PLATFORM_ORDER: PlatformKey[] = ['feishu', 'wechat', 'wecom', 'dingtalk', 'slack', 'webhook'];

const SCAN_BINDING_META: Record<ScanPlatformKey, {
  label: string;
  commandName: string;
  fallbackCommandName: string;
  args: string[];
  hint: string;
}> = {
  feishu: {
    label: '飞书扫码绑定',
    commandName: 'bot-plugin-login-feishu',
    fallbackCommandName: 'bot-plugin-login-feishu-node-exe',
    args: ['scripts/bot-plugin-helper.mjs', 'login-feishu'],
    hint: '沿用旧启动器的飞书插件绑定命令，二维码或网页登录会输出在这里。',
  },
  wechat: {
    label: '微信扫码绑定',
    commandName: 'bot-plugin-login-weixin',
    fallbackCommandName: 'bot-plugin-login-weixin-node-exe',
    args: ['scripts/bot-plugin-helper.mjs', 'login-weixin'],
    hint: '微信账号不在启动器里保存，只通过命令输出的二维码完成绑定。',
  },
  dingtalk: {
    label: '钉钉扫码授权',
    commandName: 'bot-plugin-login-dingtalk',
    fallbackCommandName: 'bot-plugin-login-dingtalk-node-exe',
    args: ['scripts/bot-plugin-helper.mjs', 'login-dingtalk'],
    hint: '调用钉钉官方 OpenClaw 连接器扫码授权，配置会写入启动器便携 data/.openclaw/openclaw.json。',
  },
};

const PLATFORM_META: Record<PlatformKey, {
  label: string;
  desc: string;
  hint: string;
  fields: FieldKey[];
  required: FieldKey[];
}> = {
  feishu: {
    label: '飞书',
    desc: '机器人、应用事件与群通知',
    hint: '适合把内测通知、运行告警和审批流推送到飞书群或飞书应用。',
    fields: ['channelMode', 'webhookUrl', 'appId', 'appSecret', 'callbackUrl', 'messageMode', 'deliveryTarget', 'notes'],
    required: ['webhookUrl'],
  },
  wechat: {
    label: '微信',
    desc: '复用桌面 RPA 的自动回复通道',
    hint: '个人微信不在启动器里直接托管账号，优先通过桌面 RPA 的受控 send/unread 接口桥接。',
    fields: ['channelMode', 'endpoint', 'token', 'callbackUrl', 'messageMode', 'deliveryTarget', 'notes'],
    required: ['endpoint'],
  },
  wecom: {
    label: '企业微信',
    desc: '企业机器人与应用消息',
    hint: '适合邀请制内测、企业群通知和客服侧消息同步。',
    fields: ['channelMode', 'webhookUrl', 'appId', 'token', 'callbackUrl', 'messageMode', 'deliveryTarget', 'notes'],
    required: ['webhookUrl'],
  },
  dingtalk: {
    label: '钉钉',
    desc: '官方机器人与 Stream 模式通道',
    hint: '适合把 OpenClaw 作为钉钉内部机器人使用，通过官方连接器扫码创建并授权。',
    fields: ['channelMode', 'appId', 'appSecret', 'messageMode', 'deliveryTarget', 'notes'],
    required: [],
  },
  slack: {
    label: 'Slack',
    desc: '海外团队通知通道',
    hint: '用于英文团队、开源协作或社区频道的事件通知。',
    fields: ['channelMode', 'webhookUrl', 'token', 'messageMode', 'deliveryTarget', 'notes'],
    required: ['webhookUrl'],
  },
  webhook: {
    label: '自定义 Webhook',
    desc: '给其他平台预留的标准出口',
    hint: '用于任何没有专门页面的平台，先用标准 Webhook 协议接入。',
    fields: ['channelMode', 'endpoint', 'token', 'callbackUrl', 'messageMode', 'deliveryTarget', 'notes'],
    required: ['endpoint'],
  },
};

export function IntegrationsPage() {
  const settings = usePreviewStore((state) => state.settings);
  const pushToast = usePreviewStore((state) => state.pushToast);
  const { data, loading, error, refresh } = useAsync(async () => {
    const [desktop, settingsSnapshot, rawConfig] = await Promise.all([
      loadDesktopSnapshot(settings),
      loadSettingsSnapshot(settings),
      readConfigValue(settings, INTEGRATIONS_CONFIG_PATH, createDefaultConfig()),
    ]);
    return {
      desktop,
      settingsSnapshot,
      config: normalizeConfig(rawConfig),
    };
  }, [settings], { cacheKey: 'integrations' });

  const [draft, setDraft] = React.useState<IntegrationConfig>(() => createDefaultConfig());
  const [bindingTarget, setBindingTarget] = React.useState<ScanPlatformKey | null>(null);
  const [bindingRunning, setBindingRunning] = React.useState(false);
  const [bindingLog, setBindingLog] = React.useState<string[]>([]);
  const [bindingQrUrl, setBindingQrUrl] = React.useState('');
  const [bindingQrDataUrl, setBindingQrDataUrl] = React.useState('');
  const bindingChildRef = React.useRef<Child | null>(null);
  const bindingOutputRef = React.useRef<HTMLPreElement>(null);

  React.useEffect(() => {
    if (data?.config) setDraft(data.config);
  }, [data?.config]);

  React.useEffect(() => {
    if (!bindingOutputRef.current) return;
    bindingOutputRef.current.scrollTop = bindingOutputRef.current.scrollHeight;
  }, [bindingLog]);

  React.useEffect(() => {
    let cancelled = false;
    if (!bindingQrUrl) {
      setBindingQrDataUrl('');
      return () => {
        cancelled = true;
      };
    }
    QRCode.toDataURL(bindingQrUrl, {
      errorCorrectionLevel: 'M',
      margin: 3,
      width: 360,
      color: { dark: '#05080d', light: '#ffffff' },
    })
      .then((url) => {
        if (!cancelled) setBindingQrDataUrl(url);
      })
      .catch(() => {
        if (!cancelled) setBindingQrDataUrl('');
      });
    return () => {
      cancelled = true;
    };
  }, [bindingQrUrl]);

  React.useEffect(() => () => {
    bindingChildRef.current?.kill().catch(() => undefined);
    bindingChildRef.current = null;
  }, []);

  const selectedId = draft.selectedId;
  const selectedMeta = PLATFORM_META[selectedId];
  const selectedDraft = draft.platforms[selectedId];
  const selectedScanMeta = isScanPlatform(selectedId) ? SCAN_BINDING_META[selectedId] : null;
  const enabledCount = PLATFORM_ORDER.filter((id) => draft.platforms[id]?.enabled).length;
  const desktopConfig = (data?.desktop?.config || {}) as Record<string, any>;
  const desktopPolicy = (desktopConfig.policy || {}) as Record<string, any>;
  const wechatConfig = (desktopConfig.wechat || {}) as Record<string, any>;
  const desktopBridgeReady = Boolean(data?.desktop?.present && desktopConfig.enabled && desktopPolicy.allowWechatSend);

  const updateSelected = (patch: Partial<IntegrationDraft>) => {
    setDraft((state) => ({
      ...state,
      platforms: {
        ...state.platforms,
        [state.selectedId]: {
          ...state.platforms[state.selectedId],
          ...patch,
        },
      },
    }));
  };

  const choosePlatform = (id: PlatformKey) => {
    setDraft((state) => ({ ...state, selectedId: id }));
  };

  const handleSave = async () => {
    const next = { ...draft, updatedAt: new Date().toISOString() };
    try {
      await writeConfigValue(settings, INTEGRATIONS_CONFIG_PATH, next);
      setDraft(next);
      pushToast({ tone: 'ok', title: '平台对接配置已保存', detail: INTEGRATIONS_CONFIG_PATH });
      refresh();
    } catch (err) {
      pushToast({ tone: 'danger', title: '保存失败', detail: String(err) });
    }
  };

  const handleProbe = () => {
    const result = validatePlatform(selectedId, selectedDraft, desktopBridgeReady);
    pushToast({
      tone: result.tone,
      title: result.title,
      detail: result.detail,
    });
  };

  const appendBindingLog = React.useCallback((data: unknown) => {
    const clean = normalizeCommandOutput(data);
    if (!clean) return;
    const url = extractBindingUrl(clean);
    if (url) setBindingQrUrl(url);
    setBindingLog((items) => [...items, clean]);
  }, []);

  const spawnBindingCommand = React.useCallback(async (
    platform: ScanPlatformKey,
    cwd: string | undefined,
    onClose: (payload: TerminatedPayload) => void | Promise<void>,
  ) => {
    const meta = SCAN_BINDING_META[platform];
    const options = makeCommandOptions(cwd);
    const attach = (command: Command<string>) => {
      command.stdout.on('data', appendBindingLog);
      command.stderr.on('data', appendBindingLog);
      command.on('close', onClose);
      command.on('error', (error) => {
        setBindingRunning(false);
        appendBindingLog(`\n[error] ${error}\n`);
        pushToast({ tone: 'danger', title: `${meta.label}启动失败`, detail: String(error) });
      });
    };

    try {
      const command = Command.create(meta.commandName, meta.args, options);
      attach(command);
      return await command.spawn();
    } catch (error) {
      appendBindingLog(`\n[fallback] ${meta.commandName} 不可用，改用 ${meta.fallbackCommandName}\n`);
      const fallback = Command.create(meta.fallbackCommandName, meta.args, options);
      attach(fallback);
      return await fallback.spawn();
    }
  }, [appendBindingLog, pushToast]);

  const handleScanBind = React.useCallback(async (platform: ScanPlatformKey) => {
    if (bindingRunning) return;
    const meta = SCAN_BINDING_META[platform];
    setBindingTarget(platform);
    setBindingLog([]);
    setBindingQrUrl('');
    setBindingQrDataUrl('');
    setBindingRunning(true);
    appendBindingLog(`> node ${meta.args.join(' ')}\n`);
    appendBindingLog('[launcher] 请在输出区扫描二维码，或按命令提示打开网页登录链接。\n');

    try {
      const cwd = await resolvePortableBasePath(settings);
      const child = await spawnBindingCommand(platform, cwd, async (payload) => {
        bindingChildRef.current = null;
        setBindingRunning(false);
        appendBindingLog(`\n[exit] code=${payload.code ?? 'null'} signal=${payload.signal ?? 'null'}\n`);
        pushToast({
          tone: payload.code === 0 ? 'ok' : 'warn',
          title: payload.code === 0 ? `${meta.label}命令已结束` : `${meta.label}需要确认`,
          detail: payload.code === 0 ? '绑定完成后重启核心服务生效。' : '请检查输出区二维码、登录链接或错误信息。',
        });
      });
      bindingChildRef.current = child;
      appendBindingLog(`[launcher] ${meta.label}已启动，PID ${child.pid}\n`);
    } catch (error) {
      bindingChildRef.current = null;
      setBindingRunning(false);
      appendBindingLog(`\n[launcher] ${meta.label}启动失败：${error}\n`);
      pushToast({ tone: 'danger', title: `${meta.label}启动失败`, detail: String(error) });
    }
  }, [appendBindingLog, bindingRunning, settings, spawnBindingCommand, pushToast]);

  const handleStopBinding = React.useCallback(async () => {
    const child = bindingChildRef.current;
    if (!child) return;
    try {
      await child.kill();
      appendBindingLog('\n[launcher] 已停止扫码绑定命令\n');
    } catch (error) {
      appendBindingLog(`\n[launcher] 停止失败：${error}\n`);
    } finally {
      bindingChildRef.current = null;
      setBindingRunning(false);
    }
  }, [appendBindingLog]);

  const handleResetSelected = () => {
    setDraft((state) => ({
      ...state,
      platforms: {
        ...state.platforms,
        [state.selectedId]: createDefaultDraft(state.selectedId),
      },
    }));
    pushToast({ tone: 'warn', title: `${selectedMeta.label} 已恢复为默认草稿`, detail: '尚未写入配置文件。' });
  };

  const renderField = (field: FieldKey) => {
    switch (field) {
      case 'channelMode':
        return (
          <Field key={field} label="接入模式">
            <Select value={selectedDraft.channelMode} onChange={(event) => updateSelected({ channelMode: event.target.value as ChannelMode })}>
              <option value="push">消息推送</option>
              <option value="reply">自动回复</option>
              <option value="relay">桥接转发</option>
            </Select>
          </Field>
        );
      case 'endpoint':
        return (
          <Field key={field} label="接口地址" hint={selectedId === 'wechat' ? '/api/desktop-agent/wechat/send' : 'HTTPS 或本地桥接地址'}>
            <Input value={selectedDraft.endpoint} onChange={(event) => updateSelected({ endpoint: event.target.value })} placeholder="https://example.com/openclaw/webhook" />
          </Field>
        );
      case 'webhookUrl':
        return (
          <Field key={field} label="Webhook 地址" hint="由平台后台生成">
            <Input value={selectedDraft.webhookUrl} onChange={(event) => updateSelected({ webhookUrl: event.target.value })} placeholder="https://..." />
          </Field>
        );
      case 'callbackUrl':
        return (
          <Field key={field} label="回调地址" hint="可选">
            <Input value={selectedDraft.callbackUrl} onChange={(event) => updateSelected({ callbackUrl: event.target.value })} placeholder="https://your-domain.com/callback" />
          </Field>
        );
      case 'appId':
        return (
          <Field key={field} label="App ID / Agent ID">
            <Input value={selectedDraft.appId} onChange={(event) => updateSelected({ appId: event.target.value })} placeholder="应用 ID 或机器人 ID" />
          </Field>
        );
      case 'appSecret':
        return (
          <Field key={field} label="App Secret" hint={maskSecret(selectedDraft.appSecret)}>
            <Input type="password" value={selectedDraft.appSecret} onChange={(event) => updateSelected({ appSecret: event.target.value })} placeholder="平台应用密钥" />
          </Field>
        );
      case 'token':
        return (
          <Field key={field} label="签名 / Token" hint={maskSecret(selectedDraft.token)}>
            <Input type="password" value={selectedDraft.token} onChange={(event) => updateSelected({ token: event.target.value })} placeholder="可选签名密钥或访问令牌" />
          </Field>
        );
      case 'messageMode':
        return (
          <Field key={field} label="消息格式">
            <Select value={selectedDraft.messageMode} onChange={(event) => updateSelected({ messageMode: event.target.value as MessageMode })}>
              <option value="text">纯文本</option>
              <option value="markdown">Markdown</option>
              <option value="card">卡片消息</option>
            </Select>
          </Field>
        );
      case 'deliveryTarget':
        return (
          <Field key={field} label="转发目标">
            <Select value={selectedDraft.deliveryTarget} onChange={(event) => updateSelected({ deliveryTarget: event.target.value as DeliveryTarget })}>
              <option value="service">核心服务</option>
              <option value="desktop">桌面 RPA</option>
              <option value="phone">APKClaw 桥接</option>
            </Select>
          </Field>
        );
      case 'notes':
        return (
          <Field key={field} label="备注">
            <TextArea rows={4} value={selectedDraft.notes} onChange={(event) => updateSelected({ notes: event.target.value })} placeholder="用途、负责人、回调范围或安全说明" />
          </Field>
        );
      default:
        return null;
    }
  };

  return (
    <div className="page-grid">
      <section className="hero-band">
        <div className="hero-copy">
          <div className="eyebrow">平台对接</div>
          <h1>把飞书、微信和其他平台放进一个专门窗口。</h1>
          <p>这里只管理外部消息、回调和桥接配置。微信自动回复继续走桌面 RPA，飞书等平台先通过配置适配层落盘，不改后端接口。</p>
        </div>
        <div className="hero-actions">
          <Button variant="primary" icon={Save} onClick={handleSave}>
            保存配置
          </Button>
          <Button variant="secondary" icon={PlayCircle} onClick={handleProbe}>
            连接校验
          </Button>
          <Button variant="quiet" icon={RefreshCcw} onClick={refresh}>
            刷新
          </Button>
        </div>
      </section>

      <section className="stats-grid">
        <StatTile label="平台" value={`${PLATFORM_ORDER.length} 个`} hint="飞书、微信、企业微信、钉钉、Slack、Webhook" tone="neutral" />
        <StatTile label="启用" value={`${enabledCount}/${PLATFORM_ORDER.length}`} hint="保存后写入专用配置文件" tone={enabledCount ? 'ok' : 'warn'} />
        <StatTile label="微信桥接" value={desktopBridgeReady ? '就绪' : '待配置'} hint={wechatConfig.sendMode ? `send: ${wechatConfig.sendMode}` : '桌面 RPA 未就绪'} tone={desktopBridgeReady ? 'ok' : 'warn'} />
        <StatTile label="最近保存" value={draft.updatedAt ? formatDateTime(draft.updatedAt) : '未保存'} hint={INTEGRATIONS_CONFIG_PATH} tone={draft.updatedAt ? 'ok' : 'neutral'} />
      </section>

      {loading ? (
        <Panel className="panel-loading">正在读取平台对接配置...</Panel>
      ) : error ? (
        <Panel className="panel-error">
          <InlineState tone="danger" title="平台对接配置读取失败" description={error} />
        </Panel>
      ) : data ? (
        <section className="content-grid content-grid-integrations">
          <Panel className="surface-panel integration-nav-panel">
            <SectionHeader
              eyebrow="平台"
              title="接入列表"
              subtitle="选择平台后只编辑它自己的字段，避免把所有配置堆到一个表单里。"
            />
            <div className="integration-list">
              {PLATFORM_ORDER.map((id) => {
                const meta = PLATFORM_META[id];
                const itemDraft = draft.platforms[id];
                const active = selectedId === id;
                return (
                  <button
                    key={id}
                    type="button"
                    className={cx('integration-item', active && 'integration-item-active')}
                    onClick={() => choosePlatform(id)}
                  >
                    <span className="integration-item-head">
                      <span>
                        <strong>{meta.label}</strong>
                        <span>{meta.desc}</span>
                      </span>
                      <Chip tone={platformTone(id, itemDraft)}>{itemDraft.enabled ? '启用' : '停用'}</Chip>
                    </span>
                    <span className="integration-item-desc">{endpointSummary(itemDraft) || '等待配置'}</span>
                  </button>
                );
              })}
            </div>
          </Panel>

          <Panel className="surface-panel integration-editor-panel">
            <SectionHeader
              eyebrow={selectedMeta.label}
              title={`${selectedMeta.label} 接入配置`}
              subtitle={selectedMeta.hint}
              action={(
                <div className="section-action-row">
                  <Chip tone={platformTone(selectedId, selectedDraft)}>{selectedDraft.enabled ? '已启用' : '未启用'}</Chip>
                  {selectedScanMeta ? (
                    <Button
                      variant="secondary"
                      icon={QrCode}
                      onClick={() => void handleScanBind(selectedId as ScanPlatformKey)}
                      disabled={bindingRunning}
                    >
                      扫码绑定
                    </Button>
                  ) : null}
                </div>
              )}
            />
            <div className="integration-switch-row">
              <Toggle
                checked={selectedDraft.enabled}
                onChange={(checked) => updateSelected({ enabled: checked })}
                label="启用此平台"
                hint="保存后写入平台对接配置，不改变后端路由。"
              />
            </div>
            <div className="form-grid integration-form-grid">
              {selectedMeta.fields.map(renderField)}
            </div>
            <div className="integration-state-stack">
              <InlineState
                tone={selectedId === 'wechat' ? (desktopBridgeReady ? 'ok' : 'warn') : 'neutral'}
                title={selectedScanMeta ? `${selectedMeta.label}支持扫码绑定` : '当前为配置适配层'}
                description={
                  selectedScanMeta
                    ? selectedScanMeta.hint
                    : selectedId === 'wechat'
                    ? `发送模式：${String(wechatConfig.sendMode || '未配置')}，未读检测：${String(wechatConfig.detectUnreadMode || '未配置')}`
                    : `配置保存到 ${INTEGRATIONS_CONFIG_PATH}，真实平台接口后续由适配层消费。`
                }
                icon={selectedId === 'wechat' ? MessageCircleMore : Webhook}
              />
            </div>
            <div className="button-row">
              <Button variant="primary" icon={Save} onClick={handleSave}>保存配置</Button>
              <Button variant="secondary" icon={PlayCircle} onClick={handleProbe}>连接校验</Button>
              <Button variant="quiet" icon={RotateCcw} onClick={handleResetSelected}>重置当前</Button>
            </div>
          </Panel>

          <Panel className="surface-panel surface-panel-wide">
            <SectionHeader
              eyebrow="边界"
              title="桌面 RPA、外部平台和配置文件"
              subtitle="这页不接管手机启动器，也不改后端协议；它只是把平台接入信息整理成可迁移的配置契约。"
              action={<Chip tone={desktopBridgeReady ? 'ok' : 'warn'}>{desktopBridgeReady ? '桌面桥接可用' : '桌面桥接待确认'}</Chip>}
            />
            <div className="integration-meta-grid">
              <div className="integration-meta-card">
                <Link2 size={16} />
                <span>保存路径</span>
                <strong>{INTEGRATIONS_CONFIG_PATH}</strong>
              </div>
              <div className="integration-meta-card">
                <MessageCircleMore size={16} />
                <span>微信发送</span>
                <strong>{String(wechatConfig.sendMode || '未配置')}</strong>
              </div>
              <div className="integration-meta-card">
                <Webhook size={16} />
                <span>读取来源</span>
                <strong>{sourceLabel(data.settingsSnapshot.source)} / {sourceLabel(data.desktop.source)}</strong>
              </div>
            </div>
            <div className="detail-stack integration-detail-stack">
              <div className="detail-row"><span className="detail-label">桌面项目</span><span className="detail-value">{String(desktopConfig.agentDir || '暂无')}</span></div>
              <div className="detail-row"><span className="detail-label">桌面端口</span><span className="detail-value">{String(desktopConfig.port || '暂无')}</span></div>
              <div className="detail-row"><span className="detail-label">发送确认</span><span className="detail-value">{desktopPolicy.requireConfirmForSend ? '需要确认' : '未要求'}</span></div>
              <div className="detail-row"><span className="detail-label">安全边界</span><span className="detail-value">仅保存配置和桥接意图，不擅自保存平台账号。</span></div>
            </div>
          </Panel>
        </section>
      ) : (
        <EmptyState title="暂无平台数据" description="刷新后会读取配置文件；接口不可用时使用本页内置 mock fallback。" />
      )}

      {bindingTarget ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal modal-binding">
            <div className="modal-head">
              <div>
                <div className="modal-title">{SCAN_BINDING_META[bindingTarget].label}</div>
                <div className="modal-subtitle">{SCAN_BINDING_META[bindingTarget].hint}</div>
              </div>
              <Chip tone={bindingRunning ? 'warn' : 'neutral'}>{bindingRunning ? '运行中' : '已停止'}</Chip>
            </div>
            <div className="modal-body">
              {bindingQrUrl ? (
                <div className="binding-qr-card">
                  {bindingQrDataUrl ? <img src={bindingQrDataUrl} alt={`${SCAN_BINDING_META[bindingTarget].label}二维码`} /> : <div className="binding-qr-placeholder">正在生成二维码...</div>}
                  <div className="binding-qr-meta">
                    <strong>请优先扫描这里的二维码</strong>
                    <span>{bindingQrUrl}</span>
                  </div>
                </div>
              ) : null}
              <pre ref={bindingOutputRef} className="modal-pre binding-console">
                {bindingLog.join('') || '等待启动扫码绑定命令...'}
              </pre>
            </div>
            <div className="modal-actions">
              {bindingRunning ? (
                <Button variant="danger" icon={Square} onClick={() => void handleStopBinding()}>
                  停止命令
                </Button>
              ) : null}
              <Button variant="secondary" icon={QrCode} onClick={() => void handleScanBind(bindingTarget)} disabled={bindingRunning}>
                重新绑定
              </Button>
              <Button variant="quiet" onClick={() => setBindingTarget(null)} disabled={bindingRunning}>
                关闭
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function createDefaultConfig(): IntegrationConfig {
  return {
    selectedId: 'wechat',
    updatedAt: '',
    platforms: PLATFORM_ORDER.reduce((acc, id) => {
      acc[id] = createDefaultDraft(id);
      return acc;
    }, {} as Record<PlatformKey, IntegrationDraft>),
  };
}

function createDefaultDraft(id: PlatformKey): IntegrationDraft {
  const base: IntegrationDraft = {
    enabled: id === 'wechat',
    channelMode: id === 'wechat' ? 'relay' : 'push',
    endpoint: '',
    webhookUrl: '',
    callbackUrl: '',
    appId: '',
    appSecret: '',
    token: '',
    messageMode: id === 'feishu' || id === 'slack' ? 'markdown' : 'text',
    deliveryTarget: id === 'wechat' ? 'desktop' : 'service',
    notes: '',
  };

  if (id === 'wechat') {
    return {
      ...base,
      endpoint: '/api/desktop-agent/wechat/send',
      notes: '个人微信由桌面 RPA 执行，启动器只保存桥接和安全策略。',
    };
  }
  if (id === 'webhook') {
    return {
      ...base,
      endpoint: 'https://example.com/openclaw/webhook',
      notes: '其他平台先走标准 Webhook，后续再补专用适配器。',
    };
  }
  return base;
}

function normalizeConfig(raw: unknown): IntegrationConfig {
  const source = raw && typeof raw === 'object' ? raw as Partial<IntegrationConfig> : {};
  const base = createDefaultConfig();
  const selectedId = isPlatformKey(source.selectedId) ? source.selectedId : base.selectedId;
  return {
    selectedId,
    updatedAt: typeof source.updatedAt === 'string' ? source.updatedAt : '',
    platforms: PLATFORM_ORDER.reduce((acc, id) => {
      const rawPlatform = source.platforms && typeof source.platforms === 'object'
        ? (source.platforms as Partial<Record<PlatformKey, Partial<IntegrationDraft>>>)[id]
        : undefined;
      acc[id] = normalizeDraft(id, rawPlatform);
      return acc;
    }, {} as Record<PlatformKey, IntegrationDraft>),
  };
}

function normalizeDraft(id: PlatformKey, raw?: Partial<IntegrationDraft>): IntegrationDraft {
  const base = createDefaultDraft(id);
  return {
    enabled: typeof raw?.enabled === 'boolean' ? raw.enabled : base.enabled,
    channelMode: isChannelMode(raw?.channelMode) ? raw.channelMode : base.channelMode,
    endpoint: stringValue(raw?.endpoint, base.endpoint),
    webhookUrl: stringValue(raw?.webhookUrl, base.webhookUrl),
    callbackUrl: stringValue(raw?.callbackUrl, base.callbackUrl),
    appId: stringValue(raw?.appId, base.appId),
    appSecret: stringValue(raw?.appSecret, base.appSecret),
    token: stringValue(raw?.token, base.token),
    messageMode: isMessageMode(raw?.messageMode) ? raw.messageMode : base.messageMode,
    deliveryTarget: isDeliveryTarget(raw?.deliveryTarget) ? raw.deliveryTarget : base.deliveryTarget,
    notes: stringValue(raw?.notes, base.notes),
  };
}

function validatePlatform(id: PlatformKey, draft: IntegrationDraft, desktopBridgeReady: boolean): { tone: 'ok' | 'warn' | 'danger'; title: string; detail: string } {
  const meta = PLATFORM_META[id];
  if (!draft.enabled) {
    return { tone: 'warn', title: `${meta.label} 未启用`, detail: '打开启用开关并保存后才会参与对接。' };
  }
  const missing = meta.required.filter((field) => !String(draft[field] || '').trim());
  if (missing.length) {
    return { tone: 'warn', title: `${meta.label} 还缺少配置`, detail: `需要补齐：${missing.map(fieldLabel).join('、')}` };
  }
  if (id === 'wechat' && draft.deliveryTarget === 'desktop' && !desktopBridgeReady) {
    return { tone: 'warn', title: '微信桌面桥接待确认', detail: '桌面 RPA 项目或微信发送权限还没有就绪。' };
  }
  return { tone: 'ok', title: `${meta.label} 接入配置可用`, detail: endpointSummary(draft) || 'mock fallback 校验通过。' };
}

function extractBindingUrl(text: string): string {
  const urls = Array.from(text.matchAll(/https?:\/\/[^\s"'<>]+/g)).map((match) => match[0].replace(/[),.;，。]+$/g, ''));
  return urls.find((url) => /open\.feishu\.cn|accounts\.feishu\.cn|accounts\.larksuite\.com|dingtalk|oapi\.dingtalk\.com|login\.dingtalk\.com|weixin|wechat|qrcode/i.test(url)) || urls[0] || '';
}

function platformTone(id: PlatformKey, draft: IntegrationDraft): 'ok' | 'warn' | 'neutral' {
  if (!draft.enabled) return 'neutral';
  const missing = PLATFORM_META[id].required.some((field) => !String(draft[field] || '').trim());
  return missing ? 'warn' : 'ok';
}

function endpointSummary(draft: IntegrationDraft): string {
  return draft.webhookUrl || draft.endpoint || draft.callbackUrl || '';
}

function fieldLabel(field: FieldKey): string {
  const map: Record<FieldKey, string> = {
    channelMode: '接入模式',
    endpoint: '接口地址',
    webhookUrl: 'Webhook 地址',
    callbackUrl: '回调地址',
    appId: 'App ID',
    appSecret: 'App Secret',
    token: '签名 / Token',
    messageMode: '消息格式',
    deliveryTarget: '转发目标',
    notes: '备注',
  };
  return map[field];
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function isPlatformKey(value: unknown): value is PlatformKey {
  return typeof value === 'string' && PLATFORM_ORDER.includes(value as PlatformKey);
}

function isScanPlatform(value: PlatformKey): value is ScanPlatformKey {
  return value === 'feishu' || value === 'wechat' || value === 'dingtalk';
}

function isChannelMode(value: unknown): value is ChannelMode {
  return value === 'push' || value === 'reply' || value === 'relay';
}

function isDeliveryTarget(value: unknown): value is DeliveryTarget {
  return value === 'service' || value === 'desktop' || value === 'phone';
}

function isMessageMode(value: unknown): value is MessageMode {
  return value === 'text' || value === 'markdown' || value === 'card';
}

function sourceLabel(value: string) {
  const map: Record<string, string> = {
    mock: '预览',
    live: '真实接口',
    mixed: '混合',
  };
  return map[value] || value;
}
