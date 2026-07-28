import React from 'react';
import { convertFileSrc } from '@tauri-apps/api/core';
import { X } from 'lucide-react';
import { Button, FieldLabel, showToast } from '../common';
import { ReferenceImagePicker } from '../creative/ReferenceImagePicker';
import type { ReferenceImage } from '../creative/mediaPresets';
import type { AssetKind, StoryboardGeneratedAsset } from './storyboardTypes';

interface Props {
  kind: AssetKind;
  prompts: string[];
  shotNumbers: number[];
  generatedAssets: StoryboardGeneratedAsset[];
  /** per-prompt reference image requestValues (data URL or asset path), aligned by index */
  referenceValues: Array<string | null>;
  imageConfigReady: boolean;
  onReferencesChange: (values: Array<string | null>) => void;
  onGenerate: (
    prompt: string,
    reference: ReferenceImage | null,
    shotNum: number,
    kind: AssetKind,
    silent?: boolean,
  ) => Promise<boolean>;
}

function toReferenceImage(value: string | null): ReferenceImage | null {
  if (!value) return null;
  // data URLs and asset paths both double as preview + request value
  return { requestValue: value, previewUrl: value, label: '已选参考图', source: 'upload' };
}

function localAssetUrl(path: string): string {
  if (/^(?:data:|blob:|https?:)/i.test(path)) return path;
  try {
    return convertFileSrc(path);
  } catch {
    return path;
  }
}

export const StoryboardAssetPanel: React.FC<Props> = ({
  kind,
  prompts,
  shotNumbers,
  generatedAssets,
  referenceValues,
  imageConfigReady,
  onReferencesChange,
  onGenerate,
}) => {
  const [busyIndex, setBusyIndex] = React.useState<number | null>(null);
  const [zoomedAsset, setZoomedAsset] = React.useState<StoryboardGeneratedAsset | null>(null);

  // keep referenceValues array aligned with prompts length
  React.useEffect(() => {
    if (referenceValues.length !== prompts.length) {
      const next = prompts.map((_, i) => referenceValues[i] ?? null);
      onReferencesChange(next);
    }
  }, [prompts, referenceValues, onReferencesChange]);

  const setReferenceAt = (index: number, ref: ReferenceImage | null) => {
    const next = prompts.map((_, i) => (i === index ? (ref?.requestValue ?? null) : referenceValues[i] ?? null));
    onReferencesChange(next);
  };

  const handleGenerate = async (index: number) => {
    const prompt = prompts[index];
    if (!prompt) { showToast('提示词为空', 'error'); return; }
    if (!imageConfigReady) { showToast('请先在「生图」tab 配置生图模型', 'error'); return; }
    const shotNum = shotNumbers[index] ?? index + 1;
    setBusyIndex(index);
    try {
      await onGenerate(prompt, toReferenceImage(referenceValues[index] ?? null), shotNum, kind);
    } finally {
      setBusyIndex(null);
    }
  };

  const handleGenerateAll = async () => {
    if (!prompts.length) { showToast('没有可用的提示词，请先生成分镜', 'error'); return; }
    if (!imageConfigReady) { showToast('请先在「生图」tab 配置生图模型', 'error'); return; }
    let succeeded = 0;
    for (let i = 0; i < prompts.length; i += 1) {
      setBusyIndex(i);
      try {
        const ok = await onGenerate(
          prompts[i],
          toReferenceImage(referenceValues[i] ?? null),
          shotNumbers[i] ?? i + 1,
          kind,
          true,
        );
        if (ok) succeeded += 1;
      } finally {
        setBusyIndex(null);
      }
    }
    if (succeeded === prompts.length) {
      showToast(`${kind}已全部生成并保存`, 'success');
    } else {
      showToast(`${kind}生成完成 ${succeeded}/${prompts.length}，失败项可单独重试`, 'error');
    }
  };

  return (
    <div data-storyboard-asset-panel={kind} className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-text-muted">从分镜自动提取的 {prompts.length} 条{kind}需求，每条可单独上传参考图（选填）。</p>
        <Button variant="primary" onClick={handleGenerateAll} disabled={busyIndex !== null || prompts.length === 0}>
          一键生成全部
        </Button>
      </div>
      {prompts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-6 text-sm text-text-muted">
          暂无{kind}提示词，请先在模块五生成分镜。
        </div>
      ) : (
        <div className="space-y-3">
          {prompts.map((prompt, index) => {
            const shotNum = shotNumbers[index] ?? index + 1;
            const generated = generatedAssets.find((asset) => asset.kind === kind && asset.shotNum === shotNum);
            return (
            <div key={`${shotNum}-${index}`} className="space-y-2 rounded-lg border border-border bg-surface-alt/30 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-bold text-accent">镜头 {shotNum}</div>
                  <div className="mt-0.5 text-xs leading-5 text-text-muted">{prompt}</div>
                </div>
                <Button
                  variant="quiet"
                  onClick={() => handleGenerate(index)}
                  disabled={busyIndex !== null}
                  className="shrink-0"
                >
                  {busyIndex === index ? '生成中...' : `生成${kind}`}
                </Button>
              </div>
              {generated?.path ? (
                <button
                  type="button"
                  className="block w-full overflow-hidden rounded-lg border border-border bg-surface"
                  onClick={() => setZoomedAsset(generated)}
                  title="查看生成结果"
                >
                  <img
                    src={localAssetUrl(generated.path)}
                    alt={`镜头 ${shotNum} ${kind}`}
                    className="h-48 w-full object-contain"
                  />
                </button>
              ) : null}
              <FieldLabel text="参考图（选填）" />
              <ReferenceImagePicker
                value={toReferenceImage(referenceValues[index] ?? null)}
                latest={null}
                onChange={(ref) => setReferenceAt(index, ref)}
              />
            </div>
            );
          })}
        </div>
      )}
      {zoomedAsset?.path ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`镜头 ${zoomedAsset.shotNum} ${zoomedAsset.kind}预览`}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-6"
          onClick={() => setZoomedAsset(null)}
        >
          <button
            type="button"
            className="absolute right-6 top-6 flex h-10 w-10 items-center justify-center rounded-full bg-black/60 text-white"
            onClick={() => setZoomedAsset(null)}
            title="关闭预览"
          >
            <X size={20} />
          </button>
          <img
            src={localAssetUrl(zoomedAsset.path)}
            alt={`镜头 ${zoomedAsset.shotNum} ${zoomedAsset.kind}`}
            className="max-h-full max-w-full object-contain"
            onClick={(event) => event.stopPropagation()}
          />
        </div>
      ) : null}
    </div>
  );
};
