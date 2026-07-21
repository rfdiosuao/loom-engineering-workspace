import React from 'react';
import { Button, FieldLabel, showToast } from '../common';
import { ReferenceImagePicker } from '../creative/ReferenceImagePicker';
import type { ReferenceImage } from '../creative/mediaPresets';
import type { AssetKind } from './storyboardTypes';

interface Props {
  kind: AssetKind;
  prompts: string[];
  /** per-prompt reference image requestValues (data URL or asset path), aligned by index */
  referenceValues: Array<string | null>;
  imageConfigReady: boolean;
  onReferencesChange: (values: Array<string | null>) => void;
  onGenerate: (prompt: string, reference: ReferenceImage | null) => Promise<void>;
}

function toReferenceImage(value: string | null): ReferenceImage | null {
  if (!value) return null;
  // data URLs and asset paths both double as preview + request value
  return { requestValue: value, previewUrl: value, label: '已选参考图', source: 'upload' };
}

export const StoryboardAssetPanel: React.FC<Props> = ({
  kind, prompts, referenceValues, imageConfigReady, onReferencesChange, onGenerate,
}) => {
  const [busyIndex, setBusyIndex] = React.useState<number | null>(null);

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
    setBusyIndex(index);
    try {
      await onGenerate(prompt, toReferenceImage(referenceValues[index] ?? null));
      showToast(`${kind}（镜头 ${index + 1}）已提交生成`, 'success');
    } finally {
      setBusyIndex(null);
    }
  };

  const handleGenerateAll = async () => {
    if (!prompts.length) { showToast('没有可用的提示词，请先生成分镜', 'error'); return; }
    if (!imageConfigReady) { showToast('请先在「生图」tab 配置生图模型', 'error'); return; }
    for (let i = 0; i < prompts.length; i += 1) {
      setBusyIndex(i);
      try {
        await onGenerate(prompts[i], toReferenceImage(referenceValues[i] ?? null));
      } finally {
        setBusyIndex(null);
      }
    }
    showToast(`全部 ${kind} 已提交生成`, 'success');
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
          {prompts.map((prompt, index) => (
            <div key={index} className="space-y-2 rounded-xl border border-border bg-surface-alt/30 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-bold text-accent">镜头 {index + 1}</div>
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
              <FieldLabel text="参考图（选填）" />
              <ReferenceImagePicker
                value={toReferenceImage(referenceValues[index] ?? null)}
                latest={null}
                onChange={(ref) => setReferenceAt(index, ref)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

