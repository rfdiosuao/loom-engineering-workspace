import React, { useEffect, useState } from 'react';
import { convertFileSrc } from '@tauri-apps/api/core';
import { Button, Input, TextArea, Select, Loading, showToast, FieldLabel } from '../common';
import { imageApi, videoApi, configApi } from '../../services/api';
import { readGatewayStoredConfig, readMemberGatewayDefaults } from '../../services/gatewayConfig';
import { useLogStore } from '../../stores/logStore';
import { Scene, type VideoProviderId } from '../../types';
import { VIDEO_PROVIDERS, getDefaultVideoModel, getVideoProvider } from '../../features/video/providers';

type ViewKey = 'front' | 'side' | 'back';
type FrameSlot = 'firstFrame' | 'lastFrame';

const PROJECT_PATH = 'data/.openclaw/storyboard_project.json';

const VIEW_KEYS: { key: ViewKey; label: string }[] = [
  { key: 'front', label: '正面' },
  { key: 'side', label: '侧面' },
  { key: 'back', label: '背面' },
];

const CHECK_KEYS: { key: keyof Scene['checks']; label: string }[] = [
  { key: 'productStable', label: '产品不变形' },
  { key: 'logoClear', label: 'Logo / 包装清晰' },
  { key: 'sellingPoint', label: '卖点一眼可懂' },
  { key: 'frameFlowGood', label: '首尾帧连贯' },
  { key: 'cropReady', label: '适合投放裁切' },
];

const DURATION_OPTIONS = ['5', '10'];
const RATIO_OPTIONS = ['9:16', '16:9', '1:1', '4:3'];
const CAMERA_OPTIONS = ['缓慢推进', '横向平移', '环绕展示', '静物特写', '拉远收束'];
const DEFAULT_CANDIDATE_PROMPT = '产品置于干净桌面，光线明亮，主体完整清晰，突出产品核心卖点，适合作为短视频广告关键帧。';
const DEFAULT_VIDEO_PROMPT = '从首帧开始，镜头自然运动，产品保持稳定不变形，画面节奏适合小广告短视频。';

interface StoryboardProject {
  title: string;
  scenes: Scene[];
  productViews: Record<ViewKey, string | null>;
}

const defaultScene = (): Scene => ({
  id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  title: '开场镜头',
  sellingPoint: '3 秒讲清产品核心卖点',
  duration: '5',
  ratio: '9:16',
  camera: '缓慢推进',
  prompt: DEFAULT_VIDEO_PROMPT,
  negative: '低清晰度，变形，杂乱背景，错误文字，遮挡产品，品牌错误。',
  candidatePrompt: DEFAULT_CANDIDATE_PROMPT,
  referenceImage: null,
  firstFrame: null,
  lastFrame: null,
  video: null,
  checks: { productStable: false, logoClear: false, sellingPoint: false, frameFlowGood: false, cropReady: false },
  productViews: { front: null, side: null, back: null },
  candidates: [],
});

const defaultProject = (): StoryboardProject => ({
  title: 'U盘小广告视频',
  productViews: { front: null, side: null, back: null },
  scenes: [defaultScene()],
});

function normalizeScene(value: any, index: number): Scene {
  const base = defaultScene();
  return {
    ...base,
    ...value,
    id: String(value?.id || `${Date.now()}-${index}`),
    title: String(value?.title || `镜头 ${index + 1}`),
    checks: { ...base.checks, ...(value?.checks || {}) },
    productViews: { ...base.productViews, ...(value?.productViews || {}) },
    candidates: Array.isArray(value?.candidates) ? value.candidates : [],
    candidatePrompt: String(value?.candidatePrompt || value?.prompt || base.candidatePrompt),
    referenceImage: value?.referenceImage || null,
  };
}

function normalizeProject(value: any): StoryboardProject {
  const fallback = defaultProject();
  const scenes = Array.isArray(value?.scenes) && value.scenes.length > 0
    ? value.scenes.map((scene: any, index: number) => normalizeScene(scene, index))
    : fallback.scenes;

  return {
    title: String(value?.title || fallback.title),
    productViews: { ...fallback.productViews, ...(value?.productViews || {}) },
    scenes,
  };
}

function imageSizeForRatio(ratio: string): string {
  if (ratio === '9:16' || ratio === '3:4') return '1024x1536';
  if (ratio === '16:9' || ratio === '4:3') return '1536x1024';
  return '1024x1024';
}

function imageAspectClass(ratio: string): string {
  if (ratio === '9:16') return 'aspect-[9/16]';
  if (ratio === '3:4') return 'aspect-[3/4]';
  if (ratio === '1:1') return 'aspect-square';
  if (ratio === '4:3') return 'aspect-[4/3]';
  return 'aspect-video';
}

function pickReferenceImage(project: StoryboardProject, scene: Scene): string | null {
  return (
    scene.referenceImage ||
    scene.firstFrame ||
    scene.lastFrame ||
    project.productViews.front ||
    project.productViews.side ||
    project.productViews.back ||
    null
  );
}

function createVideoObjectUrl(video: string): { url: string; size: number; revoke: () => void } {
  if (/^(https?:|asset:|file:|tauri:)/i.test(video)) {
    return { url: video, size: 0, revoke: () => undefined };
  }

  if (!video.startsWith('data:')) {
    return { url: convertFileSrc(video), size: 0, revoke: () => undefined };
  }

  const [header, payload = ''] = video.split(',');
  const mime = header.match(/^data:(.*?);base64$/)?.[1] || 'video/mp4';
  const binary = atob(payload);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: mime });
  const url = URL.createObjectURL(blob);
  return { url, size: blob.size, revoke: () => URL.revokeObjectURL(url) };
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = size;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

export const StoryboardPage: React.FC = () => {
  const [project, setProject] = useState<StoryboardProject>(defaultProject);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [candidates, setCandidates] = useState<string[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<number | null>(null);
  const [generatingCandidates, setGeneratingCandidates] = useState(false);
  const [generatingVideo, setGeneratingVideo] = useState(false);
  const [candidateStatus, setCandidateStatus] = useState('');
  const [videoStatus, setVideoStatus] = useState('');
  const [videoPreview, setVideoPreview] = useState<{ url: string; size: number } | null>(null);
  const [videoError, setVideoError] = useState('');
  const [videoProviderId, setVideoProviderId] = useState<VideoProviderId>('dashscope');
  const [videoApiKey, setVideoApiKey] = useState('');
  const [videoApiBase, setVideoApiBase] = useState(getVideoProvider('dashscope').apiBase);
  const [videoModel, setVideoModel] = useState(getDefaultVideoModel('dashscope', 'i2v'));
  const [saved, setSaved] = useState(false);

  const appendLog = useLogStore((state) => state.append);
  const currentScene = project.scenes[currentIndex] || project.scenes[0];
  const checkedCount = CHECK_KEYS.filter((item) => currentScene?.checks?.[item.key]).length;
  const videoProvider = getVideoProvider(videoProviderId);
  const availableVideoModels = videoProvider.models.filter((item) => item.modes.includes('i2v'));

  useEffect(() => {
    const provider = getVideoProvider(videoProviderId);
    if (videoProviderId !== 'custom') {
      setVideoApiBase(provider.apiBase);
    }
    setVideoModel((current) => {
      if (provider.models.some((item) => item.id === current && item.modes.includes('i2v'))) {
        return current;
      }
      return getDefaultVideoModel(videoProviderId, 'i2v');
    });
  }, [videoProviderId]);

  useEffect(() => {
    (async () => {
      try {
        const resp = await configApi.read(PROJECT_PATH, null);
        if (resp.data && Array.isArray((resp.data as any).scenes)) {
          const loaded = normalizeProject(resp.data);
          setProject(loaded);
          setCurrentIndex(0);
          setCandidates(loaded.scenes[0]?.candidates || []);
        }
      } catch (error) {
        appendLog(`[分镜] 项目加载失败: ${error}\n`);
      }
    })();
  }, [appendLog]);

  useEffect(() => {
    setVideoPreview(null);
    setVideoError('');
    if (!currentScene?.video) return;

    try {
      const preview = createVideoObjectUrl(currentScene.video);
      setVideoPreview({ url: preview.url, size: preview.size });
      return preview.revoke;
    } catch {
      setVideoError('视频已生成，但当前预览数据无法解析。请重新生成该镜头视频。');
    }
  }, [currentScene?.video]);

  const updateScene = (updates: Partial<Scene>) => {
    setProject((prev) => {
      const scenes = [...prev.scenes];
      scenes[currentIndex] = { ...scenes[currentIndex], ...updates };
      return { ...prev, scenes };
    });
  };

  const updateProductView = (key: ViewKey, value: string | null) => {
    setProject((prev) => ({
      ...prev,
      productViews: { ...prev.productViews, [key]: value },
    }));
  };

  const saveProject = async () => {
    try {
      await configApi.write(PROJECT_PATH, project);
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
      showToast('项目已保存', 'success');
    } catch (error: any) {
      showToast('保存失败: ' + (error?.error || error), 'error');
    }
  };

  const handleFileToBase64 = (file: File): Promise<string> =>
    new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = (event) => resolve(event.target?.result as string);
      reader.readAsDataURL(file);
    });

  const handlePickProductView = async (key: ViewKey) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = async (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;
      updateProductView(key, await handleFileToBase64(file));
    };
    input.click();
  };

  const handlePickSceneReference = async () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = async (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;
      updateScene({ referenceImage: await handleFileToBase64(file) });
      showToast('已添加九宫格产品参考图', 'success');
    };
    input.click();
  };

  const handlePickFrame = async (slot: FrameSlot) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = async (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;
      updateScene({ [slot]: await handleFileToBase64(file) });
    };
    input.click();
  };

  const addScene = () => {
    const newScene = defaultScene();
    newScene.title = `镜头 ${project.scenes.length + 1}`;
    setProject((prev) => ({ ...prev, scenes: [...prev.scenes, newScene] }));
    setCurrentIndex(project.scenes.length);
    setCandidates([]);
    setSelectedCandidate(null);
    setCandidateStatus('');
  };

  const duplicateScene = () => {
    if (!currentScene) return;
    const copy: Scene = {
      ...currentScene,
      id: `${Date.now()}`,
      title: `${currentScene.title} 副本`,
      video: null,
      candidates: [],
      checks: { ...currentScene.checks },
      productViews: { ...currentScene.productViews },
    };
    setProject((prev) => {
      const scenes = [...prev.scenes];
      scenes.splice(currentIndex + 1, 0, copy);
      return { ...prev, scenes };
    });
    setCurrentIndex(currentIndex + 1);
    setCandidates([]);
    setSelectedCandidate(null);
    setCandidateStatus('');
  };

  const deleteScene = () => {
    if (project.scenes.length <= 1) {
      showToast('至少保留一个镜头', 'info');
      return;
    }
    if (!confirm('确定删除当前镜头？')) return;
    setProject((prev) => {
      const scenes = [...prev.scenes];
      scenes.splice(currentIndex, 1);
      return { ...prev, scenes };
    });
    const nextIndex = Math.max(0, currentIndex - 1);
    setCurrentIndex(nextIndex);
    setCandidates(project.scenes[nextIndex]?.candidates || []);
    setSelectedCandidate(null);
    setCandidateStatus('');
  };

  const selectScene = (index: number) => {
    setCurrentIndex(index);
    setCandidates(project.scenes[index]?.candidates || []);
    setSelectedCandidate(null);
    setCandidateStatus('');
  };

  const composeReferenceText = () => {
    const scene = currentScene;
    const viewNames = VIEW_KEYS.filter((item) => project.productViews[item.key]).map((item) => item.label);
    if (scene.referenceImage) return '严格参考上传的产品图，保持产品外观、颜色、Logo、结构和比例一致。';
    if (viewNames.length > 0) return `参考产品${viewNames.join('、')}三视图，保持产品外观、比例、Logo 和包装文字一致。`;
    return '保持产品主体稳定一致，避免凭空改变外观。';
  };

  const composeCandidatePrompt = () => {
    const scene = currentScene;
    return [
      composeReferenceText(),
      `广告镜头：${scene.title}`,
      `核心卖点：${scene.sellingPoint}`,
      `关键帧画面：${scene.candidatePrompt || scene.prompt}`,
      `投放规格：${scene.ratio}，商业广告关键帧，主体清晰，构图完整，适合短视频投放。`,
      `避免：${scene.negative}`,
    ].filter(Boolean).join('\n');
  };

  const composeVideoPrompt = () => {
    const scene = currentScene;
    const endingText = scene.lastFrame ? '画面结尾要自然过渡到已设定尾帧的构图和情绪。' : '';

    return [
      composeReferenceText(),
      `广告镜头：${scene.title}`,
      `核心卖点：${scene.sellingPoint}`,
      `运镜方式：${scene.camera}`,
      `画面描述：${scene.prompt}`,
      `投放规格：${scene.ratio}，商业广告关键帧，主体清晰，构图完整，适合短视频投放。`,
      endingText,
      `避免：${scene.negative}`,
    ].filter(Boolean).join('\n');
  };

  const handleGenerateCandidates = async () => {
    const imgConfig = (await configApi.read('imgapi_config.json', {})).data as any;
    const stored = readGatewayStoredConfig(imgConfig);
    let baseUrl = stored.baseUrl;
    let apiKey = stored.apiKey;

    if (!baseUrl || !apiKey || stored.mode === 'member') {
      const memberGateway = await readMemberGatewayDefaults();
      if (memberGateway.hasGateway) {
        baseUrl = memberGateway.baseUrl;
        apiKey = memberGateway.imageApiKey || memberGateway.apiKey;
      }
    }

    if (!baseUrl) {
      showToast('请先在 AI 生图页面配置中转站地址', 'error');
      return;
    }
    if (!currentScene.candidatePrompt.trim()) {
      showToast('请先填写九宫格提示词', 'error');
      return;
    }

    setGeneratingCandidates(true);
    setCandidates([]);
    setSelectedCandidate(null);
    setCandidateStatus('正在生成九宫格...');

    try {
      const referenceImage = pickReferenceImage(project, currentScene);
      const resp = await imageApi.generate({
        baseUrl,
        apiKey,
        prompt: composeCandidatePrompt(),
        size: imageSizeForRatio(currentScene.ratio),
        count: 9,
        editImagePath: referenceImage || undefined,
      });

      const imgs = (resp.images || []).map((b64: string) => `data:image/png;base64,${b64}`);
      setCandidates(imgs);
      updateScene({ candidates: imgs });
      setCandidateStatus(`已生成 ${imgs.length} 张候选图`);
      showToast('九宫格生成完成', 'success');
      appendLog(`[分镜九宫格] 已生成 ${imgs.length} 张候选图\n`);
    } catch (error: any) {
      const message = error?.error || '生成失败';
      setCandidateStatus(`失败：${message}`);
      appendLog(`[分镜九宫格] ${message}\n`);
      showToast(message, 'error');
    } finally {
      setGeneratingCandidates(false);
    }
  };

  const handleAssignCandidate = (slot: FrameSlot) => {
    if (selectedCandidate === null || selectedCandidate >= candidates.length) {
      showToast('请先选择一张候选图', 'info');
      return;
    }
    updateScene({ [slot]: candidates[selectedCandidate] });
    showToast(`已设为${slot === 'firstFrame' ? '首帧' : '尾帧'}`, 'success');
  };

  const handleUseCandidateAsReference = () => {
    if (selectedCandidate === null || selectedCandidate >= candidates.length) {
      showToast('请先选择一张候选图', 'info');
      return;
    }
    updateScene({ referenceImage: candidates[selectedCandidate] });
    showToast('已设为下一轮九宫格参考图', 'success');
  };

  const clearCandidates = () => {
    setCandidates([]);
    setSelectedCandidate(null);
    setCandidateStatus('');
    updateScene({ candidates: [] });
  };

  const handleGenerateVideo = async () => {
    if (!currentScene?.firstFrame) {
      showToast('请先为当前镜头设置首帧', 'error');
      return;
    }

    const memberGateway = await readMemberGatewayDefaults();
    const cleanApiKey = videoApiKey.trim() || memberGateway.videoApiKey || memberGateway.apiKey;
    const cleanApiBase = videoApiBase.trim() || memberGateway.baseUrl;
    const cleanModel = videoModel.trim() || memberGateway.videoModel || memberGateway.defaultModel;
    if (!cleanApiKey) {
      showToast(`请填写 ${videoProvider.authLabel}`, 'error');
      return;
    }
    if (!cleanModel) {
      showToast('请填写或选择视频模型', 'error');
      return;
    }
    if (videoProviderId === 'custom' && !cleanApiBase) {
      showToast('自定义视频服务需要填写 API Base URL', 'error');
      return;
    }

    setGeneratingVideo(true);
    setVideoStatus('正在生成镜头视频...');
    setVideoError('');

    try {
      const resp = await videoApi.generate({
        providerId: videoProviderId,
        apiBase: cleanApiBase,
        model: cleanModel,
        dashKey: cleanApiKey,
        prompt: composeVideoPrompt(),
        mode: 'i2v',
        resolution: '720P',
        duration: parseInt(currentScene.duration || '5', 10),
        ratio: currentScene.ratio || '9:16',
        imagePath: currentScene.firstFrame,
      });

      if (!resp.video) {
        throw { error: '生成成功但没有返回视频数据' };
      }

      updateScene({ video: resp.path || `data:${resp.mime || 'video/mp4'};base64,${resp.video}` });
      setVideoStatus(`视频已生成${resp.size ? `，大小 ${formatBytes(resp.size)}` : ''}${resp.path ? `，保存路径：${resp.path}` : ''}`);
      showToast('视频生成成功', 'success');
      appendLog(`[分镜视频] ${videoProvider.label} / ${cleanModel} 视频生成成功\n`);
    } catch (error: any) {
      const message = error?.error || '生成失败';
      setVideoStatus(`失败：${message}`);
      appendLog(`[分镜视频] ${message}\n`);
      showToast(message, 'error');
    } finally {
      setGeneratingVideo(false);
    }
  };

  if (!currentScene) return null;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-transparent">
      <div className="flex shrink-0 items-center justify-between border-b border-white/10 bg-surface/70 px-8 py-4 backdrop-blur-xl">
        <div>
          <h1 className="text-xl font-bold text-text">AI 广告工作台</h1>
          <p className="mt-1 text-sm text-text-muted">分镜 / 三视图 / 首尾帧 / 九宫格 / 视频生成</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="rounded-full border border-border bg-white/5 px-3 py-1 text-xs text-text-muted">
            质检 {checkedCount}/{CHECK_KEYS.length}
          </span>
          <Button onClick={saveProject} variant="primary">
            {saved ? '已保存' : '保存项目'}
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 gap-4 overflow-hidden p-4">
        <aside className="flex w-56 shrink-0 flex-col rounded-2xl border border-border bg-surface-alt/75">
          <div className="border-b border-white/10 px-4 py-3">
            <div className="text-xs font-bold uppercase tracking-[0.18em] text-text-subtle">Scenes</div>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {project.scenes.map((scene, index) => (
              <button
                key={scene.id}
                onClick={() => selectScene(index)}
                className={`mb-1 w-full rounded-lg border px-3 py-2 text-left text-sm transition-all ${
                  index === currentIndex
                    ? 'border-border-strong bg-accent-soft text-text shadow-[0_0_18px_rgba(157,78,221,0.16)]'
                    : 'border-transparent text-text-muted hover:border-border hover:bg-white/5 hover:text-text'
                }`}
              >
                <div className="truncate font-semibold">{String(index + 1).padStart(2, '0')} {scene.title}</div>
                <div className="mt-0.5 truncate text-xs text-text-subtle">{scene.duration}s · {scene.ratio}</div>
              </button>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-1.5 border-t border-white/10 p-2">
            <Button onClick={addScene} variant="quiet" className="px-2 py-1 text-xs">新增</Button>
            <Button onClick={duplicateScene} variant="quiet" className="px-2 py-1 text-xs">复制</Button>
            <Button onClick={deleteScene} variant="danger" className="px-2 py-1 text-xs">删除</Button>
          </div>
        </aside>

        <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
          <section className="grid gap-4 xl:grid-cols-[minmax(320px,0.9fr)_minmax(360px,1.1fr)]">
            <div className="rounded-2xl border border-border bg-surface-alt/75 p-4">
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <div className="text-xs font-bold uppercase tracking-[0.18em] text-text-subtle">Product Board</div>
                  <div className="mt-1 text-sm font-semibold text-text">产品素材</div>
                </div>
                <Button onClick={handlePickSceneReference} variant="quiet" className="px-3 py-1.5 text-xs">
                  上传产品图
                </Button>
              </div>

              <button
                onClick={handlePickSceneReference}
                className="group mb-3 flex h-44 w-full items-center justify-center overflow-hidden rounded-xl border border-border bg-surface/80 transition-colors hover:border-border-strong"
              >
                {currentScene.referenceImage ? (
                  <img src={currentScene.referenceImage} alt="九宫格参考图" className="h-full w-full object-contain" />
                ) : (
                  <span className="text-sm text-text-muted group-hover:text-text">上传本镜头产品图，用它生成九宫格</span>
                )}
              </button>

              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="font-semibold text-text-subtle">三视图备用参考</span>
                {currentScene.referenceImage && (
                  <button onClick={() => updateScene({ referenceImage: null })} className="text-status-danger hover:underline">
                    清除本镜头参考
                  </button>
                )}
              </div>
              <div className="grid grid-cols-3 gap-2">
                {VIEW_KEYS.map((item) => (
                  <button
                    key={item.key}
                    onClick={() => handlePickProductView(item.key)}
                    className="group aspect-video overflow-hidden rounded-xl border border-border bg-surface/80 transition-colors hover:border-border-strong"
                  >
                    {project.productViews[item.key] ? (
                      <img src={project.productViews[item.key]!} alt={item.label} className="h-full w-full object-contain" />
                    ) : (
                      <span className="flex h-full items-center justify-center text-xs text-text-muted group-hover:text-text">{item.label}</span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              {([
                { slot: 'firstFrame' as const, label: '首帧', desc: '视频起始画面' },
                { slot: 'lastFrame' as const, label: '尾帧', desc: '结尾构图控制' },
              ]).map(({ slot, label, desc }) => (
                <div key={slot} className="rounded-2xl border border-border bg-surface-alt/75 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <div>
                      <div className="text-sm font-semibold text-text">{label}</div>
                      <div className="text-xs text-text-muted">{desc}</div>
                    </div>
                    {currentScene[slot] && <Button onClick={() => updateScene({ [slot]: null })} variant="quiet" className="px-2 py-1 text-xs">清除</Button>}
                  </div>
                  <button
                    onClick={() => handlePickFrame(slot)}
                    className={`flex w-full items-center justify-center overflow-hidden rounded-xl border border-border bg-surface/80 transition-colors hover:border-border-strong ${imageAspectClass(currentScene.ratio)}`}
                  >
                    {currentScene[slot] ? (
                      <img src={currentScene[slot]!} alt={label} className="h-full w-full object-contain" />
                    ) : (
                      <span className="text-sm text-text-muted">上传或从九宫格指定</span>
                    )}
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section className="grid gap-4 rounded-2xl border border-border bg-surface-alt/75 p-4 xl:grid-cols-[minmax(300px,0.8fr)_minmax(420px,1.2fr)]">
            <div className="min-w-0">
              <div className="mb-3">
                <div className="text-sm font-semibold text-text">九宫格创作</div>
                <div className="mt-1 text-xs text-text-muted">当前参考源：{currentScene.referenceImage ? '本镜头产品图' : pickReferenceImage(project, currentScene) ? '三视图 / 首尾帧' : '仅提示词'}</div>
              </div>
              <FieldLabel text="九宫格提示词" required />
              <TextArea
                value={currentScene.candidatePrompt}
                onChange={(event) => updateScene({ candidatePrompt: event.target.value })}
                rows={8}
                placeholder="写清楚画面、主体、光线、背景、卖点和投放平台风格..."
                className="min-h-[180px]"
              />
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Button onClick={handleGenerateCandidates} variant="primary" disabled={generatingCandidates}>
                  {generatingCandidates ? '生成中...' : '生成九宫格'}
                </Button>
                <Button onClick={clearCandidates} variant="quiet" disabled={generatingCandidates || candidates.length === 0}>
                  清空候选
                </Button>
                <Button onClick={() => handleAssignCandidate('firstFrame')} variant="quiet" disabled={selectedCandidate === null}>
                  设为首帧
                </Button>
                <Button onClick={() => handleAssignCandidate('lastFrame')} variant="quiet" disabled={selectedCandidate === null}>
                  设为尾帧
                </Button>
                <Button onClick={handleUseCandidateAsReference} variant="quiet" disabled={selectedCandidate === null} className="col-span-2">
                  作为下一轮参考图
                </Button>
              </div>
              {candidateStatus && (
                <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
                  candidateStatus.includes('失败')
                    ? 'border-status-danger/30 bg-status-danger/10 text-status-danger'
                    : 'border-border bg-surface/70 text-text-muted'
                }`}>
                  {candidateStatus}
                </div>
              )}
              {selectedCandidate !== null && candidates[selectedCandidate] && (
                <div className="mt-3 overflow-hidden rounded-xl border border-border bg-surface/80">
                  <img src={candidates[selectedCandidate]} alt="当前选中的候选图" className="max-h-72 w-full object-contain" />
                </div>
              )}
            </div>

            <div className="min-w-0">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-xs font-bold uppercase tracking-[0.18em] text-text-subtle">Nine Frames</div>
                <span className="text-xs text-text-muted">{candidates.length}/9</span>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {Array.from({ length: 9 }).map((_, index) => (
                  <button
                    key={index}
                    onClick={() => index < candidates.length && setSelectedCandidate(index)}
                    className={`overflow-hidden rounded-xl border bg-surface/80 transition-all ${imageAspectClass(currentScene.ratio)} ${
                      index === selectedCandidate ? 'border-accent ring-2 ring-accent/35' : 'border-border hover:border-border-strong'
                    }`}
                  >
                    {index < candidates.length ? (
                      <img src={candidates[index]} alt={`候选图 ${index + 1}`} className="h-full w-full object-cover" />
                    ) : generatingCandidates ? (
                      <Loading text="" />
                    ) : (
                      <span className="flex h-full items-center justify-center text-lg text-text-subtle">{index + 1}</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          </section>
        </main>

        <aside className="flex w-80 shrink-0 flex-col overflow-y-auto rounded-2xl border border-border bg-surface-alt/75 p-4">
          <div className="mb-3 text-xs font-bold uppercase tracking-[0.18em] text-text-subtle">Scene Settings</div>
          <div className="space-y-3">
            <div>
              <FieldLabel text="镜头标题" />
              <Input value={currentScene.title} onChange={(event) => updateScene({ title: event.target.value })} />
            </div>
            <div>
              <FieldLabel text="核心卖点" />
              <Input value={currentScene.sellingPoint} onChange={(event) => updateScene({ sellingPoint: event.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <FieldLabel text="时长" />
                <Select value={currentScene.duration} onChange={(event) => updateScene({ duration: event.target.value })} className="w-full">
                  {DURATION_OPTIONS.map((item) => <option key={item} value={item}>{item}s</option>)}
                </Select>
              </div>
              <div>
                <FieldLabel text="比例" />
                <Select value={currentScene.ratio} onChange={(event) => updateScene({ ratio: event.target.value })} className="w-full">
                  {RATIO_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                </Select>
              </div>
            </div>
            <div>
              <FieldLabel text="运镜" />
              <Select value={currentScene.camera} onChange={(event) => updateScene({ camera: event.target.value })} className="w-full">
                {CAMERA_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
              </Select>
            </div>
            <div>
              <FieldLabel text="视频提示词" />
              <TextArea value={currentScene.prompt} onChange={(event) => updateScene({ prompt: event.target.value })} rows={5} />
            </div>
            <div>
              <FieldLabel text="负面词" />
              <TextArea value={currentScene.negative} onChange={(event) => updateScene({ negative: event.target.value })} rows={3} />
            </div>

            <div className="border-t border-white/10 pt-3">
              <div className="mb-2 text-xs font-semibold text-text-subtle">质量检查</div>
              <div className="space-y-1.5">
                {CHECK_KEYS.map((item) => (
                  <label key={item.key} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1 text-xs text-text-muted hover:bg-white/5">
                    <input
                      type="checkbox"
                      checked={Boolean(currentScene.checks[item.key])}
                      onChange={(event) => updateScene({ checks: { ...currentScene.checks, [item.key]: event.target.checked } })}
                      className="h-4 w-4 accent-accent"
                    />
                    {item.label}
                  </label>
                ))}
              </div>
            </div>

            <div className="border-t border-white/10 pt-3">
              <div className="mb-3">
                <FieldLabel text="视频服务商" required />
                <Select
                  value={videoProviderId}
                  onChange={(event) => setVideoProviderId(event.target.value as VideoProviderId)}
                  className="w-full"
                >
                  {VIDEO_PROVIDERS.map((provider) => (
                    <option key={provider.id} value={provider.id}>{provider.label}</option>
                  ))}
                </Select>
                <p className="mt-1 text-xs text-text-subtle">{videoProvider.description}</p>
              </div>
              <div className="mb-3">
                <FieldLabel text={videoProvider.authLabel} required />
                <Input
                  type="password"
                  value={videoApiKey}
                  onChange={(event) => setVideoApiKey(event.target.value)}
                  placeholder="仅本次使用，不会保存"
                  autoComplete="off"
                />
              </div>
              <div className="mb-3">
                <FieldLabel text="API Base URL" required={videoProviderId === 'custom'} />
                <Input
                  value={videoApiBase}
                  onChange={(event) => setVideoApiBase(event.target.value)}
                  placeholder="例如 https://ark.cn-beijing.volces.com"
                />
              </div>
              <div className="mb-3">
                <FieldLabel text="视频模型" required />
                <Select
                  value={availableVideoModels.some((item) => item.id === videoModel) ? videoModel : ''}
                  onChange={(event) => setVideoModel(event.target.value)}
                  className="mb-2 w-full"
                  disabled={availableVideoModels.length === 0}
                >
                  <option value="">{availableVideoModels.length > 0 ? '选择预设模型' : '暂无预设模型'}</option>
                  {availableVideoModels.map((item) => (
                    <option key={item.id} value={item.id}>{item.label}</option>
                  ))}
                </Select>
                <Input
                  value={videoModel}
                  onChange={(event) => setVideoModel(event.target.value)}
                  placeholder="也可以手动输入模型 ID"
                />
              </div>
              <div className="mb-2 flex gap-2">
                <Button onClick={saveProject} variant="quiet" className="flex-1 px-2 py-1.5 text-xs">保存镜头</Button>
                <Button onClick={handleGenerateVideo} variant="primary" disabled={generatingVideo} className="flex-1 px-2 py-1.5 text-xs">
                  {generatingVideo ? '生成中...' : '生成视频'}
                </Button>
              </div>
              {videoStatus && (
                <p className={`mb-2 text-xs ${videoStatus.includes('失败') ? 'text-status-danger' : 'text-text-muted'}`}>{videoStatus}</p>
              )}
              {generatingVideo && <Loading text="正在生成视频..." />}
              {videoPreview && !generatingVideo && (
                <div className="space-y-2">
                  <video
                    src={videoPreview.url}
                    controls
                    preload="metadata"
                    className="w-full rounded-xl border border-border bg-black"
                    onError={() => setVideoError('视频已生成，但当前播放器无法解码。请重新生成或检查返回的视频格式。')}
                  />
                  {videoPreview.size > 0 && <div className="text-xs text-text-muted">{formatBytes(videoPreview.size)}</div>}
                  {videoError && <div className="rounded-lg border border-status-danger/30 bg-status-danger/10 px-3 py-2 text-xs text-status-danger">{videoError}</div>}
                </div>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
};
