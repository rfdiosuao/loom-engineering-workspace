import 'tsx/esm';

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { CapabilityCenterPage } from './capabilities/CapabilityCenterPage.tsx';
import { IMAGE_RATIO_PRESETS, validateReferenceFile } from './creative/mediaPresets.ts';

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
