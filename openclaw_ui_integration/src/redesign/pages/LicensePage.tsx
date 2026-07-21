import React from 'react';
import { BadgeCheck, ExternalLink, LogIn, LogOut, RefreshCcw, ShieldCheck } from 'lucide-react';
import {
  activateLicense,
  bindAccountTicket,
  loadAccountSnapshot,
  loadClientConfig,
  loadLicenseBundle,
  loginAccount,
  logoutAccount,
  refreshMember,
  startProcess,
  syncAccount,
} from '../api/adapters';
import { Button, Chip, EmptyState, Field, Input, InlineState, Panel, SectionHeader, StatTile, Tabs } from '../components/ui';
import { translateLicenseError, type FriendlyError } from '../lib/errors';
import { useAsync } from '../lib/useAsync';
import { usePreviewStore } from '../store/appStore';

type AuthMode = 'account' | 'license';

export function LicensePage() {
  const settings = usePreviewStore((state) => state.settings);
  const pushToast = usePreviewStore((state) => state.pushToast);
  const [mode, setMode] = React.useState<AuthMode>('account');
  const [licenseCode, setLicenseCode] = React.useState('');
  const [accountName, setAccountName] = React.useState('');
  const [accountPassword, setAccountPassword] = React.useState('');
  const [accountBaseUrl, setAccountBaseUrl] = React.useState('https://api.heang.top');
  const [accountApiToken, setAccountApiToken] = React.useState('');
  const [accountBindTicket, setAccountBindTicket] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [activationError, setActivationError] = React.useState<FriendlyError | null>(null);
  const [accountError, setAccountError] = React.useState('');
  const { data, loading, error, refresh } = useAsync(async () => {
    const [bundle, clientConfig, account] = await Promise.all([
      loadLicenseBundle(settings),
      loadClientConfig(settings),
      loadAccountSnapshot(settings),
    ]);
    return { ...bundle, clientConfig: clientConfig.data, account };
  }, [settings], { cacheKey: 'license' });

  const license = data?.license;
  const member = data?.member;
  const gateway = data?.gateway;
  const cardSite = data?.clientConfig?.cardSite;
  const account = data?.account;
  const accountLoggedIn = Boolean(account?.loggedIn);
  const accountModelTotal = (account?.models.text.length || 0) + (account?.models.image.length || 0) + (account?.models.video.length || 0);

  const handleActivateLicense = async () => {
    if (!licenseCode.trim()) {
      pushToast({ tone: 'danger', title: '缺少授权码', detail: '激活前需要输入授权码。' });
      return;
    }
    setBusy(true);
    setActivationError(null);
    try {
      await activateLicense(settings, licenseCode.trim());
      pushToast({ tone: 'ok', title: '授权已激活', detail: licenseCode.trim() });
      refresh();
      try {
        await startProcess(settings);
        pushToast({ tone: 'ok', title: '核心服务启动中', detail: '授权已生效，正在拉起 OpenClaw 运行时。' });
      } catch {
        pushToast({ tone: 'warn', title: '已授权，服务待启动', detail: '稍后可在「服务 / CLI」页手动启动。' });
      }
    } catch (err) {
      const friendly = translateLicenseError(err);
      setActivationError(friendly);
      pushToast({ tone: 'danger', title: friendly.title, detail: friendly.hint, diagnostic: friendly.diagnostic, logRoute: friendly.logRoute });
    } finally {
      setBusy(false);
    }
  };

  const handleAccountLogin = async () => {
    if (!accountName.trim() || !accountPassword.trim()) {
      const message = '请输入中转站账号和密码。';
      setAccountError(message);
      pushToast({ tone: 'danger', title: '登录信息不完整', detail: message, logRoute: 'license' });
      return;
    }
    setBusy(true);
    setAccountError('');
    try {
      await loginAccount(settings, {
        username: accountName.trim(),
        password: accountPassword,
        baseUrl: accountBaseUrl.trim() || 'https://api.heang.top',
        apiToken: accountApiToken.trim() || undefined,
      });
      setAccountPassword('');
      setAccountApiToken('');
      refresh();
      pushToast({ tone: 'ok', title: '账号已登录', detail: '模型配置已同步到本机。' });
      try {
        await startProcess(settings);
      } catch {
        pushToast({ tone: 'warn', title: '账号已登录，服务待启动', detail: '核心服务稍后可在「服务 / CLI」页启动。' });
      }
    } catch (err) {
      const message = errorMessage(err);
      setAccountError(message);
      pushToast({ tone: 'danger', title: '账号登录失败', detail: message, diagnostic: String(err), logRoute: 'license' });
    } finally {
      setBusy(false);
    }
  };

  const handleAccountSync = async () => {
    setBusy(true);
    setAccountError('');
    try {
      await syncAccount(settings);
      refresh();
      pushToast({ tone: 'ok', title: '模型已同步', detail: '已重新读取中转站模型列表和本机配置。' });
    } catch (err) {
      const message = errorMessage(err);
      setAccountError(message);
      pushToast({ tone: 'danger', title: '同步失败', detail: message, diagnostic: String(err), logRoute: 'license' });
    } finally {
      setBusy(false);
    }
  };

  const handleAccountBindTicket = async () => {
    if (!accountBindTicket.trim()) {
      setAccountError('请输入网站绑定码。');
      return;
    }
    setBusy(true);
    setAccountError('');
    try {
      await bindAccountTicket(settings, {
        ticket: accountBindTicket.trim(),
        baseUrl: accountBaseUrl.trim() || 'https://api.heang.top',
      });
      setAccountBindTicket('');
      refresh();
      pushToast({ tone: 'ok', title: '网站账号已绑定', detail: '模型配置已同步到本机。' });
      try {
        await startProcess(settings);
      } catch {
        pushToast({ tone: 'warn', title: '账号已绑定，服务待启动', detail: '可在「服务 / CLI」页面手动启动。' });
      }
    } catch (err) {
      const message = errorMessage(err);
      setAccountError(message);
      pushToast({ tone: 'danger', title: '网站绑定失败', detail: message, diagnostic: String(err), logRoute: 'license' });
    } finally {
      setBusy(false);
    }
  };

  const handleAccountLogout = async () => {
    setBusy(true);
    setAccountError('');
    try {
      await logoutAccount(settings);
      refresh();
      pushToast({ tone: 'ok', title: '账号已退出', detail: '已清理账号托管的本机网关配置。' });
    } catch (err) {
      const message = errorMessage(err);
      setAccountError(message);
      pushToast({ tone: 'danger', title: '退出失败', detail: message, diagnostic: String(err), logRoute: 'license' });
    } finally {
      setBusy(false);
    }
  };

  const handleRefreshMember = async () => {
    setBusy(true);
    try {
      await refreshMember(settings);
      refresh();
      pushToast({ tone: 'ok', title: '账号信息已刷新', detail: '当前账号与可用额度已重新读取。' });
    } catch (err) {
      const friendly = translateLicenseError(err);
      pushToast({ tone: 'danger', title: friendly.title, detail: friendly.hint, diagnostic: friendly.diagnostic, logRoute: friendly.logRoute });
    } finally {
      setBusy(false);
    }
  };

  const openCardSite = async () => {
    if (!cardSite?.url) {
      pushToast({ tone: 'warn', title: '暂未提供获取授权入口', detail: '服务端 client-config 未返回 cardSite.url。' });
      return;
    }
    try {
      const { open } = await import('@tauri-apps/plugin-shell');
      await open(cardSite.url);
    } catch {
      window.open(cardSite.url, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <div className="page-grid">
      <section className="hero-band">
        <div className="hero-copy">
          <div className="eyebrow">账号 / 授权</div>
          <h1>登录中转站账号，同步可用模型。</h1>
        </div>
        <div className="hero-actions">
          <Button variant="primary" icon={RefreshCcw} onClick={refresh}>
            刷新
          </Button>
          <Button variant="secondary" icon={ShieldCheck} onClick={handleRefreshMember} disabled={busy}>
            刷新状态
          </Button>
        </div>
      </section>

      <section className="stats-grid">
        <StatTile label="账号" value={accountLoggedIn ? '已登录' : '未登录'} hint={accountLoggedIn ? account?.account : '中转站账号'} tone={accountLoggedIn ? 'ok' : 'warn'} />
        <StatTile label="模型" value={accountModelTotal || '暂无'} hint="文本 / 图像 / 视频" tone={accountModelTotal ? 'ok' : 'neutral'} />
        <StatTile label="授权" value={license?.authorized ? '已激活' : '未激活'} hint={license?.licensee || '兼容旧授权码'} tone={license?.authorized ? 'ok' : 'warn'} />
        <StatTile label="网关" value={account?.gatewayBaseUrl || gateway?.baseUrl || '暂无'} hint={account?.tokenMasked || gateway?.apiKeyMasked || '未同步'} tone={accountLoggedIn || gateway?.hasGateway ? 'ok' : 'neutral'} />
      </section>

      {loading ? (
        <Panel className="panel-loading">正在读取账号信息...</Panel>
      ) : error ? (
        <Panel className="panel-error">
          <InlineState tone="danger" title="账号信息读取失败" description={error} />
        </Panel>
      ) : data ? (
        <section className="content-grid content-grid-license">
          <Panel className="surface-panel">
            <SectionHeader
              eyebrow="登录"
              title="接入方式"
              action={
                <Tabs
                  value={mode}
                  onChange={(value) => setMode(value as AuthMode)}
                  items={[
                    { key: 'account', label: '账号登录' },
                    { key: 'license', label: '授权码' },
                  ]}
                />
              }
            />

            {mode === 'account' ? (
              <div className="detail-stack">
                <Field label="中转站地址">
                  <Input value={accountBaseUrl} onChange={(event) => setAccountBaseUrl(event.target.value)} placeholder="https://api.heang.top" />
                </Field>
                <Field label="账号">
                  <Input value={accountName} onChange={(event) => setAccountName(event.target.value)} placeholder="邮箱或用户名" autoComplete="username" />
                </Field>
                <Field label="密码">
                  <Input value={accountPassword} onChange={(event) => setAccountPassword(event.target.value)} placeholder="中转站登录密码" type="password" autoComplete="current-password" />
                </Field>
                <Field label="API Token" hint="可选">
                  <Input value={accountApiToken} onChange={(event) => setAccountApiToken(event.target.value)} placeholder="New API 已创建的 sk-..." type="password" autoComplete="off" />
                </Field>
                <Field label="网站绑定码" hint="可选">
                  <Input value={accountBindTicket} onChange={(event) => setAccountBindTicket(event.target.value)} placeholder="ocb_..." autoComplete="off" />
                </Field>
                {accountError ? <InlineState tone="danger" title="账号操作失败" description={accountError} /> : null}
                <div className="button-row">
                  <Button variant="primary" icon={LogIn} onClick={handleAccountLogin} disabled={busy}>
                    {busy ? '登录中...' : '登录并同步'}
                  </Button>
                  <Button variant="secondary" icon={LogIn} onClick={handleAccountBindTicket} disabled={busy}>
                    绑定网站账号
                  </Button>
                  <Button variant="secondary" icon={RefreshCcw} onClick={handleAccountSync} disabled={busy || !accountLoggedIn}>
                    同步模型
                  </Button>
                  <Button variant="quiet" icon={LogOut} onClick={handleAccountLogout} disabled={busy || !accountLoggedIn}>
                    退出
                  </Button>
                </div>
              </div>
            ) : (
              <div className="detail-stack">
                <Field label="授权码" hint="OC-PRO-xxxx-xxxx">
                  <Input value={licenseCode} onChange={(event) => setLicenseCode(event.target.value)} placeholder="OC-PRO-XXXX-XXXX-XXXX-XXXX" />
                </Field>
                {activationError ? <InlineState tone="danger" title={activationError.title} description={activationError.hint} /> : null}
                <div className="button-row">
                  <Button variant="primary" icon={BadgeCheck} onClick={handleActivateLicense} disabled={busy}>
                    激活授权
                  </Button>
                  <Button variant="secondary" icon={ExternalLink} onClick={openCardSite} disabled={!cardSite?.enabled}>
                    获取授权
                  </Button>
                </div>
              </div>
            )}
          </Panel>

          <Panel className="surface-panel">
            <SectionHeader
              eyebrow="账号"
              title="当前账号"
              action={<Chip tone={accountLoggedIn ? 'ok' : 'neutral'}>{accountLoggedIn ? '已登录' : '未登录'}</Chip>}
            />
            {accountLoggedIn ? (
              <div className="detail-stack">
                <div className="detail-row"><span className="detail-label">账号</span><span className="detail-value">{account?.account}</span></div>
                <div className="detail-row"><span className="detail-label">用户 ID</span><span className="detail-value">{account?.memberId || '暂无'}</span></div>
                <div className="detail-row"><span className="detail-label">网关</span><span className="detail-value">{account?.gatewayBaseUrl || '暂无'}</span></div>
                <div className="detail-row"><span className="detail-label">Token</span><span className="detail-value">{account?.tokenMasked || '暂无'}</span></div>
                <div className="detail-row"><span className="detail-label">最后同步</span><span className="detail-value">{formatTime(account?.lastOnlineAt)}</span></div>
                <div className="detail-row"><span className="detail-label">离线宽限</span><span className="detail-value">{formatTime(account?.graceExpiresAt)}</span></div>
              </div>
            ) : (
              <EmptyState title="未登录" description="登录后会同步中转站的 API Token 与模型列表。" />
            )}
          </Panel>

          <Panel className="surface-panel">
            <SectionHeader eyebrow="模型" title="同步结果" />
            <div className="quota-grid">
              <div className="quota-box"><span>文本模型</span><strong>{account?.models.text.length || 0}</strong></div>
              <div className="quota-box"><span>图像模型</span><strong>{account?.models.image.length || 0}</strong></div>
              <div className="quota-box"><span>视频模型</span><strong>{account?.models.video.length || 0}</strong></div>
              <div className="quota-box"><span>来源</span><strong>{account?.source || '手动'}</strong></div>
            </div>
            <div className="model-list-block">
              <ModelLine label="文本" values={account?.models.text} />
              <ModelLine label="图像" values={account?.models.image} />
              <ModelLine label="视频" values={account?.models.video} />
            </div>
            {account?.models.video.length ? (
              <InlineState tone="warn" title="视频模型已识别" description="已记录模型列表；视频生成通道会继续使用当前兼容配置，避免误切到不兼容接口。" />
            ) : null}
          </Panel>

          <Panel className="surface-panel">
            <SectionHeader eyebrow="兼容" title="旧授权状态" />
            {license?.authorized || member?.status === 'active' ? (
              <div className="detail-stack">
                <div className="detail-row"><span className="detail-label">授权</span><span className="detail-value">{license?.authorized ? displayEdition(license.edition) : '暂无'}</span></div>
                <div className="detail-row"><span className="detail-label">账号状态</span><span className="detail-value">{memberStatusLabel(member?.status)}</span></div>
                <div className="detail-row"><span className="detail-label">到期时间</span><span className="detail-value">{license?.expires || member?.expiresAt || '暂无'}</span></div>
                <div className="detail-row"><span className="detail-label">网关地址</span><span className="detail-value">{gateway?.baseUrl || '暂无'}</span></div>
              </div>
            ) : (
              <EmptyState title="暂无旧授权" description="旧授权码通道仍可用于兼容部署。" />
            )}
          </Panel>
        </section>
      ) : null}
    </div>
  );
}

function ModelLine({ label, values = [] }: { label: string; values?: string[] }) {
  return (
    <div className="detail-row">
      <span className="detail-label">{label}</span>
      <span className="detail-value">{values.length ? values.slice(0, 6).join(' / ') : '暂无'}</span>
    </div>
  );
}

function errorMessage(err: unknown) {
  if (err instanceof Error) return err.message || '请求失败';
  return String(err || '请求失败');
}

function formatTime(value?: string) {
  if (!value) return '暂无';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function displayEdition(value?: string) {
  if (!value) return '已授权';
  if (value === 'Pro') return '专业版';
  if (value === 'Free') return '免费版';
  return value;
}

function memberStatusLabel(value?: string) {
  if (!value) return '未激活';
  if (value === 'active') return '已激活';
  if (value === 'inactive') return '未激活';
  return value;
}
