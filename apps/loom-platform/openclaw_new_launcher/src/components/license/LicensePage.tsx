import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { open } from '@tauri-apps/plugin-shell';
import { UserRound } from 'lucide-react';
import qrcode from 'qrcode-generator';
import { BusyOverlay, showToast } from '../common';
import { LoomLogoMark } from '../brand/LoomBrand';
import {
  accountApi,
  parseErrorText,
  type AccountSnapshot,
  type AccountAuthCapabilities,
  type AccountPaymentCatalog,
  type AccountPaymentOrder,
  type AccountSubscriptionSnapshot,
} from '../../services/api';
import { accountCacheUsable, loadCachedAccount, saveCachedAccount } from '../../services/startupCache';
import { useAgentStore } from '../../stores/agentStore';
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

function displayValue(value: unknown, fallback = '服务暂未返回'): string {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value);
}

function planDisplayName(value: unknown): string {
  const plan = displayValue(value, '').trim();
  const names: Record<string, string> = {
    default: '基础套餐',
    free: '基础套餐',
    basic: '基础套餐',
    standard: '标准套餐',
    pro: '专业套餐',
    professional: '专业套餐',
    enterprise: '企业套餐',
    inactive: '未激活',
  };
  return names[plan.toLowerCase()] || plan || '服务暂未返回';
}

function usageValue(account: AccountSnapshot | null, keys: string[], fallback = '服务暂未返回'): string {
  const usage = account?.usage;
  if (!usage || typeof usage !== 'object') return fallback;
  for (const key of keys) {
    const value = usage[key];
    if (value !== undefined && value !== null && value !== '') return String(value);
  }
  return fallback;
}

function formatTime(value?: string | number | null, fallback = '暂无'): string {
  if (value === undefined || value === null || value === '') return fallback;
  const normalized = typeof value === 'number' && value < 10_000_000_000 ? value * 1000 : value;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return String(value);
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

function accountIdentity(account: AccountSnapshot | null): string {
  return String(
    account?.accountEntitlement?.accountId
    || account?.memberId
    || account?.account
    || '',
  ).trim();
}

const PAYMENT_RESUME_STORAGE_KEY = 'loom.account.payment.resume.v1';
const PAYMENT_RESUME_MAX_AGE_MS = 24 * 60 * 60 * 1000;

interface PaymentResumeState {
  schema: 'loom.payment-resume.v1';
  accountIdentity: string;
  planKey: string;
  paymentType: 'alipay' | 'wxpay';
  requestId: string;
  orderId?: string;
  savedAt: number;
}

function readPaymentResume(identity: string): PaymentResumeState | null {
  try {
    const raw = window.localStorage.getItem(PAYMENT_RESUME_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PaymentResumeState>;
    const valid = parsed.schema === 'loom.payment-resume.v1'
      && parsed.accountIdentity === identity
      && typeof parsed.planKey === 'string'
      && ['alipay', 'wxpay'].includes(String(parsed.paymentType || ''))
      && typeof parsed.requestId === 'string'
      && /^[A-Za-z0-9_-]{16,128}$/.test(parsed.requestId)
      && typeof parsed.savedAt === 'number'
      && Date.now() - parsed.savedAt <= PAYMENT_RESUME_MAX_AGE_MS
      && (!parsed.orderId || /^[A-Za-z0-9_-]{1,160}$/.test(parsed.orderId));
    if (!valid) {
      window.localStorage.removeItem(PAYMENT_RESUME_STORAGE_KEY);
      return null;
    }
    return parsed as PaymentResumeState;
  } catch {
    return null;
  }
}

function writePaymentResume(state: Omit<PaymentResumeState, 'schema' | 'savedAt'>): void {
  try {
    window.localStorage.setItem(PAYMENT_RESUME_STORAGE_KEY, JSON.stringify({
      schema: 'loom.payment-resume.v1',
      ...state,
      savedAt: Date.now(),
    } satisfies PaymentResumeState));
  } catch {
    // The server-side idempotency key still protects the current in-memory attempt.
  }
}

function clearPaymentResume(identity: string): void {
  const current = readPaymentResume(identity);
  if (!current) return;
  try {
    window.localStorage.removeItem(PAYMENT_RESUME_STORAGE_KEY);
  } catch {
    // Storage may be unavailable in hardened WebView profiles.
  }
}

function createPaymentRequestId(): string {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi?.getRandomValues) {
    throw new Error('当前环境缺少安全随机数，无法安全创建支付订单');
  }
  if (typeof cryptoApi.randomUUID === 'function') return cryptoApi.randomUUID();
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
}

function createPaymentQrDataUri(value?: string): string {
  const content = String(value || '').trim();
  if (!content || content.length > 4096) return '';
  try {
    const qr = qrcode(0, 'M');
    qr.addData(content);
    qr.make();
    const dataUrl = qr.createDataURL(5, 2);
    return dataUrl.startsWith('data:image/gif;base64') ? dataUrl : '';
  } catch {
    return '';
  }
}

function paymentStatusText(status?: string): string {
  const values: Record<string, string> = {
    pending: '等待扫码支付',
    paid: '支付成功，权益已同步',
    expired: '订单已过期，请重新下单',
    creation_uncertain: '订单创建结果待确认，请勿重复付款',
    failed: '订单失败，请重新下单',
  };
  return values[String(status || '')] || String(status || '等待确认');
}

export const LicensePage: React.FC = () => {
  const cachedAccount = useRef<AccountSnapshot | null>(loadCachedAccount());
  const subscriptionRequestVersion = useRef(0);
  const paymentRequestVersion = useRef(0);
  const paymentRestoreIdentity = useRef('');
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
  const [entitlementCode, setEntitlementCode] = useState('');
  const [paymentCatalog, setPaymentCatalog] = useState<AccountPaymentCatalog | null>(null);
  const [paymentCatalogLoading, setPaymentCatalogLoading] = useState(false);
  const [paymentChannel, setPaymentChannel] = useState<'alipay' | 'wxpay'>('alipay');
  const [paymentOrder, setPaymentOrder] = useState<AccountPaymentOrder | null>(null);
  const [paymentBusy, setPaymentBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(() => !hasCachedAccount);
  const [usingCachedAccount, setUsingCachedAccount] = useState(hasCachedAccount);
  const [statusText, setStatusText] = useState('');
  const { checkLicense, setCurrentPage } = useAppStore();

  const loggedIn = Boolean(account?.loggedIn);
  const accountWritable = loggedIn && !usingCachedAccount;
  const subscriptionIsCached = Boolean(subscription?.offline || subscription?.stale);
  const totalModels = modelTotal(account);
  const modelHint = useMemo(() => {
    const selected = account?.selectedModels?.text;
    if (selected) return selected;
    return account?.models?.text?.slice(0, 3).join(' / ') || '登录后同步';
  }, [account]);
  const purchaseUrl = subscription?.purchaseUrl || account?.purchaseUrl || DEFAULT_ACCOUNT_CENTER_URL;
  const subscriptionUrl = useMemo(() => safeSubscriptionUrl(purchaseUrl), [purchaseUrl]);
  const accountStateText = loading ? '读取中' : usingCachedAccount ? '待在线验证' : loggedIn ? '已登录' : '未登录';
  const accountEntitlement = account?.accountEntitlement;
  const entitlementActive = accountEntitlement?.source === 'signed_lease'
    && accountEntitlement?.features?.includes('matrix.devices') === true;
  const entitlementExpiresAt = entitlementActive
    ? formatTime(accountEntitlement?.expiresAt)
    : '未激活';
  const activeAccountIdentity = accountIdentity(account);
  const paymentQrSrc = useMemo(
    () => createPaymentQrDataUri(paymentOrder?.qrcode || paymentOrder?.payUrl),
    [paymentOrder?.payUrl, paymentOrder?.qrcode],
  );

  const applyAccount = useCallback((
    next: AccountSnapshot | null,
    options: { cached?: boolean; persist?: boolean } = {},
  ) => {
    subscriptionRequestVersion.current += 1;
    const previousIdentity = accountIdentity(cachedAccount.current);
    const nextIdentity = accountIdentity(next);
    if (previousIdentity !== nextIdentity) {
      useAgentStore.getState().reset();
      paymentRequestVersion.current += 1;
      paymentRestoreIdentity.current = '';
      setPaymentCatalog(null);
      setPaymentOrder(null);
    }
    cachedAccount.current = next;
    if (options.persist !== false) saveCachedAccount(next);
    setAccount(next);
    setSubscription(next?.subscription || null);
    setUsingCachedAccount(Boolean(options.cached || next?.offline || next?.stale));
  }, []);

  const refresh = useCallback(async (options: { background?: boolean } = {}) => {
    if (!options.background) setLoading(true);
    try {
      const resp = cachedAccount.current?.loggedIn
        ? await accountApi.sync()
        : await accountApi.current();
      applyAccount(resp.account || null, { persist: true });
      setStatusText('');
    } catch (error) {
      const cached = loadCachedAccount();
      applyAccount(cached || null, { cached: Boolean(cached), persist: false });
      setStatusText(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [applyAccount]);

  useEffect(() => {
    if (accountCacheUsable(cachedAccount.current)) {
      applyAccount(cachedAccount.current, { cached: true, persist: false });
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

  const loadSubscription = useCallback(async (quiet = false) => {
    const requestVersion = ++subscriptionRequestVersion.current;
    if (!quiet) setBusy(true);
    try {
      const resp = await accountApi.subscription();
      if (requestVersion !== subscriptionRequestVersion.current) return;
      setSubscription(resp.subscription || null);
      if (!quiet) {
        if (resp.subscription?.offline || resp.subscription?.stale) {
          const message = resp.subscription?.message || '余额与套餐显示上次快照；服务恢复后可重新刷新。';
          setStatusText(message);
          showToast(message, 'info');
        } else {
          setStatusText('余额与套餐已从服务端更新');
          showToast('余额与套餐已更新', 'success');
        }
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
  }, []);

  const loadPaymentPlans = useCallback(async (quiet = true) => {
    const requestVersion = ++paymentRequestVersion.current;
    const identity = accountIdentity(cachedAccount.current);
    if (!cachedAccount.current?.loggedIn || !identity) return;
    setPaymentCatalogLoading(true);
    try {
      const response = await accountApi.paymentPlans();
      if (
        requestVersion !== paymentRequestVersion.current
        || identity !== accountIdentity(cachedAccount.current)
      ) return;
      setPaymentCatalog(response);
      const availableChannels = response.payment?.channels || [];
      if (!availableChannels.includes(paymentChannel)) {
        if (availableChannels.includes('alipay')) setPaymentChannel('alipay');
        else if (availableChannels.includes('wxpay')) setPaymentChannel('wxpay');
      }
    } catch (error) {
      if (
        requestVersion !== paymentRequestVersion.current
        || identity !== accountIdentity(cachedAccount.current)
      ) return;
      setPaymentCatalog(null);
      if (!quiet) {
        const message = errorMessage(error);
        setStatusText(message);
        showToast(message || '套餐加载失败', 'error');
      }
    } finally {
      if (requestVersion === paymentRequestVersion.current) {
        setPaymentCatalogLoading(false);
      }
    }
  }, [paymentChannel]);

  const verifyPaymentOrder = useCallback(async (
    orderId: string,
    quiet = false,
    reconcile = false,
  ) => {
    const requestVersion = ++paymentRequestVersion.current;
    const identity = accountIdentity(cachedAccount.current);
    if (!identity || !orderId) return;
    if (!quiet) setPaymentBusy(true);
    try {
      const response = await accountApi.paymentOrderStatus({ orderId, reconcile });
      if (
        requestVersion !== paymentRequestVersion.current
        || identity !== accountIdentity(cachedAccount.current)
      ) return;
      setPaymentOrder(response.order);
      if (response.order.status === 'paid') {
        clearPaymentResume(identity);
        if (response.account) applyAccount(response.account);
        const refreshResults = await Promise.allSettled([
          checkLicense(),
          loadSubscription(true),
        ]);
        const localSyncPending = response.entitlementSyncPending
          || refreshResults.some((result) => result.status === 'rejected');
        const message = localSyncPending
          ? '支付已确认，权益正在同步；请稍后点击刷新账号。'
          : '支付已确认，手机矩阵、云模板和 Skill 权益已开通。';
        setStatusText(message);
        showToast(message, localSyncPending ? 'info' : 'success');
      } else {
        if (['expired', 'failed'].includes(response.order.status)) {
          clearPaymentResume(identity);
        }
        if (quiet) return;
        const message = paymentStatusText(response.order.status);
        setStatusText(message);
        showToast(message, response.order.status === 'pending' ? 'info' : 'error');
      }
    } catch (error) {
      if (
        requestVersion !== paymentRequestVersion.current
        || identity !== accountIdentity(cachedAccount.current)
      ) return;
      if (!quiet) {
        const message = errorMessage(error);
        setStatusText(message);
        showToast(message || '订单状态查询失败', 'error');
      }
    } finally {
      if (!quiet && requestVersion === paymentRequestVersion.current) {
        setPaymentBusy(false);
      }
    }
  }, [applyAccount, checkLicense, loadSubscription]);

  const startPayment = async (planKey: string) => {
    if (!accountWritable) {
      const message = '请先完成账号在线验证，再创建支付订单。';
      setStatusText(message);
      showToast(message, 'info');
      return;
    }
    const requestVersion = ++paymentRequestVersion.current;
    const identity = accountIdentity(cachedAccount.current);
    const previousAttempt = readPaymentResume(identity);
    const requestId = previousAttempt?.planKey === planKey
      && previousAttempt.paymentType === paymentChannel
      ? previousAttempt.requestId
      : createPaymentRequestId();
    writePaymentResume({
      accountIdentity: identity,
      planKey,
      paymentType: paymentChannel,
      requestId,
      orderId: previousAttempt?.planKey === planKey
        && previousAttempt.paymentType === paymentChannel
        ? previousAttempt.orderId
        : undefined,
    });
    setPaymentBusy(true);
    setPaymentOrder(null);
    try {
      const response = await accountApi.createPaymentOrder({
        planKey,
        paymentType: paymentChannel,
        requestId,
      });
      if (
        requestVersion !== paymentRequestVersion.current
        || identity !== accountIdentity(cachedAccount.current)
      ) return;
      setPaymentOrder(response.order);
      writePaymentResume({
        accountIdentity: identity,
        planKey,
        paymentType: paymentChannel,
        requestId,
        orderId: response.order.orderId,
      });
      if (['paid', 'expired', 'failed'].includes(response.order.status)) {
        clearPaymentResume(identity);
      }
      const message = response.order.status === 'creation_uncertain'
        ? '订单创建结果待确认，请勿重复付款。'
        : '订单已创建，请使用手机扫码支付。';
      setStatusText(message);
      showToast(message, response.order.status === 'creation_uncertain' ? 'info' : 'success');
    } catch (error) {
      if (
        requestVersion !== paymentRequestVersion.current
        || identity !== accountIdentity(cachedAccount.current)
      ) return;
      const message = errorMessage(error);
      setStatusText(message);
      showToast(message || '订单创建失败', 'error');
    } finally {
      if (requestVersion === paymentRequestVersion.current) setPaymentBusy(false);
    }
  };

  useEffect(() => {
    if (!accountWritable || !activeAccountIdentity) {
      paymentRequestVersion.current += 1;
      setPaymentCatalog(null);
      setPaymentOrder(null);
      return;
    }
    void loadPaymentPlans(true);
  }, [accountWritable, activeAccountIdentity, loadPaymentPlans]);

  useEffect(() => {
    if (!accountWritable || !activeAccountIdentity) {
      paymentRestoreIdentity.current = '';
      return;
    }
    if (paymentRestoreIdentity.current === activeAccountIdentity) return;
    paymentRestoreIdentity.current = activeAccountIdentity;
    const resumable = readPaymentResume(activeAccountIdentity);
    if (resumable?.orderId) {
      void verifyPaymentOrder(resumable.orderId, true);
    } else if (resumable) {
      setStatusText('检测到上次未完成的下单请求；再次选择同一套餐即可安全恢复。');
    }
  }, [accountWritable, activeAccountIdentity, verifyPaymentOrder]);

  useEffect(() => {
    if (!paymentOrder?.orderId || paymentOrder.status !== 'pending') return;
    let checking = false;
    const timer = window.setInterval(() => {
      if (checking) return;
      checking = true;
      void verifyPaymentOrder(paymentOrder.orderId, true).finally(() => {
        checking = false;
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [paymentOrder?.orderId, paymentOrder?.status, verifyPaymentOrder]);

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
    if (!accountWritable) {
      const message = '当前显示上次安全快照，请先重试在线验证后再同步模型。';
      setStatusText(message);
      showToast(message, 'info');
      return;
    }
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

  const handleRedeemEntitlement = async () => {
    if (!accountWritable) {
      const message = '当前显示上次安全快照，请先重试在线验证后再绑定商业授权。';
      setStatusText(message);
      showToast(message, 'info');
      return;
    }
    const code = entitlementCode.trim();
    if (!code) {
      showToast('请输入商业矩阵授权码', 'error');
      return;
    }
    setBusy(true);
    setStatusText('正在绑定商业矩阵授权...');
    try {
      const resp = await accountApi.redeemEntitlement({ code });
      applyAccount(resp.account || null);
      await checkLicense();
      setEntitlementCode('');
      const message = '商业矩阵授权已绑定当前账号';
      setStatusText(message);
      showToast(message, 'success');
    } catch (error) {
      const message = errorMessage(error);
      setStatusText(message);
      showToast(message || '商业矩阵授权绑定失败', 'error');
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    subscriptionRequestVersion.current += 1;
    paymentRequestVersion.current += 1;
    clearPaymentResume(activeAccountIdentity);
    setBusy(true);
    setStatusText('正在退出模型账号...');
    try {
      await accountApi.logout();
      applyAccount(null);
      setSubscription(null);
      setPaymentCatalog(null);
      setPaymentOrder(null);
      setEntitlementCode('');
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
        className="loom-white-page flex h-full flex-col overflow-hidden bg-app-bg text-text"
      >
        <BusyOverlay
          active={busy}
          title={busyTitle}
          detail={`${APP_DISPLAY_NAME} 正在连接模型服务。`}
        />

        <header
          className="shrink-0 border-b border-border bg-surface px-6 py-4 xl:px-8"
          data-account-compact-header
        >
          <div className="text-xs font-black text-accent">模型服务账户</div>
          <div className="mt-1.5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-[24px] font-black leading-tight text-text">账户与用量</h1>
              <p className="mt-1 max-w-2xl text-xs leading-5 text-text-muted">
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
                {usingCachedAccount ? '重试在线验证' : '刷新账号'}
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

        {usingCachedAccount ? (
          <div
            data-account-cache-warning
            role="status"
            className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-status-warning bg-status-warning-soft px-6 py-3 text-sm text-status-warning-ink xl:px-8"
          >
            <div>
              <span className="font-black">当前显示上次安全快照，账号待在线验证。</span>
              <span className="ml-2">余额、套餐和授权状态可能已变化；写入操作已暂停。</span>
            </div>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading || busy}
              className="h-8 rounded-[8px] border border-status-warning px-3 text-xs font-black disabled:opacity-55"
            >
              重试在线验证
            </button>
          </div>
        ) : null}

        <main className="loom-account-main min-h-0 flex-1 overflow-y-auto px-6 py-6 xl:px-8">
          <div className="loom-account-layout mx-auto grid w-full max-w-[1320px] gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
            <section className="loom-account-sidebar space-y-5">
              <div className="border-y border-border/70 py-5">
                <div className="flex items-start gap-4">
                  <span
                    className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[8px] border border-border bg-surface-alt text-accent"
                    aria-hidden="true"
                    data-account-avatar
                  >
                    <UserRound className="h-6 w-6" />
                  </span>
                  <div className="min-w-0">
                    <div className="text-xs font-black text-accent">模型服务账户 · 已登录</div>
                    <div className="mt-1 truncate text-xl font-black text-text" title={account?.account || ''}>
                      {account?.account || '模型账户'}
                    </div>
                    <div className="mt-2 text-sm text-text-muted">
                      {totalModels ? `${totalModels} 个模型可用` : '模型待同步'}
                    </div>
                  </div>
                </div>
              </div>

              <div data-account-entitlement className="border-y border-border/70 py-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-black text-text">商业矩阵授权</div>
                    <div className="mt-1 text-xs leading-5 text-text-muted">授权绑定当前账号，可在已登录设备上使用。</div>
                  </div>
                  <span className={[
                    'shrink-0 rounded-full px-3 py-1 text-xs font-black',
                    entitlementActive ? 'bg-accent/12 text-accent' : 'bg-surface-alt text-text-muted',
                  ].join(' ')}>
                    {entitlementActive ? '已激活' : '未激活'}
                  </span>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-y border-border/70 py-4">
                  <div>
                    <div className="text-xs font-bold text-text-subtle">手机数上限</div>
                    <div className="mt-1 text-sm font-black text-text">
                      {entitlementActive ? '不限' : '0 台'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-bold text-text-subtle">到期时间</div>
                    <div className="mt-1 break-words text-sm font-black text-text">{entitlementExpiresAt}</div>
                  </div>
                </div>

                <label className="mt-4 block">
                  <span className="mb-2 block text-xs font-bold text-text-subtle">授权码</span>
                  <input
                    aria-label="商业矩阵授权码"
                    aria-describedby="commercial-entitlement-help"
                    value={entitlementCode}
                    disabled={!accountWritable}
                    onChange={(event) => setEntitlementCode(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') void handleRedeemEntitlement();
                    }}
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    className="h-11 w-full rounded-[8px] border border-border bg-surface-alt px-3 text-sm text-text outline-none transition placeholder:text-text-subtle focus:border-accent focus:ring-2 focus:ring-accent/20"
                    placeholder="请输入商业矩阵授权码"
                  />
                </label>
                <p
                  id="commercial-entitlement-help"
                  className="mt-2 text-xs leading-5 text-text-muted"
                  data-entitlement-helper
                >
                  {accountWritable
                    ? '授权码仅提交给授权服务验证；麓鸣不会回显或写入日志。'
                    : '当前为只读快照。请先完成在线验证，再输入授权码。'}
                </p>
                <button
                  type="button"
                  onClick={handleRedeemEntitlement}
                  disabled={busy || !accountWritable || !entitlementCode.trim()}
                  className="mt-3 h-11 w-full rounded-[8px] bg-accent text-sm font-black text-accent-ink transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled"
                >
                  {busy ? '正在绑定...' : '绑定当前账号'}
                </button>
              </div>

              <div className="border-y border-border/70 py-5">
                <div className="text-sm font-black text-text">当前模型</div>
                <InfoRow label="默认文本模型" value={modelHint} />
                <InfoRow label="最近同步" value={formatTime(account?.lastOnlineAt)} />
                <div className="mt-5 grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={syncModels}
                    disabled={busy || !accountWritable}
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
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
                <div>
                  <h2 className="text-lg font-black text-text">账户与余额</h2>
                  <p className="mt-1 text-xs leading-5 text-text-muted">充值、消耗记录与 API 密钥由模型服务同步；矩阵套餐可在麓鸣内扫码购买。</p>
                </div>
                <div className="flex items-center gap-3">
                  <span
                    className={subscriptionIsCached
                      ? 'rounded-full bg-status-warning-soft px-3 py-1 text-xs font-black text-status-warning-ink'
                      : 'rounded-full bg-accent/10 px-3 py-1 text-xs font-black text-accent'}
                    data-subscription-provenance
                  >
                    {subscriptionIsCached ? '上次快照' : '在线数据'}
                  </span>
                  <button
                    type="button"
                    onClick={() => loadSubscription(false)}
                    disabled={busy}
                    className="h-9 rounded-[8px] border border-border bg-surface-alt px-4 text-xs font-black text-text transition hover:border-accent/50 disabled:opacity-55"
                  >
                    刷新余额
                  </button>
                </div>
              </div>
              <div className="loom-account-subscription-body space-y-6 px-6 py-6">
                <div className="loom-account-metric-grid grid gap-4">
                  <MetricTile label="可用余额" value={displayValue(subscription?.balance, usageValue(account, ['quota', 'remainQuota', 'remainingQuota']))} />
                  <MetricTile label="累计消耗" value={displayValue(subscription?.usage?.usedQuota, usageValue(account, ['usedQuota', 'used', 'quotaUsed']))} />
                  <MetricTile label="请求次数" value={displayValue(subscription?.usage?.requestCount, usageValue(account, ['requestCount', 'requests']))} />
                  <MetricTile label="我的邀请码" value={displayValue(subscription?.inviteCode || subscription?.invitationCode || subscription?.referralCode, usageValue(account, ['inviteCode', 'invitationCode', 'referralCode'], '服务暂未返回'))} />
                  <MetricTile label="当前套餐" value={planDisplayName(subscription?.plan || account?.plan)} />
                </div>

                <div
                  data-native-payment-catalog
                  className="space-y-5 border-t border-border/70 pt-5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-4">
                    <div>
                      <div className="text-sm font-black text-text">矩阵套餐与购买</div>
                      <div className="mt-1 text-xs leading-5 text-text-muted">
                        手机矩阵、获客、飞书流转、云模板和 Skill 共用同一份矩阵授权。
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void loadPaymentPlans(false)}
                        disabled={paymentCatalogLoading || !accountWritable}
                        className="h-9 rounded-[8px] border border-border bg-surface-alt px-3 text-xs font-black text-text transition hover:border-accent/50 disabled:opacity-55"
                      >
                        {paymentCatalogLoading ? '加载中...' : '刷新套餐'}
                      </button>
                      <button
                        type="button"
                        onClick={handleOpenSubscription}
                        disabled={!subscriptionUrl}
                        className="h-9 rounded-[8px] border border-border bg-surface-alt px-3 text-xs font-black text-text transition hover:border-accent/50 disabled:opacity-55"
                      >
                        打开账户中心
                      </button>
                    </div>
                  </div>

                  {paymentCatalog?.payment.configured && paymentCatalog.plans.length ? (
                    <>
                      <div data-payment-channel className="flex flex-wrap items-center gap-2">
                        <span className="mr-1 text-xs font-bold text-text-subtle">支付方式</span>
                        {paymentCatalog.payment.channels?.includes('alipay') ? (
                          <button
                            type="button"
                            onClick={() => setPaymentChannel('alipay')}
                            className={[
                              'h-9 rounded-[8px] border px-4 text-xs font-black transition',
                              paymentChannel === 'alipay'
                                ? 'border-accent bg-accent/10 text-accent'
                                : 'border-border bg-surface-alt text-text-muted',
                            ].join(' ')}
                          >
                            支付宝
                          </button>
                        ) : null}
                        {paymentCatalog.payment.channels?.includes('wxpay') ? (
                          <button
                            type="button"
                            onClick={() => setPaymentChannel('wxpay')}
                            className={[
                              'h-9 rounded-[8px] border px-4 text-xs font-black transition',
                              paymentChannel === 'wxpay'
                                ? 'border-accent bg-accent/10 text-accent'
                                : 'border-border bg-surface-alt text-text-muted',
                            ].join(' ')}
                          >
                            微信支付
                          </button>
                        ) : null}
                      </div>

                      <div className="grid gap-3 lg:grid-cols-2">
                        {paymentCatalog.plans.map((plan) => (
                          <article
                            key={plan.planKey}
                            className="rounded-[10px] border border-border bg-surface-alt/40 p-4"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <div className="text-base font-black text-text">{plan.displayName}</div>
                                <div className="mt-1 text-xs leading-5 text-text-muted">
                                  {plan.description || `${plan.durationDays} 天矩阵授权`}
                                </div>
                              </div>
                              <div className="shrink-0 text-right">
                                <div className="text-xl font-black text-accent">¥{plan.amount}</div>
                                <div className="text-[11px] font-bold text-text-subtle">{plan.currency}</div>
                              </div>
                            </div>
                            {plan.benefits?.length ? (
                              <ul className="mt-3 space-y-1 text-xs leading-5 text-text-muted">
                                {plan.benefits.map((benefit) => (
                                  <li key={benefit}>· {benefit}</li>
                                ))}
                              </ul>
                            ) : null}
                            <button
                              type="button"
                              onClick={() => void startPayment(plan.planKey)}
                              disabled={paymentBusy || !accountWritable}
                              className="mt-4 h-10 w-full rounded-[8px] bg-accent text-sm font-black text-accent-ink transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-55"
                            >
                              {paymentBusy ? '正在创建订单...' : `${paymentChannel === 'wxpay' ? '微信' : '支付宝'}扫码购买`}
                            </button>
                          </article>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="rounded-[8px] border border-border bg-surface-alt/35 px-4 py-3 text-xs leading-5 text-text-muted">
                      {paymentCatalogLoading
                        ? '正在从服务端加载可购买套餐...'
                        : '在线扫码套餐尚未开放；仍可通过账户中心查看其他模型服务套餐。'}
                    </div>
                  )}

                  {paymentOrder ? (
                    <div className="grid gap-5 rounded-[12px] border border-accent/35 bg-accent/5 p-5 md:grid-cols-[180px_minmax(0,1fr)]">
                      <div
                        data-payment-qr
                        className="flex min-h-[180px] items-center justify-center rounded-[8px] border border-border bg-white p-3"
                      >
                        {paymentQrSrc ? (
                          <img src={paymentQrSrc} alt="麓鸣套餐支付二维码" className="h-[156px] w-[156px]" />
                        ) : (
                          <div className="px-3 text-center text-xs leading-5 text-slate-600">支付二维码暂不可用，请查询订单或打开直达支付。</div>
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="text-xs font-black text-accent">{paymentStatusText(paymentOrder.status)}</div>
                        <div className="mt-2 text-lg font-black text-text">
                          {paymentOrder.displayName || paymentOrder.planKey || '矩阵套餐'} · ¥{paymentOrder.amount || '--'}
                        </div>
                        <div className="mt-2 break-all text-xs leading-5 text-text-muted">订单号：{paymentOrder.orderId}</div>
                        <div className="mt-1 text-xs leading-5 text-text-muted">有效期：{formatTime(paymentOrder.expiresAt, '以支付页面为准')}</div>
                        <p className="mt-3 text-xs leading-5 text-text-muted">
                          开通只以服务端验签通知或服务端向支付平台主动查单并严格核对后的结果为准；返回页不会直接发放权益。
                        </p>
                        <div className="mt-4 flex flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => void verifyPaymentOrder(paymentOrder.orderId, false, true)}
                            disabled={paymentBusy}
                            className="h-9 rounded-[8px] bg-accent px-4 text-xs font-black text-accent-ink disabled:opacity-55"
                          >
                            {paymentBusy ? '查询中...' : '我已付款，查询状态'}
                          </button>
                          {paymentOrder.payUrl ? (
                            <button
                              type="button"
                              onClick={() => void openExternalUrl(paymentOrder.payUrl || '')}
                              className="h-9 rounded-[8px] border border-border bg-surface px-4 text-xs font-black text-text"
                            >
                              打开直达支付
                            </button>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  ) : null}

                  <div className="max-w-xl">
                    <InfoPanel label="套餐到期时间" value={formatTime(subscription?.expiresAt, '服务暂未返回')} />
                  </div>
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
      className="relative h-full overflow-y-auto overflow-x-hidden bg-app-bg text-text"
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
            <InfoRow label="订阅" value={planDisplayName(subscription?.plan || account?.plan)} />
            <InfoRow label="最近同步" value={formatTime(account?.lastOnlineAt)} />
          </aside>
        </div>
      </div>

      <div className="absolute inset-0 bg-overlay backdrop-blur-[2px]" />

      <div className="relative z-10 flex min-h-full items-start justify-center px-6 py-8 lg:items-center">
        <section className="w-full max-w-[440px] rounded-[8px] border border-border-strong bg-surface-deeper p-8 text-white shadow-elevation-high">
          <div className="mb-7 flex items-start justify-between gap-4">
            <div className="flex min-w-0 gap-4">
              <LoomLogoMark className="h-11 w-11 rounded-[8px] border border-white/15 bg-surface-deep" />
              <div className="min-w-0">
                <h1 className="text-[24px] font-black leading-tight">{APP_DISPLAY_NAME}</h1>
                <p className="mt-2 text-sm leading-6 text-white/65">
                  登录后同步模型、余额与智能体配置。
                </p>
                <button
                  type="button"
                  onClick={handleOpenRegistration}
                  className="mt-3 inline-flex rounded-full border border-info bg-info-soft px-3 py-1 text-xs font-black text-info-ink transition hover:bg-info"
                >
                  新用户请前往网页注册
                </button>
              </div>
            </div>
            <button
              type="button"
              className="shrink-0 text-2xl leading-none text-white/55 transition hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)]"
              onClick={() => setCurrentPage('dashboard')}
              aria-label="关闭登录页"
            >
              ×
            </button>
          </div>

          <div className="space-y-4">
              <div className="grid grid-cols-2 gap-2 rounded-[8px] border border-white/15 bg-surface-deep p-1">
                <ModeButton
                  active={authMode === 'email'}
                  onClick={() => setAuthMode('email')}
                  disabled={!authCapabilities.inlineEmailCode}
                  title={authCapabilities.emailReason}
                >验证码登录</ModeButton>
                <ModeButton active={authMode === 'password'} onClick={() => setAuthMode('password')}>密码登录</ModeButton>
              </div>

              {authMode !== 'password' && (!authCapabilities.inlineEmailCode || authCapabilities.webRegistrationRequired) ? (
                <div className="rounded-[8px] border border-info bg-info-soft px-3 py-3 text-xs leading-5 text-info-ink" role="status">
                  <div>{authCapabilities.emailReason}</div>
                  {authCapabilities.webRegistrationRequired ? (
                    <button
                      type="button"
                      onClick={handleOpenRegistration}
                      className="mt-2 font-black text-info-ink underline decoration-info underline-offset-4"
                    >
                      网页注册
                    </button>
                  ) : null}
                </div>
              ) : null}

              {authMode === 'email' ? (
                <>
                  <label className="block">
                    <span className="mb-2 block text-xs font-bold text-white/65">邮箱</span>
                    <input
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      className="h-11 w-full rounded-[8px] border border-white/15 bg-surface-deep px-3 text-sm text-white outline-none transition placeholder:text-white/35 focus:border-info focus:ring-2 focus:ring-[var(--color-focus-soft)]"
                      placeholder="请输入模型账号邮箱"
                      autoComplete="email"
                    />
                  </label>
                  <div className="grid grid-cols-[minmax(0,1fr)_112px] gap-2">
                    <label className="block min-w-0">
                      <span className="mb-2 block text-xs font-bold text-white/65">邮箱验证码</span>
                      <input
                        value={emailCode}
                        onChange={(event) => setEmailCode(event.target.value)}
                        className="h-11 w-full rounded-[8px] border border-white/15 bg-surface-deep px-3 text-sm text-white outline-none transition placeholder:text-white/35 focus:border-info focus:ring-2 focus:ring-[var(--color-focus-soft)]"
                        placeholder="6 位验证码"
                        autoComplete="one-time-code"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={sendEmailCode}
                      disabled={busy}
                      className="mt-[22px] h-11 rounded-[8px] border border-white/15 bg-surface-deep text-sm font-black text-white/80 transition hover:border-info disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled"
                    >
                      发送验证码
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={handleEmailCodeLogin}
                    disabled={busy}
                    className="h-11 w-full rounded-[8px] bg-accent text-sm font-black text-accent-ink shadow-elevation-medium transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled"
                  >
                    {busy ? '验证中...' : '验证并登录'}
                  </button>
                  <button
                    type="button"
                    onClick={handleOpenRegistration}
                    className="w-full text-center text-sm font-bold text-white/65 transition hover:text-white"
                  >
                    还没有账户？网页注册
                  </button>
                </>
              ) : (
                <>
                  <label className="block">
                    <span className="mb-2 block text-xs font-bold text-white/65">用户名或邮箱</span>
                    <input
                      value={loginName}
                      onChange={(event) => setLoginName(event.target.value)}
                      className="h-11 w-full rounded-[8px] border border-white/15 bg-surface-deep px-3 text-sm text-white outline-none transition placeholder:text-white/35 focus:border-info focus:ring-2 focus:ring-[var(--color-focus-soft)]"
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
                    className="h-11 w-full rounded-[8px] bg-accent text-sm font-black text-accent-ink shadow-elevation-medium transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled"
                  >
                    {busy ? '登录中...' : '登录'}
                  </button>
                  <button
                    type="button"
                    onClick={handleOpenRegistration}
                    className="w-full text-center text-sm font-bold text-white/65 transition hover:text-white"
                  >
                    还没有账户？网页注册
                  </button>
                </>
              )}

              <button
                type="button"
                onClick={continueAsGuest}
                className="mt-5 w-full rounded-[8px] border border-white/15 bg-surface-deep px-4 py-3 text-sm font-black text-white transition hover:border-info hover:bg-hover"
              >
                暂不登录，继续以访客身份浏览
              </button>
              <button
                type="button"
                onClick={handleOpenSubscription}
                className="w-full text-center text-sm font-bold text-white/65 transition hover:text-white"
              >
                打开订阅页
              </button>

          </div>

          {statusText ? (
            <div className="mt-5 rounded-[8px] border border-white/15 bg-surface-deep px-3 py-2 text-sm leading-6 text-white/75" role="status" aria-live="polite">
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
      active ? 'bg-selected text-selected-ink' : 'text-white/65 hover:bg-hover hover:text-white',
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
    <span className="mb-2 block text-xs font-bold text-white/65">密码</span>
    <input
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-11 w-full rounded-[8px] border border-white/15 bg-surface-deep px-3 text-sm text-white outline-none transition placeholder:text-white/35 focus:border-info focus:ring-2 focus:ring-[var(--color-focus-soft)]"
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

const MetricTile: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="min-w-0 rounded-[8px] border border-border bg-surface-alt/40 p-4">
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
