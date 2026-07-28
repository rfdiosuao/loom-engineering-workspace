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

test('React presentation modules do not introduce private business hex colors', () => {
  const componentsRoot = new URL('./', import.meta.url);
  const violations = recursiveFiles(componentsRoot)
    .filter((file) => file.pathname.endsWith('.tsx'))
    .filter((file) => {
      const relative = decodeURIComponent(file.pathname.split('/components/')[1] || '').replace(/\//g, '\\');
      return relative.replace(/\\/g, '/') !== 'phone/PhoneDemoPage.tsx';
    })
    .flatMap((file) => {
      const source = readFileSync(file, 'utf8');
      const relative = decodeURIComponent(file.pathname.split('/components/')[1] || file.pathname);
      return source.split(/\r?\n/).flatMap((line, index) => {
        const matches = [...line.matchAll(/#[0-9a-f]{3,8}\b/gi)];
        const fixedLogoPathColor = relative === 'brand/LoomBrand.tsx' && /<(path|rect|circle)\b/.test(line);
        return fixedLogoPathColor ? [] : matches.map((match) => `${relative}:${index + 1}:${match[0]}`);
      });
    });

  assert.deepEqual(violations, []);
});

test('business components use canonical semantic utility names', () => {
  const componentsRoot = new URL('./', import.meta.url);
  const violations = recursiveFiles(componentsRoot)
    .filter((file) => file.pathname.endsWith('.tsx'))
    .filter((file) => !file.pathname.endsWith('/phone/PhoneDemoPage.tsx'))
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
  assert.ok(settingsSource.includes('aria-label={copy.appearance.languageTitle}'));
});

test('account login no longer exposes the legacy license-code activation block', () => {
  const licenseSource = readSource('./license/LicensePage.tsx');

  assert.doesNotMatch(licenseSource, /handleLegacyActivate/);
  assert.doesNotMatch(licenseSource, /licenseApi\.activate/);
  assert.doesNotMatch(licenseSource, /aria-label="旧授权码"/);
});

test('shared modal, confirmation, and toast controls expose accessibility contracts', () => {
  const source = readSource('./common/index.tsx');
  const modal = sourceBlock(source, 'export const Modal', 'type ConfirmTone');
  const confirmation = sourceBlock(source, 'export const ConfirmDialogHost', 'let toastId = 0;');
  const toast = sourceBlock(source, 'export const ToastContainer', 'export function showToast');

  assert.doesNotMatch(modal, /<div[^>]*onClick=\{onClose\}/);
  assert.match(modal, /<button[\s\S]*?data-modal-backdrop[\s\S]*?aria-label=/);
  assert.match(modal, /aria-label=\{title \? `关闭\$\{title\}` : '关闭对话框'\}/);
  assert.match(confirmation, /onKeyDown=\{handleConfirmKeyDown\}/);
  assert.match(confirmation, /tabIndex=\{-1\}/);
  assert.match(confirmation, /ref=\{dialogPanelRef\}/);
  assert.match(confirmation, /data-confirm-cancel/);
  assert.match(confirmation, /previouslyFocusedElementRef/);
  assert.match(toast, /role="status"/);
  assert.match(toast, /aria-live="polite"/);
  assert.match(toast, /aria-atomic="true"/);
  assert.ok(toast.includes('aria-label={`关闭通知：${toast.message}`}'));
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
