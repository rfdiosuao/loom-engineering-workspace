import React from 'react';
import { Button, showToast } from '../common';
import type { StoryboardShot } from './storyboardTypes';

interface Props {
  shots: StoryboardShot[];
  assetPrompts: { 人物图: string[]; 产品图: string[]; 场景图: string[] };
  generating: boolean;
  scriptContent: string;
  onGenerate: () => Promise<StoryboardShot[] | null>;
}

export const StoryboardShotsPanel: React.FC<Props> = ({ shots, assetPrompts, generating, scriptContent, onGenerate }) => {
  const handleGenerate = async () => {
    if (!scriptContent.trim()) {
      showToast('请先在模块四生成或保存文案', 'error');
      return;
    }
    const result = await onGenerate();
    if (result) showToast(`已生成 ${result.length} 个分镜`, 'success');
  };
  return (
    <div data-storyboard-shots-panel className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-text-muted">基于已保存文案自动同步并逐镜拆解，同时提取人物/产品/场景素材提示词。</p>
        <Button variant="primary" onClick={handleGenerate} disabled={generating || !scriptContent.trim()}>
          {generating ? '生成中...' : '生成分镜'}
        </Button>
      </div>
      {shots.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-6 text-sm text-text-muted">暂无分镜。</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-xs">
            <thead className="bg-surface-alt/60 text-text-muted">
              <tr>
                {['镜', '时长', '景别', '画面', '口播/字幕', '素材', '特效'].map((h) => (
                  <th key={h} className="px-2 py-2 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shots.map((shot) => (
                <tr key={shot.num} className="border-t border-border">
                  <td className="px-2 py-2 font-bold text-accent">{shot.num}</td>
                  <td className="px-2 py-2 text-text-muted">{shot.time || ''}</td>
                  <td className="px-2 py-2 text-text-muted">{shot.shotType || ''}</td>
                  <td className="px-2 py-2 text-text">{shot.scene || ''}</td>
                  <td className="px-2 py-2 text-text">{shot.voice || ''}</td>
                  <td className="px-2 py-2 text-text-muted">{shot.assetType || ''}</td>
                  <td className="px-2 py-2 text-text-muted">{shot.effect || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(assetPrompts.人物图.length > 0 || assetPrompts.产品图.length > 0 || assetPrompts.场景图.length > 0) && (
        <div className="grid gap-3 md:grid-cols-3">
          {(['人物图', '产品图', '场景图'] as const).map((kind) => (
            <div key={kind} className="rounded-xl border border-border bg-surface-alt/30 p-3">
              <div className="mb-2 text-xs font-black text-text">{kind}提示词</div>
              {assetPrompts[kind].length === 0 ? (
                <div className="text-xs text-text-muted">无</div>
              ) : (
                <ul className="space-y-2">
                  {assetPrompts[kind].map((p, i) => (
                    <li key={i} className="rounded-lg bg-surface px-2 py-1.5 text-xs text-text-muted">{p}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
