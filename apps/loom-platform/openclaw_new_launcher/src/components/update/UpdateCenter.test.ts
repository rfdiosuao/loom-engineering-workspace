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

test('update verification copy describes the LOOM release signature', () => {
  const source = readFileSync(new URL('./UpdateCenter.tsx', import.meta.url), 'utf8');
  assert.match(source, /LOOM 官方发布签名/);
  assert.doesNotMatch(source, /SHA256 与 Windows 发布者校验/);
});
