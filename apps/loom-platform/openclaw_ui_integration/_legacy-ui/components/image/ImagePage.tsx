import React, { useState } from 'react';
import { Button, Input, TextArea, Select, Loading, showToast, FieldLabel } from '../common';
import { imageApi, configApi } from '../../services/api';
import { loadPhoneConfig, phoneApi } from '../../services/phoneApi';
import { useLogStore } from '../../stores/logStore';
import { useAppStore } from '../../stores/appStore';
import { getDefaultPublishDraftSeed, usePublishHandoffStore } from '../../stores/publishStore';
import { readGatewayStoredConfig, readMemberGatewayDefaults, type GatewayMode } from '../../services/gatewayConfig';

const SIZES = ['1024x1024', '1024x1536', '1536x1024', '512x512'];
const IMAGE_CONFIG_PATH = 'imgapi_config.json';

export const ImagePage: React.FC = () => {
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [prompt, setPrompt] = useState('');
  const [size, setSize] = useState('1024x1024');
  const [editImage, setEditImage] = useState<string | null>(null);
  const [gatewayMode, setGatewayMode] = useState<GatewayMode>('manual');
  const [generating, setGenerating] = useState(false);
  const [tripleGenerating, setTripleGenerating] = useState(false);
  const [resultImage, setResultImage] = useState<string | null>(null);
  const [resultFile, setResultFile] = useState<string | null>(null);
  const [tripleResults, setTripleResults] = useState<(string | null)[]>([null, null, null]);
  const [tripleStatus, setTripleStatus] = useState('');
  const [sendToPhone, setSendToPhone] = useState(true);
  const [phoneSyncStatus, setPhoneSyncStatus] = useState('');

  const appendLog = useLogStore((s) => s.append);
  const setCurrentPage = useAppStore((state) => state.setCurrentPage);
  const setPublishDraftSeed = usePublishHandoffStore((state) => state.setDraftSeed);
  const managedMode = gatewayMode === 'member';

  const loadConfig = async () => {
    let storedMode: GatewayMode | null = null;
    let storedBaseUrl = '';
    let storedApiKey = '';

    try {
      const resp = await configApi.read(IMAGE_CONFIG_PATH, {});
      const stored = readGatewayStoredConfig(resp.data);
      storedMode = stored.mode;
      storedBaseUrl = stored.baseUrl;
      storedApiKey = stored.apiKey;
    } catch (e) {
      appendLog('[生图] 读取配置失败: ' + e + '\n');
    }

    try {
      const memberGateway = await readMemberGatewayDefaults();

      if (storedMode === 'member') {
        setGatewayMode('member');
        setBaseUrl(memberGateway.imageBaseUrl || memberGateway.baseUrl || storedBaseUrl);
        setApiKey(memberGateway.imageApiKey || memberGateway.apiKey || storedApiKey);
        return;
      }

      if (storedMode === 'manual') {
        setGatewayMode('manual');
        setBaseUrl(storedBaseUrl);
        setApiKey(storedApiKey);
        return;
      }

      if (storedBaseUrl || storedApiKey) {
        setGatewayMode('manual');
        setBaseUrl(storedBaseUrl);
        setApiKey(storedApiKey);
        return;
      }

      if (memberGateway.hasGateway) {
        setGatewayMode('member');
        setBaseUrl(memberGateway.imageBaseUrl || memberGateway.baseUrl);
        setApiKey(memberGateway.imageApiKey || memberGateway.apiKey);
      }
    } catch {
      if (storedBaseUrl || storedApiKey) {
        setGatewayMode('manual');
        setBaseUrl(storedBaseUrl);
        setApiKey(storedApiKey);
      }
    }
  };

  React.useEffect(() => { loadConfig(); }, []);

  const saveConfig = async () => {
    try {
      await configApi.write(IMAGE_CONFIG_PATH, {
        gatewayMode,
        managedMode,
        baseUrl: baseUrl.trim(),
        apiKey: apiKey.trim(),
      });
    } catch (e) {
      appendLog('[生图] 保存配置失败: ' + e + '\n');
    }
  };

  const handleGatewayModeChange = async (nextMode: GatewayMode) => {
    setGatewayMode(nextMode);
    if (nextMode !== 'member') return;

    try {
      const memberGateway = await readMemberGatewayDefaults();
      if (memberGateway.hasGateway) {
        setBaseUrl(memberGateway.imageBaseUrl || memberGateway.baseUrl);
        setApiKey(memberGateway.imageApiKey || memberGateway.apiKey);
      }
    } catch {
      // keep current manual values if the license lookup fails
    }
  };

  const handleGenerate = async () => {
    if ((!baseUrl && !managedMode) || !prompt) {
      showToast('请填写中转站地址和提示词', 'error');
      return;
    }
    setGenerating(true);
    setResultImage(null);
    setResultFile(null);
    setPhoneSyncStatus('');
    try {
      await saveConfig();
      const resp = await imageApi.generate({ baseUrl: baseUrl.trim(), apiKey: apiKey.trim(), prompt, size, count: 1, editImagePath: editImage || undefined });
      if (resp.images?.[0]) {
        const dataUrl = `data:image/png;base64,${resp.images[0]}`;
        const file = resp.files?.[0];
        setResultImage(dataUrl);
        setResultFile(file?.path || null);
        showToast('图片生成成功', 'success');
        appendLog(`[生图] 单图生成成功${file?.path ? `：${file.path}` : ''}\n`);
        await maybeSendImageToPhone(dataUrl, file?.filename || `openclaw-image-${Date.now()}.png`);
      }
    } catch (e: any) {
      showToast(e?.error || '生成失败', 'error');
      appendLog(`[生图] 失败: ${e?.error}\n`);
    } finally {
      setGenerating(false);
    }
  };

  const handleSendToPublish = () => {
    if (!resultImage) return;
    const name = resultFile?.split(/[\\/]/).pop() || `openclaw-image-${Date.now()}.png`;
    setPublishDraftSeed({
      ...getDefaultPublishDraftSeed(),
      platformId: 'xiaohongshu',
      transportMode: 'direct',
      contentType: 'image',
      title: prompt.trim().slice(0, 60) || 'OpenClaw 图文发布',
      body: prompt.trim(),
      hashtags: ['OpenClaw', 'AI创作'],
      assets: [{
        id: `image-${Date.now()}`,
        kind: 'image',
        name,
        mime: 'image/png',
        dataUrl: resultImage,
        sourcePath: resultFile || undefined,
      }],
    });
    setCurrentPage('publish');
  };

  const TRIPLE_PROMPTS = [
    { label: '主图', prefix: 'product photography, hero shot, studio lighting, clean background, professional product photo' },
    { label: '白底图', prefix: 'pure white background, clean product photography, studio lighting, commercial product shot on white' },
    { label: '详情图', prefix: 'product detail closeup, high quality product photography, texture detail, professional lighting' },
  ];

  const handleTripleGenerate = async () => {
    if ((!baseUrl && !managedMode) || !prompt) {
      showToast('请填写中转站地址和提示词', 'error');
      return;
    }
    setTripleGenerating(true);
    setTripleResults([null, null, null]);
    setPhoneSyncStatus('');
    await saveConfig();

    for (let i = 0; i < 3; i++) {
      setTripleStatus(`生成中: ${i + 1}/3 - ${TRIPLE_PROMPTS[i].label}`);
      try {
        const fullPrompt = `${prompt}\n${TRIPLE_PROMPTS[i].prefix}`;
        const resp = await imageApi.generate({ baseUrl: baseUrl.trim(), apiKey: apiKey.trim(), prompt: fullPrompt, size, count: 1 });
        if (resp.images?.[0]) {
          const dataUrl = `data:image/png;base64,${resp.images[0]}`;
          const file = resp.files?.[0];
          setTripleResults((prev) => { const n = [...prev]; n[i] = dataUrl; return n; });
          appendLog(`[生图] ${TRIPLE_PROMPTS[i].label} 已保存${file?.path ? `：${file.path}` : ''}\n`);
          await maybeSendImageToPhone(dataUrl, file?.filename || `openclaw-${TRIPLE_PROMPTS[i].label}-${Date.now()}.png`);
        }
      } catch (e: any) {
        setTripleResults((prev) => { const n = [...prev]; n[i] = `error:${e?.error}`; return n; });
      }
    }
    setTripleStatus('');
    showToast('三图生成完成', 'success');
  };

  const maybeSendImageToPhone = async (dataUrl: string, filename: string) => {
    if (!sendToPhone) return;
    const phoneConfig = loadPhoneConfig();
    if (!phoneConfig.baseUrl.trim() || !phoneConfig.token.trim()) {
      setPhoneSyncStatus('手机未配置，图片已保存在本地');
      appendLog('[生图] 手机未配置，跳过相册同步\n');
      return;
    }

    setPhoneSyncStatus('正在发送到手机相册...');
    const result = await phoneApi.importImageDataUrl(phoneConfig, dataUrl, {
      album: 'OpenClaw',
      filename,
    });
    if (result.ok) {
      const phonePath = result.data?.relativePath || result.data?.path || '手机相册';
      setPhoneSyncStatus(`已发送到手机：${phonePath}`);
      appendLog(`[生图] 已发送到手机：${phonePath}\n`);
      showToast('已发送到手机相册', 'success');
    } else {
      setPhoneSyncStatus(`手机同步失败：${result.error || '未知错误'}`);
      appendLog(`[生图] 手机同步失败：${result.error || '未知错误'}\n`);
    }
  };

  const handlePickImage = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          setEditImage(ev.target?.result as string);
        };
        reader.readAsDataURL(file);
      }
    };
    input.click();
  };

  return (
    <div className="flex flex-col h-full bg-surface overflow-y-auto">
      <div className="flex-shrink-0 px-8 py-6 border-b border-border bg-surface">
        <h1 className="text-xl font-semibold text-text">AI 生图</h1>
        <p className="text-sm text-text-muted mt-1">生成或编辑图片</p>
      </div>

      {/* Form Card */}
      <div className="px-8 py-6">
        <div className="bg-surface-alt rounded-lg border border-border p-6 max-w-3xl">
          <div className="space-y-4">
            <div>
              <FieldLabel text="URL 链接" required />
              <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://..." />
              {managedMode && <div className="mt-1 text-xs text-status-success">已读取会员网关配置</div>}
            </div>
            <div>
              <FieldLabel text="API Key" />
              <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." />
            </div>
            <div className="flex gap-4 items-end">
              <div className="flex-1">
                <FieldLabel text="尺寸" />
                <Select value={size} onChange={(e) => setSize(e.target.value)} className="w-full">
                  {SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
                </Select>
              </div>
              <Button onClick={handlePickImage} variant="quiet">
                {editImage ? '已选图片' : '上传原图'}
              </Button>
              {editImage && (
                <Button onClick={() => setEditImage(null)} variant="quiet">清除</Button>
              )}
            </div>
            <label className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface px-3 py-2">
              <span>
                <span className="block text-sm font-semibold text-text">生成后发送手机相册</span>
                <span className="block text-xs text-text-muted">手机 Agent 已配置时自动导入相册</span>
              </span>
              <input
                type="checkbox"
                checked={sendToPhone}
                onChange={(event) => setSendToPhone(event.target.checked)}
                className="h-4 w-4 accent-[var(--color-accent)]"
              />
            </label>
            <div className="rounded-xl border border-border bg-surface p-2">
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
                会员模式会自动读取授权后台的网关配置；手动模式保留当前填写的地址和密钥。
              </p>
            </div>
            <div>
              <FieldLabel text="提示词" required />
              <TextArea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4} placeholder="描述你想要生成的图片..." />
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3 mt-4">
          <Button onClick={handleGenerate} variant="primary" disabled={generating}>
            {generating ? '生成中...' : '生成图片'}
          </Button>
          <Button onClick={handleTripleGenerate} variant="success" disabled={tripleGenerating}>
            {tripleGenerating ? tripleStatus : '一键三图'}
          </Button>
        </div>
        {phoneSyncStatus && <div className="mt-3 text-xs text-text-muted">{phoneSyncStatus}</div>}

        {/* Result Area */}
        <div className="mt-8">
          {generating && <Loading text="正在生成图片..." />}
          {resultImage && (
            <div>
              <div className="border border-border rounded-lg overflow-hidden inline-block max-w-lg">
                <img src={resultImage} alt="Generated" className="max-w-full" />
              </div>
              <div className="mt-3 space-y-1 text-xs text-text-muted">
                {resultFile && <div>本地：{resultFile}</div>}
                {phoneSyncStatus && <div>{phoneSyncStatus}</div>}
                <div className="mt-4">
                <Button onClick={handleSendToPublish} variant="default">
                  去平台发布
                </Button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Triple Results */}
        {tripleGenerating && tripleResults.some(r => r) && (
          <div className="mt-6 grid grid-cols-3 gap-4">
            {TRIPLE_PROMPTS.map((tpl, i) => (
              <div key={i} className="border border-border rounded-lg p-4 bg-surface-alt">
                <p className="text-sm font-medium text-text mb-2">{tpl.label}</p>
                {tripleResults[i]?.startsWith('data:') ? (
                  <img src={tripleResults[i]!} alt={tpl.label} className="w-full rounded" />
                ) : tripleResults[i]?.startsWith('error:') ? (
                  <p className="text-xs text-status-danger">{tripleResults[i]?.slice(6)}</p>
                ) : (
                  <div className="w-full aspect-square bg-surface-alt border border-border rounded flex items-center justify-center">
                    <Loading text="生成中..." />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {!resultImage && !generating && !tripleGenerating && (
          <div className="mt-8 text-center text-text-muted text-sm py-12">
            生成结果将显示在这里
          </div>
        )}
      </div>
    </div>
  );
};
