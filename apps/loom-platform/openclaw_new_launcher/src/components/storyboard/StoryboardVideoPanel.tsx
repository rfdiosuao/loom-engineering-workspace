import React from 'react';
import { Button, FieldLabel, TextArea, showToast } from '../common';

interface Props {
  prompt: string;
  generating: boolean;
  videoGenerating: boolean;
  videoConfigReady: boolean;
  videoPath?: string;
  videoFilename?: string;
  onPromptChange: (prompt: string) => void;
  onGeneratePrompt: () => Promise<string | null>;
  onGenerateVideo: (prompt: string) => Promise<void>;
  onSave: (prompt: string) => Promise<void>;
}

export const StoryboardVideoPanel: React.FC<Props> = ({
  prompt,
  generating,
  videoGenerating,
  videoConfigReady,
  videoPath,
  videoFilename,
  onPromptChange,
  onGeneratePrompt,
  onGenerateVideo,
  onSave,
}) => {
  const [draft, setDraft] = React.useState(prompt);
  React.useEffect(() => setDraft(prompt), [prompt]);

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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="primary" onClick={handleGenerateVideo} disabled={videoGenerating || !draft.trim()}>
          {videoGenerating ? '视频生成中...' : '生成视频'}
        </Button>
        {videoPath ? (
          <span className="text-xs text-status-success">已生成：{videoFilename || videoPath}</span>
        ) : null}
      </div>
      {videoPath ? (
        <div className="overflow-hidden rounded-xl border border-border bg-black">
          <video src={`asset://localhost/${videoPath.replace(/\\/g, '/')}`} controls className="h-full max-h-80 w-full object-contain" />
        </div>
      ) : null}
    </div>
  );
};
