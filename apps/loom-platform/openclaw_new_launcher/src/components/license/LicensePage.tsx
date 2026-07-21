import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { open } from '@tauri-apps/plugin-shell';
import { BusyOverlay, showToast } from '../common';
import { LoomLogoMark } from '../brand/LoomBrand';
import {
  accountApi,
  parseErrorText,
  type AccountSnapshot,
  type AccountAuthCapabilities,
  type AccountSubscriptionSnapshot,
} from '../../services/api';
import { accountCacheUsable, loadCachedAccount, saveCachedAccount } from '../../services/startupCache';
import { useAppStore } from '../../stores/appStore';
import { APP_DISPLAY_NAME } from '../../version';

const DEFAULT_BASE_URL = 'https://api.heang.top';
const DEFAULT_ACCOUNT_CENTER_URL = `${DEFAULT_BASE_URL}/wallet`;

type AuthMode = 'email' | 'password';
type RuntimeSyncResult = { target?: string; ok?: boolean; error?: string };

function errorMessage(error: unknown): string {
  const friendly = parseErrorText(error);
  if (friendly) return friendly;
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const record = error as Record<string, unknown>;
    if (typeof record.error === 'string') return record.error;
    if (typeof record.message === 'string') return record.message;
  }
  return '请求失败，请稍后重试';
}

function modelTotal(account: AccountSnapshot | null): number {
  const models = account?.models || {};
  return (models.text?.length || 0) + (models.image?.length || 0) + (models.video?.length || 0);
}

function failedSyncResults(results?: RuntimeSyncResult[]): RuntimeSyncResult[] {
  return (results || []).filter((item) => item.ok === false);
}

function displayValue(value: unknown, fallback = '暂无'): string {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value);
}

function usageValue(account: AccountSnapshot | null, keys: string[], fallback = '暂无'): string {
  const usage = account?.usage;
  if (!usage || typeof usage !== 'object') return fallback;
  for (const key of keys) {
    const value = usage[key];
    if (value !== undefined && value !== null && value !== '') return String(value);
  }
  return fallback;
}

function formatTime(value?: string): string {
  if (!value) return '暂无';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

async function openExternalUrl(url: string): Promise<void> {
  try {
    await open(url);
  } catch (error) {
    const opened = window.open(url, '_blank', 'noopener,noreferrer');
    if (!opened) throw error;
  }
}

function isLocalSubscriptionUrl(url: string): boolean {
  try {
    const parsed = new URL(url, DEFAULT_BASE_URL);
    return ['localhost', '127.0.0.1', '0.0.0.0', '::1'].includes(parsed.hostname) || parsed.protocol === 'file:';
  } catch {
    return true;
  }
}

function safeSubscriptionUrl(url: string): string {
  const candidate = String(url || '').trim() || DEFAULT_ACCOUNT_CENTER_URL;
  if (isLocalSubscriptionUrl(candidate)) return '';
  try {
    const parsed = new URL(candidate, DEFAULT_BASE_URL);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return '';
    if (['api-cn.heang.top', 'api.heang.top'].includes(parsed.hostname) && parsed.pathname.replace(/\/+$/, '') === '/topup') {
      return DEFAULT_ACCOUNT_CENTER_URL;
    }
    return parsed.toString();
  } catch {
    return '';
  }
}

export const LicensePage: React.FC = () => {
  const cachedAccount = useRef<AccountSnapshot | null>(loadCachedAccount());
  const subscriptionRequestVersion = useRef(0);
  const hasCachedAccount = accountCacheUsable(cachedAccount.current);
  const [account, setAccount] = useState<AccountSnapshot | null>(() => cachedAccount.current);
  const [subscription, setSubscription] = useState<AccountSubscriptionSnapshot | null>(() => cachedAccount.current?.subscription || null);
  const [authMode, setAuthMode] = useState<AuthMode>('password');
  const [authCapabilities, setAuthCapabilities] = useState<AccountAuthCapabilities>({
    passwordLogin: true,
    inlineEmailCode: false,
    webRegistrationRequired: true,
    registrationUrl: `${DEFAULT_BASE_URL}/register`,
    emailReason: '正在检测邮箱能力；密码登录可直接使用。',
  });
  const [loginName, setLoginName] = useState('');
  const [email, setEmail] = useState('');
  const [emailCode, setEmailCode] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(() => !hasCachedAccount);
  const [statusText, setStatusText] = useState('');
  const { setCurrentPage } = useAppStore();

  const loggedIn = Boolean(account?.loggedIn);
  const totalModels = modelTotal(account);
  const modelHint = useMemo(() => {
    const selected = account?.selectedModels?.text;
    if (selected) return selected;
    return account?.models?.text?.slice(0, 3).join(' / ') || '登录后同步';
  }, [account]);
  const purchaseUrl = subscription?.purchaseUrl || account?.purchaseUrl || DEFAULT_ACCOUNT_CENTER_URL;
  const subscriptionUrl = useMemo(() => safeSubscriptionUrl(purchaseUrl), [purchaseUrl]);
  const accountStateText = loading ? '读取中' : loggedIn ? '已登录' : '未登录';

  const applyAccount = useCallback((next: AccountSnapshot | null) => {
    subscriptionRequestVersion.current += 1;
    cachedAccount.current = next;
    saveCachedAccount(next);
    setAccount(next);
    setSubscription(next?.subscription || null);
  }, []);

  const refresh = useCallback(async (options: { background?: boolean } = {}) => {
    if (!options.background) setLoading(true);
    try {
      const resp = await accountApi.current();
      applyAccount(resp.account || null);
      setStatusText('');
    } catch (error) {
      const cached = loadCachedAccount();
      applyAccount(cached || null);
      setStatusText(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [applyAccount]);

  useEffect(() => {
    if (accountCacheUsable(cachedAccount.current)) {
      applyAccount(cachedAccount.current);
      setStatusText('');
      setLoading(false);
      void refresh({ background: true });
      return;
    }
    void refresh();
  }, [applyAccount, refresh]);

  useEffect(() => {
    void accountApi.capabilities().then((response) => {
      const next = response.capabilities;
      setAuthCapabilities(next);
      setAuthMode((current) => {
        if (current === 'email' && !next.inlineEmailCode) return 'password';
        return current;
      });
    }).catch(() => {
      setAuthCapabilities((current) => ({
        ...current,
        inlineEmailCode: false,
        webRegistrationRequired: true,
        emailReason: '邮箱能力暂时无法确认，请使用密码登录或网页注册。',
      }));
    });
  }, []);

  const loadSubscription = async (quiet = false) => {
    const requestVersion = ++subscriptionRequestVersion.current;
    if (!quiet) setBusy(true);
    try {
      const resp = await accountApi.subscription();
      if (requestVersion !== subscriptionRequestVersion.current) return;
      setSubscription(resp.subscription || null);
      if (!quiet) {
        setStatusText(resp.subscription?.message || '订阅信息已更新');
        showToast('订阅信息已更新', 'success');
      }
    } catch (error) {
      if (requestVersion !== subscriptionRequestVersion.current) return;
      const message = errorMessage(error);
      if (!quiet) {
        setStatusText(message);
        showToast(message || '订阅信息获取失败', 'error');
      }
    } finally {
      if (!quiet && requestVersion === subscriptionRequestVersion.current) setBusy(false);
    }
  };

  const sendEmailCode = async () => {
    if (!authCapabilities.inlineEmailCode) {
      const message = authCapabilities.emailReason || '当前请使用密码登录或网页注册。';
      setStatusText(message);
      showToast(message, 'info');
      return;
    }
    const targetEmail = email.trim();
    if (!targetEmail) {
      showToast('请输入邮箱', 'error');
      return;
    }
    setBusy(true);
    setStatusText('正在发送邮箱验证码...');
    try {
      await accountApi.sendEmailCode({
        email: targetEmail,
        baseUrl: DEFAULT_BASE_URL,
        purpose: 'login',
      });
      setStatusText('验证码已发送，请查看邮箱');
      showToast('验证码已发送', 'success');
    } catch (error) {
      const message = errorMessage(error);
      setStatusText(message);
      showToast(message || '验证码发送失败', 'error');
    } finally {
      setBusy(false);
    }
  };

  const finishLogin = async (
    next: AccountSnapshot | null,
    message: string,
    syncResults?: RuntimeSyncResult[],
    syncPending = false,
  ) => {
    applyAccount(next);
    setPassword('');
    setEmailCode('');
    const failures = failedSyncResults(syncResults);
    const codexFailure = failures.find((item) => item.target === 'codex');
    if (syncPending) {
      const syncing = '登录成功，本地智能体配置正在后台同步；现在即可继续使用。';
      setStatusText(syncing);
      showToast(syncing, 'success');
    } else if (codexFailure) {
      const warning = `登录成功，但 Codex 模型配置未完成：${codexFailure.error || '请前往安装页重新写入模型配置'}`;
      setStatusText(warning);
      showToast(warning, 'info');
    } else if (failures.length) {
      const warning = `登录成功，但有 ${failures.length} 项运行配置待修复。可在安装页重新检测。`;
      setStatusText(warning);
      showToast(warning, 'info');
    } else {
      setStatusText(message);
      showToast(message, 'success');
    }
    void loadSubscription(true);
  };

  const handlePasswordLogin = async () => {
    const name = loginName.trim();
    if (!name || !password.trim()) {
      showToast('请输入模型账号和密码', 'error');
      return;
    }

    setBusy(true);
    setStatusText('正在登录模型账号并同步模型...');
    try {
      const loginPayload = name.includes('@')
        ? { email: name, password, baseUrl: DEFAULT_BASE_URL }
        : { username: name, password, baseUrl: DEFAULT_BASE_URL };
      const resp = await accountApi.login(loginPayload);
      await finishLogin(resp.account || null, '登录成功', resp.syncResults, resp.syncPending);
    } catch (error) {
      const message = errorMessage(error);
      setStatusText(message);
      showToast(message || '登录失败', 'error');
    } finally {
      setBusy(false);
    }
  };

  const handleEmailCodeLogin = async () => {
    if (!email.trim() || !emailCode.trim()) {
      showToast('请输入邮箱和验证码', 'error');
      return;
    }

    setBusy(true);
    setStatusText('正在验证邮箱并同步模型...');
    try {
      const resp = await accountApi.loginWithEmailCode({
        email: email.trim(),
        code: emailCode.trim(),
        baseUrl: DEFAULT_BASE_URL,
      });
      await finishLogin(resp.account || null, '登录成功', resp.syncResults, resp.syncPending);
    } catch (error) {
      const message = errorMessage(error);
      setStatusText(message);
      showToast(message || '验证码登录失败', 'error');
    } finally {
      setBusy(false);
    }
  };

  const syncModels = async () => {
    setBusy(true);
    setStatusText('正在同步模型...');
    try {
      const resp = await accountApi.sync();
      applyAccount(resp.account || null);
      setStatusText('模型已同步');
      showToast('模型已同步', 'success');
      await loadSubscription(true);
    } catch (error) {
      const message = errorMessage(error);
      setStatusText(message);
      showToast(message || '同步失败', 'error');
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    subscriptionRequestVersion.current += 1;
    setBusy(true);
    setStatusText('正在退出模型账号...');
    try {
      await accountApi.logout();
      applyAccount(null);
      setSubscription(null);
      setStatusText('已退出账号');
      showToast('已退出模型账号', 'info');
    } catch (error) {
      const message = errorMessage(error);
      setStatusText(message);
      showToast(message || '退出失败', 'error');
    } finally {
      setBusy(false);
    }
  };

  const handleOpenSubscription = async () => {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      const message = '当前网络不可用，请联网后再打开订阅页';
      setStatusText(message);
      showToast(message, 'error');
      return;
    }
    if (!subscriptionUrl) {
      const message = '订阅页地址不可用，请刷新账号后重试';
      setStatusText(message);
      showToast(message, 'error');
      return;
    }
    try {
      await openExternalUrl(subscriptionUrl);
      const message = '订阅页已在浏览器打开';
      setStatusText(message);
      showToast(message, 'success');
    } catch (error) {
      const message = `订阅页打开失败：${errorMessage(error)}`;
      setStatusText(message);
      showToast(message, 'error');
    }
  };

  const handleOpenRegistration = async () => {
    const url = authCapabilities.registrationUrl || `${DEFAULT_BASE_URL}/register`;
    try {
      await openExternalUrl(url);
      const message = '已在浏览器打开网页注册；注册完成后返回这里使用密码登录。';
      setStatusText(message);
      showToast(message, 'success');
    } catch (error) {
      const message = `网页注册打开失败：${errorMessage(error)}`;
      setStatusText(message);
      showToast(message, 'error');
    }
  };

  const continueAsGuest = () => {
    showToast('已关闭模型账号登录页。模型同步需要先登录账号。', 'info');
    setCurrentPage('dashboard');
  };

  const busyTitle = '正在处理账号请求';

  if (loggedIn) {
    return (
      <div
        data-account-subscription-page
        data-white-label-layout="account-subscription"
        className="loom-white-page flex h-full flex-col overflow-hidden bg-surface text-text"
      >
        <BusyOverlay
          active={busy}
          title={busyTitle}
          detail={`${APP_DISPLAY_NAME} 正在连接模型服务。`}
        />

        <header className="shrink-0 border-b border-border px-8 py-7">
          <div className="text-sm font-black text-accent">模型账户</div>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-[30px] font-black leading-tight text-text">账户与用量</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">
                模型、余额、套餐和用量均以服务端账户数据为准。
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void refresh()}
                disabled={loading || busy}
                className="h-10 rounded-[8px] border border-border bg-surface-alt px-4 text-sm font-black text-text transition hover:border-accent/50 disabled:opacity-55"
              >
                刷新账号
              </button>
              <button
                type="button"
                onClick={() => setCurrentPage('models')}
                className="h-10 rounded-[8px] bg-accent px-4 text-sm font-black text-accent-ink transition hover:bg-accent-hover"
              >
                模型选择
              </button>
            </div>
          </div>
        </header>

        <main className="loom-account-main min-h-0 flex-1 overflow-y-auto px-6 py-6 xl:px-8">
          <div className="loom-account-layout mx-auto grid w-full max-w-[1320px] gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
            <section className="loom-account-sidebar space-y-5">
              <div className="border-y border-border/70 py-5">
                <div className="flex items-start gap-4">
                  <LoomLogoMark className="h-12 w-12 rounded-[8px] border border-border bg-surface-alt" />
                  <div className="min-w-0">
                    <div className="text-xs font-black text-accent">已登录</div>
                    <div className="mt-1 truncate text-xl font-black text-text" title={account?.account || ''}>
                      {account?.account || '模型账户'}
                    </div>
                    <div className="mt-2 text-sm text-text-muted">
                      {totalModels ? `${totalModels} 个模型可用` : '模型待同步'}
                    </div>
                  </div>
                </div>
              </div>

              <div className="border-y border-border/70 py-5">
                <div className="text-sm font-black text-text">当前模型</div>
                <InfoRow label="默认文本模型" value={modelHint} />
                <InfoRow label="最近同步" value={formatTime(account?.lastOnlineAt)} />
                <div className="mt-5 grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={syncModels}
                    disabled={busy}
                    className="h-11 rounded-[8px] bg-accent text-sm font-black text-accent-ink transition hover:bg-accent-hover disabled:opacity-55"
                  >
                    同步模型
                  </button>
                  <button
                    type="button"
                    onClick={logout}
                    disabled={busy}
                    className="h-11 rounded-[8px] border border-border bg-surface text-sm font-black text-text-muted transition hover:border-status-danger/50 hover:text-status-danger disabled:opacity-55"
                  >
                    退出登录
                  </button>
                </div>
              </div>
            </section>

            <section
              data-native-subscription-dashboard
              data-subscription-external-fallback
              className="loom-account-subscription border-y border-border/70"
            >
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <div>
                  <h2 className="text-lg font-black text-text">账户与余额</h2>
                  <p className="mt-1 text-xs leading-5 text-text-muted">充值、消耗记录与 API 密钥由模型服务同步；购买与支付在浏览器完成。</p>
                </div>
                <button
                  type="button"
                  onClick={() => loadSubscription(false)}
                  disabled={busy}
                  className="h-9 rounded-[8px] border border-border bg-surface-alt px-4 text-xs font-black text-text transition hover:border-accent/50 disabled:opacity-55"
                >
                  刷新余额
                </button>
              </div>
              <div className="loom-account-subscription-body space-y-6 px-6 py-6">
                <div className="loom-account-metric-grid grid gap-4">
                  <MetricTile label="可用余额" value={displayValue(subscription?.balance, usageValue(account, ['quota', 'remainQuota', 'remainingQuota']))} accent />
                  <MetricTile label="累计消耗" value={displayValue(subscription?.usage?.usedQuota, usageValue(account, ['usedQuota', 'used', 'quotaUsed']))} />
                  <MetricTile label="请求次数" value={displayValue(subscription?.usage?.requestCount, usageValue(account, ['requestCount', 'requests']))} />
                  <MetricTile label="我的邀请码" value={displayValue(subscription?.inviteCode || subscription?.invitationCode || subscription?.referralCode, usageValue(account, ['inviteCode', 'invitationCode', 'referralCode'], '登录后查看'))} />
                  <MetricTile label="当前套餐" value={displayValue(subscription?.plan, account?.plan || '暂无')} />
                </div>

                <div className="flex flex-wrap items-center justify-between gap-4 border-t border-border/70 pt-5">
                  <div>
                    <div className="text-sm font-black text-text">套餐与购买</div>
                    <div className="mt-1 text-xs leading-5 text-text-muted">套餐详情与支付流程由服务端账户中心提供。</div>
                  </div>
                  <button
                    type="button"
                    onClick={handleOpenSubscription}
                    disabled={!subscriptionUrl}
                    className="h-10 rounded-[8px] bg-accent px-4 text-sm font-black text-accent-ink transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-55"
                  >
                    打开账户中心
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <InfoPanel label="到期时间" value={formatTime(subscription?.expiresAt)} />
                  <InfoPanel label="购买入口" value={subscriptionUrl ? '浏览器打开' : '地址不可用'} />
                </div>
              </div>
            </section>
          </div>

          {statusText ? (
            <div className="mt-5 rounded-[12px] border border-border bg-surface-alt px-4 py-3 text-sm leading-6 text-text-muted">
              {statusText}
            </div>
          ) : null}
        </main>
      </div>
    );
  }

  return (
    <div
      data-account-subscription-page
      className="relative h-full overflow-hidden bg-app-bg text-text"
    >
      <BusyOverlay
        active={busy}
        title={busyTitle}
        detail={`${APP_DISPLAY_NAME} 正在连接模型服务。`}
      />

      <div className="absolute inset-0 opacity-80">
        <div className="mx-auto grid h-full max-w-[1160px] grid-cols-[minmax(0,1fr)_360px] gap-7 px-8 py-7 blur-[1px]">
          <section className="min-w-0">
            <div className="text-[11px] font-bold tracking-[0.18em] text-accent">模型账户</div>
            <h1 className="mt-2 text-[34px] font-black leading-tight text-text">登录模型账户</h1>
            <div className="mt-8 grid grid-cols-2 gap-4">
              <GhostTile label="账号" value={accountStateText} />
              <GhostTile label="模型" value={totalModels ? `${totalModels} 个` : '待同步'} />
              <GhostTile label="余额" value={displayValue(subscription?.balance, usageValue(account, ['quota', 'remainQuota', 'remainingQuota']))} />
              <GhostTile label="来源" value="api.heang.top" />
            </div>
            <div className="mt-7 rounded-[22px] border border-border/70 bg-surface-alt/45 p-6">
              <div className="text-sm font-black text-text">演示版能力</div>
              <div className="mt-4 grid grid-cols-3 gap-3">
                <SoftPill>安装器</SoftPill>
                <SoftPill>手机控制</SoftPill>
                <SoftPill>模型同步</SoftPill>
              </div>
            </div>
          </section>

          <aside className="rounded-[22px] border border-border/70 bg-surface-alt/35 p-5">
            <div className="text-sm font-black text-text">当前状态</div>
            <InfoRow label="账号" value={account?.account || '访客'} />
            <InfoRow label="订阅" value={displayValue(subscription?.plan, account?.plan || '暂无')} />
            <InfoRow label="最近同步" value={formatTime(account?.lastOnlineAt)} />
          </aside>
        </div>
      </div>

      <div className="absolute inset-0 bg-[#1c211c]/45 backdrop-blur-[2px]" />

      <div className="relative z-10 flex h-full items-center justify-center px-6 py-8">
        <section className="w-full max-w-[440px] rounded-[18px] border border-[#2C332C] bg-[#14140F]/96 p-8 text-[#F6F2E8] shadow-[0_34px_100px_rgba(0,0,0,0.42)]">
          <div className="mb-7 flex items-start justify-between gap-4">
            <div className="flex min-w-0 gap-4">
              <LoomLogoMark className="h-11 w-11 rounded-[12px] border border-[#31554B] bg-[#0B2F2A]" />
              <div className="min-w-0">
                <h1 className="text-[24px] font-black leading-tight">{APP_DISPLAY_NAME}</h1>
                <p className="mt-2 text-sm leading-6 text-[#AAA59A]">
                  登录后同步模型、余额与智能体配置。
                </p>
                <button
                  type="button"
                  onClick={handleOpenRegistration}
                  className="mt-3 inline-flex rounded-full border border-[#1E7A63]/45 bg-[#0B6B57]/16 px-3 py-1 text-xs font-black text-[#BFF7E7] transition hover:border-[#3DBD9D] hover:bg-[#0B6B57]/28"
                >
                  新用户请前往网页注册
                </button>
              </div>
            </div>
            <button
              type="button"
              className="shrink-0 text-2xl leading-none text-[#9D978C] transition hover:text-[#F6F2E8]"
              onClick={() => setCurrentPage('dashboard')}
              aria-label="关闭登录页"
            >
              ×
            </button>
          </div>

          <div className="space-y-4">
              <div className="grid grid-cols-2 gap-2 rounded-[11px] border border-[#302B23] bg-[#100F0B] p-1">
                <ModeButton
                  active={authMode === 'email'}
                  onClick={() => setAuthMode('email')}
                  disabled={!authCapabilities.inlineEmailCode}
                  title={authCapabilities.emailReason}
                >验证码登录</ModeButton>
                <ModeButton active={authMode === 'password'} onClick={() => setAuthMode('password')}>密码登录</ModeButton>
              </div>

              {authMode !== 'password' && (!authCapabilities.inlineEmailCode || authCapabilities.webRegistrationRequired) ? (
                <div className="rounded-[10px] border border-[#31554B] bg-[#10201B] px-3 py-3 text-xs leading-5 text-[#CDEFE4]">
                  <div>{authCapabilities.emailReason}</div>
                  {authCapabilities.webRegistrationRequired ? (
                    <button
                      type="button"
                      onClick={handleOpenRegistration}
                      className="mt-2 font-black text-[#F6F2E8] underline decoration-[#1E7A63] underline-offset-4"
                    >
                      网页注册
                    </button>
                  ) : null}
                </div>
              ) : null}

              {authMode === 'email' ? (
                <>
                  <label className="block">
                    <span className="mb-2 block text-xs font-bold text-[#A9A397]">邮箱</span>
                    <input
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      className="h-11 w-full rounded-[9px] border border-[#3A3327] bg-[#12100B] px-3 text-sm text-[#F6F2E8] outline-none transition placeholder:text-[#615B52] focus:border-[#1E7A63] focus:ring-2 focus:ring-[#1E7A63]/25"
                      placeholder="请输入模型账号邮箱"
                      autoComplete="email"
                    />
                  </label>
                  <div className="grid grid-cols-[minmax(0,1fr)_112px] gap-2">
                    <label className="block min-w-0">
                      <span className="mb-2 block text-xs font-bold text-[#A9A397]">邮箱验证码</span>
                      <input
                        value={emailCode}
                        onChange={(event) => setEmailCode(event.target.value)}
                        className="h-11 w-full rounded-[9px] border border-[#3A3327] bg-[#12100B] px-3 text-sm text-[#F6F2E8] outline-none transition placeholder:text-[#615B52] focus:border-[#1E7A63] focus:ring-2 focus:ring-[#1E7A63]/25"
                        placeholder="6 位验证码"
                        autoComplete="one-time-code"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={sendEmailCode}
                      disabled={busy}
                      className="mt-[22px] h-11 rounded-[9px] border border-[#31554B] bg-[#10201B] text-sm font-black text-[#CDEFE4] transition hover:border-[#0B6B57] disabled:opacity-55"
                    >
                      发送验证码
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={handleEmailCodeLogin}
                    disabled={busy}
                    className="h-11 w-full rounded-[9px] bg-[#0B6B57] text-sm font-black text-[#F5FFF9] shadow-[0_16px_30px_rgba(11,107,87,0.26)] transition hover:bg-[#0E7B64] disabled:cursor-not-allowed disabled:opacity-55"
                  >
                    {busy ? '验证中...' : '验证并登录'}
                  </button>
                  <button
                    type="button"
                    onClick={handleOpenRegistration}
                    className="w-full text-center text-sm font-bold text-[#A9A397] transition hover:text-[#F6F2E8]"
                  >
                    还没有账户？网页注册
                  </button>
                </>
              ) : (
                <>
                  <label className="block">
                    <span className="mb-2 block text-xs font-bold text-[#A9A397]">用户名或邮箱</span>
                    <input
                      value={loginName}
                      onChange={(event) => setLoginName(event.target.value)}
                      className="h-11 w-full rounded-[9px] border border-[#3A3327] bg-[#12100B] px-3 text-sm text-[#F6F2E8] outline-none transition placeholder:text-[#615B52] focus:border-[#1E7A63] focus:ring-2 focus:ring-[#1E7A63]/25"
                      placeholder="请输入模型账号"
                      autoComplete="username"
                      autoFocus
                    />
                  </label>
                  <PasswordInput
                    value={password}
                    autoComplete="current-password"
                    onChange={setPassword}
                    onEnter={handlePasswordLogin}
                  />
                  <button
                    type="button"
                    onClick={handlePasswordLogin}
                    disabled={busy}
                    className="h-11 w-full rounded-[9px] bg-[#0B6B57] text-sm font-black text-[#F5FFF9] shadow-[0_16px_30px_rgba(11,107,87,0.26)] transition hover:bg-[#0E7B64] disabled:cursor-not-allowed disabled:opacity-55"
                  >
                    {busy ? '登录中...' : '登录'}
                  </button>
                  <button
                    type="button"
                    onClick={handleOpenRegistration}
                    className="w-full text-center text-sm font-bold text-[#A9A397] transition hover:text-[#F6F2E8]"
                  >
                    还没有账户？网页注册
                  </button>
                </>
              )}

              <button
                type="button"
                onClick={continueAsGuest}
                className="mt-5 w-full rounded-[10px] border border-[#3A3327] bg-[#15130E] px-4 py-3 text-sm font-black text-[#F6F2E8] transition hover:border-[#0B6B57]/60 hover:bg-[#10201B]"
              >
                暂不登录，继续以访客身份浏览
              </button>
              <button
                type="button"
                onClick={handleOpenSubscription}
                className="w-full text-center text-sm font-bold text-[#A9A397] transition hover:text-[#F6F2E8]"
              >
                打开订阅页
              </button>

          </div>

          {statusText ? (
            <div className="mt-5 rounded-[10px] border border-[#3A3327] bg-[#10130F] px-3 py-2 text-sm leading-6 text-[#BBB5A9]">
              {statusText}
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
};

const ModeButton: React.FC<{
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  children: React.ReactNode;
}> = ({ active, onClick, disabled = false, title, children }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    title={title}
    className={[
      'h-9 rounded-[8px] text-xs font-black transition disabled:cursor-not-allowed disabled:opacity-45',
      active ? 'bg-[#0B6B57] text-[#F5FFF9]' : 'text-[#A9A397] hover:bg-[#171A14] hover:text-[#F6F2E8]',
    ].join(' ')}
  >
    {children}
  </button>
);

const PasswordInput: React.FC<{
  value: string;
  autoComplete: string;
  onChange: (value: string) => void;
  onEnter: () => void;
}> = ({ value, autoComplete, onChange, onEnter }) => (
  <label className="block">
    <span className="mb-2 block text-xs font-bold text-[#A9A397]">密码</span>
    <input
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-11 w-full rounded-[9px] border border-[#3A3327] bg-[#12100B] px-3 text-sm text-[#F6F2E8] outline-none transition placeholder:text-[#615B52] focus:border-[#1E7A63] focus:ring-2 focus:ring-[#1E7A63]/25"
      placeholder="请输入密码"
      type="password"
      autoComplete={autoComplete}
      onKeyDown={(event) => {
        if (event.key === 'Enter') onEnter();
      }}
    />
  </label>
);

const GhostTile: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="min-w-0 rounded-[8px] border border-border/70 bg-surface-alt/35 p-4">
    <div className="text-xs font-bold text-text-subtle">{label}</div>
    <div className="mt-2 truncate text-xl font-black text-text" title={value}>{value}</div>
  </div>
);

const MetricTile: React.FC<{ label: string; value: string; accent?: boolean }> = ({ label, value, accent }) => (
  <div className={['min-w-0 rounded-[8px] border bg-surface-alt/40 p-4', accent ? 'border-accent/45' : 'border-border'].join(' ')}>
    <div className="text-xs font-bold text-text-subtle">{label}</div>
    <div className="mt-2 truncate text-[22px] font-black text-text" title={value}>{value}</div>
  </div>
);

const InfoPanel: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="min-w-0 rounded-[8px] border border-border bg-surface-alt/35 px-4 py-3">
    <div className="text-xs font-bold text-text-subtle">{label}</div>
    <div className="mt-1 break-words text-sm font-black text-text" title={value}>{value}</div>
  </div>
);

const SoftPill: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="rounded-full border border-border/70 bg-surface/45 px-3 py-2 text-center text-xs font-black text-text-muted">
    {children}
  </span>
);

const InfoRow: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="mt-4 border-t border-border/60 pt-4">
    <div className="text-xs font-bold text-text-subtle">{label}</div>
    <div className="mt-2 truncate text-sm font-bold text-text" title={value}>{value}</div>
  </div>
);
