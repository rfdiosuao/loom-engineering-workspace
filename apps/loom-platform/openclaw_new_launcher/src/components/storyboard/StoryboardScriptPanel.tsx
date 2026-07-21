import React from 'react';
import { Button, FieldLabel, TextArea, showToast } from '../common';

interface Props {
  content: string;
  generating: boolean;
  onContentChange: (content: string) => void;
  onGenerate: () => Promise<string | null>;
  onSave: (content: string) => Promise<void>;
}

export const StoryboardScriptPanel: React.FC<Props> = ({ content, generating, onContentChange, onGenerate, onSave }) => {
  const [draft, setDraft] = React.useState(content);
  React.useEffect(() => setDraft(content), [content]);

  const handleGenerate = async () => {
    const text = await onGenerate();
    if (text) {
      setDraft(text);
      showToast('文案已生成，记得保存', 'success');
    }
  };
  const handleSave = async () => {
    onContentChange(draft);
    await onSave(draft);
    showToast('文案已保存', 'success');
  };

  return (
    <div data-storyboard-script-panel className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-text-muted">点「生成文案」基于模块一/二/三的设定产出文案；可在下方直接修改后保存。</p>
        <div className="flex gap-2">
          <Button variant="primary" onClick={handleGenerate} disabled={generating}>{generating ? '生成中...' : '生成文案'}</Button>
          <Button variant="quiet" onClick={handleSave} disabled={generating || draft === content}>保存</Button>
        </div>
      </div>
      <label className="block">
        <FieldLabel text="短视频文案" required />
        <TextArea value={draft} onChange={(e) => setDraft(e.target.value)} rows={12} placeholder="生成或手写的口播/剧情文案..." />
      </label>
    </div>
  );
};
