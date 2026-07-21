import React, { useState } from 'react';
import { convertFileSrc, invoke } from '@tauri-apps/api/core';
import { Button, FieldLabel, Input, Loading, Select, TextArea, showToast } from '../common';
import { videoApi, configApi } from '../../services/api';
import { readGatewayStoredConfig, readMemberGatewayDefaults, type GatewayMode } from '../../services/gatewayConfig';
import { useLogStore } from '../../stores/logStore';
import { useAppStore } from '../../stores/appStore';
import { getDefaultPublishDraftSeed, usePublishHandoffStore } from '../../stores/publishStore';
import type { VideoMode, VideoProviderId } from '../../types';
import { VIDEO_PROVIDERS, getDefaultVideoModel, getVideoProvider } from '../../features/video/providers';

const RESOLUTIONS = ['720P', '1080P'];
const DURATIONS = [5, 10];
const RATIOS = ['16:9', '9:16', '1:1', '4:3', '3:4'];
const VIDEO_CONFIG_PATH = 'videoapi_config.json';

type GeneratedVideo = {
  previewUrl: string;
  downloadUrl: string;
  blobUrl?: string;
  mime: string;
  size: number;
  path?: string;
  directory?: string;
  filename?: string;
};

function createVideoBlobUrl(base64: string, mime = 'video/mp4') {
  const cleanBase64 = base64.includes(',') ? base64.split(',').pop() || '' : base64;
  const binary = atob(cleanBase64);
  const chunkSize = 32768;
  const chunks: BlobPart[] = [];

  for (let offset = 0; offset < binary.length; offset += chunkSize) {
    const slice = binary.slice(offset, offset + chunkSize);
    const bytes = new Uint8Array(slice.length);
    for (let i = 0; i < slice.length; i += 1) {
      bytes[i] = slice.charCodeAt(i);
    }
    chunks.push(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
  }

  const blob = new Blob(chunks, { type: mime });
  return { url: URL.createObjectURL(blob), size: blob.size };
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Failed to read local video'));
    reader.onload = () => resolve(String(reader.result || ''));
    reader.readAsDataURL(blob);
  });
}

function createGeneratedVideo(resp: {
  video?: string;
  mime?: string;
  size?: number;
  path?: string;
  directory?: string;
  filename?: string;
}): GeneratedVideo {
  const mime = resp.mime || 'video/mp4';
  const blobVideo = resp.video ? createVideoBlobUrl(resp.video, mime) : null;
  const previewUrl = resp.path ? convertFileSrc(resp.path) : blobVideo?.url || '';

  if (!previewUrl) {
    throw { error: '生成成功但没有可预览的视频地址' };
  }

  return {
    previewUrl,
    downloadUrl: blobVideo?.url || previewUrl,
    blobUrl: blobVideo?.url,
    mime,
    size: resp.size || blobVideo?.size || 0,
    path: resp.path,
    directory: resp.directory,
    filename: resp.filename,
  };
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export const VideoPage: React.FC = () => {
  const [providerId, setProviderId] = useState<VideoProviderId>('dashscope');
  const [apiKey, setApiKey] = useState('');
  const [apiBase, setApiBase] = useState(getVideoProvider('dashscope').apiBase);
  const [model, setModel] = useState(getDefaultVideoModel('dashscope', 't2v'));
  const [gatewayMode, setGatewayMode] = useState<GatewayMode>('manual');
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<VideoMode>('t2v');
  const [resolution, setResolution] = useState('720P');
  const [duration, setDuration] = useState(5);
  const [ratio, setRatio] = useState('16:9');
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState('');
  const [resultVideo, setResultVideo] = useState<GeneratedVideo | null>(null);
  const [videoError, setVideoError] = useState('');

  const appendLog = useLogStore((s) => s.append);
  const setCurrentPage = useAppStore((state) => state.setCurrentPage);
  const setPublishDraftSeed = usePublishHandoffStore((state) => state.setDraftSeed);
  const managedMode = gatewayMode === 'member';
  const provider = getVideoProvider(providerId);
  const availableModels = provider.models.filter((item) => item.modes.includes(mode));

  React.useEffect(() => {
    const nextProvider = getVideoProvider(providerId);
    if (providerId !== 'custom') {
      setApiBase(nextProvider.apiBase);
    }
    setModel((current) => {
      if (nextProvider.models.some((item) => item.id === current && item.modes.includes(mode))) {
        return current;
      }
      return getDefaultVideoModel(providerId, mode);
    });
  }, [providerId, mode]);

  React.useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const resp = await configApi.read(VIDEO_CONFIG_PATH, {});
        if (cancelled) return;

        const stored = readGatewayStoredConfig(resp.data);
        const data = resp.data as any;
        const storedProviderId = ['dashscope', 'seedance', 'agnes', 'custom'].includes(String(data?.providerId || ''))
          ? (String(data?.providerId || '') as VideoProviderId)
          : null;
        const storedApiBase = String(data?.apiBase || '').trim();
        const storedApiKey = String(data?.apiKey || '').trim();
        const storedModel = String(data?.model || '').trim();
        const memberGateway = await readMemberGatewayDefaults();

        if (stored.mode === 'member') {
          setGatewayMode('member');
          setProviderId('custom');
          setApiBase(memberGateway.videoBaseUrl || memberGateway.baseUrl || storedApiBase);
          setApiKey(memberGateway.videoApiKey || memberGateway.apiKey || storedApiKey);
          setModel(memberGateway.videoModel || memberGateway.defaultModel || storedModel || getDefaultVideoModel('custom', 't2v'));
          return;
        }

        if (stored.mode === 'manual') {
          setGatewayMode('manual');
          if (storedProviderId) setProviderId(storedProviderId);
          setApiBase(storedApiBase);
          setApiKey(storedApiKey);
          if (storedModel) setModel(storedModel);
          return;
        }

        if (storedProviderId) setProviderId(storedProviderId);
        if (storedApiBase || storedApiKey || storedModel) {
          setGatewayMode('manual');
          setApiBase(storedApiBase);
          setApiKey(storedApiKey);
          if (storedModel) setModel(storedModel);
          return;
        }

        if (memberGateway.hasGateway) {
          setGatewayMode('member');
          setProviderId('custom');
          setApiBase(memberGateway.videoBaseUrl || memberGateway.baseUrl);
          setApiKey(memberGateway.apiKey);
          setModel(memberGateway.videoModel || memberGateway.defaultModel || getDefaultVideoModel('custom', mode));
        }
      } catch {
        // ignore gateway bootstrap failures; manual mode remains available
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  React.useEffect(() => () => {
    if (resultVideo?.blobUrl) {
      URL.revokeObjectURL(resultVideo.blobUrl);
    }
  }, [resultVideo?.blobUrl]);

  const saveConfig = async () => {
    try {
      await configApi.write(VIDEO_CONFIG_PATH, {
        gatewayMode,
        managedMode,
        providerId,
        apiBase: apiBase.trim(),
        apiKey: apiKey.trim(),
        model: model.trim(),
      });
    } catch {
      // ignore config write failures; generation can still proceed
    }
  };

  const handleGatewayModeChange = async (nextMode: GatewayMode) => {
    setGatewayMode(nextMode);
    if (nextMode !== 'member') return;

    try {
      const memberGateway = await readMemberGatewayDefaults();
      if (memberGateway.hasGateway) {
        setProviderId('custom');
        setApiBase(memberGateway.videoBaseUrl || memberGateway.baseUrl);
        setApiKey(memberGateway.videoApiKey || memberGateway.apiKey);
        setModel(memberGateway.videoModel || memberGateway.defaultModel || getDefaultVideoModel('custom', mode));
      }
    } catch {
      // keep current manual values if the license lookup fails
    }
  };

  const handlePickImage = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (readerEvent) => {
        const dataUrl = readerEvent.target?.result as string;
        setImageBase64(dataUrl);
        setImagePreview(dataUrl);
      };
      reader.readAsDataURL(file);
    };
    input.click();
  };

  const handleGenerate = async () => {
    const cleanApiKey = apiKey.trim();
    const cleanApiBase = apiBase.trim();
    const cleanModel = model.trim();
    const cleanPrompt = prompt.trim();
    if (!cleanApiKey || !cleanPrompt) {
      showToast(`请填写 ${provider.authLabel} 和提示词`, 'error');
      return;
    }
    if (!cleanModel) {
      showToast('请填写或选择视频模型', 'error');
      return;
    }
    if (providerId === 'custom' && !cleanApiBase) {
      showToast('自定义视频服务需要填写 API Base URL', 'error');
      return;
    }
    if (mode === 'i2v' && !imageBase64) {
      showToast('图生视频需要上传参考图', 'error');
      return;
    }

    setGenerating(true);
    setResultVideo(null);
    setVideoError('');
    setProgress('正在提交任务...');

    await saveConfig();

    try {
      const resp = await videoApi.generate({
        providerId,
        apiBase: cleanApiBase,
        model: cleanModel,
        dashKey: cleanApiKey,
        prompt: cleanPrompt,
        mode,
        resolution,
        duration,
        ratio,
        imagePath: mode === 'i2v' ? imageBase64 || undefined : undefined,
      });

      if (!resp.video) {
        throw { error: '生成成功但没有返回视频数据' };
      }

      const result = createGeneratedVideo(resp);
      setResultVideo(result);

      const savedMessage = resp.path ? `视频生成成功，已保存到：${resp.path}` : '视频生成成功';
      showToast(savedMessage, 'success');
      appendLog(`[视频] ${provider.label} / ${cleanModel} 生成成功，大小 ${formatBytes(result.size)}${resp.path ? `，保存路径：${resp.path}` : ''}\n`);
    } catch (error: any) {
      const message = error?.error || '生成失败';
      showToast(message, 'error');
      appendLog(`[视频] 生成失败: ${message}\n`);
    } finally {
      setGenerating(false);
      setProgress('');
    }
  };

  const handleSendToPublish = async () => {
    if (!resultVideo) return;
    let dataUrl = '';
    if (resultVideo.blobUrl) {
      dataUrl = await blobToDataUrl(await (await fetch(resultVideo.blobUrl)).blob());
    }
    const name = resultVideo.filename || `openclaw-video-${Date.now()}.mp4`;
    setPublishDraftSeed({
      ...getDefaultPublishDraftSeed(),
      platformId: 'douyin',
      transportMode: 'direct',
      contentType: 'video',
      title: `OpenClaw 视频发布 ${new Date().toLocaleDateString()}`,
      body: '',
      hashtags: ['OpenClaw', 'AI视频'],
      assets: [{
        id: `video-${Date.now()}`,
        kind: 'video',
        name,
        mime: resultVideo.mime || 'video/mp4',
        dataUrl,
        size: resultVideo.size,
        sourcePath: resultVideo.path,
      }],
    });
    setCurrentPage('publish');
  };

  const handleOpenVideoDir = async () => {
    if (!resultVideo?.directory) {
      showToast('暂无保存目录', 'info');
      return;
    }
    try {
      await invoke('open_path', { path: resultVideo.directory });
      showToast(`已打开目录：${resultVideo.directory}`, 'info');
    } catch (error: any) {
      showToast(`打开目录失败：${error?.error || error}`, 'error');
    }
  };

  const handleDownloadClick = () => {
    if (resultVideo?.path) {
      showToast(`视频已保存到：${resultVideo.path}`, 'info');
    }
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-surface">
      <div className="shrink-0 border-b border-border bg-surface px-8 py-6">
        <h1 className="text-xl font-semibold text-text">AI 视频</h1>
        <p className="mt-1 text-sm text-text-muted">文生视频 / 图生视频</p>
      </div>

      <div className="px-8 py-6">
        <div className="max-w-3xl rounded-lg border border-border bg-surface-alt p-6">
          <div className="space-y-4">
            <div>
              <FieldLabel text="视频服务商" required />
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                {VIDEO_PROVIDERS.map((item) => {
                  const active = item.id === providerId;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setProviderId(item.id)}
                      className={`min-h-[96px] rounded-lg border px-4 py-3 text-left transition-all ${
                        active
                          ? 'border-border-strong bg-accent-soft text-text shadow-[0_0_22px_rgba(37,99,235,0.16)]'
                          : 'border-border bg-surface text-text-muted hover:border-border-strong hover:bg-hover'
                      }`}
                    >
                      <div className="text-sm font-semibold">{item.label}</div>
                      <div className="mt-1 text-xs leading-5 text-text-subtle">{item.description}</div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <FieldLabel text={provider.authLabel} required />
              <Input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={`${provider.authPlaceholder}，每次启动后需手动填写，不会保存到本地`}
                autoComplete="off"
              />
            </div>

            <div className="mb-3 rounded-xl border border-border bg-surface p-2">
              <div className="grid grid-cols-2 gap-2">
                <Button
                  type="button"
                  variant={managedMode ? 'primary' : 'quiet'}
                  onClick={() => { void handleGatewayModeChange('member'); }}
                  className="justify-center"
                >
                  会员模式
                </Button>
                <Button
                  type="button"
                  variant={!managedMode ? 'primary' : 'quiet'}
                  onClick={() => setGatewayMode('manual')}
                  className="justify-center"
                >
                  手动模式
                </Button>
              </div>
              <p className="mt-2 text-xs text-text-muted">
                会员模式会自动读取授权后台的网关配置；手动模式保留当前填写的视频服务商地址和密钥。
              </p>
            </div>

            <div>
              <FieldLabel text="API Base URL" required={providerId === 'custom'} />
              <Input
                value={apiBase}
                onChange={(event) => setApiBase(event.target.value)}
                placeholder="例如 https://dashscope.aliyuncs.com/api/v1"
              />
              {provider.docsUrl && (
                <a className="mt-1 inline-block text-xs text-accent hover:underline" href={provider.docsUrl} target="_blank" rel="noreferrer">
                  查看服务商文档
                </a>
              )}
            </div>

            <div>
              <FieldLabel text="视频模型" required />
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <Select
                  value={availableModels.some((item) => item.id === model) ? model : ''}
                  onChange={(event) => setModel(event.target.value)}
                  className="w-full"
                  disabled={availableModels.length === 0}
                >
                  <option value="">{availableModels.length > 0 ? '选择预设模型' : '暂无预设模型'}</option>
                  {availableModels.map((item) => (
                    <option key={item.id} value={item.id}>{item.label}</option>
                  ))}
                </Select>
                <Input
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  placeholder="也可以手动输入模型 ID"
                />
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setMode('t2v')}
                className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${mode === 't2v' ? 'bg-accent text-white' : 'border border-border bg-surface text-text'}`}
              >
                文生视频
              </button>
              <button
                onClick={() => setMode('i2v')}
                className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${mode === 'i2v' ? 'bg-accent text-white' : 'border border-border bg-surface text-text'}`}
              >
                图生视频
              </button>
            </div>

            <div>
              <FieldLabel text="提示词" required />
              <TextArea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={4}
                placeholder="描述你想要生成的视频..."
              />
            </div>

            {mode === 'i2v' && (
              <div>
                <FieldLabel text="首帧图片" />
                <div className="flex items-center gap-3">
                  <Button onClick={handlePickImage} variant="quiet">
                    {imageBase64 ? '已选择图片' : '选择图片'}
                  </Button>
                  {imagePreview && <img src={imagePreview} alt="preview" className="h-16 w-16 rounded object-cover" />}
                </div>
              </div>
            )}

            <div className="grid grid-cols-3 gap-4">
              <div>
                <FieldLabel text="分辨率" />
                <Select value={resolution} onChange={(event) => setResolution(event.target.value)} className="w-full">
                  {RESOLUTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                </Select>
              </div>
              <div>
                <FieldLabel text="时长" />
                <Select value={duration} onChange={(event) => setDuration(Number(event.target.value))} className="w-full">
                  {DURATIONS.map((item) => <option key={item} value={item}>{item}秒</option>)}
                </Select>
              </div>
              <div>
                <FieldLabel text="比例" />
                <Select value={ratio} onChange={(event) => setRatio(event.target.value)} className="w-full">
                  {RATIOS.map((item) => <option key={item} value={item}>{item}</option>)}
                </Select>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-4 flex gap-3">
          <Button onClick={handleGenerate} variant="primary" disabled={generating}>
            {generating ? '生成中...' : '生成视频'}
          </Button>
        </div>

        {generating && <Loading text={progress || '正在生成视频...'} />}

        {resultVideo && (
          <div className="mt-8 max-w-3xl">
            <video
              key={resultVideo.previewUrl}
              controls
              preload="metadata"
              className="aspect-video w-full rounded-lg border border-border bg-black"
              onError={() => setVideoError('视频已生成并保存，但当前播放器无法读取本地预览。请点击下载视频或打开保存目录查看。')}
            >
              <source src={resultVideo.previewUrl} type={resultVideo.mime || 'video/mp4'} />
            </video>

            <div className="mt-3 space-y-2 text-sm text-text-muted">
              <div>大小：{formatBytes(resultVideo.size)}</div>
              {resultVideo.path && <div className="break-all">保存路径：{resultVideo.path}</div>}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
              <a
                href={resultVideo.downloadUrl}
                download={resultVideo.filename || `openclaw-video-${Date.now()}.mp4`}
                onClick={handleDownloadClick}
                className="text-accent hover:underline"
              >
                下载视频
              </a>
              <Button onClick={handleSendToPublish} variant="default">
                去平台发布
              </Button>
              {resultVideo.directory && (
                <button onClick={handleOpenVideoDir} className="text-accent hover:underline">
                  打开保存目录
                </button>
              )}
            </div>

            {videoError && (
              <div className="mt-3 rounded-md border border-status-danger/30 bg-status-danger/10 px-4 py-3 text-sm text-status-danger">
                {videoError}
              </div>
            )}
          </div>
        )}

        {!resultVideo && !generating && (
          <div className="mt-8 py-12 text-center text-sm text-text-muted">
            生成结果将显示在这里
          </div>
        )}
      </div>
    </div>
  );
};
