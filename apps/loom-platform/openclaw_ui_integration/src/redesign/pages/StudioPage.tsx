import React from 'react';
import { Film, ImagePlus, RefreshCcw, Settings2, Upload, X } from 'lucide-react';
import { Button, Chip, EmptyState, Field, Input, InlineState, Panel, SectionHeader, Select, Tabs, TextArea } from '../components/ui';
import { generateImage, generateVideo, loadPromptTemplates, loadStudioSnapshot, requestPhoneData, waitForVideoGenerationJob } from '../api/adapters';
import { useAsync } from '../lib/useAsync';
import type { ImageResult, PromptTemplate, VideoResult } from '../types';
import type { BridgeJob, VideoGenerationPayload } from '../api/adapters';
import { usePreviewStore } from '../store/appStore';
import { translateMediaError } from '../lib/errors';
import type { FriendlyError } from '../lib/errors';
import { copyText } from '../lib/clipboard';

type StudioTab = 'image' | 'video';

const IMAGE_SIZE_OPTIONS = [
  { value: '1024x1024', label: '1:1 · 1024x1024' },
  { value: '1536x1024', label: '3:2 · 1536x1024' },
  { value: '1024x1536', label: '2:3 · 1024x1536' },
  { value: '1792x1024', label: '16:9 · 1792x1024' },
  { value: '1024x1792', label: '9:16 · 1024x1792' },
];

const VIDEO_MODE_OPTIONS = [
  { value: 't2v', label: '文生视频' },
  { value: 'i2v', label: '图生视频' },
];

const VIDEO_RESOLUTION_OPTIONS = [
  { value: '480P', label: '480P' },
  { value: '720P', label: '720P' },
  { value: '1080P', label: '1080P' },
];

const VIDEO_RATIO_OPTIONS = [
  { value: '16:9', label: '16:9 横屏' },
  { value: '9:16', label: '9:16 竖屏' },
  { value: '1:1', label: '1:1 方图' },
  { value: '4:3', label: '4:3 标准' },
  { value: '3:4', label: '3:4 竖版' },
  { value: '21:9', label: '21:9 宽银幕' },
];

const IMAGE_LOADING_TIPS = [
  '正在连接图像网关…',
  '模型绘制中，请稍候…',
  '高分辨率渲染需要一点时间…',
  '马上好了，正在收尾…',
];

const VIDEO_LOADING_TIPS = [
  '任务已提交，等待网关排队',
  '生成中，通常需要 1-3 分钟',
  '正在同步进度，切走也会保留',
  '接近完成，等待视频文件返回',
];

const ACTIVE_VIDEO_JOB_STORAGE_KEY = 'openclaw.studio.activeVideoJob.v1';
const VIDEO_JOB_TIMEOUT_MS = 20 * 60 * 1000;
const VIDEO_JOB_STALE_MS = 25 * 60 * 1000;
const VIDEO_JOB_POLLERS = new Set<string>();

interface ActiveVideoJob {
  jobId: string;
  payload: VideoGenerationPayload;
  startedAt: number;
  updatedAt: number;
  message: string;
}

function StudioLoading({ kind, message = '', startedAt }: { kind: 'image' | 'video'; message?: string; startedAt?: number }) {
  const [secs, setSecs] = React.useState(0);
  React.useEffect(() => {
    const update = () => {
      if (startedAt) {
        setSecs(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
      } else {
        setSecs((value) => value + 1);
      }
    };
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [startedAt]);
  const tips = kind === 'image' ? IMAGE_LOADING_TIPS : VIDEO_LOADING_TIPS;
  const step = kind === 'image' ? 8 : 20; // 视频更慢，换一条提示的间隔更长
  const tip = message || tips[Math.min(tips.length - 1, Math.floor(secs / step))];
  const mins = Math.floor(secs / 60);
  const rest = String(secs % 60).padStart(2, '0');
  return (
    <div className="studio-loading" role="status" aria-live="polite">
      <div className="studio-spinner-ring" aria-hidden="true">
        <div className="studio-spinner" />
      </div>
      <div className="studio-loading-title">{kind === 'image' ? '正在生成图像' : '正在生成视频'}</div>
      <div className="studio-loading-tip">{tip}</div>
      <div className="studio-loading-bar"><span /></div>
      <div className="studio-loading-secs">已用时 {mins}:{rest}</div>
    </div>
  );
}

function FailureCard({ failure, onRetry }: { failure: FriendlyError; onRetry?: () => void }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <div className="inline-state inline-state-danger">
      <div>
        <div className="inline-state-title">{failure.title}</div>
        <div className="inline-state-desc">{failure.hint}</div>
        <div className="button-row" style={{ marginTop: 8 }}>
          <Button
            type="button"
            variant="quiet"
            onClick={async () => {
              const ok = await copyText(failure.diagnostic);
              setCopied(ok);
              window.setTimeout(() => setCopied(false), 1800);
            }}
          >
            {copied ? '已复制' : '复制诊断'}
          </Button>
          {onRetry ? <Button type="button" variant="secondary" onClick={onRetry}>重试</Button> : null}
        </div>
      </div>
    </div>
  );
}

function TemplateGallery({ templates, onApply, onCopy }: {
  templates: PromptTemplate[];
  onApply: (template: PromptTemplate) => void;
  onCopy: (template: PromptTemplate) => void;
}) {
  if (!templates.length) return null;
  return (
    <div className="template-gallery">
      <div className="template-gallery-head">模板库 · 一键套用</div>
      <div className="template-row">
        {templates.map((template) => (
          <div key={template.id} className="template-card">
            <div className="template-card-title">{template.title}</div>
            <div className="template-card-prompt">{template.prompt}</div>
            {template.tags.length ? (
              <div className="template-card-tags">
                {template.tags.map((tag) => <span key={tag}>#{tag}</span>)}
              </div>
            ) : null}
            <div className="template-card-actions">
              <button type="button" className="template-btn primary" onClick={() => onApply(template)}>套用</button>
              <button type="button" className="template-btn" onClick={() => onCopy(template)}>复制</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function readActiveVideoJob(): ActiveVideoJob | null {
  try {
    const raw = window.localStorage.getItem(ACTIVE_VIDEO_JOB_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ActiveVideoJob;
    if (!parsed?.jobId || !parsed?.payload || !parsed.startedAt) return null;
    if (Date.now() - Number(parsed.startedAt) > VIDEO_JOB_STALE_MS) {
      window.localStorage.removeItem(ACTIVE_VIDEO_JOB_STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function writeActiveVideoJob(job: ActiveVideoJob | null) {
  try {
    if (!job) {
      window.localStorage.removeItem(ACTIVE_VIDEO_JOB_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(ACTIVE_VIDEO_JOB_STORAGE_KEY, JSON.stringify(job));
  } catch {
    // Best effort only. The live job still runs in the bridge.
  }
}

function videoJobMessage(job: BridgeJob<any>): string {
  return String(job.progress?.message || job.message || '').trim();
}

export function StudioPage() {
  const settings = usePreviewStore((state) => state.settings);
  const navigate = usePreviewStore((state) => state.navigate);
  const pushToast = usePreviewStore((state) => state.pushToast);
  const studio = usePreviewStore((state) => state.studio);
  const updateStudio = usePreviewStore((state) => state.updateStudio);
  const { data, loading, error, refresh } = useAsync(() => loadStudioSnapshot(settings), [settings], { cacheKey: "studio" });
  const {
    tab,
    imagePrompt,
    imageSize,
    imageCount,
    imageEditPath,
    imageReferenceName,
    imageStartedAt,
    videoPrompt,
    videoMode,
    videoResolution,
    videoDuration,
    videoRatio,
    videoImagePath,
    videoReferenceName,
    videoProgress,
    videoStartedAt,
    imageBusy,
    videoBusy,
    activeVideoJob,
    selectedImage,
    selectedVideo,
    imageHistory,
    videoHistory,
  } = studio;
  const imageReferenceInputRef = React.useRef<HTMLInputElement>(null);
  const videoReferenceInputRef = React.useRef<HTMLInputElement>(null);
  const activeVideoJobRef = React.useRef<ActiveVideoJob | null>(activeVideoJob);
  const [imageFailure, setImageFailure] = React.useState<FriendlyError | null>(null);
  const [videoFailure, setVideoFailure] = React.useState<FriendlyError | null>(null);
  const [imageTaskState, setImageTaskState] = React.useState<'idle' | 'success' | 'failed'>('idle');
  const [videoTaskState, setVideoTaskState] = React.useState<'idle' | 'success' | 'failed'>('idle');

  const { data: imageTemplates } = useAsync(() => loadPromptTemplates(settings, 'image'), [settings], { cacheKey: 'templates-image', ttlMs: 300000 });
  const { data: videoTemplates } = useAsync(() => loadPromptTemplates(settings, 'video'), [settings], { cacheKey: 'templates-video', ttlMs: 300000 });

  React.useEffect(() => {
    activeVideoJobRef.current = activeVideoJob;
  }, [activeVideoJob]);

  const applyImageTemplate = React.useCallback((template: PromptTemplate) => {
    updateStudio({ imagePrompt: template.prompt });
    const size = template.params?.size;
    if (size) updateStudio({ imageSize: String(size) });
    pushToast({ tone: 'ok', title: '已套用模板', detail: template.title });
  }, [pushToast, updateStudio]);

  const applyVideoTemplate = React.useCallback((template: PromptTemplate) => {
    updateStudio({ videoPrompt: template.prompt });
    const params = template.params || {};
    const patch: Partial<typeof studio> = {};
    if (params.mode) patch.videoMode = String(params.mode);
    if (params.resolution) patch.videoResolution = String(params.resolution);
    if (params.ratio) patch.videoRatio = String(params.ratio);
    if (params.duration) patch.videoDuration = Number(params.duration) || 5;
    if (Object.keys(patch).length) updateStudio(patch);
    pushToast({ tone: 'ok', title: '已套用模板', detail: template.title });
  }, [pushToast, studio, updateStudio]);

  const copyTemplate = React.useCallback(async (template: PromptTemplate) => {
    try {
      await navigator.clipboard.writeText(template.prompt);
      pushToast({ tone: 'ok', title: '已复制提示词', detail: template.title });
    } catch {
      pushToast({ tone: 'danger', title: '复制失败', detail: '请手动选择文本复制。' });
    }
  }, [pushToast]);

  React.useEffect(() => {
    if (!data) return;
    updateStudio((current) => ({
      imageHistory: !current.imageHistory.length && data.imageHistory.length ? data.imageHistory : current.imageHistory,
      videoHistory: !current.videoHistory.length && data.videoHistory.length ? data.videoHistory : current.videoHistory,
      selectedImage: !current.selectedImage && data.imageHistory.length ? data.imageHistory[0] : current.selectedImage,
      selectedVideo: !current.selectedVideo && data.videoHistory.length ? data.videoHistory[0] : current.selectedVideo,
    }));
  }, [data, updateStudio]);

  const importImagesToPhone = React.useCallback(async (result: ImageResult) => {
    const phoneBaseUrl = settings.phoneBaseUrl.trim();
    const phoneToken = settings.phoneToken.trim();
    if (!phoneBaseUrl || !phoneToken || !result.previewUrls.length) return 0;

    let imported = 0;
    for (let index = 0; index < result.previewUrls.length; index += 1) {
      const dataUrl = result.previewUrls[index];
      if (!dataUrl.startsWith('data:image/')) continue;
      await requestPhoneData(
        settings,
        { baseUrl: phoneBaseUrl, token: phoneToken },
        '/api/lumi/media/import_image',
        'POST',
        {
          dataUrl,
          album: 'OpenClaw',
          filename: result.files[index]?.filename || 'openclaw-image-' + Date.now() + '-' + (index + 1) + '.png',
        },
      );
      imported += 1;
    }
    return imported;
  }, [settings]);

  const importVideoToPhone = React.useCallback(async (result: VideoResult) => {
    const phoneBaseUrl = settings.phoneBaseUrl.trim();
    const phoneToken = settings.phoneToken.trim();
    const dataUrl = result.previewUrl;
    if (!phoneBaseUrl || !phoneToken || !dataUrl.startsWith('data:video/')) return false;

    await requestPhoneData(
      settings,
      { baseUrl: phoneBaseUrl, token: phoneToken },
      '/api/lumi/media/import_video',
      'POST',
      {
        dataUrl,
        album: 'OpenClaw',
        filename: result.file?.filename || 'openclaw-video-' + Date.now() + '.mp4',
      },
    );
    return true;
  }, [settings]);

  const finishVideoResult = React.useCallback((result: VideoResult) => {
    updateStudio((current) => ({
      selectedVideo: result,
      videoHistory: [result, ...current.videoHistory].slice(0, 6),
      activeVideoJob: null,
      videoStartedAt: 0,
    }));
    setVideoFailure(null);
    setVideoTaskState('success');
    if (activeVideoJobRef.current?.jobId) VIDEO_JOB_POLLERS.delete(activeVideoJobRef.current.jobId);
    activeVideoJobRef.current = null;
    writeActiveVideoJob(null);
    void importVideoToPhone(result)
      .then((imported) => {
        if (imported) {
          pushToast({ tone: 'ok', title: '视频已导入手机', detail: 'Movies/OpenClaw · ' + (result.file?.filename || 'openclaw-video.mp4') });
        }
      })
      .catch((err) => {
        pushToast({ tone: 'warn', title: '手机视频导入失败', detail: String(err) });
    });
    pushToast({ tone: 'ok', title: '视频已生成', detail: result.file?.filename || '预览已就绪' });
  }, [importVideoToPhone, pushToast, updateStudio]);

  React.useEffect(() => {
    const stored = activeVideoJob || readActiveVideoJob();
    if (!stored?.jobId) return;
    if (VIDEO_JOB_POLLERS.has(stored.jobId)) {
      updateStudio({ tab: 'video', activeVideoJob: stored, videoBusy: true, videoProgress: stored.message || '正在生成视频' });
      return;
    }
    VIDEO_JOB_POLLERS.add(stored.jobId);
    activeVideoJobRef.current = stored;
    updateStudio({ tab: 'video', activeVideoJob: stored, videoBusy: true, videoProgress: stored.message || '正在恢复视频任务' });

    let cancelled = false;
    const elapsedMs = Math.max(0, Date.now() - stored.startedAt);
    const remainingMs = Math.max(60_000, VIDEO_JOB_TIMEOUT_MS - elapsedMs);

    void waitForVideoGenerationJob(settings, stored.jobId, stored.payload, (job) => {
      if (cancelled) return;
      const message = videoJobMessage(job);
      if (!message) return;
      const next = { ...stored, message, updatedAt: Date.now() };
      activeVideoJobRef.current = next;
      updateStudio({ videoProgress: message, activeVideoJob: next });
      writeActiveVideoJob(next);
    }, remainingMs)
      .then((result) => {
        if (cancelled) return;
        finishVideoResult(result.data);
      })
      .catch((err) => {
        if (cancelled) return;
        VIDEO_JOB_POLLERS.delete(stored.jobId);
        activeVideoJobRef.current = null;
        updateStudio({ activeVideoJob: null, videoStartedAt: 0 });
        writeActiveVideoJob(null);
        const failure = translateMediaError(err, 'video');
        setVideoFailure(failure);
        setVideoTaskState('failed');
        pushToast({ tone: 'danger', title: failure.title, detail: failure.hint, diagnostic: failure.diagnostic, logRoute: failure.logRoute });
      })
      .finally(() => {
        if (cancelled) return;
        VIDEO_JOB_POLLERS.delete(stored.jobId);
        updateStudio({ videoBusy: false, videoProgress: '', videoStartedAt: 0 });
      });

    return () => {
      cancelled = true;
    };
  }, [activeVideoJob, finishVideoResult, pushToast, settings, updateStudio]);

  const handleGenerateImage = async () => {
    const baseUrl = data?.imageDefaults.baseUrl.trim() || '';
    const apiKey = data?.imageDefaults.apiKey.trim() || '';
    if (!baseUrl || !apiKey) {
      pushToast({
        tone: 'danger',
        title: '还没有配置图像接口',
        detail: '请先在设置里填写图像生成 API 地址和密钥。',
        logRoute: 'settings',
      });
      return;
    }
    setImageFailure(null);
    setImageTaskState('idle');
    updateStudio({ imageBusy: true, imageStartedAt: Date.now(), tab: 'image' });
    try {
      const result = await generateImage(settings, {
        baseUrl,
        apiKey,
        prompt: imagePrompt.trim(),
        size: imageSize,
        count: imageCount,
        editImagePath: imageEditPath.trim() || undefined,
        model: data?.imageDefaults.model,
      });
      updateStudio((current) => ({
        selectedImage: result.data,
        imageHistory: [result.data, ...current.imageHistory].slice(0, 6),
      }));
      setImageTaskState('success');
      pushToast({ tone: 'ok', title: '图像已生成', detail: String(result.data.count) + ' 个结果' });
      try {
        const imported = await importImagesToPhone(result.data);
        if (imported) {
          pushToast({ tone: 'ok', title: '已导入手机相册', detail: 'Pictures/OpenClaw · ' + imported + ' 张' });
        }
      } catch (err) {
        pushToast({ tone: 'warn', title: '手机相册导入失败', detail: String(err) });
      }
    } catch (err) {
      const failure = translateMediaError(err, 'image');
      setImageFailure(failure);
      setImageTaskState('failed');
      pushToast({ tone: 'danger', title: failure.title, detail: failure.hint, diagnostic: failure.diagnostic, logRoute: failure.logRoute });
    } finally {
      updateStudio({ imageBusy: false, imageStartedAt: 0 });
    }
  };

  const handleGenerateVideo = async () => {
    const apiBase = data?.videoDefaults.apiBase.trim() || '';
    const apiKey = data?.videoDefaults.apiKey.trim() || '';
    const model = data?.videoDefaults.model.trim() || '';
    const providerId = inferVideoProviderId(data?.videoDefaults.providerId || '', apiBase, model);
    if (!apiBase || !apiKey) {
      pushToast({
        tone: 'danger',
        title: '还没有配置视频接口',
        detail: '请先在设置里填写视频生成 API 地址和密钥。',
        logRoute: 'settings',
      });
      return;
    }
    setVideoFailure(null);
    setVideoTaskState('idle');
    const payload: VideoGenerationPayload = {
      providerId,
      apiBase,
      model: model || (providerId === 'agnes' ? 'agnes-video-v2.0' : ''),
      dashKey: apiKey,
      prompt: videoPrompt.trim(),
      mode: videoMode,
      resolution: videoResolution,
      duration: videoDuration,
      ratio: videoRatio,
      imagePath: videoImagePath.trim() || undefined,
    };
    const videoStart = Date.now();
    updateStudio({ videoBusy: true, videoStartedAt: videoStart, videoProgress: '正在提交视频任务', tab: 'video' });
    try {
      const result = await generateVideo(settings, payload, (job) => {
        const message = videoJobMessage(job);
        if (message) updateStudio({ videoProgress: message });
        const currentJob = activeVideoJobRef.current;
        if (message && currentJob?.jobId) {
          const next = { ...currentJob, message, updatedAt: Date.now() };
          activeVideoJobRef.current = next;
          updateStudio({ activeVideoJob: next });
          writeActiveVideoJob(next);
        }
      }, ({ jobId, job }) => {
        const message = videoJobMessage(job || {}) || '任务已提交，等待网关排队';
        const next = { jobId, payload, startedAt: videoStart, updatedAt: Date.now(), message };
        VIDEO_JOB_POLLERS.add(jobId);
        activeVideoJobRef.current = next;
        updateStudio({ activeVideoJob: next, videoProgress: message });
        writeActiveVideoJob(next);
      });
      finishVideoResult(result.data);
    } catch (err) {
      if (activeVideoJobRef.current?.jobId) VIDEO_JOB_POLLERS.delete(activeVideoJobRef.current.jobId);
      activeVideoJobRef.current = null;
      updateStudio({ activeVideoJob: null, videoStartedAt: 0 });
      writeActiveVideoJob(null);
      const failure = translateMediaError(err, 'video');
      setVideoFailure(failure);
      setVideoTaskState('failed');
      pushToast({ tone: 'danger', title: failure.title, detail: failure.hint, diagnostic: failure.diagnostic, logRoute: failure.logRoute });
    } finally {
      if (activeVideoJobRef.current?.jobId) VIDEO_JOB_POLLERS.delete(activeVideoJobRef.current.jobId);
      updateStudio({ videoBusy: false, videoProgress: '', videoStartedAt: 0 });
    }
  };

  const handleReferenceFile = async (event: React.ChangeEvent<HTMLInputElement>, kind: 'image' | 'video') => {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    try {
      const dataUrl = await readFileAsDataUrl(file);
      if (kind === 'image') {
        updateStudio({ imageEditPath: dataUrl, imageReferenceName: file.name });
      } else {
        updateStudio({ videoImagePath: dataUrl, videoReferenceName: file.name, videoMode: 'i2v' });
      }
    } catch (err) {
      pushToast({ tone: 'danger', title: '参考图读取失败', detail: String(err) });
    } finally {
      input.value = '';
    }
  };

  return (
    <div className="page-grid">
      <section className="hero-band">
        <div className="hero-copy">
          <div className="eyebrow">生成任务</div>
          <h1>图像和视频生成保留，但密钥不再散落在页面里。</h1>
          <p>这里只做任务提交和结果预览；网关、模型和密钥统一从设置页读取。</p>
        </div>
        <div className="hero-actions">
          <Button variant="primary" icon={RefreshCcw} onClick={refresh}>刷新默认值</Button>
          <Button variant="secondary" icon={Settings2} onClick={() => navigate('settings')}>打开设置</Button>
        </div>
      </section>

      <section className="content-grid content-grid-studio">
        <Panel className="surface-panel">
          <SectionHeader
            eyebrow="网关"
            title="已解析的默认配置"
            subtitle="这些值来自统一设置和配置文件，不在当前页面临时改写。"
          />
          {loading ? (
            <div className="panel-loading-inline">正在读取生成配置...</div>
          ) : error ? (
            <InlineState tone="danger" title="生成配置读取失败" description={error} />
          ) : data ? (
            <div className="detail-stack">
              {tab === 'image' ? (
                <>
                  <div className="detail-row"><span className="detail-label">图像地址</span><span className="detail-value">{data.imageDefaults.baseUrl || '暂无'}</span></div>
                  <div className="detail-row"><span className="detail-label">图像密钥</span><span className="detail-value">{data.imageDefaults.apiKeyMasked}</span></div>
                  <div className="detail-row"><span className="detail-label">图像模型</span><span className="detail-value">{data.imageDefaults.model || 'gpt-image-2'}</span></div>
                </>
              ) : (
                <>
                  <div className="detail-row"><span className="detail-label">视频地址</span><span className="detail-value">{data.videoDefaults.apiBase || '暂无'}</span></div>
                  <div className="detail-row"><span className="detail-label">视频密钥</span><span className="detail-value">{data.videoDefaults.apiKeyMasked}</span></div>
                  <div className="detail-row"><span className="detail-label">视频模型</span><span className="detail-value">{data.videoDefaults.model || 'agnes-video-v2.0'}</span></div>
                </>
              )}
              <div className="detail-row"><span className="detail-label">服务商</span><span className="detail-value">{inferVideoProviderId(data.videoDefaults.providerId, data.videoDefaults.apiBase, data.videoDefaults.model)}</span></div>
              <div className="detail-row"><span className="detail-label">来源</span><span className="detail-value">{data.gateway.mode}</span></div>
              {tab === 'image' && (!data.imageDefaults.baseUrl.trim() || !data.imageDefaults.apiKey.trim()) ? (
                <InlineState
                  tone="warn"
                  title="还没有配置图像接口"
                  description={
                    <Button type="button" variant="secondary" icon={Settings2} onClick={() => navigate('settings')}>去填写图像接口</Button>
                  }
                />
              ) : null}
              {tab === 'video' && (!data.videoDefaults.apiBase.trim() || !data.videoDefaults.apiKey.trim()) ? (
                <InlineState
                  tone="warn"
                  title="还没有配置视频接口"
                  description={
                    <Button type="button" variant="secondary" icon={Settings2} onClick={() => navigate('settings')}>去填写视频接口</Button>
                  }
                />
              ) : null}
            </div>
          ) : null}
        </Panel>

        <Panel className="surface-panel surface-panel-wide">
          <SectionHeader
            eyebrow="工作台"
            title="图像 / 视频工作台"
            subtitle="提示词、参数、结果预览和设置跳转分开，便于排错。"
            action={
              <Tabs
                value={tab}
                onChange={(value) => updateStudio({ tab: value as StudioTab })}
                items={[
                  { key: 'image', label: '图像' },
                  { key: 'video', label: '视频' },
                ]}
              />
            }
          />

          {tab === 'image' ? (
            <div className="studio-layout">
              <div className="studio-form">
                <TemplateGallery templates={imageTemplates || []} onApply={applyImageTemplate} onCopy={copyTemplate} />
                <Field label="提示词" hint="映射到 /api/image/generate.prompt">
                  <TextArea rows={7} value={imagePrompt} onChange={(event) => updateStudio({ imagePrompt: event.target.value })} />
                </Field>
                <div className="form-grid">
                  <Field label="尺寸">
                    <Select value={imageSize} onChange={(event) => updateStudio({ imageSize: event.target.value })}>
                      {IMAGE_SIZE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                    </Select>
                  </Field>
                  <Field label="数量">
                    <Input type="number" min={1} max={4} value={imageCount} onChange={(event) => updateStudio({ imageCount: Number(event.target.value) || 1 })} />
                  </Field>
                </div>
                <Field label="参考图" hint="可选，选择本地图片后自动转为 data URL">
                  <input
                    ref={imageReferenceInputRef}
                    type="file"
                    accept="image/*"
                    className="visually-hidden-file"
                    onChange={(event) => void handleReferenceFile(event, 'image')}
                  />
                  <div className="upload-row">
                    <Button type="button" variant="secondary" icon={Upload} onClick={() => imageReferenceInputRef.current?.click()}>选择图片</Button>
                    {imageReferenceName ? <Chip tone="ok" className="upload-chip">{imageReferenceName}</Chip> : <span className="upload-hint">未选择参考图</span>}
                    {imageEditPath ? <Button type="button" variant="quiet" icon={X} onClick={() => updateStudio({ imageEditPath: '', imageReferenceName: '' })}>清除</Button> : null}
                  </div>
                </Field>
                <div className="button-row">
                  <Button variant="primary" icon={ImagePlus} onClick={handleGenerateImage} disabled={imageBusy}>生成图像</Button>
                </div>
                <div className="upload-hint" role="status">
                  生成任务状态：{imageBusy ? '生成中…' : imageTaskState === 'success' ? '成功' : imageTaskState === 'failed' ? '失败' : '空闲'}
                </div>
              </div>

              <div className="studio-preview">
                <SectionHeader eyebrow="结果" title="图像结果" subtitle="最新结果在上方，历史结果在下方。" />
                {imageBusy ? (
                  <StudioLoading kind="image" startedAt={imageStartedAt || undefined} />
                ) : imageFailure ? (
                  <FailureCard failure={imageFailure} onRetry={handleGenerateImage} />
                ) : selectedImage ? (
                  <div className="result-grid">
                    {selectedImage.previewUrls.map((url, index) => (
                      <button type="button" key={url + index} className="result-card" onClick={() => updateStudio({ selectedImage })}>
                        <img src={url} alt={'generated-' + index} />
                        <div className="result-meta">
                          <span>{selectedImage.size}</span>
                          <span>{selectedImage.files[index]?.filename || '图像 ' + (index + 1)}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="暂无图像" description="生成后会显示在预览区。" />
                )}
                {imageHistory.length ? (
                  <div className="history-strip">
                    {imageHistory.map((item, index) => (
                      <button key={item.prompt + '-' + index} type="button" className="history-card" onClick={() => updateStudio({ selectedImage: item })}>
                        <img src={item.previewUrls[0]} alt={item.prompt} />
                        <span>{item.files[0]?.filename || '结果 ' + (index + 1)}</span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="studio-layout">
              <div className="studio-form">
                <TemplateGallery templates={videoTemplates || []} onApply={applyVideoTemplate} onCopy={copyTemplate} />
                <Field label="提示词" hint="映射到 /api/video/generate.prompt">
                  <TextArea rows={7} value={videoPrompt} onChange={(event) => updateStudio({ videoPrompt: event.target.value })} />
                </Field>
                <div className="form-grid">
                  <Field label="模式">
                    <Select value={videoMode} onChange={(event) => updateStudio({ videoMode: event.target.value })}>
                      {VIDEO_MODE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                    </Select>
                  </Field>
                  <Field label="分辨率">
                    <Select value={videoResolution} onChange={(event) => updateStudio({ videoResolution: event.target.value })}>
                      {VIDEO_RESOLUTION_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                    </Select>
                  </Field>
                  <Field label="时长">
                    <Input type="number" min={1} max={30} value={videoDuration} onChange={(event) => updateStudio({ videoDuration: Number(event.target.value) || 5 })} />
                  </Field>
                  <Field label="比例">
                    <Select value={videoRatio} onChange={(event) => updateStudio({ videoRatio: event.target.value })}>
                      {VIDEO_RATIO_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                    </Select>
                  </Field>
                </div>
                <Field label="参考图" hint="可选，选择后自动切换为图生视频">
                  <input
                    ref={videoReferenceInputRef}
                    type="file"
                    accept="image/*"
                    className="visually-hidden-file"
                    onChange={(event) => void handleReferenceFile(event, 'video')}
                  />
                  <div className="upload-row">
                    <Button type="button" variant="secondary" icon={Upload} onClick={() => videoReferenceInputRef.current?.click()}>选择图片</Button>
                    {videoReferenceName ? <Chip tone="ok" className="upload-chip">{videoReferenceName}</Chip> : <span className="upload-hint">未选择参考图</span>}
                    {videoImagePath ? <Button type="button" variant="quiet" icon={X} onClick={() => updateStudio({ videoImagePath: '', videoReferenceName: '' })}>清除</Button> : null}
                  </div>
                </Field>
                <div className="button-row">
                  <Button variant="primary" icon={Film} onClick={handleGenerateVideo} disabled={videoBusy}>生成视频</Button>
                </div>
                <div className="upload-hint" role="status">
                  生成任务状态：{videoBusy ? (videoProgress || '排队中…') : videoTaskState === 'success' ? '成功' : videoTaskState === 'failed' ? '失败' : '空闲'}
                </div>
              </div>

              <div className="studio-preview">
                <SectionHeader eyebrow="结果" title="视频结果" subtitle="真实模式返回 mp4；Agnes 视频会自动按任务接口轮询。" />
                {videoBusy ? (
                  <StudioLoading kind="video" message={videoProgress} startedAt={activeVideoJob?.startedAt || videoStartedAt || undefined} />
                ) : videoFailure ? (
                  <FailureCard failure={videoFailure} onRetry={handleGenerateVideo} />
                ) : selectedVideo ? (
                  <div className="video-preview-shell">
                    {!selectedVideo.previewUrl ? (
                      <EmptyState title="视频已保存" description={selectedVideo.file?.filename || '文件已写入本地目录'} />
                    ) : selectedVideo.mime.startsWith('video/') ? (
                      <video controls src={selectedVideo.previewUrl} className="video-preview" />
                    ) : (
                      <img src={selectedVideo.previewUrl} alt={selectedVideo.prompt} className="video-preview" />
                    )}
                    <div className="result-meta-grid">
                      <div><span>模式</span><strong>{selectedVideo.mode}</strong></div>
                      <div><span>分辨率</span><strong>{selectedVideo.resolution}</strong></div>
                      <div><span>时长</span><strong>{selectedVideo.duration}s</strong></div>
                      <div><span>比例</span><strong>{selectedVideo.ratio}</strong></div>
                      <div><span>Mime</span><strong>{selectedVideo.mime}</strong></div>
                      <div><span>文件</span><strong>{selectedVideo.file?.filename || '预览图'}</strong></div>
                    </div>
                  </div>
                ) : (
                  <EmptyState title="暂无视频" description="生成后会显示在这里。" />
                )}
                {videoHistory.length ? (
                  <div className="history-strip">
                    {videoHistory.map((item, index) => (
                      <button key={item.prompt + '-' + index} type="button" className="history-card" onClick={() => updateStudio({ selectedVideo: item })}>
                        {item.mime.startsWith('video/') ? <video src={item.previewUrl} muted /> : <img src={item.previewUrl} alt={item.prompt} />}
                        <span>{item.file?.filename || '片段 ' + (index + 1)}</span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </Panel>
      </section>
    </div>
  );
}

function inferVideoProviderId(providerId: string, apiBase: string, model: string) {
  const id = providerId.trim().toLowerCase();
  const base = apiBase.trim().toLowerCase();
  const modelId = model.trim().toLowerCase();
  if (id === 'agnes' || base.includes('agnes-ai.com') || modelId.startsWith('agnes-video')) return 'agnes';
  if (id === 'seedance' || base.includes('volces.com') || modelId.includes('seedance')) return 'seedance';
  if (id === 'custom') return 'custom';
  return 'dashscope';
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('file_read_failed'));
    reader.readAsDataURL(file);
  });
}
