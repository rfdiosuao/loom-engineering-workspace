import React from 'react';
import { convertFileSrc } from '@tauri-apps/api/core';
import { X } from 'lucide-react';
import { Button, FieldLabel, TextArea, showToast } from '../common';
import type { StoryboardGeneratedAsset, StoryboardShot } from './storyboardTypes';

interface Props {
  prompt: string;
  generating: boolean;
  videoGenerating: boolean;
  videoConfigReady: boolean;
  videoPath?: string;
  videoFilename?: string;
  shots: StoryboardShot[];
  generatedAssets: StoryboardGeneratedAsset[];
  onPromptChange: (prompt: string) => void;
  onGeneratePrompt: () => Promise<string | null>;
  onGenerateVideo: (prompt: string) => Promise<void>;
  onSave: (prompt: string) => Promise<void>;
}

function localAssetUrl(path: string): string {
  if (/^(?:data:|blob:|https?:)/i.test(path)) return path;
  try {
    return convertFileSrc(path);
  } catch {
    return path;
  }
}

export const StoryboardVideoPanel: React.FC<Props> = ({
  prompt,
  generating,
  videoGenerating,
  videoConfigReady,
  videoPath,
  videoFilename,
  shots,
  generatedAssets,
  onPromptChange,
  onGeneratePrompt,
  onGenerateVideo,
  onSave,
}) => {
  const [draft, setDraft] = React.useState(prompt);
  const [zoomedAsset, setZoomedAsset] = React.useState<StoryboardGeneratedAsset | null>(null);
  React.useEffect(() => setDraft(prompt), [prompt]);
  const shotScenes = React.useMemo(
    () => new Map(shots.map((shot) => [shot.num, shot.scene || ''])),
    [shots],
  );
  const galleryAssets = React.useMemo(
    () => generatedAssets
      .filter((asset) => Boolean(asset.path))
      .slice()
      .sort((left, right) => left.shotNum - right.shotNum),
    [generatedAssets],
  );

  const handleGeneratePrompt = async () => {
    const text = await onGeneratePrompt();
    if (text) { setDraft(text); showToast('视频提示词已生成', 'success'); }
  };
  const handleSave = async () => {
    onPromptChange(draft);
    await onSave(draft);
    showToast('已保存', 'success');
  };
  const handleGenerateVideo = async () => {
    if (!draft.trim()) { showToast('请先生成或填写视频提示词', 'error'); return; }
    if (!videoConfigReady) { showToast('请先在「生视频」tab 配置视频模型', 'error'); return; }
    await onGenerateVideo(draft.trim());
  };

  return (
    <div data-storyboard-video-panel className="space-y-4">
      <p className="text-xs text-text-muted">基于文案与分镜，组装视频提示词并一键生成视频。</p>
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="quiet" onClick={handleGeneratePrompt} disabled={generating || videoGenerating}>
          {generating ? '生成中...' : '生成视频提示词'}
        </Button>
        <Button variant="quiet" onClick={handleSave} disabled={generating || videoGenerating}>保存提示词</Button>
      </div>
      <label className="block">
        <FieldLabel text="视频提示词" />
        <TextArea value={draft} onChange={(e) => setDraft(e.target.value)} rows={8} />
      </label>
      {galleryAssets.length > 0 ? (
        <section className="space-y-2">
          <div>
            <h3 className="text-sm font-bold text-text">已生成的分镜素材</h3>
            <p className="mt-1 text-xs text-text-muted">按真实镜头编号归档，可点击放大核对。</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {galleryAssets.map((asset) => (
              <button
                key={`${asset.shotNum}-${asset.kind}-${asset.path}`}
                type="button"
                className="overflow-hidden rounded-lg border border-border bg-surface text-left"
                onClick={() => setZoomedAsset(asset)}
                title="查看分镜素材"
              >
                <img
                  src={localAssetUrl(asset.path)}
                  alt={`镜头 ${asset.shotNum} ${asset.kind}`}
                  className="h-36 w-full object-cover"
                />
                <span className="block px-3 py-2">
                  <span className="block text-xs font-bold text-text">镜头 {asset.shotNum} · {asset.kind}</span>
                  {shotScenes.get(asset.shotNum) ? (
                    <span className="mt-1 block truncate text-xs text-text-muted">{shotScenes.get(asset.shotNum)}</span>
                  ) : null}
                </span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="primary" onClick={handleGenerateVideo} disabled={videoGenerating || !draft.trim()}>
          {videoGenerating ? '视频生成中...' : '生成视频'}
        </Button>
        {videoPath ? (
          <span className="text-xs text-status-success">已生成：{videoFilename || videoPath}</span>
        ) : null}
      </div>
      {videoPath ? (
        <div className="overflow-hidden rounded-lg border border-border bg-black">
          <video src={localAssetUrl(videoPath)} controls className="h-full max-h-80 w-full object-contain" />
        </div>
      ) : null}
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
