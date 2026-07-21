import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

const sourceUrl = new URL('./PhoneDemoPage.tsx', import.meta.url);
const apiUrl = new URL('../../services/api.ts', import.meta.url);

test('phone status targets the selected device and requires an explicit online result', async () => {
  const source = await readFile(sourceUrl, 'utf8');
  assert.match(source, /phoneApi\.status\(\{ deviceId: targetDeviceId \}\)/);
  assert.match(source, /target\?\.ok === true && target\?\.status\?\.online === true/);
  assert.doesNotMatch(source, /some\?\.\(\(item: any\) => item\?\.ok !== false\)/);
});

test('fresh explicit connection checks take precedence over matrix snapshots', async () => {
  const source = await readFile(sourceUrl, 'utf8');
  const stateBlock = source.slice(
    source.indexOf('const selectedRuntimeState ='),
    source.indexOf('const connectionVerified ='),
  );
  const freshIndex = stateBlock.indexOf('selectedRuntimeIsFresh && selectedCheckedRuntime');
  const matrixIndex = stateBlock.indexOf('selectedMatrixDevice');
  assert.ok(freshIndex >= 0, 'fresh runtime branch is present');
  assert.match(stateBlock, /selectedMatrixDevice && selectedMatrixIsFresh/);
  assert.ok(matrixIndex > freshIndex, 'fresh runtime branch is evaluated before the fresh matrix fallback');
});

test('phone status API accepts a device id', async () => {
  const source = await readFile(apiUrl, 'utf8');
  assert.match(source, /status: \(params: \{ deviceId\?: string \} = \{\}\)/);
  assert.match(source, /api\('\/api\/phone\/status', 'POST', params\)/);
});

test('unsaved address and token edits require saving before phone actions', async () => {
  const source = await readFile(sourceUrl, 'utf8');

  assert.match(
    source,
    /const hasUnsavedPhoneConfig = isAddingDevice\s+\|\| Boolean\(phoneToken\.trim\(\)\)\s+\|\| displayPhoneAddress\(phoneAddress\) !== displayPhoneAddress\(selectedConfiguredPhone\?\.baseUrl \|\| ''\);/,
  );
  assert.match(source, /手机 IP 或连接令牌有未保存修改，请先点击“保存并检测”，再继续操作。/);
  assert.match(source, /请先填写手机 IP 和连接令牌，然后点击“保存并检测”。/);
});

test('connection checks, screen reads, and task submissions guard before using saved config', async () => {
  const source = await readFile(sourceUrl, 'utf8');
  const actionBlock = (start: string, end: string) => source.slice(source.indexOf(start), source.indexOf(end));
  const cases = [
    ['const checkConnection =', 'const readScreen =', 'phoneApi.status'],
    ['const readScreen =', 'const executePhoneTask =', 'phoneApi.read'],
    ['const executePhoneTask =', 'const applyQuickTask =', 'phoneApi.task'],
  ] as const;

  for (const [start, end, apiCall] of cases) {
    const block = actionBlock(start, end);
    const guardIndex = block.indexOf('requireSavedPhoneConfig()');
    const apiIndex = block.indexOf(apiCall);
    assert.ok(guardIndex >= 0, `${start} checks the saved configuration guard`);
    assert.ok(apiIndex > guardIndex, `${start} guards before ${apiCall}`);
  }

  const saveBlock = actionBlock('const saveDeviceAndDetect =', 'const checkConnection =');
  assert.match(saveBlock, /await checkConnection\(deviceId, true\)/);
});
