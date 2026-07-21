import React from 'react';
import { convertFileSrc } from '@tauri-apps/api/core';
import { Button, FieldLabel, Input, Loading, Select, TextArea, showToast } from '../common';
import { configApi } from '../../services/api';
import { loadPhoneDevices, getSelectedPhoneConfig, phoneApi, type PhoneConnectionConfig } from '../../services/phoneApi';
import {
  buildPublishPrompt,
  buildReversePublishPacket,
  contentTypeLabel,
  DEFAULT_PUBLISH_ALBUM,
  getPublishPlatform,
  normalizeHashtagInput,
  type PublishAsset,
  type PublishContentType,
  type PublishPlatformId,
  type PublishTransportMode,
} from '../../services/publish';
import { usePublishHandoffStore } from '../../stores/publishStore';

const PUBLISH_CONFIG_PATH = 'data/.openclaw/launcher/publish.json';
const DEFAULT_TIMEOUT_SEC = 600;

interface PublishHistoryItem {
  id: number;
  platformLabel: string;
  transportMode: PublishTransportMode;
  status: 'draft' | 'uploading' | 'running' | 'success' | 'error' | 'packet';
  startedAt: string;
  finishedAt?: string;
  summary?: string;
  error?: string;
  mediaCount: number;
}

function platformIdFromValue(value: unknown): PublishPlatformId {
  const text = String(value || '').trim().toLowerCase();
  if (text === 'x' || text === 'xiaohongshu' || text === 'douyin' || text === 'wechat' || text === 'custom') {
    return text as PublishPlatformId;
  }
  return 'xiaohongshu';
}

function transportFromValue(value: unknown): PublishTransportMode {
  return String(value || '').trim().toLowerCase() === 'reverse' ? 'reverse' : 'direct';
}

function contentTypeFromValue(value: unknown): PublishContentType {
  const text = String(value || '').trim().toLowerCase();
  if (text === 'text' || text === 'image' || text === 'video' || text === 'mixed') return text as PublishContentType;
  return 'mixed';
}

function toDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
    reader.onload = () => resolve(String(reader.result || ''));
    reader.readAsDataURL(file);
  });
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Failed to read local media'));
    reader.onload = () => resolve(String(reader.result || ''));
    reader.readAsDataURL(blob);
  });
}

function isVideoFile(file: File): boolean {
  return file.type.startsWith('video/') || /\.(mp4|webm|mov|mkv)$/i.test(file.name);
}

function assetKind(file: File): PublishAsset['kind'] {
  return isVideoFile(file) ? 'video' : 'image';
}

async function resolveAssetDataUrl(asset: PublishAsset): Promise<string> {
  if (asset.dataUrl) return asset.dataUrl;
  if (!asset.sourcePath) return '';
  const response = await fetch(convertFileSrc(asset.sourcePath));
  if (!response.ok) {
    throw new Error(`Failed to load ${asset.name}`);
  }
  return blobToDataUrl(await response.blob());
}

export const PublishPage: React.FC = () => {
  const seedDraft = usePublishHandoffStore((state) => state.draftSeed);
  const [loading, setLoading] = React.useState<'config' | 'upload' | 'publish' | null>('config');
  const [phoneDevices, setPhoneDevices] = React.useState<PhoneConnectionConfig[]>([]);
  const [platformId, setPlatformId] = React.useState<PublishPlatformId>('xiaohongshu');
  const [transportMode, setTransportMode] = React.useState<PublishTransportMode>('direct');
  const [contentType, setContentType] = React.useState<PublishContentType>('image');
  const [title, setTitle] = React.useState('');
  const [body, setBody] = React.useState('');
  const [hashtagsText, setHashtagsText] = React.useState('');
  const [phoneAlbum, setPhoneAlbum] = React.useState(DEFAULT_PUBLISH_ALBUM);
  const [sendToPhoneAlbum, setSendToPhoneAlbum] = React.useState(true);
  const [selectedDeviceId, setSelectedDeviceId] = React.useState('');
  const [reverseRelayUrl, setReverseRelayUrl] = React.useState('');
  const [reverseRelayToken, setReverseRelayToken] = React.useState('');
  const [reverseChannelId, setReverseChannelId] = React.useState('');
  const [notes, setNotes] = React.useState('');
  const [assets, setAssets] = React.useState<PublishAsset[]>([]);
  const [statusText, setStatusText] = React.useState('');
  const [previewText, setPreviewText] = React.useState('');
  const [history, setHistory] = React.useState<PublishHistoryItem[]>([]);
  const [jobSeq, setJobSeq] = React.useState(0);

  const selectedPlatform = React.useMemo(() => getPublishPlatform(platformId), [platformId]);
  const selectedDevice = React.useMemo(
    () => phoneDevices.find((device) => device.id === selectedDeviceId) || null,
    [phoneDevices, selectedDeviceId]
  );
  const normalizedHashtags = React.useMemo(() => normalizeHashtagInput(hashtagsText), [hashtagsText]);
  const draftPreview = React.useMemo(() => ({
    platformId,
    transportMode,
    contentType,
    title,
    body,
    hashtags: normalizedHashtags,
    assets,
    phoneAlbum,
    sendToPhoneAlbum,
    selectedDeviceId,
    reverseRelayUrl,
    reverseRelayToken,
    reverseChannelId,
    notes,
  }), [
    assets,
    body,
    contentType,
    hashtagsText,
    notes,
    phoneAlbum,
    platformId,
    reverseChannelId,
    reverseRelayUrl,
    reverseRelayToken,
    selectedDeviceId,
    sendToPhoneAlbum,
    title,
    transportMode,
    normalizedHashtags,
  ]);

  React.useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [configResp, devices] = await Promise.all([
          configApi.read(PUBLISH_CONFIG_PATH, {}),
          Promise.resolve(loadPhoneDevices()),
        ]);
        if (cancelled) return;

        const stored = configResp.data && typeof configResp.data === 'object' ? configResp.data as Record<string, any> : {};
        const storedPlatform = platformIdFromValue(stored.platformId || stored.platform || 'xiaohongshu');
        const nextPlatform = storedPlatform;
        setPlatformId(nextPlatform);
        setTransportMode(transportFromValue(stored.transportMode || stored.transport));
        setContentType(contentTypeFromValue(stored.contentType || getPublishPlatform(nextPlatform).defaultContentType));
        setTitle(String(stored.title || ''));
        setBody(String(stored.body || stored.caption || ''));
        setHashtagsText(Array.isArray(stored.hashtags) ? stored.hashtags.join('\n') : String(stored.hashtags || ''));
        setPhoneAlbum(String(stored.phoneAlbum || DEFAULT_PUBLISH_ALBUM));
        setSendToPhoneAlbum(stored.sendToPhoneAlbum !== false);
        setSelectedDeviceId(String(stored.selectedDeviceId || devices.find((item) => item.id)?.id || getSelectedPhoneConfig()?.id || '').trim());
        setReverseRelayUrl(String(stored.reverseRelayUrl || '').trim());
        setReverseRelayToken(String(stored.reverseRelayToken || '').trim());
        setReverseChannelId(String(stored.reverseChannelId || '').trim());
        setNotes(String(stored.notes || '').trim());
        setPhoneDevices(devices);
      } catch {
        setPhoneDevices(loadPhoneDevices());
        const selected = getSelectedPhoneConfig();
        setSelectedDeviceId(selected.id || '');
      } finally {
        if (!cancelled) setLoading(null);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  React.useEffect(() => {
    if (transportMode === 'reverse') {
      setSendToPhoneAlbum(false);
    }
  }, [transportMode]);

  React.useEffect(() => {
    if (seedDraft && seedDraft.assets?.length) {
      setPlatformId(seedDraft.platformId);
      setTransportMode(seedDraft.transportMode);
      setContentType(seedDraft.contentType);
      setTitle(seedDraft.title || '');
      setBody(seedDraft.body || '');
      setHashtagsText((seedDraft.hashtags || []).join('\n'));
      setPhoneAlbum(seedDraft.phoneAlbum || DEFAULT_PUBLISH_ALBUM);
      setSendToPhoneAlbum(seedDraft.sendToPhoneAlbum !== false);
      setSelectedDeviceId(seedDraft.selectedDeviceId || selectedDeviceId);
      setReverseRelayUrl(seedDraft.reverseRelayUrl || '');
      setReverseRelayToken(seedDraft.reverseRelayToken || '');
      setReverseChannelId(seedDraft.reverseChannelId || '');
      setNotes(seedDraft.notes || '');
      setAssets(seedDraft.assets || []);
      setStatusText('已载入最近生成素材');
      showToast('已载入最近生成素材', 'success');
    }
  }, [seedDraft]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveConfig = React.useCallback(async () => {
    await configApi.write(PUBLISH_CONFIG_PATH, {
      platformId,
      transportMode,
      contentType,
      title,
      body,
      hashtags: normalizedHashtags,
      phoneAlbum,
      sendToPhoneAlbum,
      selectedDeviceId,
      reverseRelayUrl,
      reverseRelayToken,
      reverseChannelId,
      notes,
      updatedAt: new Date().toISOString(),
    });
  }, [
    body,
    contentType,
    hashtagsText,
    notes,
    normalizedHashtags,
    phoneAlbum,
    platformId,
    reverseChannelId,
    reverseRelayUrl,
    reverseRelayToken,
    selectedDeviceId,
    sendToPhoneAlbum,
    title,
    transportMode,
  ]);

  const handlePickAssets = React.useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = 'image/*,video/*';
    input.onchange = async (event) => {
      const files = Array.from((event.target as HTMLInputElement).files || []);
      if (!files.length) return;
      const added: PublishAsset[] = [];
      for (const file of files) {
        try {
          const dataUrl = await toDataUrl(file);
          added.push({
            id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
            kind: assetKind(file),
            name: file.name,
            mime: file.type || (isVideoFile(file) ? 'video/mp4' : 'image/png'),
            dataUrl,
            size: file.size,
            sourcePath: file.name,
          });
        } catch {
          // skip broken files
        }
      }
      if (added.length) {
        setAssets((current) => [...current, ...added].slice(0, 6));
        setStatusText(`已添加 ${added.length} 个素材`);
        showToast(`已添加 ${added.length} 个素材`, 'success');
      }
    };
    input.click();
  }, []);

  const handleUseSeed = React.useCallback(() => {
    if (!seedDraft) {
      showToast('没有可用的最近素材', 'info');
      return;
    }
    setPlatformId(seedDraft.platformId);
    setTransportMode(seedDraft.transportMode);
    setContentType(seedDraft.contentType);
    setTitle(seedDraft.title || '');
    setBody(seedDraft.body || '');
    setHashtagsText((seedDraft.hashtags || []).join('\n'));
    setPhoneAlbum(seedDraft.phoneAlbum || DEFAULT_PUBLISH_ALBUM);
    setSendToPhoneAlbum(seedDraft.sendToPhoneAlbum !== false);
    setSelectedDeviceId(seedDraft.selectedDeviceId || selectedDeviceId);
    setReverseRelayUrl(seedDraft.reverseRelayUrl || '');
    setReverseRelayToken(seedDraft.reverseRelayToken || '');
    setReverseChannelId(seedDraft.reverseChannelId || '');
    setNotes(seedDraft.notes || '');
    setAssets(seedDraft.assets || []);
    setStatusText('已使用最近生成素材');
    showToast('已使用最近生成素材', 'success');
  }, [seedDraft, selectedDeviceId]);

  const removeAsset = React.useCallback((assetId: string) => {
    setAssets((current) => current.filter((asset) => asset.id !== assetId));
  }, []);

  const updatePlatform = React.useCallback((nextPlatformId: PublishPlatformId) => {
    setPlatformId(nextPlatformId);
    setContentType(getPublishPlatform(nextPlatformId).defaultContentType);
  }, []);

  const persistJobHistory = React.useCallback((patch: Partial<PublishHistoryItem> & { id: number }) => {
    setHistory((items) => items.map((item) => (item.id === patch.id ? ({ ...item, ...patch } as PublishHistoryItem) : item)));
  }, []);

  const handlePublish = React.useCallback(async () => {
    const jobId = jobSeq + 1;
    setJobSeq(jobId);
    const platform = getPublishPlatform(platformId);
    const draft = {
      ...draftPreview,
      transportMode,
      assets,
    };

    if (!title.trim() && !body.trim() && !assets.length) {
      showToast('请至少填写标题、正文或素材', 'error');
      return;
    }
    if (transportMode === 'direct' && !selectedDevice?.baseUrl.trim()) {
      showToast('请先选择一个已配置的手机设备', 'error');
      return;
    }

    const startedAt = new Date().toISOString();
    const initialStatus: PublishHistoryItem['status'] = transportMode === 'reverse' ? 'packet' : 'draft';
    setHistory((items) => [
      {
        id: jobId,
        platformLabel: platform.label,
        transportMode,
        status: initialStatus,
        startedAt,
        mediaCount: assets.length,
      },
      ...items,
    ].slice(0, 8));

    setLoading(transportMode === 'reverse' ? 'publish' : 'upload');
    setStatusText(transportMode === 'reverse' ? '正在生成反向发布包...' : '正在准备发布任务...');

    try {
      await saveConfig();

      if (transportMode === 'reverse') {
        const packet = buildReversePublishPacket(draft, assets);
        const packetText = `${JSON.stringify(packet, null, 2)}\n`;
        setPreviewText(packetText);
        await navigator.clipboard.writeText(packetText);
        if (reverseRelayUrl.trim()) {
          const headers: Record<string, string> = { 'Content-Type': 'application/json' };
          if (reverseRelayToken.trim()) {
            headers.Authorization = `Bearer ${reverseRelayToken.trim()}`;
            headers['X-OpenClaw-Relay-Token'] = reverseRelayToken.trim();
          }
          const response = await fetch(reverseRelayUrl.trim(), {
            method: 'POST',
            headers,
            body: packetText,
          });
          if (!response.ok) {
            throw new Error(`Relay rejected packet: ${response.status}`);
          }
        }
        const finishedAt = new Date().toISOString();
        persistJobHistory({
          id: jobId,
          status: 'packet',
          finishedAt,
          summary: '反向发布包已复制到剪贴板',
        });
        setStatusText('反向发布包已生成并复制到剪贴板');
        showToast('反向发布包已生成', 'success');
        return;
      }

      const phoneConfig = selectedDevice || getSelectedPhoneConfig(selectedDeviceId || null);
      const mediaRefs: Array<{
        kind: PublishAsset['kind'];
        name: string;
        mime?: string;
        size?: number;
        sourcePath?: string;
        uploadedPath?: string;
        uploadedRelativePath?: string;
        album?: string;
      }> = [];

      if (sendToPhoneAlbum && assets.length) {
        for (const asset of assets) {
          setStatusText(`正在上传素材到手机：${asset.name}`);
          const dataUrl = await resolveAssetDataUrl(asset);
          const uploadResult = asset.kind === 'video'
            ? await phoneApi.importVideoDataUrl(phoneConfig, dataUrl, {
                album: phoneAlbum || DEFAULT_PUBLISH_ALBUM,
                filename: asset.name,
              })
            : await phoneApi.importImageDataUrl(phoneConfig, dataUrl, {
                album: phoneAlbum || DEFAULT_PUBLISH_ALBUM,
                filename: asset.name,
              });
          if (!uploadResult.ok || !uploadResult.data) {
            throw new Error(uploadResult.error || `上传素材失败：${asset.name}`);
          }
          const data = uploadResult.data;
          mediaRefs.push({
            kind: asset.kind,
            name: asset.name,
            mime: asset.mime,
            size: asset.size,
            sourcePath: asset.sourcePath,
            uploadedPath: data.path || '',
            uploadedRelativePath: data.relativePath || data.path || '',
            album: phoneAlbum || DEFAULT_PUBLISH_ALBUM,
          });
        }
      } else {
        mediaRefs.push(...assets.map((asset) => ({
          kind: asset.kind,
          name: asset.name,
          mime: asset.mime,
          size: asset.size,
          sourcePath: asset.sourcePath,
        })));
      }

      const prompt = buildPublishPrompt({
        ...draft,
        hashtags: normalizedHashtags,
      }, mediaRefs);
      setPreviewText(prompt);
      setStatusText(`正在提交 ${platform.label} 发布任务...`);
      persistJobHistory({
        id: jobId,
        status: 'running',
        summary: `提交到 ${platform.label}`,
      });

      const result = await phoneApi.executeTask(phoneConfig, {
        prompt,
        useTemplate: false,
        forceAgent: true,
        learnTemplate: false,
        readOnly: false,
        toolPolicy: 'safe_action',
        timeoutSec: DEFAULT_TIMEOUT_SEC,
      });
      const finishedAt = new Date().toISOString();
      if (!result.ok || !result.data) {
        const message = result.error || '发布任务失败';
        persistJobHistory({
          id: jobId,
          status: 'error',
          finishedAt,
          error: message,
        });
        setStatusText(`发布失败：${message}`);
        showToast(`发布失败：${message}`, 'error');
        return;
      }

      const answer = result.data.answer || '发布任务已完成';
      persistJobHistory({
        id: jobId,
        status: 'success',
        finishedAt,
        summary: answer,
      });
      setStatusText(answer);
      showToast('发布任务已提交并完成', 'success');
    } catch (error: any) {
      const message = error?.error || error?.message || '发布失败';
      const finishedAt = new Date().toISOString();
      persistJobHistory({
        id: jobId,
        status: 'error',
        finishedAt,
        error: message,
      });
      setStatusText(message);
      showToast(message, 'error');
    } finally {
      setLoading(null);
    }
  }, [
    assets,
    body,
    draftPreview,
    jobSeq,
    normalizedHashtags,
    phoneAlbum,
    phoneDevices,
    platformId,
    persistJobHistory,
    saveConfig,
    seedDraft,
    selectedDevice,
    selectedDeviceId,
    sendToPhoneAlbum,
    title,
    transportMode,
    reverseRelayUrl,
    reverseRelayToken,
  ]);

  const previewPacketOrPrompt = React.useMemo(() => {
    if (transportMode === 'reverse') {
      return `${JSON.stringify(buildReversePublishPacket({
        ...draftPreview,
        hashtags: normalizedHashtags,
      }, assets), null, 2)}\n`;
    }
    return buildPublishPrompt({
      ...draftPreview,
      hashtags: normalizedHashtags,
    }, assets.map((asset) => ({
      kind: asset.kind,
      name: asset.name,
      mime: asset.mime,
      size: asset.size,
      sourcePath: asset.sourcePath,
      uploadedPath: asset.uploadedPath,
      uploadedRelativePath: asset.uploadedRelativePath,
      album: phoneAlbum || DEFAULT_PUBLISH_ALBUM,
    })));
  }, [assets, draftPreview, normalizedHashtags, phoneAlbum, transportMode]);

  React.useEffect(() => {
    setPreviewText(previewPacketOrPrompt);
  }, [previewPacketOrPrompt]);

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-surface">
      <div className="shrink-0 border-b border-border bg-surface px-8 py-6">
        <h1 className="text-xl font-semibold text-text">平台发布</h1>
        <p className="mt-1 text-sm text-text-muted">把生成好的图文 / 视频整理成一次真实的发布任务，支持直连手机和反向任务包两种模式。</p>
      </div>

      <div className="flex-1 px-8 py-6">
        {loading === 'config' ? (
          <Loading text="正在加载发布配置..." />
        ) : (
          <div className="space-y-6">
            <section className="rounded-[16px] border border-border bg-surface-alt/30 p-5">
              <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(340px,0.9fr)]">
                <div className="space-y-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel text="平台" required />
                      <Select value={platformId} onChange={(event) => updatePlatform(platformIdFromValue(event.target.value))} className="w-full">
                        {(['xiaohongshu', 'douyin', 'x', 'wechat', 'custom'] as PublishPlatformId[]).map((item) => (
                          <option key={item} value={item}>{getPublishPlatform(item).label}</option>
                        ))}
                      </Select>
                    </div>
                    <div>
                      <FieldLabel text="传输模式" required />
                      <Select value={transportMode} onChange={(event) => setTransportMode(transportFromValue(event.target.value))} className="w-full">
                        <option value="direct">直连手机</option>
                        <option value="reverse">反向任务包</option>
                      </Select>
                    </div>
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel text="内容类型" required />
                      <Select value={contentType} onChange={(event) => setContentType(contentTypeFromValue(event.target.value))} className="w-full">
                        <option value="text">纯文本</option>
                        <option value="image">图文</option>
                        <option value="video">视频</option>
                        <option value="mixed">混合</option>
                      </Select>
                    </div>
                    <div>
                      <FieldLabel text="目标设备" required={transportMode === 'direct'} />
                      <Select
                        value={selectedDeviceId}
                        onChange={(event) => setSelectedDeviceId(event.target.value)}
                        className="w-full"
                        disabled={transportMode === 'reverse'}
                      >
                        <option value="">自动选择当前设备</option>
                        {phoneDevices.map((device) => (
                          <option key={device.id || device.baseUrl} value={device.id}>
                            {device.name || device.id || device.baseUrl}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </div>

                  <div>
                    <FieldLabel text="标题" />
                    <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="帖子标题、视频标题、或者留空" />
                  </div>

                  <div>
                    <FieldLabel text="发布文案" />
                    <TextArea
                      value={body}
                      onChange={(event) => setBody(event.target.value)}
                      placeholder="正文、说明、商品文案、话题说明"
                      rows={7}
                    />
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <FieldLabel text="话题标签" />
                      <TextArea
                        value={hashtagsText}
                        onChange={(event) => setHashtagsText(event.target.value)}
                        placeholder="#OpenClaw\n#AI创作"
                        rows={5}
                      />
                    </div>
                    <div>
                      <FieldLabel text="补充说明" />
                      <TextArea
                        value={notes}
                        onChange={(event) => setNotes(event.target.value)}
                        placeholder="例如：必须先检查封面、不要自动生成新素材、需要保留草稿等"
                        rows={5}
                      />
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="rounded-[16px] border border-border bg-surface/60 p-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-black text-text">平台提示</div>
                        <div className="text-xs text-text-muted">{selectedPlatform.description}</div>
                      </div>
                      {seedDraft?.assets?.length ? (
                        <Button onClick={handleUseSeed} variant="quiet">载入最近素材</Button>
                      ) : null}
                    </div>
                    <div className="rounded-[14px] border border-border bg-input/70 px-4 py-3 text-xs leading-6 text-text-muted">
                      <div className="font-semibold text-text">{selectedPlatform.appName}</div>
                      <div className="mt-1">{selectedPlatform.promptHint}</div>
                      <div className="mt-2">推荐素材：{selectedPlatform.preferredAssetKinds.join(' / ')}</div>
                      <div className="mt-1">是否允许纯文本：{selectedPlatform.allowsTextOnly ? '是' : '否'}</div>
                    </div>
                  </div>

                  <div className="rounded-[16px] border border-border bg-surface/60 p-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-black text-text">素材</div>
                        <div className="text-xs text-text-muted">可从本地导入图片 / 视频，也可以直接复用最近的生成结果。</div>
                      </div>
                      <Button onClick={handlePickAssets} variant="quiet">选择素材</Button>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <div>
                        <FieldLabel text="手机相册" />
                        <Input value={phoneAlbum} onChange={(event) => setPhoneAlbum(event.target.value)} placeholder={DEFAULT_PUBLISH_ALBUM} />
                      </div>
                      <div>
                        <FieldLabel text="最近素材接入" />
                        <label className="flex h-[42px] items-center justify-between rounded-xl border border-border bg-input px-3 text-sm text-text">
                          <span>发送到手机相册</span>
                          <input
                            type="checkbox"
                            checked={sendToPhoneAlbum}
                            onChange={(event) => setSendToPhoneAlbum(event.target.checked)}
                            disabled={transportMode === 'reverse'}
                          />
                        </label>
                      </div>
                    </div>

                    <div className="mt-4 grid gap-3">
                      {assets.length ? assets.map((asset) => (
                        <div key={asset.id} className="rounded-[14px] border border-border bg-surface-alt/50 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="truncate text-sm font-semibold text-text">{asset.name}</div>
                              <div className="mt-0.5 text-xs text-text-muted">{asset.kind} / {asset.mime || 'unknown'} / {asset.size ? `${Math.round(asset.size / 1024)} KB` : 'size unknown'}</div>
                            </div>
                            <Button onClick={() => removeAsset(asset.id)} variant="quiet">移除</Button>
                          </div>
                          {asset.kind === 'image' ? (
                            <img src={asset.dataUrl} alt={asset.name} className="mt-3 max-h-56 w-full rounded-xl border border-border object-cover" />
                          ) : (
                            <video controls src={asset.dataUrl} className="mt-3 max-h-56 w-full rounded-xl border border-border bg-black" />
                          )}
                        </div>
                      )) : (
                        <div className="rounded-[14px] border border-dashed border-border bg-surface/40 px-4 py-6 text-sm text-text-muted">
                          暂无素材。可直接选择本地文件，也可以从图片 / 视频页面先生成后再带入。
                        </div>
                      )}
                    </div>

                    {transportMode === 'reverse' && (
                      <div className="mt-4 grid gap-4 md:grid-cols-2">
                        <div>
                          <FieldLabel text="反向 Relay URL" required />
                          <Input value={reverseRelayUrl} onChange={(event) => setReverseRelayUrl(event.target.value)} placeholder="https://relay.example.com/api/lumi/publish/packet" />
                        </div>
                        <div>
                          <FieldLabel text="反向频道" required />
                          <Input value={reverseChannelId} onChange={(event) => setReverseChannelId(event.target.value)} placeholder="publish-channel-01" />
                        </div>
                        <div className="md:col-span-2">
                          <FieldLabel text="Relay Token" />
                          <Input value={reverseRelayToken} onChange={(event) => setReverseRelayToken(event.target.value)} placeholder="公网 relay 建议填写共享 token" />
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </section>

            <section className="rounded-[16px] border border-border bg-surface-alt/30 p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-black text-text">任务预览</div>
                  <div className="mt-0.5 text-xs text-text-muted">
                    {transportMode === 'direct'
                      ? '直连模式会把素材上传到手机，再通过 APKClaw 直接执行发布任务。'
                      : '反向模式只生成可传递给回连客户端的任务包。'}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => navigator.clipboard.writeText(previewText || '')} variant="quiet">复制预览</Button>
                  <Button onClick={handlePublish} variant="primary" disabled={loading === 'upload' || loading === 'publish'}>
                    {loading === 'upload' || loading === 'publish'
                      ? '处理中...'
                      : transportMode === 'reverse'
                        ? '生成发布包'
                        : '开始发布'}
                  </Button>
                </div>
              </div>

              <TextArea
                value={previewText}
                readOnly
                rows={14}
                className="mt-4 font-mono text-xs leading-6"
              />

              <div className="mt-3 text-xs text-text-muted">
                预览里会显示 {transportMode === 'reverse' ? '反向发布包 JSON' : '实际发送给手机 Agent 的发布指令'}。
              </div>
            </section>

            <section className="rounded-[16px] border border-border bg-surface-alt/30 p-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-black text-text">执行状态</div>
                  <div className="mt-0.5 text-xs text-text-muted">{statusText || '等待开始发布'}</div>
                </div>
                <div className="text-xs text-text-subtle">
                  {selectedDevice ? `${selectedDevice.name || selectedDevice.id || '当前设备'}` : '自动设备'}
                </div>
              </div>

              <div className="mt-4 grid gap-3">
                {history.map((item) => (
                  <div key={item.id} className="rounded-[14px] border border-border bg-surface/60 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-text">
                          {item.platformLabel} · {item.transportMode === 'direct' ? '直连' : '反向'}
                        </div>
                        <div className="mt-0.5 text-xs text-text-muted">
                          {item.mediaCount} 个素材 · {new Date(item.startedAt).toLocaleString('zh-CN', { hour12: false })}
                          {item.finishedAt ? ` · ${new Date(item.finishedAt).toLocaleString('zh-CN', { hour12: false })}` : ''}
                        </div>
                      </div>
                      <div className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                        item.status === 'success'
                          ? 'border-status-success/35 text-status-success'
                          : item.status === 'error'
                            ? 'border-status-danger/35 text-status-danger'
                            : item.status === 'packet'
                              ? 'border-accent/35 text-accent'
                              : 'border-border text-text-muted'
                      }`}>
                        {item.status === 'success' ? '已完成' : item.status === 'error' ? '失败' : item.status === 'packet' ? '已生成包' : '进行中'}
                      </div>
                    </div>
                    {item.summary && <div className="mt-2 text-xs leading-5 text-text-muted">{item.summary}</div>}
                    {item.error && <div className="mt-2 text-xs leading-5 text-status-danger">{item.error}</div>}
                  </div>
                ))}

                {!history.length && (
                  <div className="rounded-[14px] border border-dashed border-border bg-surface/40 px-4 py-6 text-sm text-text-muted">
                    还没有发布记录。完成一次任务后，这里会显示执行结果与错误原因。
                  </div>
                )}
              </div>
            </section>

            <section className="rounded-[16px] border border-border bg-surface-alt/30 p-5">
              <div className="text-sm font-black text-text">当前草稿摘要</div>
              <div className="mt-2 whitespace-pre-wrap text-xs leading-6 text-text-muted">
                {[
                  `平台: ${selectedPlatform.label}`,
                  `内容类型: ${contentTypeLabel(contentType)}`,
                  title.trim() ? `标题: ${title.trim()}` : '标题: -',
                  body.trim() ? `正文: ${body.trim()}` : '正文: -',
                  normalizedHashtags.length ? `话题: ${normalizedHashtags.map((tag) => `#${tag}`).join(' ')}` : '话题: -',
                  `素材: ${assets.length}`,
                  `模式: ${transportMode === 'direct' ? '直连手机' : '反向任务包'}`,
                  transportMode === 'direct' ? `手机相册: ${phoneAlbum || DEFAULT_PUBLISH_ALBUM}` : `Relay: ${reverseRelayUrl || '-'}`,
                  `补充说明: ${notes || '-'}`,
                ].join('\n')}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
};
