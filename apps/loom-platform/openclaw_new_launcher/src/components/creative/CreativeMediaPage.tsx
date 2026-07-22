import React from 'react';
import { convertFileSrc } from '@tauri-apps/api/core';
import { Button, FieldLabel, Input, Loading, Select, TextArea, showConfirm, showToast } from '../common';
import {
  imageApi,
  jobApi,
  mediaApi,
  parseErrorText,
  phoneApi,
  videoApi,
  waitForJob,
  type BridgeJob,
  type MediaAsset,
  type MediaConfigSnapshot,
  type MediaPhoneTransferResult,
  type PhoneDeviceSummary,
} from '../../services/api';
import type { VideoProviderId } from '../../types';
import { MediaLibraryPanel } from './MediaLibraryPanel';
import { ReferenceImagePicker } from './ReferenceImagePicker';
import {
  IMAGE_RATIO_PRESETS,
  cssAspectRatio,
  type ImageMode,
  type ReferenceImage,
  type VideoMode,
} from './mediaPresets';

const StoryboardWorkbench = React.lazy(() => import('../storyboard/StoryboardWorkbench').then((m) => ({ default: m.StoryboardWorkbench })));

type CreativeTab = 'image' | 'video' | 'storyboard';
const DEFAULT_IMAGE_MODEL = 'gpt-image-2';

type PhoneTransferState = Partial<MediaPhoneTransferResult>;

type ImageResult = {
  images?: string[];
  files?: Array<{ path?: string; directory?: string; filename?: string; size?: number; mime?: string }>;
  count?: number;
  ratio?: string;
  size?: string;
  phoneTransfer?: PhoneTransferState;
};

type VideoResult = {
  video?: string;
  mime?: string;
  path?: string;
  directory?: string;
  filename?: string;
  size?: number;
  phoneTransfer?: PhoneTransferState;
  success?: boolean;
  manualRequired?: boolean;
  message?: string;
  question?: string;
  requestKey?: string;
  threadId?: string;
  runId?: string;
  webThreadLink?: string;
};

let rememberedCreativeJobs: Partial<Record<CreativeTab, string>> = {};

function localAssetUrl(path: string): string {
  try {
    return convertFileSrc(path);
  } catch {
    return path;
  }
}

function GenerationPreview({
  kind,
  src,
  alt,
  ratio,
}: {
  kind: 'image' | 'video';
  src: string;
  alt: string;
  ratio: string;
}) {
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [src]);

  return (
    <div className="w-full bg-surface" style={{ aspectRatio: cssAspectRatio(ratio) }}>
      {failed ? (
        <div data-media-preview-error className="flex h-full min-h-40 items-center justify-center px-6 text-center text-sm text-text-muted">
          预览加载失败，文件仍保存在本地
        </div>
      ) : kind === 'image' ? (
        <img src={src} alt={alt} className="h-full w-full object-contain" onError={() => setFailed(true)} />
      ) : (
        <video
          src={src}
          aria-label={alt}
          controls
          preload="metadata"
          className="h-full w-full bg-black object-contain"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}

function jobDone(job: BridgeJob | null): boolean {
  return Boolean(job && ['succeeded', 'success', 'completed', 'complete'].includes(String(job.status || '').toLowerCase()));
}

function jobFailed(job: BridgeJob | null): boolean {
  return Boolean(job && ['failed', 'error', 'cancelled', 'canceled'].includes(String(job.status || '').toLowerCase()));
}

function jobNeedsManual(job: BridgeJob | null): boolean {
  return Boolean(job && String(job.status || '').toLowerCase() === 'needs_manual');
}

function createVideoRequestKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `video_${crypto.randomUUID()}`;
  }
  return `video_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function friendlyError(error: unknown, fallback: string): string {
  return parseErrorText(error) || fallback;
}

function imagePayload(state: {
  imageBaseUrl: string;
  imageApiKey: string;
  imageModel: string;
  imageSize: string;
  imageCount: number;
}) {
  return {
    baseUrl: state.imageBaseUrl.trim(),
    apiKey: state.imageApiKey.trim(),
    model: state.imageModel.trim(),
    size: state.imageSize,
    count: state.imageCount,
  };
}

function videoPayload(state: {
  videoProvider: VideoProviderId;
  videoBaseUrl: string;
  videoApiKey: string;
  videoModel: string;
  videoResolution: string;
  videoDuration: number;
  videoRatio: string;
  videoMode: VideoMode;
}) {
  return {
    providerId: state.videoProvider,
    apiBase: state.videoBaseUrl.trim(),
    apiKey: state.videoApiKey.trim(),
    dashKey: state.videoApiKey.trim(),
    model: state.videoModel.trim(),
    mode: state.videoMode,
    resolution: state.videoResolution,
    duration: state.videoDuration,
    ratio: state.videoRatio,
  };
}

export const CreativeMediaPage: React.FC = () => {
  const [tab, setTab] = React.useState<CreativeTab>('image');
  const [config, setConfig] = React.useState<MediaConfigSnapshot | null>(null);
  const [loadingConfig, setLoadingConfig] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [testing, setTesting] = React.useState(false);
  const [activeJobs, setActiveJobs] = React.useState<Record<CreativeTab, BridgeJob | null>>({ image: null, video: null, storyboard: null });
  const [imageResult, setImageResult] = React.useState<ImageResult | null>(null);
  const [videoResult, setVideoResult] = React.useState<VideoResult | null>(null);
  const [assets, setAssets] = React.useState<MediaAsset[]>([]);
  const [assetKind, setAssetKind] = React.useState<'all' | 'image' | 'video'>('all');
  const [assetsHasMore, setAssetsHasMore] = React.useState(false);
  const [assetsLoading, setAssetsLoading] = React.useState(false);
  const [assetsError, setAssetsError] = React.useState('');
  const [phoneDevices, setPhoneDevices] = React.useState<PhoneDeviceSummary[]>([]);
  const [transferringAssetId, setTransferringAssetId] = React.useState('');
  const [assetTransferResults, setAssetTransferResults] = React.useState<Record<string, MediaPhoneTransferResult>>({});
  const pollRefs = React.useRef<Record<CreativeTab, number | null>>({ image: null, video: null, storyboard: null });
  const assetsCursorRef = React.useRef('');

  const [imageBaseUrl, setImageBaseUrl] = React.useState('https://api.heang.top/v1');
  const [imageApiKey, setImageApiKey] = React.useState('');
  const [imageModel, setImageModel] = React.useState(DEFAULT_IMAGE_MODEL);
  const [imageRatio, setImageRatio] = React.useState<(typeof IMAGE_RATIO_PRESETS)[number]['ratio']>('1:1');
  const [imageMode, setImageMode] = React.useState<ImageMode>('t2i');
  const [imageReference, setImageReference] = React.useState<ReferenceImage | null>(null);
  const [imageCount, setImageCount] = React.useState(1);
  const [imagePrompt, setImagePrompt] = React.useState('商务产品海报，米白深绿，界面清晰。');

  const [videoProvider, setVideoProvider] = React.useState<VideoProviderId>('dashscope');
  const [videoBaseUrl, setVideoBaseUrl] = React.useState('');
  const [videoApiKey, setVideoApiKey] = React.useState('');
  const [videoModel, setVideoModel] = React.useState('');
  const [videoResolution, setVideoResolution] = React.useState('720P');
  const [videoDuration, setVideoDuration] = React.useState(5);
  const [videoRatio, setVideoRatio] = React.useState('16:9');
  const [videoMode, setVideoMode] = React.useState<VideoMode>('t2v');
  const [videoReference, setVideoReference] = React.useState<ReferenceImage | null>(null);
  const [videoPrompt, setVideoPrompt] = React.useState('商务科技短片，多设备协同工作。');
  const [videoRequestKey, setVideoRequestKey] = React.useState('');
  const [videoManualReply, setVideoManualReply] = React.useState('');

  const activeJob = activeJobs[tab];
  const imageRunning = Boolean(activeJobs.image && !jobDone(activeJobs.image) && !jobFailed(activeJobs.image));
  const videoRunning = Boolean(activeJobs.video && !jobDone(activeJobs.video) && !jobFailed(activeJobs.video) && !jobNeedsManual(activeJobs.video));
  const videoManualResult = (activeJobs.video?.result || videoResult || null) as VideoResult | null;
  const videoNeedsManual = jobNeedsManual(activeJobs.video);
  const generationRunning = tab === 'image' ? imageRunning : videoRunning;
  const activeMessage = String(activeJob?.progress?.message || activeJob?.message || '生成中');
  const selectedImagePreset = IMAGE_RATIO_PRESETS.find((preset) => preset.ratio === imageRatio) || IMAGE_RATIO_PRESETS[0];
  const imagePreviewSources = React.useMemo(() => {
    if (imageResult?.images?.length) {
      return imageResult.images.map((image, index) => ({
        src: `data:${imageResult.files?.[index]?.mime || 'image/png'};base64,${image}`,
        file: imageResult.files?.[index],
      }));
    }
    return (imageResult?.files || [])
      .filter((file) => Boolean(file.path))
      .map((file) => ({ src: localAssetUrl(String(file.path)), file }));
  }, [imageResult]);
  const videoPreviewSource = videoResult?.video
    ? `data:${videoResult.mime || 'video/mp4'};base64,${videoResult.video}`
    : videoResult?.path
      ? localAssetUrl(videoResult.path)
      : '';
  const activePhoneTransfer = tab === 'image' ? imageResult?.phoneTransfer : videoResult?.phoneTransfer;
  const phoneTransferTone = activePhoneTransfer?.status === 'succeeded'
    ? 'border-status-success/25 bg-status-success/8 text-status-success'
    : activePhoneTransfer?.status === 'failed'
      ? 'border-status-danger/25 bg-status-danger/8 text-status-danger'
      : 'border-border bg-surface-alt/45 text-text-muted';

  const assetReference = React.useCallback((asset: MediaAsset): ReferenceImage => ({
    requestValue: asset.path,
    previewUrl: localAssetUrl(asset.path),
    label: asset.filename,
    source: 'library',
  }), []);

  const latestImageReference = React.useMemo(() => {
    const latest = assets.find((asset) => asset.kind === 'image');
    return latest ? assetReference(latest) : null;
  }, [assetReference, assets]);

  const setKindJob = React.useCallback((kind: CreativeTab, job: BridgeJob | null) => {
    setActiveJobs((current) => ({ ...current, [kind]: job }));
  }, []);

  const applyConfig = React.useCallback((snapshot: MediaConfigSnapshot | null) => {
    if (!snapshot) return;
    setConfig(snapshot);
    if (snapshot.image?.baseUrl) setImageBaseUrl(snapshot.image.baseUrl);
    setImageModel(snapshot.image?.model || DEFAULT_IMAGE_MODEL);
    if (snapshot.image?.size) {
      const preset = IMAGE_RATIO_PRESETS.find((item) => item.size === snapshot.image.size);
      if (preset) setImageRatio(preset.ratio);
    }
    if (snapshot.image?.count) setImageCount(snapshot.image.count);
    if (snapshot.video?.model?.toLowerCase().includes('agnes-video')) {
      setVideoProvider('agnes');
    } else if (snapshot.video?.providerId && ['dashscope', 'agnes', 'seedance', 'pippit', 'custom'].includes(String(snapshot.video.providerId))) {
      setVideoProvider(String(snapshot.video.providerId) as VideoProviderId);
    }
    if (snapshot.video?.apiBase) setVideoBaseUrl(snapshot.video.apiBase);
    if (snapshot.video?.model) setVideoModel(snapshot.video.model);
    if (snapshot.video?.resolution) setVideoResolution(snapshot.video.resolution);
    if (snapshot.video?.duration) setVideoDuration(snapshot.video.duration);
    if (snapshot.video?.ratio) setVideoRatio(snapshot.video.ratio);
  }, []);

  const refreshConfig = React.useCallback(async () => {
    setLoadingConfig(true);
    try {
      const response = await mediaApi.config();
      applyConfig(response.config);
    } catch (error) {
      showToast(friendlyError(error, '读取创作配置失败'), 'error');
    } finally {
      setLoadingConfig(false);
    }
  }, [applyConfig]);

  const refreshAssets = React.useCallback(async (append = false) => {
    setAssetsLoading(true);
    setAssetsError('');
    try {
      const response = await mediaApi.assets(assetKind === 'all' ? undefined : assetKind, append ? assetsCursorRef.current : '', 20);
      setAssets((current) => append ? [...current, ...response.items.filter((item) => !current.some((existing) => existing.id === item.id))] : response.items);
      assetsCursorRef.current = response.nextCursor || '';
      setAssetsHasMore(Boolean(response.hasMore));
    } catch (error) {
      setAssetsError(friendlyError(error, '读取本地素材失败'));
    } finally {
      setAssetsLoading(false);
    }
  }, [assetKind]);

  const refreshPhoneDevices = React.useCallback(async () => {
    try {
      const snapshot = await phoneApi.config();
      setPhoneDevices(snapshot.devices || []);
    } catch {
      setPhoneDevices([]);
    }
  }, []);

  const stopPolling = React.useCallback((kind?: CreativeTab) => {
    const kinds: CreativeTab[] = kind ? [kind] : ['image', 'video'];
    kinds.forEach((item) => {
      if (pollRefs.current[item] !== null) {
        window.clearInterval(pollRefs.current[item] as number);
        pollRefs.current[item] = null;
      }
    });
  }, []);

  const applyFinishedJob = React.useCallback((job: BridgeJob, kind: CreativeTab) => {
    if (kind === 'image') {
      setImageResult((job.result || null) as ImageResult | null);
    } else {
      setVideoResult((job.result || null) as VideoResult | null);
    }
    delete rememberedCreativeJobs[kind];
  }, []);

  const pollJob = React.useCallback((jobId: string, kind: CreativeTab) => {
    stopPolling(kind);
    const tick = async () => {
      try {
        const { job } = await jobApi.get(jobId);
        setKindJob(kind, job);
        if (jobDone(job)) {
          stopPolling(kind);
          applyFinishedJob(job, kind);
          void refreshAssets(false);
          showToast(kind === 'image' ? '图片生成完成' : '视频生成完成', 'success');
        } else if (jobNeedsManual(job)) {
          stopPolling(kind);
          const result = (job.result || null) as VideoResult | null;
          if (kind === 'video') {
            setVideoResult(result);
            setVideoRequestKey(result?.requestKey || '');
            setVideoManualReply('');
          }
          // Keep the terminal job id so leaving and returning to the page restores
          // the manual continuation instead of silently losing the paid run.
          rememberedCreativeJobs[kind] = jobId;
          showToast(result?.question || '小云雀需要补充信息后继续', 'info');
        } else if (jobFailed(job)) {
          stopPolling(kind);
          delete rememberedCreativeJobs[kind];
          showToast(job.error || job.message || '生成失败', 'error');
        }
      } catch (error) {
        stopPolling(kind);
        showToast(friendlyError(error, '读取生成状态失败'), 'error');
      }
    };
    void tick();
    pollRefs.current[kind] = window.setInterval(tick, 1300);
  }, [applyFinishedJob, refreshAssets, setKindJob, stopPolling]);

  React.useEffect(() => {
    void refreshConfig();
    void refreshAssets(false);
    void refreshPhoneDevices();
    (Object.entries(rememberedCreativeJobs) as Array<[CreativeTab, string]>).forEach(([kind, id]) => {
      if (id) pollJob(id, kind);
    });
    return () => stopPolling();
  }, [pollJob, refreshAssets, refreshConfig, refreshPhoneDevices, stopPolling]);

  const saveConfig = async () => {
    setSaving(true);
    try {
      const response = await mediaApi.saveConfig({
        image: imagePayload({ imageBaseUrl, imageApiKey, imageModel, imageSize: selectedImagePreset.size, imageCount }),
        video: videoPayload({ videoProvider, videoBaseUrl, videoApiKey, videoModel, videoResolution, videoDuration, videoRatio, videoMode }),
      });
      applyConfig(response.config);
      setImageApiKey('');
      setVideoApiKey('');
      showToast('创作配置已保存', 'success');
    } catch (error) {
      showToast(friendlyError(error, '保存创作配置失败'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const testConfig = async () => {
    setTesting(true);
    try {
      const response = await mediaApi.testConfig({
        kind: tab === 'image' ? 'image' : 'video',
        image: imagePayload({ imageBaseUrl, imageApiKey, imageModel, imageSize: selectedImagePreset.size, imageCount }),
        video: videoPayload({ videoProvider, videoBaseUrl, videoApiKey, videoModel, videoResolution, videoDuration, videoRatio, videoMode }),
      });
      if (response.config) applyConfig(response.config);
      showToast(response.message || (response.ok ? '配置可用' : '配置未完整'), response.ok ? 'success' : 'error');
    } catch (error) {
      showToast(friendlyError(error, '测试配置失败'), 'error');
    } finally {
      setTesting(false);
    }
  };

  const submitImage = async () => {
    if (!imagePrompt.trim()) {
      showToast('请先填写图片提示词', 'error');
      return;
    }
    if (imageMode === 'i2i' && !imageReference) {
      showToast('图生图需要先选择参考图', 'error');
      return;
    }
    const optimistic: BridgeJob = {
      id: `pending_image_${Date.now()}`,
      kind: 'image',
      label: '图片生成',
      status: 'queued',
      message: '生成中',
      progress: { message: '正在提交图片生成任务', phase: 'submitting' },
    };
    setTab('image');
    setKindJob('image', optimistic);
    setImageResult(null);
    try {
      const params = imagePayload({ imageBaseUrl, imageApiKey, imageModel, imageSize: selectedImagePreset.size, imageCount });
      await mediaApi.saveConfig({ image: params });
      const { jobId, job } = await imageApi.submit({
        ...params,
        prompt: imagePrompt.trim(),
        ratio: selectedImagePreset.ratio,
        source: 'ui',
        ...(imageMode === 'i2i' ? { editImagePath: imageReference?.requestValue } : {}),
      });
      rememberedCreativeJobs.image = jobId;
      setKindJob('image', job);
      pollJob(jobId, 'image');
    } catch (error) {
      delete rememberedCreativeJobs.image;
      setKindJob('image', { ...optimistic, status: 'failed', error: friendlyError(error, '图片生成提交失败') });
      showToast(friendlyError(error, '图片生成提交失败'), 'error');
    }
  };

  const submitVideo = async () => {
    if (!videoPrompt.trim()) {
      showToast('请先填写视频提示词', 'error');
      return;
    }
    if (videoMode === 'i2v' && !videoReference) {
      showToast('图生视频需要先选择参考图', 'error');
      return;
    }
    const optimistic: BridgeJob = {
      id: `pending_video_${Date.now()}`,
      kind: 'video',
      label: '视频生成',
      status: 'queued',
      message: '生成中',
      progress: { message: '正在提交视频生成任务', phase: 'submitting' },
    };
    setTab('video');
    setKindJob('video', optimistic);
    setVideoResult(null);
    setVideoManualReply('');
    try {
      const params = videoPayload({ videoProvider, videoBaseUrl, videoApiKey, videoModel, videoResolution, videoDuration, videoRatio, videoMode });
      const requestKey = videoProvider === 'pippit' ? createVideoRequestKey() : '';
      setVideoRequestKey(requestKey);
      await mediaApi.saveConfig({ video: params });
      const { jobId, job } = await videoApi.submit({
        ...params,
        prompt: videoPrompt.trim(),
        source: 'ui',
        ...(requestKey ? { requestKey } : {}),
        ...(videoMode === 'i2v' ? { imagePath: videoReference?.requestValue } : {}),
      });
      rememberedCreativeJobs.video = jobId;
      setKindJob('video', job);
      pollJob(jobId, 'video');
    } catch (error) {
      delete rememberedCreativeJobs.video;
      setKindJob('video', { ...optimistic, status: 'failed', error: friendlyError(error, '视频生成提交失败') });
      showToast(friendlyError(error, '视频生成提交失败'), 'error');
    }
  };

  const continuePippitVideo = async () => {
    const requestKey = videoManualResult?.requestKey || videoRequestKey;
    const reply = videoManualReply.trim();
    if (!requestKey || !reply) {
      showToast('请先填写给小云雀的补充信息', 'error');
      return;
    }
    const optimistic: BridgeJob = {
      id: `pending_video_continue_${Date.now()}`,
      kind: 'video',
      label: '继续小云雀视频生成',
      status: 'queued',
      message: '正在继续原任务',
      progress: { message: '正在用原小云雀会话继续生成', phase: 'submitting' },
    };
    setKindJob('video', optimistic);
    try {
      const params = videoPayload({ videoProvider, videoBaseUrl, videoApiKey, videoModel, videoResolution, videoDuration, videoRatio, videoMode });
      const { jobId, job } = await videoApi.submit({
        ...params,
        prompt: videoPrompt.trim(),
        source: 'ui',
        requestKey,
        continuationMessage: reply,
      });
      rememberedCreativeJobs.video = jobId;
      setKindJob('video', job);
      pollJob(jobId, 'video');
    } catch (error) {
      setKindJob('video', { ...optimistic, status: 'failed', error: friendlyError(error, '继续小云雀任务失败') });
      showToast(friendlyError(error, '继续小云雀任务失败'), 'error');
    }
  };

  const copyPath = async (path?: string) => {
    if (!path) return;
    try {
      await navigator.clipboard.writeText(path);
      showToast('路径已复制', 'success');
    } catch {
      showToast(path, 'info');
    }
  };

  const useAssetForImage = (asset: MediaAsset) => {
    setImageReference(assetReference(asset));
    setImageMode('i2i');
    setTab('image');
    showToast('已设为图生图参考图', 'success');
  };

  const useAssetForVideo = (asset: MediaAsset) => {
    setVideoReference(assetReference(asset));
    setVideoMode('i2v');
    setTab('video');
    showToast('已设为图生视频参考图', 'success');
  };

  const revealAsset = async (asset: MediaAsset) => {
    try {
      await mediaApi.reveal(asset.id);
    } catch (error) {
      showToast(friendlyError(error, '打开素材位置失败'), 'error');
    }
  };

  const transferAsset = async (asset: MediaAsset, deviceIds: string[]) => {
    if (!deviceIds.length || transferringAssetId) return;
    setTransferringAssetId(asset.id);
    setAssetTransferResults((current) => {
      const next = { ...current };
      delete next[asset.id];
      return next;
    });
    try {
      const submitted = await mediaApi.transferAsset(asset.id, deviceIds);
      const job = await waitForJob<MediaPhoneTransferResult>(submitted.jobId, {
        timeoutMs: 30 * 60 * 1000,
        intervalMs: 1000,
      });
      const result = job.result || {
        status: 'failed',
        message: '传输任务未返回结果',
      };
      setAssetTransferResults((current) => ({ ...current, [asset.id]: result }));
      showToast(result.message || '手机相册传输已完成', result.status === 'succeeded' ? 'success' : 'error');
    } catch (error) {
      const message = friendlyError(error, '传输到手机失败');
      setAssetTransferResults((current) => ({
        ...current,
        [asset.id]: { status: 'failed', message },
      }));
      showToast(message, 'error');
    } finally {
      setTransferringAssetId('');
    }
  };

  const deleteAsset = async (asset: MediaAsset) => {
    const confirmed = await showConfirm({
      title: '删除本地素材',
      message: `确定删除“${asset.filename}”吗？此操作会删除本地文件。`,
      confirmText: '删除',
      tone: 'danger',
    });
    if (!confirmed) return;
    try {
      await mediaApi.deleteAsset(asset.id);
      if (imageReference?.requestValue === asset.path) setImageReference(null);
      if (videoReference?.requestValue === asset.path) setVideoReference(null);
      await refreshAssets(false);
      showToast('素材已删除', 'success');
    } catch (error) {
      showToast(friendlyError(error, '删除素材失败'), 'error');
    }
  };

  return (
    <div data-creative-media-page className="flex h-full flex-col overflow-hidden bg-surface">
      <header className="shrink-0 border-b border-border px-8 py-7">
        <div className="text-sm font-black text-accent">创作</div>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[30px] font-black leading-tight text-text">生图 / 生视频</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-text-muted">接入自己的模型服务，提交生成任务，并持续查看进度与结果。</p>
          </div>
          <div className="flex rounded-[8px] border border-border bg-surface-alt/60 p-1">
            <button
              data-creative-tab-image
              type="button"
              onClick={() => setTab('image')}
              className={`rounded-[6px] px-5 py-2 text-sm font-black transition-colors duration-150 ${tab === 'image' ? 'bg-accent text-accent-ink' : 'text-text-muted hover:text-text'}`}
            >
              生图
            </button>
            <button
              data-creative-tab-video
              type="button"
              onClick={() => setTab('video')}
              className={`rounded-[6px] px-5 py-2 text-sm font-black transition-colors duration-150 ${tab === 'video' ? 'bg-accent text-accent-ink' : 'text-text-muted hover:text-text'}`}
            >
              生视频
            </button>
            <button
              data-creative-tab-storyboard
              type="button"
              onClick={() => setTab('storyboard')}
              className={`rounded-[10px] px-5 py-2 text-sm font-black transition ${tab === 'storyboard' ? 'bg-accent text-accent-ink shadow-[0_12px_28px_rgba(8,60,49,0.18)]' : 'text-text-muted hover:text-text'}`}
            >
              全案九步
            </button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-6 py-6 xl:px-8">
        {tab === 'storyboard' ? (
          <React.Suspense fallback={<Loading />}>
            <StoryboardWorkbench />
          </React.Suspense>
        ) : (
          <>
        <div className="mx-auto grid w-full max-w-[1320px] gap-5">
          <section className="border-y border-border/70 py-4">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-black text-text">自定义 API</h2>
                <p className="mt-1 text-xs leading-5 text-text-muted">
                  {loadingConfig ? '正在读取配置...' : 'API Key 只写入本地配置，页面不会回显。'}
                </p>
              </div>
              <span className="rounded-full border border-border bg-surface px-3 py-1 text-xs font-black text-text-muted">
                {tab === 'image' ? (config?.image?.hasApiKey ? '生图已配置' : '生图未配置') : (config?.video?.hasApiKey ? '视频已配置' : '视频未配置')}
              </span>
            </div>

            <details data-creative-config-details className="border-t border-border/60 pt-3">
              <summary className="cursor-pointer select-none text-sm font-black text-text">
                展开配置
              </summary>

            {tab === 'image' ? (
              <div className="mt-4 grid gap-3">
                <label>
                  <FieldLabel text="Base URL" />
                  <Input value={imageBaseUrl} onChange={(event) => setImageBaseUrl(event.target.value)} placeholder="https://api.heang.top/v1" />
                </label>
                <label>
                  <FieldLabel text="API Key" />
                  <Input type="password" value={imageApiKey} onChange={(event) => setImageApiKey(event.target.value)} placeholder={config?.image?.hasApiKey ? '已保存，留空继续使用' : 'sk-...'} autoComplete="off" />
                </label>
                <label>
                  <FieldLabel text="模型" />
                  <Input value={imageModel} onChange={(event) => setImageModel(event.target.value)} placeholder="gpt-image-2" />
                </label>
                <label>
                  <FieldLabel text="数量" />
                  <Input type="number" min={1} max={9} value={imageCount} onChange={(event) => setImageCount(Number(event.target.value || 1))} />
                </label>
              </div>
            ) : (
              <div className="mt-4 grid gap-3">
                <label>
                  <FieldLabel text="Provider" />
                  <Select
                    value={videoProvider}
                    onChange={(event) => {
                      const provider = event.target.value as VideoProviderId;
                      setVideoProvider(provider);
                      if (provider === 'pippit') {
                        setVideoBaseUrl('https://xyq.jianying.com');
                        setVideoModel('pippit-video');
                      }
                    }}
                    className="w-full"
                  >
                    <option value="dashscope">DashScope</option>
                    <option value="agnes">Agnes / OpenAI 视频</option>
                    <option value="seedance">Seedance</option>
                    <option value="pippit">小云雀 / Pippit</option>
                    <option value="custom">自定义 OpenAI 兼容</option>
                  </Select>
                </label>
                <label>
                  <FieldLabel text="API Base" />
                  <Input value={videoBaseUrl} onChange={(event) => setVideoBaseUrl(event.target.value)} placeholder="留空使用 provider 默认地址" />
                </label>
                <label>
                  <FieldLabel text="API Key" />
                  <Input type="password" value={videoApiKey} onChange={(event) => setVideoApiKey(event.target.value)} placeholder={config?.video?.hasApiKey ? '已保存，留空继续使用' : videoProvider === 'pippit' ? '小云雀 Access Key' : 'sk-...'} autoComplete="off" />
                </label>
                {videoProvider !== 'pippit' ? (
                  <label>
                    <FieldLabel text="模型" />
                    <Input value={videoModel} onChange={(event) => setVideoModel(event.target.value)} placeholder="留空使用 provider 默认模型" />
                  </label>
                ) : null}
                <div className="grid grid-cols-3 gap-3">
                  <label>
                    <FieldLabel text="清晰度" />
                    <Select value={videoResolution} onChange={(event) => setVideoResolution(event.target.value)} className="w-full">
                      <option value="480P">480P</option>
                      <option value="720P">720P</option>
                      <option value="1080P">1080P</option>
                    </Select>
                  </label>
                  <label>
                    <FieldLabel text="秒数" />
                    <Input type="number" min={1} max={30} value={videoDuration} onChange={(event) => setVideoDuration(Number(event.target.value || 5))} />
                  </label>
                  <label>
                    <FieldLabel text="比例" />
                    <Select value={videoRatio} onChange={(event) => setVideoRatio(event.target.value)} className="w-full">
                      <option value="16:9">16:9</option>
                      <option value="9:16">9:16</option>
                      <option value="1:1">1:1</option>
                    </Select>
                  </label>
                </div>
              </div>
            )}

            <div className="mt-5 flex flex-wrap gap-3">
              <Button variant="primary" onClick={saveConfig} disabled={saving || testing || generationRunning}>
                {saving ? '保存中...' : '保存配置'}
              </Button>
              <Button variant="quiet" onClick={testConfig} disabled={saving || testing || generationRunning}>
                {testing ? '检测中...' : '测试配置'}
              </Button>
            </div>
            </details>
          </section>

          <section className="border-y border-border/70 py-5">
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
              <div>
                <h2 className="text-lg font-black text-text">{tab === 'image' ? '图片生成' : '视频生成'}</h2>
                <p className="mt-1 text-xs leading-5 text-text-muted">提交后会持续轮询本地任务状态，切页回来仍可继续查看。</p>
                <div className="mt-5 flex rounded-[8px] border border-border bg-surface-alt/60 p-1">
                  {tab === 'image' ? (
                    <>
                      <button
                        data-creative-mode-t2i
                        type="button"
                        aria-pressed={imageMode === 't2i'}
                        onClick={() => setImageMode('t2i')}
                        className={`min-w-0 flex-1 rounded-[6px] px-3 py-2 text-sm font-black ${imageMode === 't2i' ? 'bg-accent text-accent-ink' : 'text-text-muted'}`}
                      >文生图</button>
                      <button
                        data-creative-mode-i2i
                        type="button"
                        aria-pressed={imageMode === 'i2i'}
                        onClick={() => setImageMode('i2i')}
                        className={`min-w-0 flex-1 rounded-[6px] px-3 py-2 text-sm font-black ${imageMode === 'i2i' ? 'bg-accent text-accent-ink' : 'text-text-muted'}`}
                      >图生图</button>
                    </>
                  ) : (
                    <>
                      <button
                        data-creative-mode-t2v
                        type="button"
                        aria-pressed={videoMode === 't2v'}
                        onClick={() => setVideoMode('t2v')}
                        className={`min-w-0 flex-1 rounded-[6px] px-3 py-2 text-sm font-black ${videoMode === 't2v' ? 'bg-accent text-accent-ink' : 'text-text-muted'}`}
                      >文生视频</button>
                      <button
                        data-creative-mode-i2v
                        type="button"
                        aria-pressed={videoMode === 'i2v'}
                        onClick={() => setVideoMode('i2v')}
                        className={`min-w-0 flex-1 rounded-[6px] px-3 py-2 text-sm font-black ${videoMode === 'i2v' ? 'bg-accent text-accent-ink' : 'text-text-muted'}`}
                      >图生视频</button>
                    </>
                  )}
                </div>
                {tab === 'image' && imageMode === 'i2i' ? (
                  <div className="mt-4"><ReferenceImagePicker value={imageReference} latest={latestImageReference} onChange={setImageReference} /></div>
                ) : null}
                {tab === 'video' && videoMode === 'i2v' ? (
                  <div className="mt-4"><ReferenceImagePicker value={videoReference} latest={latestImageReference} onChange={setVideoReference} /></div>
                ) : null}
                {tab === 'image' ? (
                  <div className="mt-4">
                    <FieldLabel text="常用比例" />
                    <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                      {IMAGE_RATIO_PRESETS.map((preset) => (
                        <button
                          key={preset.ratio}
                          type="button"
                          aria-pressed={imageRatio === preset.ratio}
                          onClick={() => setImageRatio(preset.ratio)}
                          className={`h-10 rounded-[6px] border text-xs font-black ${imageRatio === preset.ratio ? 'border-accent bg-accent-soft text-accent' : 'border-border bg-surface text-text-muted'}`}
                        >{preset.ratio}</button>
                      ))}
                    </div>
                  </div>
                ) : null}
                <label className="mt-5 block">
                  <FieldLabel text="提示词" required />
                  <TextArea
                    value={tab === 'image' ? imagePrompt : videoPrompt}
                    onChange={(event) => (tab === 'image' ? setImagePrompt(event.target.value) : setVideoPrompt(event.target.value))}
                    rows={8}
                    placeholder="描述你想生成的画面..."
                  />
                </label>
                <div className="mt-4 flex flex-wrap gap-3">
                  {tab === 'image' ? (
                    <Button variant="primary" onClick={submitImage} disabled={imageRunning}>
                      {imageRunning ? '生成中...' : '生成图片'}
                    </Button>
                  ) : (
                    <Button variant="primary" onClick={submitVideo} disabled={videoRunning}>
                      {videoRunning ? '生成中...' : '生成视频'}
                    </Button>
                  )}
                  <Button variant="quiet" onClick={() => void refreshConfig()} disabled={generationRunning || loadingConfig}>
                    刷新配置
                  </Button>
                </div>
              </div>

              <div className="rounded-[8px] border border-border bg-surface-alt/35 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-black text-text">任务状态</span>
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-black ${jobFailed(activeJob) ? 'bg-status-danger/12 text-status-danger' : videoNeedsManual && tab === 'video' ? 'bg-status-warning/12 text-status-warning' : generationRunning ? 'bg-accent-soft text-accent' : 'bg-surface text-text-muted'}`}>
                    {generationRunning ? '生成中' : videoNeedsManual && tab === 'video' ? '待补充' : jobFailed(activeJob) ? '失败' : jobDone(activeJob) ? '完成' : '待提交'}
                  </span>
                </div>
                <div className="mt-5 flex min-h-[178px] flex-col items-center justify-center rounded-[8px] bg-surface/70 p-5 text-center">
                  {generationRunning ? (
                    <>
                      <div className="generationPulse relative h-16 w-16 rounded-full border border-accent/30 bg-accent-soft" />
                      <div className="mt-4 text-sm font-black text-text">{activeMessage}</div>
                      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-border">
                        <div className="creative-progress-bar h-full w-2/3 rounded-full bg-accent" />
                      </div>
                    </>
                  ) : videoNeedsManual && tab === 'video' ? (
                    <div className="w-full max-w-xl text-left">
                      <div className="text-sm font-black text-text">小云雀需要补充信息</div>
                      <div className="mt-2 text-sm leading-6 text-text-muted">
                        {videoManualResult?.question || '请确认生成要求后继续原任务。'}
                      </div>
                      <TextArea
                        className="mt-4 min-h-24"
                        value={videoManualReply}
                        onChange={(event) => setVideoManualReply(event.target.value)}
                        placeholder="输入补充信息或确认内容"
                      />
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button variant="primary" onClick={() => void continuePippitVideo()} disabled={!videoManualReply.trim()}>
                          继续原任务
                        </Button>
                        {videoManualResult?.webThreadLink ? (
                          <Button variant="quiet" onClick={() => window.open(videoManualResult.webThreadLink, '_blank', 'noopener,noreferrer')}>
                            打开任务页
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  ) : jobFailed(activeJob) ? (
                    <div className="text-sm leading-6 text-status-danger">{activeJob?.error || activeJob?.message || '生成失败'}</div>
                  ) : (
                    <div className="text-sm leading-6 text-text-muted">提交任务后会显示阶段状态。</div>
                  )}
                </div>
                {activeJob?.progress?.history?.length ? (
                  <div className="mt-4 max-h-28 space-y-2 overflow-auto text-xs leading-5 text-text-muted">
                    {activeJob.progress.history.slice(-5).map((entry, index) => (
                      <div key={`${entry.updatedAt || index}-${entry.message}`}>{entry.message}</div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>

            <div data-current-generation-results className="mt-6 border-t border-border pt-5">
              <h3 className="text-base font-black text-text">结果</h3>
              {activePhoneTransfer ? (
                <div data-phone-transfer-state role="status" className={`mt-3 rounded-[8px] border px-3 py-2 text-xs font-bold ${phoneTransferTone}`}>
                  {activePhoneTransfer.message || '手机相册传送状态已更新'}
                </div>
              ) : null}
              {tab === 'image' ? (
                <div className="mt-4 grid gap-4 md:grid-cols-2">
                  {imagePreviewSources.length ? imagePreviewSources.map((preview, index) => (
                    <div key={index} className="overflow-hidden rounded-[8px] border border-border bg-surface-alt/40">
                      <GenerationPreview
                        kind="image"
                        src={preview.src}
                        alt={`LOOM generated ${index + 1}`}
                        ratio={imageResult?.ratio || imageRatio}
                      />
                      <div className="flex items-center justify-between gap-3 px-3 py-2 text-xs text-text-muted">
                        <span className="truncate">{preview.file?.filename || `image-${index + 1}.png`}</span>
                        {preview.file?.path ? (
                          <button type="button" className="font-black text-accent" onClick={() => void copyPath(preview.file?.path)}>复制路径</button>
                        ) : (
                          <span className="text-text-muted" role="status">未返回本地路径</span>
                        )}
                      </div>
                    </div>
                  )) : (
                    <div className="rounded-[8px] border border-dashed border-border p-6 text-sm text-text-muted">暂无图片结果。</div>
                  )}
                </div>
              ) : (
                <div className="mt-4">
                  {videoPreviewSource ? (
                    <div className="overflow-hidden rounded-[8px] border border-border bg-surface-alt/40">
                      <GenerationPreview
                        kind="video"
                        src={videoPreviewSource}
                        alt={videoResult?.filename || 'LOOM generated video'}
                        ratio={videoRatio}
                      />
                      <div className="flex items-center justify-between gap-3 px-3 py-2 text-xs text-text-muted">
                        <span className="truncate">{videoResult?.filename || 'loom-video.mp4'}</span>
                        {videoResult?.path ? (
                          <button type="button" className="font-black text-accent" onClick={() => void copyPath(videoResult?.path)}>复制路径</button>
                        ) : (
                          <span className="text-text-muted" role="status">未返回本地路径</span>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-[8px] border border-dashed border-border p-6 text-sm text-text-muted">暂无视频结果。</div>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>
        <section data-local-media-library className="mx-auto mt-5 w-full max-w-[1320px] border-y border-border/70 py-5">
          <MediaLibraryPanel
            kind={assetKind}
            assets={assets}
            loading={assetsLoading}
            error={assetsError}
            hasMore={assetsHasMore}
            onKindChange={(kind) => {
              assetsCursorRef.current = '';
              setAssetKind(kind);
            }}
            onLoadMore={() => void refreshAssets(true)}
            onRefresh={() => void refreshAssets(false)}
            onReveal={(asset) => void revealAsset(asset)}
            onDelete={(asset) => void deleteAsset(asset)}
            onUseForImage={useAssetForImage}
            onUseForVideo={useAssetForVideo}
            phones={phoneDevices}
            transferringAssetId={transferringAssetId}
            transferResults={assetTransferResults}
            onTransfer={(asset, deviceIds) => void transferAsset(asset, deviceIds)}
          />
        </section>
          </>
        )}
      </main>
    </div>
  );
};
