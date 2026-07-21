import React from 'react';
import { Button, FieldLabel, Input, Loading, showToast } from '../common';
import { imageApi, videoApi, parseErrorText, mediaApi, waitForJob, type MediaConfigSnapshot } from '../../services/api';
import { storyboardApi } from '../../services/storyboardApi';
import { STORYBOARD_STEPS } from './storyboardSteps';
import type { StoryboardProject, StoryboardSelections, StoryboardShot } from './storyboardTypes';
import {
  emptyProject, loadProjectsIndex, loadProject, saveProject, deleteProject as deleteProjectEntry,
} from './projectStore';
import { StoryboardProjectsSidebar } from './StoryboardProjectsSidebar';
import { StoryboardScriptPanel } from './StoryboardScriptPanel';
import { StoryboardShotsPanel } from './StoryboardShotsPanel';
import { StoryboardAssetPanel } from './StoryboardAssetPanel';
import { StoryboardVideoPanel } from './StoryboardVideoPanel';

const OptionGroups = React.lazy(() => import('./StoryboardOptionGroups').then((m) => ({ default: m.StoryboardOptionGroups })));

function assetKindFor(module: string): '人物图' | '产品图' | '场景图' {
  if (module === '模块六') return '人物图';
  if (module === '模块七') return '产品图';
  return '场景图';
}

function parseShotsJson(text: string): StoryboardShot[] {
  const start = text.indexOf('[');
  const end = text.lastIndexOf(']');
  if (start < 0 || end < 0) return [];
  try {
    const parsed = JSON.parse(text.slice(start, end + 1));
    return Array.isArray(parsed) ? (parsed as StoryboardShot[]) : [];
  } catch {
    return [];
  }
}

function extractAssetPromptsFrontend(shots: StoryboardShot[], project: StoryboardProject) {
  const result = { 人物图: [] as string[], 产品图: [] as string[], 场景图: [] as string[] };
  const moduleMap = { 人物图: '模块六', 产品图: '模块七', 场景图: '模块八' } as const;
  for (const shot of shots) {
    const kind = shot.assetType as keyof typeof result;
    if (!(kind in result)) continue;
    const sel = (project.selections[moduleMap[kind]] || {}) as Record<string, Array<string | boolean>>;
    const styleParts: string[] = [];
    for (const [cat, vals] of Object.entries(sel)) {
      const strings = (vals || []).filter((v): v is string => typeof v === 'string');
      if (strings.length) styleParts.push(`${cat}:${strings.join(',')}`);
    }
    result[kind].push(`镜头${shot.num}：${shot.scene || ''}${styleParts.length ? '；' + styleParts.join('；') : ''}`);
  }
  return result;
}

export const StoryboardWorkbench: React.FC = () => {
  const [entries, setEntries] = React.useState<Array<{ projectId: string; title: string; updatedAt: string }>>([]);
  const [entriesLoading, setEntriesLoading] = React.useState(true);
  const [project, setProject] = React.useState<StoryboardProject | null>(null);
  const [activeStepId, setActiveStepId] = React.useState(0);
  const [mediaConfig, setMediaConfig] = React.useState<MediaConfigSnapshot | null>(null);
  const [generatingStage, setGeneratingStage] = React.useState<'script' | 'storyboard' | 'videoPrompt' | null>(null);
  const [videoGenerating, setVideoGenerating] = React.useState(false);

  const refreshEntries = React.useCallback(async () => {
    setEntriesLoading(true);
    try {
      setEntries(await loadProjectsIndex());
    } catch (error) {
      showToast(parseErrorText(error) || '读取项目列表失败', 'error');
    } finally {
      setEntriesLoading(false);
    }
  }, []);

  const refreshMediaConfig = React.useCallback(async () => {
    try {
      const { config } = await mediaApi.config();
      setMediaConfig(config);
    } catch {
      setMediaConfig(null);
    }
  }, []);

  React.useEffect(() => {
    void refreshEntries();
    void refreshMediaConfig();
  }, [refreshEntries, refreshMediaConfig]);

  const selectProject = React.useCallback(async (projectId: string) => {
    try {
      const loaded = await loadProject(projectId);
      if (loaded) setProject(loaded);
    } catch (error) {
      showToast(parseErrorText(error) || '读取项目失败', 'error');
    }
  }, []);

  const createProject = React.useCallback(async () => {
    const fresh = emptyProject();
    await saveProject(fresh);
    setProject(fresh);
    setActiveStepId(0);
    await refreshEntries();
  }, [refreshEntries]);

  const persist = React.useCallback(async (next: StoryboardProject) => {
    setProject(next);
    try {
      await saveProject(next);
      await refreshEntries();
    } catch (error) {
      showToast(parseErrorText(error) || '保存项目失败', 'error');
    }
  }, [refreshEntries]);

  const renameProject = React.useCallback(async (projectId: string, title: string) => {
    if (!project || project.projectId !== projectId) return;
    await persist({ ...project, title });
  }, [project, persist]);

  const removeProject = React.useCallback(async (projectId: string) => {
    await deleteProjectEntry(projectId);
    if (project?.projectId === projectId) setProject(null);
    await refreshEntries();
  }, [project, refreshEntries]);

  const setSelection = React.useCallback((module: string, category: string, values: Array<string | boolean>) => {
    if (!project) return;
    const moduleSel = { ...(project.selections[module as keyof StoryboardSelections] || {}) };
    moduleSel[category] = values;
    const next = { ...project, selections: { ...project.selections, [module]: moduleSel } };
    void persist(next);
  }, [project, persist]);

  const generate = React.useCallback(async (stage: 'script' | 'storyboard' | 'videoPrompt') => {
    if (!project) return null;
    setGeneratingStage(stage);
    try {
      const { result } = await storyboardApi.generate({ stage, project });
      if (stage === 'storyboard') {
        const shots = parseShotsJson(result);
        const assetPrompts = extractAssetPromptsFrontend(shots, project);
        await persist({ ...project, storyboard: { shots, generatedAt: new Date().toISOString() }, assetPrompts });
        return shots;
      }
      if (stage === 'script') {
        await persist({ ...project, script: { ...project.script, content: result, generatedAt: new Date().toISOString() } });
      }
      if (stage === 'videoPrompt') {
        await persist({ ...project, videoPrompt: { content: result, generatedAt: new Date().toISOString() } });
      }
      return result;
    } catch (error) {
      showToast(parseErrorText(error) || `${stage} 生成失败`, 'error');
      return null;
    } finally {
      setGeneratingStage(null);
    }
  }, [project, persist]);

  const submitAssetImage = React.useCallback(async (prompt: string, reference: { requestValue: string } | null) => {
    if (!mediaConfig?.image?.baseUrl || !mediaConfig?.image?.hasApiKey) {
      showToast('请先在「生图」tab 配置生图模型', 'error');
      return;
    }
    try {
      const { jobId } = await imageApi.submit({
        baseUrl: mediaConfig.image.baseUrl!,
        apiKey: '',
        prompt,
        size: '1024x1024',
        model: mediaConfig.image.model || undefined,
        editImagePath: reference?.requestValue,
        source: 'storyboard',
      });
      await waitForJob(jobId, { timeoutMs: 10 * 60 * 1000 });
      showToast('图片生成完成，结果已存入媒体库', 'success');
    } catch (error) {
      showToast(parseErrorText(error) || '图片生成失败', 'error');
    }
  }, [mediaConfig]);

  const submitVideo = React.useCallback(async (prompt: string) => {
    if (!project) return;
    const vc = mediaConfig?.video;
    if (!vc?.hasApiKey) {
      showToast('请先在「生视频」tab 配置视频模型', 'error');
      return;
    }
    setVideoGenerating(true);
    try {
      const { jobId } = await videoApi.submit({
        providerId: vc.providerId as import('../../types').VideoProviderId | undefined,
        apiBase: vc.apiBase,
        model: vc.model,
        dashKey: '',
        prompt,
        mode: vc.mode || 't2v',
        resolution: vc.resolution || '720P',
        duration: vc.duration || 5,
        ratio: vc.ratio || '16:9',
        source: 'storyboard',
      });
      const job = await waitForJob<{ video?: string; path?: string; filename?: string; mime?: string }>(jobId, { timeoutMs: 10 * 60 * 1000 });
      const result = job.result || {};
      const videoPath = result.path || '';
      if (videoPath) {
        const next = { ...project, videoResult: { path: videoPath, filename: result.filename, generatedAt: new Date().toISOString() } };
        setProject(next);
        await saveProject(next);
        showToast('视频生成完成，已保存到项目', 'success');
      } else {
        showToast('视频已生成（未返回本地路径，可在媒体库查看）', 'success');
      }
    } catch (error) {
      showToast(parseErrorText(error) || '视频生成失败', 'error');
    } finally {
      setVideoGenerating(false);
    }
  }, [mediaConfig, project]);

  const step = STORYBOARD_STEPS.find((s) => s.id === activeStepId) || STORYBOARD_STEPS[0];
  const imageReady = Boolean(mediaConfig?.image?.baseUrl && mediaConfig?.image?.hasApiKey);
  const videoReady = Boolean(mediaConfig?.video?.hasApiKey);

  return (
    <div data-storyboard-workbench className="flex h-full overflow-hidden">
      <div data-storyboard-projects-sidebar>
        <StoryboardProjectsSidebar
          entries={entries}
          activeProjectId={project?.projectId ?? null}
          loading={entriesLoading}
          onRefresh={refreshEntries}
          onSelect={(id) => void selectProject(id)}
          onCreate={() => void createProject()}
          onRename={(id, title) => void renameProject(id, title)}
          onDelete={(id) => void removeProject(id)}
        />
      </div>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {!project ? (
          <div className="flex flex-1 items-center justify-center text-sm text-text-muted">
           请新建或选择一个项目开始。
          </div>
        ) : (
          <>
            <header className="shrink-0 border-b border-border px-6 py-4">
              <div className="text-xs font-bold tracking-widest text-accent">全案九步</div>
              <h1 className="mt-1 text-2xl font-black text-text">{project.title}</h1>
            </header>
            <nav data-storyboard-step-bar className="flex shrink-0 gap-1 overflow-x-auto border-b border-border px-6 py-2">
              {STORYBOARD_STEPS.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  data-storyboard-step={s.id}
                  onClick={() => setActiveStepId(s.id)}
                  className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition ${s.id === activeStepId ? 'bg-accent text-accent-ink' : 'text-text-muted hover:bg-hover'}`}
                >
                  {s.id}. {s.icon} {s.label}
                </button>
              ))}
            </nav>
            <main className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
              {step.id === 0 ? (
                <div className="max-w-2xl space-y-4">
                  <div className="text-sm text-text-muted">{step.goal}</div>
                  <label className="block">
                    <FieldLabel text="目标对象品类" />
                    <Input
                      value={project.target.category}
                      onChange={(e) => setProject({ ...project, target: { ...project.target, category: e.target.value } })}
                      placeholder="如：食品饮料 / 美妆护肤 / 故事文章"
                    />
                  </label>
                  <label className="block">
                    <FieldLabel text="目标对象名称" required />
                    <Input
                      value={project.target.object}
                      onChange={(e) => setProject({ ...project, target: { ...project.target, object: e.target.value } })}
                      placeholder="产品名称 / 场景描述 / 故事文章"
                    />
                  </label>
                  <Button variant="primary" onClick={() => void persist(project)}>保存</Button>
                </div>
              ) : null}

              {step.optionGroups.length > 0 ? (
                <div className="space-y-4">
                  <div className="text-sm text-text-muted">{step.goal}</div>
                  <React.Suspense fallback={<Loading />}>
                    <OptionGroups
                      step={step}
                      selections={project.selections}
                      onSelectionChange={(module, category, values) => setSelection(module as string, category, values)}
                    />
                  </React.Suspense>
                </div>
              ) : null}

              {step.generateStage === 'script' ? (
                <StoryboardScriptPanel
                  content={project.script.content}
                  generating={generatingStage === 'script'}
                  onContentChange={(content) => { setProject({ ...project, script: { ...project.script, content } }); }}
                  onGenerate={() => generate('script') as Promise<string | null>}
                  onSave={async (content) => { await saveProject({ ...project, script: { ...project.script, content } }); }}
                />
              ) : null}

              {step.generateStage === 'storyboard' ? (
                <StoryboardShotsPanel
                  shots={project.storyboard.shots}
                  assetPrompts={project.assetPrompts || { 人物图: [], 产品图: [], 场景图: [] }}
                  generating={generatingStage === 'storyboard'}
                  scriptContent={project.script.content}
                  onGenerate={() => generate('storyboard') as Promise<StoryboardShot[] | null>}
                />
              ) : null}

              {(step.module === '模块六' || step.module === '模块七' || step.module === '模块八') && project.assetPrompts ? (
                <div className="space-y-4">
                  <div className="text-sm text-text-muted">{step.goal}</div>
                  <StoryboardAssetPanel
                    kind={assetKindFor(step.module)}
                    prompts={project.assetPrompts[assetKindFor(step.module)]}
                    referenceValues={(project.assetReferences?.[assetKindFor(step.module)]) || []}
                    imageConfigReady={imageReady}
                    onReferencesChange={(values) => {
                      const kind = assetKindFor(step.module);
                      const nextRefs = { ...(project.assetReferences || { 人物图: [], 产品图: [], 场景图: [] }) };
                      nextRefs[kind] = values;
                      void persist({ ...project, assetReferences: nextRefs });
                    }}
                    onGenerate={submitAssetImage}
                  />
                </div>
              ) : null}

              {step.generateStage === 'videoPrompt' ? (
                <StoryboardVideoPanel
                  prompt={project.videoPrompt?.content || ''}
                  generating={generatingStage === 'videoPrompt'}
                  videoGenerating={videoGenerating}
                  videoConfigReady={videoReady}
                  videoPath={project.videoResult?.path}
                  videoFilename={project.videoResult?.filename}
                  onPromptChange={(content) => { setProject({ ...project, videoPrompt: { content } }); }}
                  onSave={async (content) => { await saveProject({ ...project, videoPrompt: { content } }); }}
                  onGeneratePrompt={() => generate('videoPrompt') as Promise<string | null>}
                  onGenerateVideo={submitVideo}
                />
              ) : null}
            </main>
          </>
        )}
      </div>
    </div>
  );
};
