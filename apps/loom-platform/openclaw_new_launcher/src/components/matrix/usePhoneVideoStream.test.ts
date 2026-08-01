import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('./usePhoneVideoStream.ts', import.meta.url), 'utf8');

test('uses only a one-time local ticket for the direct binary stream', () => {
  assert.match(source, /Authorization: `Bearer \$\{grant\.ticket\}`/);
  assert.doesNotMatch(source, /phoneToken|launcherSecret|streamToken/);
  assert.match(source, /credentials: 'omit'/);
  assert.match(source, /referrerPolicy: 'no-referrer'/);
});

test('pauses on hidden windows and labels failures as screenshot degradation', () => {
  assert.match(source, /document\.visibilityState === 'visible'/);
  assert.match(source, /status: 'degraded'/);
  assert.match(source, /已自动降级为截图/);
  assert.match(source, /matrixApi\.stopPhoneStream/);
});
