import assert from 'node:assert/strict';
import test from 'node:test';

import type { StoryboardGeneratedAsset, StoryboardShot } from './storyboardTypes';
import { mergeGeneratedAsset, shotNumbersFor } from './storyboardViewModel';

test('shotNumbersFor preserves the real matching shot numbers, including numeric strings', () => {
  const shots = [
    { num: 2, assetType: '人物图' },
    { num: 5, assetType: '产品图' },
    { num: '7', assetType: '人物图' },
    { num: Number.NaN, assetType: '人物图' },
  ] as unknown as StoryboardShot[];

  assert.deepEqual(shotNumbersFor(shots, '人物图'), [2, 7]);
});

test('mergeGeneratedAsset replaces only the same shot and asset kind', () => {
  const existing: StoryboardGeneratedAsset[] = [
    { shotNum: 2, kind: '人物图', path: 'old-person.png' },
    { shotNum: 2, kind: '场景图', path: 'scene.png' },
    { shotNum: 5, kind: '人物图', path: 'other-person.png' },
  ];
  const replacement: StoryboardGeneratedAsset = {
    shotNum: 2,
    kind: '人物图',
    path: 'new-person.png',
  };

  assert.deepEqual(mergeGeneratedAsset(existing, replacement), [
    { shotNum: 2, kind: '场景图', path: 'scene.png' },
    { shotNum: 5, kind: '人物图', path: 'other-person.png' },
    replacement,
  ]);
});
