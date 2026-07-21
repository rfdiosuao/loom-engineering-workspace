import React, { useEffect, useState } from 'react';
import { open } from '@tauri-apps/plugin-shell';
import { Button, Input, showToast } from '../common';
import { licenseApi } from '../../services/api';
import { useAppStore } from '../../stores/appStore';
import { useLogStore } from '../../stores/logStore';

const ACTIVATION_CODE_LABEL_KEY = 'openclaw_activation_code_label';

function activationCodeLabelFromCode(value: string): string {
  const last8 = value.replace(/[^a-z0-9]/gi, '').toUpperCase().slice(-8);
  return last8.length === 8 ? `${last8.slice(0, 4)}-${last8.slice(4)}` : last8;
}

function activationCodeLabelFromLicense(license: unknown): string {
  const data = license && typeof license === 'object' ? license as Record<string, unknown> : {};
  const explicit = String(data.activationCodeLabel || data.codeLabel || '').trim();
  if (explicit) return explicit;
  const last8 = String(data.activationCodeLast8 || '').trim();
  return last8 ? activationCodeLabelFromCode(last8) : '';
}

export const LicensePage: React.FC = () => {
  const [code, setCode] = useState('');
  const [activating, setActivating] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [cardSite, setCardSite] = useState<{ enabled?: boolean; label?: string; url?: string } | null>(null);
  const { isAuthorized, licenseInfo, setAuthorized, setLicenseInfo, setCurrentPage } = useAppStore();
  const appendLog = useLogStore((state) => state.append);

  useEffect(() => {
    let mounted = true;
    licenseApi.clientConfig()
      .then((config) => {
        if (!mounted) return;
        const site = config.cardSite;
        if (site?.enabled && site.url) setCardSite(site);
        else setCardSite(null);
      })
      .catch(() => {
        if (mounted) setCardSite(null);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleActivate = async () => {
    if (!code.trim()) {
      showToast('请输入授权码', 'error');
      return;
    }
    setActivating(true);
    setStatusText('正在连接授权服务器...');
    try {
      const resp = await licenseApi.activate(code);
      const license = resp.license;
      if (!license || typeof license !== 'object') {
        setStatusText('激活失败：服务器返回了无效许可证');
        showToast('激活失败', 'error');
        return;
      }
      setLicenseInfo(license as any);
      setAuthorized(true);
      const codeLabel = activationCodeLabelFromLicense(license) || activationCodeLabelFromCode(code);
      if (codeLabel) {
        try { localStorage.setItem(ACTIVATION_CODE_LABEL_KEY, codeLabel); } catch { /* ignore */ }
      }
      if (typeof (window as any).__reloadTheme === 'function') {
        await (window as any).__reloadTheme();
      }
      setStatusText(`激活成功：${(license as any).licensee || 'OpenClaw User'}`);
      appendLog(`[授权] 激活成功：${(license as any).licensee || 'OpenClaw User'}\n`);
      showToast('激活成功，主题已更新', 'success');
      setTimeout(() => setCurrentPage('terminal'), 1200);
    } catch (error: any) {
      setStatusText(error?.error || '激活失败');
      showToast('激活失败', 'error');
    } finally {
      setActivating(false);
    }
  };

  const handleRefresh = async () => {
    try {
      const resp = await licenseApi.current();
      if (resp.license) {
        setLicenseInfo(resp.license as any);
        setAuthorized(true);
        showToast('授权状态已刷新', 'success');
      } else {
        setLicenseInfo(null);
        setAuthorized(false);
        showToast('当前未授权', 'info');
      }
    } catch {
      showToast('刷新授权状态失败', 'error');
    }
  };

  const handleOpenCardSite = async () => {
    const url = String(cardSite?.url || '').trim();
    if (!url) {
      showToast('发卡网站暂未配置', 'info');
      return;
    }
    try {
      await open(url);
    } catch {
      showToast('打开购买页面失败，请检查发卡网站链接', 'error');
    }
  };

  const features = licenseInfo?.features?.join(' / ') || '';
  const gatewayBaseUrl = String((licenseInfo as any)?.gatewayBaseUrl || (licenseInfo as any)?.gatewayUrl || '').trim();
  const gatewayToken = String((licenseInfo as any)?.gatewayAccessToken || (licenseInfo as any)?.gatewayToken || '').trim();
  const memberMode = Boolean(gatewayBaseUrl && gatewayToken);
  const activationCodeLabel = activationCodeLabelFromLicense(licenseInfo) || (() => {
    try { return localStorage.getItem(ACTIVATION_CODE_LABEL_KEY) || ''; } catch { return ''; }
  })();

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-surface">
      <div className="shrink-0 border-b border-border bg-surface px-8 py-6">
        <h1 className="text-xl font-black text-text">授权管理</h1>
        <p className="mt-1 text-sm text-text-muted">输入授权码后解锁启动服务、AI 生图、AI 视频和广告视频工作台。</p>
      </div>

      <div className="flex-1 px-8 py-6">
        <div className="max-w-xl rounded-2xl border border-border bg-surface-alt/78 p-6 shadow-[0_20px_56px_rgba(0,0,0,0.18)]">
          <div className={`mb-4 text-sm font-bold ${isAuthorized ? 'text-status-success' : 'text-status-danger'}`}>
            {isAuthorized ? '已授权' : '未授权'}
          </div>

          {isAuthorized && licenseInfo && (
            <div className="mb-5 space-y-1 rounded-xl border border-border bg-surface/65 p-4 text-sm text-text-muted">
              {activationCodeLabel && <p>授权码后八位：<span className="font-mono text-text">{activationCodeLabel}</span></p>}
              <p>客户：{licenseInfo.licensee || '未命名'}</p>
              <p>版本：{licenseInfo.edition || 'pro'}</p>
              <p>到期：{licenseInfo.expires || '永久'}</p>
              <p>功能：{features || '标准功能'}</p>
              {memberMode && <p>会员网关：{gatewayBaseUrl}</p>}
              {memberMode && <p>会员模式：托管 / 月卡</p>}
            </div>
          )}

          <label className="mb-2 block text-sm font-medium text-text-muted">授权码</label>
          <Input
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="OC-PRO-XXXX-XXXX-XXXX-XXXX"
            className="border-2 border-border-strong py-3 px-4 font-mono text-base"
          />
          <p className="mb-4 mt-1 text-xs text-accent">格式示例：OC-PRO-XXXX-XXXX-XXXX-XXXX</p>

          <div className="mb-4 flex flex-wrap items-center gap-3">
            <Button onClick={handleActivate} variant="primary" disabled={activating}>
              {activating ? '激活中...' : isAuthorized ? '重新激活' : '在线激活'}
            </Button>
            <Button onClick={handleRefresh} variant="quiet">刷新状态</Button>
            <Button onClick={() => setCurrentPage('diagnostics')} variant="quiet">环境诊断</Button>
            {cardSite?.url && (
              <Button onClick={handleOpenCardSite} variant="quiet">
                {cardSite.label || '购买授权码'}
              </Button>
            )}
          </div>

          {statusText && (
            <p className={`text-sm ${
              statusText.includes('成功') ? 'text-status-success' :
              statusText.includes('连接') ? 'text-accent' :
              'text-status-danger'
            }`}>
              {statusText}
            </p>
          )}
        </div>

        <p className="mt-5 text-xs text-text-muted">安装 ID 会在激活时自动生成。OpenClaw 版仍沿用现有授权流程。</p>
      </div>
    </div>
  );
};
