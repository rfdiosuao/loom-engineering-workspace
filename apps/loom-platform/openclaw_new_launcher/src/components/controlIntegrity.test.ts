import 'tsx/esm';

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { CapabilityCenterPage } from './capabilities/CapabilityCenterPage.tsx';
import { IMAGE_RATIO_PRESETS, validateReferenceFile } from './creative/mediaPresets.ts';
import { DARK_THEME, LIGHT_THEME } from '../theme/default.ts';
import {
  configurationCheckSucceeded,
  resolveDashboardJourneyState,
} from './dashboard/dashboardJourneyState.ts';

function readSource(relativePath: string): string {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8');
}

function sourceBlock(source: string, start: string, end: string): string {
  const startIndex = source.indexOf(start);
  const endIndex = source.indexOf(end, startIndex + start.length);
  assert.notEqual(startIndex, -1, `missing source block start: ${start}`);
  assert.notEqual(endIndex, -1, `missing source block end: ${end}`);
  return source.slice(startIndex, endIndex);
}

function recursiveFiles(directory: URL): URL[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const child = new URL(entry.name, directory.href.endsWith('/') ? directory : new URL(`${directory.href}/`));
    return entry.isDirectory() ? recursiveFiles(child) : [child];
  });
}

test('semantic theme contract covers light and dark operational states', () => {
  const requiredColors = [
    'info', 'info_soft', 'info_border', 'info_ink',
    'success', 'success_soft', 'success_border', 'success_ink',
    'warning', 'warning_soft', 'warning_border', 'warning_ink',
    'danger', 'danger_soft', 'danger_border', 'danger_ink',
    'focus', 'focus_soft', 'selected', 'selected_hover', 'selected_ink',
    'disabled', 'disabled_text', 'overlay',
  ] as const;
  const defaultThemeSource = readSource('../theme/default.ts');

  for (const key of requiredColors) {
    assert.ok(LIGHT_THEME.colors[key], `light theme missing ${key}`);
    assert.ok(DARK_THEME.colors[key], `dark theme missing ${key}`);
    assert.match(defaultThemeSource, new RegExp(`${key}:\\s*'--color-`), `CSS variable map missing ${key}`);
  }
  for (const duration of ['150ms', '200ms', '300ms']) {
    assert.match(defaultThemeSource, new RegExp(`['"]${duration}['"]`));
  }
  assert.deepEqual(Object.keys(LIGHT_THEME.colors).sort(), Object.keys(DARK_THEME.colors).sort());
  assert.doesNotMatch(readSource('../styles/theme.css'), /#[0-9a-f]{3,8}\b/i);
});

test('React presentation modules do not introduce unreviewed colors or arbitrary shadows', () => {
  const componentsRoot = new URL('./', import.meta.url);
  const legacyAllowlist = new Set([
    'agent/AgentComposer.tsx|shadow|shadow-[0_10px_30px_rgba(5,35,29,0.08)]',
    'agent/AgentDebugger.tsx|shadow|shadow-[-18px_0_48px_rgba(5,25,22,0.18)]',
    'agent/AgentModelMenu.tsx|shadow|shadow-[0_18px_50px_rgba(5,25,22,0.22)]',
    'agent/AgentScopeMenu.tsx|shadow|shadow-[0_18px_50px_rgba(5,25,22,0.22)]',
    'agents/AgentInstallerPage.tsx|shadow|shadow-[0_12px_30px_rgba(8,35,48,0.05)]',
    'agents/AgentLogo.tsx|shadow|shadow-[0_14px_30px_rgba(0,0,0,0.14)]',
    'brand/LoomBrand.tsx|shadow|shadow-[0_8px_22px_rgba(3,30,38,0.22)]',
    'dashboard/DashboardPage.tsx|shadow|shadow-[0_10px_28px_rgba(8,60,49,0.08)]',
    'sidebar/Sidebar.tsx|color|rgba(55,213,163,0.08)',
    'sidebar/Sidebar.tsx|shadow|shadow-[inset_0_0_0_1px_rgba(55,213,163,0.16)]',
    'sidebar/Sidebar.tsx|shadow|shadow-[0_14px_30px_rgba(0,0,0,0.34),0_0_0_1px_rgba(223,250,255,0.04)]',
    'terminal/TerminalPage.tsx|shadow|shadow-[0_24px_70px_rgba(0,0,0,0.32)]',
  ]);
  const violations = recursiveFiles(componentsRoot)
    .filter((file) => file.pathname.endsWith('.tsx'))
    .flatMap((file) => {
      const source = readFileSync(file, 'utf8');
      const relative = decodeURIComponent(file.pathname.split('/components/')[1] || file.pathname);
      return source.split(/\r?\n/).flatMap((line, index) => {
        const arbitraryShadows = [...line.matchAll(/\bshadow-\[[^\]]+\]/gi)];
        const shadowRanges = arbitraryShadows.map((match) => [
          match.index ?? 0,
          (match.index ?? 0) + match[0].length,
        ] as const);
        const shadowViolations = arbitraryShadows.map(
          (match) => `${relative}|shadow|${match[0]}`,
        );
        const matches = [...line.matchAll(/#[0-9a-f]{3,8}\b|rgba?\([^)]*\)/gi)]
          .filter((match) => !shadowRanges.some(
            ([start, end]) => (match.index ?? 0) >= start && (match.index ?? 0) < end,
          ));
        const fixedLogoPathColor = relative === 'brand/LoomBrand.tsx' && /<(path|rect|circle)\b/.test(line);
        const colorViolations = fixedLogoPathColor
          ? []
          : matches.map((match) => `${relative}|color|${match[0]}`);
        return [...shadowViolations, ...colorViolations]
          .filter((violation) => !legacyAllowlist.has(violation))
          .map((violation) => `${violation}|line:${index + 1}`);
      });
    });

  assert.deepEqual(violations, []);
});

test('business components use canonical semantic utility names', () => {
  const componentsRoot = new URL('./', import.meta.url);
  const violations = recursiveFiles(componentsRoot)
    .filter((file) => file.pathname.endsWith('.tsx'))
    .flatMap((file) => {
      const source = readFileSync(file, 'utf8');
      const relative = decodeURIComponent(file.pathname.split('/components/')[1] || file.pathname);
      return [
        ...[...source.matchAll(/\b(?:border|bg|text)-status-info(?:\/\d+)?\b/g)].map((match) => `${relative}:${match[0]}`),
        ...[...source.matchAll(/\btext-disabled-text\b/g)].map((match) => `${relative}:${match[0]}`),
      ];
    });

  assert.deepEqual(violations, []);
});

test('Matrix phone selection and focus keep a visible semantic ring width', () => {
  const source = readSource('./matrix/PhoneTile.tsx');

  assert.match(source, /\(focused \|\| selected\) \? 'ring-2 ring-focus'/);
  assert.doesNotMatch(source, /\? 'ring-focus'/);
});

test('major workbenches share the canonical canvas and surface color hierarchy', () => {
  const styles = readSource('../styles/index.css');
  const matrixTheme = sourceBlock(styles, '.loom-matrix-shell {', '.matrix-live-feed-row {');
  const acquisition = readSource('./acquisition/AcquisitionWorkbenchPage.tsx');
  const agent = readSource('./agent/AgentWorkbenchPage.tsx');
  const creative = readSource('./creative/CreativeMediaPage.tsx');
  const diagnostics = readSource('./diagnostics/DiagnosticsPage.tsx');
  const models = readSource('./models/ModelsPage.tsx');

  assert.match(matrixTheme, /\.loom-matrix-shell\s*\{\s*background:\s*var\(--color-app-bg\)/);
  assert.match(matrixTheme, /\.loom-matrix-shell header\s*\{\s*background:\s*var\(--color-surface\)/);
  assert.match(matrixTheme, /background:\s*var\(--color-surface-alt\)/);
  assert.doesNotMatch(matrixTheme, /background:\s*var\(--color-surface-deep(?:er)?\)/);

  assert.match(acquisition, /data-acquisition-hero/);
  assert.match(acquisition, /bg-surface-alt/);
  assert.match(acquisition, /: 'border-border bg-surface text-accent'/);
  assert.match(acquisition, /type StatusTone = 'neutral' \| 'info' \| 'success' \| 'warning' \| 'danger'/);
  assert.match(acquisition, /if \(counts\.failed > 0\) return 'danger'/);
  assert.match(acquisition, /status === '执行中'[\s\S]{0,80}\? 'text-info'/);
  assert.match(acquisition, /<StatusPill tone=/);
  assert.doesNotMatch(acquisition, /border-info bg-info-soft text-info-ink/);
  assert.doesNotMatch(acquisition, /data-acquisition-overview[\s\S]{0,500}bg-surface-deep/);
  assert.doesNotMatch(acquisition, /data-acquisition-overview[\s\S]{0,900}text-white/);
  assert.match(agent, /bg-app-bg/);
  assert.match(creative, /data-creative-media-page[^>]+bg-app-bg/);
  assert.match(diagnostics, /data-diagnostics-page[^>]+bg-app-bg/);
  assert.doesNotMatch(diagnostics, /bg-black/);
  assert.doesNotMatch(diagnostics, /rgba\(79,112,95,0\.45\)/);
  assert.match(models, /data-models-page[^>]+bg-app-bg/);
  assert.doesNotMatch(models, /rounded-\[20px\]/);
  assert.doesNotMatch(creative, /rounded-\[10px\]/);
});

test('toast notifications expose one live region per message', () => {
  const common = readSource('./common/index.tsx');
  const container = sourceBlock(common, 'data-toast-container', '{toasts.map');

  assert.doesNotMatch(container, /role=/);
  assert.doesNotMatch(container, /aria-live=/);
  assert.match(common, /role=\{toast\.type === 'error' \? 'alert' : 'status'\}/);
  assert.match(common, /aria-live=\{toast\.type === 'error' \? 'assertive' : 'polite'\}/);
});

test('unavailable capabilities render as non-interactive status rows', () => {
  const markup = renderToStaticMarkup(React.createElement(CapabilityCenterPage));

  assert.equal((markup.match(/data-capability-status-row/g) || []).length, 4);
  assert.doesNotMatch(markup, /<button\b/);
  assert.equal((markup.match(/role="status"/g) || []).length, 4);
});

test('logged-out subscription action reaches the external opener and reports failures', () => {
  const source = readSource('./license/LicensePage.tsx');
  const handler = sourceBlock(source, 'const handleOpenSubscription', 'const handleOpenRegistration');

  assert.doesNotMatch(handler, /if\s*\(!loggedIn\)/);
  assert.match(handler, /await openExternalUrl\(subscriptionUrl\)/);
  assert.match(handler, /catch\s*\(error\)/);
  assert.match(handler, /showToast\([^\n]+, 'success'\)/);
  assert.match(handler, /showToast\([^\n]+, 'error'\)/);
});

test('web registration opener reports success and failure instead of rejecting silently', () => {
  const source = readSource('./license/LicensePage.tsx');
  const handler = sourceBlock(source, 'const handleOpenRegistration', 'const continueAsGuest');

  assert.match(handler, /await openExternalUrl\(url\)/);
  assert.match(handler, /catch\s*\(error\)/);
  assert.match(handler, /showToast\([^\n]+, 'success'\)/);
  assert.match(handler, /showToast\([^\n]+, 'error'\)/);
});

test('Models page does not render an unreachable re-login notice branch', () => {
  const source = readSource('./models/ModelsPage.tsx');

  assert.doesNotMatch(source, /accountNotice/);
  assert.match(source, /aria-label=\{label\}/);
});

test('Models shutdown confirms rollback and describes the resulting configuration truthfully', () => {
  const source = readSource('./models/ModelsPage.tsx');
  const handler = sourceBlock(source, 'const disableModelSource', 'const loggedIn');

  assert.match(handler, /await showConfirm/);
  assert.ok(handler.indexOf('await showConfirm') < handler.indexOf('await loomClient.wire.rollback'));
  assert.match(handler, /tone: 'danger'/);
  assert.doesNotMatch(source, /不会改动本地 Provider/);
  assert.match(source, /回滚到上一份可用配置/);
});

test('Creative copy-path actions only render when a local path exists', () => {
  const source = readSource('./creative/CreativeMediaPage.tsx');

  assert.match(source, /preview\.file\?\.path \? \(/);
  assert.match(source, /videoResult\?\.path \? \(/);
  assert.equal((source.match(/未返回本地路径/g) || []).length, 2);
});

test('Creative media exposes only the six supported image ratios', () => {
  assert.deepEqual(
    IMAGE_RATIO_PRESETS.map((preset) => [preset.ratio, preset.size]),
    [
      ['1:1', '1024x1024'],
      ['3:4', '1152x1536'],
      ['4:3', '1536x1152'],
      ['9:16', '1152x2048'],
      ['16:9', '2048x1152'],
      ['5:2', '2560x1024'],
    ],
  );
});

test('Creative reference image validation rejects unsupported and oversized files', () => {
  assert.equal(validateReferenceFile({ type: 'image/png', size: 1024 } as File), '');
  assert.equal(validateReferenceFile({ type: 'image/gif', size: 1024 } as File), '仅支持 PNG、JPG、WebP 图片');
  assert.equal(validateReferenceFile({ type: 'image/jpeg', size: 21 * 1024 * 1024 } as File), '参考图不能超过 20 MB');
});

test('Agent detection failures stop preparation before installation', () => {
  const source = readSource('./agents/AgentInstallerPage.tsx');
  const preparation = sourceBlock(source, 'const prepareComponent', 'const install = async');
  const detection = sourceBlock(preparation, 'let next: ComponentSnapshot | null = null;', 'const current = next.components');
  const catchBlock = detection.match(/catch\s*\(error: any\)\s*\{([\s\S]*?)\n\s*\}/)?.[1] || '';

  assert.match(catchBlock, /throw new Error/);
  assert.match(catchBlock, /检测失败，已停止安装/);
  assert.doesNotMatch(catchBlock, /components\.install/);
});

test('named form controls expose accessible labels', () => {
  const agentSource = readSource('./agents/AgentInstallerPage.tsx');
  const acquisitionSource = readSource('./acquisition/AcquisitionWorkbenchPage.tsx');
  const phoneSource = readSource('./phone/PhoneDemoPage.tsx');
  const settingsSource = readSource('./settings/SettingsPage.tsx');

  assert.ok(agentSource.includes('aria-label={`${component.name} 托管模型`}'));
  assert.ok(acquisitionSource.includes('aria-label="飞书多维表格链接"'));
  assert.ok(acquisitionSource.includes('aria-label="AI 接入提示词预览"'));
  assert.ok(phoneSource.includes('aria-label="手机任务描述"'));
  assert.ok(phoneSource.includes('aria-label="选择 USB 手机"'));
  assert.ok(settingsSource.includes('aria-label={copy.appearance.languageTitle}'));
});

test('account login exposes account entitlement redemption without the legacy activation block', () => {
  const licenseSource = readSource('./license/LicensePage.tsx');

  assert.doesNotMatch(licenseSource, /handleLegacyActivate/);
  assert.doesNotMatch(licenseSource, /licenseApi\.activate/);
  assert.doesNotMatch(licenseSource, /aria-label="旧授权码"/);
  assert.match(licenseSource, /aria-label="商业矩阵授权码"/);
});

test('account identity transitions clear all in-memory Agent projections and attachment drafts', () => {
  const licenseSource = readSource('./license/LicensePage.tsx');
  const applyAccount = sourceBlock(
    licenseSource,
    'const applyAccount',
    'const refresh',
  );

  assert.match(licenseSource, /import \{ useAgentStore \} from '\.\.\/\.\.\/stores\/agentStore'/);
  assert.match(applyAccount, /previousIdentity !== nextIdentity/);
  assert.match(applyAccount, /useAgentStore\.getState\(\)\.reset\(\)/);
  assert.ok(
    applyAccount.indexOf('useAgentStore.getState().reset()')
      < applyAccount.indexOf('cachedAccount.current = next'),
  );
});

test('phone matrix gate sends authorization binding through the logged-in account page', () => {
  const gateSource = readSource('./license/PhoneMatrixAccessGate.tsx');
  const paywallSource = readSource('./license/LicensePaywall.tsx');

  assert.match(gateSource, /accountBindingOnly/);
  assert.match(paywallSource, /accountBindingOnly/);
  assert.match(paywallSource, /setCurrentPage\('license'\)/);
  assert.match(paywallSource, /登录模型账号并绑定授权码/);
  assert.match(paywallSource, /未激活账号可用 0 台手机/);
  assert.match(paywallSource, /当前账号下已连接的全部手机均可使用/);
  assert.doesNotMatch(paywallSource, /正在核验这台电脑的矩阵使用资格/);
});

test('shared modal, confirmation, and toast controls expose accessibility contracts', () => {
  const source = readSource('./common/index.tsx');
  const modal = sourceBlock(source, 'export const Modal', 'type ConfirmTone');
  const confirmation = sourceBlock(source, 'export const ConfirmDialogHost', 'let toastId = 0;');
  const toast = sourceBlock(source, 'export const ToastContainer', 'export function showToast');

  assert.doesNotMatch(modal, /<div[^>]*onClick=\{onClose\}/);
  assert.match(modal, /<button[\s\S]*?data-modal-backdrop[\s\S]*?aria-label=/);
  assert.match(modal, /aria-label=\{title \? `关闭\$\{title\}` : '关闭对话框'\}/);
  assert.match(modal, /onKeyDown=\{handleModalKeyDown\}/);
  assert.match(modal, /ref=\{dialogPanelRef\}/);
  assert.match(modal, /previouslyFocusedElementRef/);
  assert.match(modal, /focusableElements/);
  assert.match(modal, /previouslyFocused\.focus\(\)/);
  assert.match(confirmation, /onKeyDown=\{handleConfirmKeyDown\}/);
  assert.match(confirmation, /tabIndex=\{-1\}/);
  assert.match(confirmation, /ref=\{dialogPanelRef\}/);
  assert.match(confirmation, /data-confirm-cancel/);
  assert.match(confirmation, /previouslyFocusedElementRef/);
  assert.match(toast, /role=\{toast\.type === 'error' \? 'alert' : 'status'\}/);
  assert.match(toast, /aria-live=\{toast\.type === 'error' \? 'assertive' : 'polite'\}/);
  assert.match(toast, /aria-atomic="true"/);
  assert.ok(toast.includes('aria-label={`关闭通知：${toast.message}`}'));
});

test('phone and acquisition status mappings use danger for failures and info for active work', () => {
  const phoneSource = readSource('./phone/PhoneDemoPage.tsx');
  const acquisitionSource = readSource('./acquisition/AcquisitionWorkbenchPage.tsx');
  const phoneTone = sourceBlock(phoneSource, 'function jobTone', 'function parseJsonMaybe');

  assert.match(phoneTone, /\['failed', 'error'\][\s\S]{0,140}status-danger/);
  assert.match(phoneTone, /\['queued', 'running'\][\s\S]{0,140}border-info[\s\S]{0,100}bg-info-soft[\s\S]{0,100}text-info-ink/);
  assert.match(acquisitionSource, /if \(counts\.failed > 0\) return 'danger'/);
  assert.match(acquisitionSource, /tone=\{matrixCounts\.failed > 0 \|\| matrixError \? 'danger' : 'default'\}/);
});

test('dashboard journey advances only from current Bridge responses', () => {
  const source = readSource('./dashboard/DashboardPage.tsx');

  assert.match(source, /data-dashboard-journey/);
  assert.match(source, /wireApi\.current\(\)/);
  assert.match(source, /wireApi\.verify\(\)/);
  assert.match(source, /loadCachedComponentSnapshot/);
  assert.match(source, /loadLastVerifiedJourney/);
  assert.match(source, /componentsProvenance === 'live'/);
  assert.match(source, /const liveComponents = componentsProvenance === 'live'/);
  assert.match(source, /历史记录不会解锁当前入口/);
  assert.match(source, /resolveDashboardJourneyState/);
  assert.doesNotMatch(source, /restoredVerificationReady|const journeyReady = verificationReady \|\|/);
  assert.match(source, /安装 Agent/);
  assert.match(source, /选择模型/);
  assert.match(source, /配置检查/);
  assert.match(source, /进入 Agent/);
});

test('dashboard history and refresh state never unlock the current journey', () => {
  const cached = resolveDashboardJourneyState({
    loading: false,
    componentsProvenance: 'cache',
    readyAgentIds: ['codex-desktop'],
    hasConfiguredTextModel: true,
    configurationCheckPassed: false,
  });
  assert.equal(cached.liveInstallReady, false);
  assert.equal(cached.canCheckNow, false);
  assert.equal(cached.journeyReady, false);

  const refreshing = resolveDashboardJourneyState({
    loading: true,
    componentsProvenance: 'live',
    readyAgentIds: ['codex-desktop'],
    hasConfiguredTextModel: true,
    configurationCheckPassed: true,
  });
  assert.equal(refreshing.canCheckNow, false);
  assert.equal(refreshing.journeyReady, false);
});

test('dashboard configuration check ignores unrelated modules but requires a usable current Agent', () => {
  const result = {
    targets: {
      token: { ok: true },
      codex: { ok: true },
      image: { ok: false },
      phone: { ok: false },
      video: { ok: false },
    },
  };
  assert.equal(configurationCheckSucceeded(result, ['codex-desktop']), true);
  assert.equal(configurationCheckSucceeded(result, ['claude-code']), false);
  assert.equal(configurationCheckSucceeded({ targets: { token: { ok: false }, codex: { ok: true } } }, ['codex-desktop']), false);

  const current = resolveDashboardJourneyState({
    loading: false,
    componentsProvenance: 'live',
    readyAgentIds: ['codex-desktop'],
    hasConfiguredTextModel: true,
    configurationCheckPassed: true,
  });
  assert.equal(current.canCheckNow, true);
  assert.equal(current.journeyReady, true);
  assert.equal(current.activeStep, 4);
});
