import assert from 'node:assert/strict';
import path from 'node:path';
import { test } from 'node:test';

import {
  phoneFrameCachePath,
  phoneFrameMetadataPath,
  phoneFrameOutputPath,
} from '../lib/phone-frame-paths.mjs';

test('phone frame cache is isolated by device and capture specification', () => {
  const outputDir = path.resolve('data/phone-frames');
  const base = {
    deviceId: 'phone-a',
    phoneUrl: 'http://192.168.1.8:9527',
    format: 'jpeg',
    quality: 48,
    maxLongSide: 640,
    overlayGrid: false,
  };

  const first = phoneFrameCachePath(outputDir, base);
  assert.equal(first, phoneFrameCachePath(outputDir, { ...base }));
  assert.notEqual(first, phoneFrameCachePath(outputDir, { ...base, deviceId: 'phone-b' }));
  assert.notEqual(first, phoneFrameCachePath(outputDir, { ...base, quality: 62, maxLongSide: 960 }));
  assert.equal(first.includes('phone-a'), false);
  assert.equal(first.includes('192.168.1.8'), false);
  assert.equal(phoneFrameMetadataPath(first), `${first}.json`);
});

test('parallel phone frame output paths include a process-safe unique suffix', () => {
  const outputDir = path.resolve('data/phone-frames');
  const output = phoneFrameOutputPath(outputDir, { deviceId: 'phone-a' }, 'jpg');

  assert.equal(path.dirname(output), outputDir);
  assert.match(path.basename(output), /^vision-frame-\d+-\d+-[a-f0-9]{16}\.jpg$/);
});
