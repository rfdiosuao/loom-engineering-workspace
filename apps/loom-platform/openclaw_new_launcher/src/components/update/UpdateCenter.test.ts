import 'tsx/esm';

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import * as updateCenter from './UpdateCenter.tsx';

test('reopening the update center preserves actionable in-flight state', () => {
  const shouldReuse = (updateCenter as unknown as {
    shouldReuseUpdateSession?: (phase: string) => boolean;
  }).shouldReuseUpdateSession;
  assert.equal(typeof shouldReuse, 'function');
  if (!shouldReuse) return;

  for (const phase of ['available', 'downloading', 'verifying', 'ready', 'restarting', 'success', 'cancelled']) {
    assert.equal(shouldReuse(phase), true, phase);
  }
  for (const phase of ['idle', 'checking', 'current', 'failed']) {
    assert.equal(shouldReuse(phase), false, phase);
  }
});

test('post-restart receipt polling stops when the backend reports no pending receipt', () => {
  const source = readFileSync(new URL('./UpdateCenter.tsx', import.meta.url), 'utf8');
  assert.match(source, /if \(!response\.pending\) return;/);
});

test('update verification copy describes the active brand release signature', () => {
  const source = readFileSync(new URL('./UpdateCenter.tsx', import.meta.url), 'utf8');
  assert.match(source, /APP_DISPLAY_NAME/);
  assert.match(source, /官方发布签名/);
  assert.doesNotMatch(source, /SHA256 与 Windows 发布者校验/);
});

test('signature failures expose the one-time official installer bridge', () => {
  const shouldOffer = (updateCenter as unknown as {
    shouldOfferManualUpdateBridge?: (errorCode: string) => boolean;
  }).shouldOfferManualUpdateBridge;
  const bridgeUrl = (updateCenter as unknown as {
    manualUpdateBridgeUrl?: (releaseUrl?: string) => string;
  }).manualUpdateBridgeUrl;

  assert.equal(typeof shouldOffer, 'function');
  assert.equal(typeof bridgeUrl, 'function');
  if (!shouldOffer || !bridgeUrl) return;

  assert.equal(shouldOffer('signature_invalid'), true);
  assert.equal(shouldOffer('network_interrupted'), false);
  assert.equal(
    bridgeUrl('https://github.com/rfdiosuao/loom-engineering-workspace/releases/tag/v2.3.22'),
    'https://github.com/rfdiosuao/loom-engineering-workspace/releases/tag/v2.3.22',
  );
  assert.equal(
    bridgeUrl('javascript:alert(1)'),
    'https://github.com/rfdiosuao/loom-engineering-workspace/releases/latest',
  );
});

test('handoff failures keep the verified installer available for manual recovery', () => {
  const source = readFileSync(new URL('./UpdateCenter.tsx', import.meta.url), 'utf8');
  assert.match(source, /setErrorCode\('update_handoff_failed'\)/);
  assert.match(source, /当前版本尚未关闭，已下载并验证的安装包仍然保留/);
  assert.match(source, /完全退出 \$\{APP_DISPLAY_NAME\} 后运行：\$\{installerPath\}/);
});

test('restart handoff reports a recoverable failure when the old app does not exit', () => {
  const restartWatchdogMs = (updateCenter as unknown as {
    RESTART_EXIT_WATCHDOG_MS?: number;
  }).RESTART_EXIT_WATCHDOG_MS;
  const source = readFileSync(new URL('./UpdateCenter.tsx', import.meta.url), 'utf8');

  assert.equal(restartWatchdogMs, 15_000);
  assert.match(source, /window\.setTimeout\(\(\) =>/);
  assert.match(source, /setErrorCode\('update_restart_timeout'\)/);
  assert.match(source, /旧版本未能自动退出/);
  assert.match(source, /已下载并验证的安装包仍然保留/);
});

test('restart watchdog leaves margin above native ready and forced-exit deadlines', () => {
  const restartWatchdogMs = (updateCenter as unknown as {
    RESTART_EXIT_WATCHDOG_MS?: number;
  }).RESTART_EXIT_WATCHDOG_MS;

  assert.equal(typeof restartWatchdogMs, 'number');
  assert.ok((restartWatchdogMs || 0) > 5_000 + 6_000);
});
