import type { AssetKind, StoryboardGeneratedAsset, StoryboardShot } from './storyboardTypes';

export function shotNumbersFor(shots: StoryboardShot[], kind: AssetKind): number[] {
  return shots
    .filter((shot) => shot.assetType === kind)
    .map((shot) => Number(shot.num))
    .filter((shotNum) => Number.isFinite(shotNum) && shotNum > 0);
}

export function mergeGeneratedAsset(
  existing: StoryboardGeneratedAsset[],
  asset: StoryboardGeneratedAsset,
): StoryboardGeneratedAsset[] {
  return [
    ...existing.filter(
      (candidate) => candidate.shotNum !== asset.shotNum || candidate.kind !== asset.kind,
    ),
    asset,
  ];
}
