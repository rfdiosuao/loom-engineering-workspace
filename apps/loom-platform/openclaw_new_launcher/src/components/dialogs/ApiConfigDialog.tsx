import React, { useEffect, useMemo, useState } from 'react';
import { Button, FieldLabel, Input, showToast } from '../common';
import { configApi } from '../../services/api';

const AUTH_PROFILES_PATH = 'data/.openclaw/agents/main/agent/auth-profiles.json';

type ProviderPreset = {
  url: string;
  models: string[];
};

const PROVIDERS: Record<string, ProviderPreset> = {
  'Heang AI': {
    url: 'https://api.heang.top/v1',
    models: ['kimi-k2.5', 'qwen3.6-plus', 'gpt-4o', 'gpt-4.1', 'gpt-4.1-mini'],
  },
  OpenAI: {
    url: 'https://api.openai.com/v1',
    models: ['gpt-4o', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-3.5-turbo'],
  },
  DeepSeek: {
    url: 'https://api.deepseek.com/v1',
    models: ['deepseek-chat', 'deepseek-reasoner', 'deepseek-coder'],
  },
  MiniMax: {
    url: 'https://api.minimaxi.com/v1',
    models: ['MiniMax-M1', 'abab6.5s-chat', 'abab6.5g-chat'],
  },
  Moonshot: {
    url: 'https://api.moonshot.cn/v1',
    models: ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'],
  },
  '智谱AI': {
    url: 'https://open.bigmodel.cn/api/paas/v4',
    models: ['glm-4', 'glm-4-flash', 'glm-4-plus'],
  },
  自定义: {
    url: '',
    models: [],
  },
};

function parseModels(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\n,，\s]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function providerIdFromUrl(baseUrl: string, fallback: string): string {
  try {
    const parsed = new URL(baseUrl.includes('://') ? baseUrl : `https://${baseUrl}`);
    const host = parsed.hostname.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    return `custom-${host || 'api'}`;
  } catch {
    const slug = fallback.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'api';
    return `custom-${slug}`;
  }
}

function modelDefinition(id: string) {
  // Qwen thinking parameters differ across OpenAI-compatible gateways; keeping
  // qwen3 plain avoids invalid thinking_budget/max_completion_tokens payloads.
  const reasoning = /^(claude|o1|o3|o4|deepseek-reasoner)/i.test(id);
  const contextWindow = id.startsWith('qwen3') ? 16000000 : id.startsWith('claude') ? 200000 : 128000;
  const maxTokens = id.startsWith('qwen3') ? 4096000 : 32000;
  return {
    id,
    name: `${id} (Custom Provider)`,
    reasoning,
    input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow,
    maxTokens,
    api: 'openai-completions',
  };
}

export const ApiConfigDialog: React.FC<{ onClose: () => void; onSaved?: () => void }> = ({ onClose, onSaved }) => {
  const [provider, setProvider] = useState('Heang AI');
  const [apiUrl, setApiUrl] = useState(PROVIDERS['Heang AI'].url);
  const [apiKey, setApiKey] = useState('');
  const [modelText, setModelText] = useState(PROVIDERS['Heang AI'].models[0]);
  const [saving, setSaving] = useState(false);

  const presetModels = useMemo(() => PROVIDERS[provider]?.models || [], [provider]);
  const modelIds = useMemo(() => parseModels(modelText), [modelText]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const resp = await configApi.read(AUTH_PROFILES_PATH, { models: { providers: {} } });
        if (cancelled) return;

        const data = resp.data as any;
        const providers = data?.models?.providers || {};
        const primary = data?.models?.primary;
        const savedProvider = primary && providers[primary] ? providers[primary] : (Object.values(providers)[0] as any);
        if (!savedProvider) return;

        const savedName = String(savedProvider.name || '');
        setProvider(PROVIDERS[savedName] ? savedName : '自定义');
        setApiUrl(String(savedProvider.baseUrl || savedProvider.url || ''));
        setApiKey(String(savedProvider.apiKey || ''));

        const savedModels = Array.isArray(savedProvider.models) ? savedProvider.models : [];
        const savedModelIds = savedModels
          .map((item: any) => (typeof item === 'string' ? item : item?.id))
          .filter(Boolean);
        if (savedModelIds.length > 0) {
          setModelText(savedModelIds.join(', '));
        }
      } catch {
        // Keep defaults when the package has no API profile yet.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleProviderChange = (nextProvider: string) => {
    const preset = PROVIDERS[nextProvider];
    setProvider(nextProvider);
    if (!preset) return;

    if (nextProvider !== '自定义') {
      setApiUrl(preset.url);
      setModelText(preset.models[0] || '');
    }
  };

  const handleSave = async () => {
    const cleanApiUrl = apiUrl.trim().replace(/\/+$/, '');
    const cleanApiKey = apiKey.trim();
    const cleanModels = parseModels(modelText);

    if (!cleanApiUrl) {
      showToast('请输入 API 地址', 'error');
      return;
    }
    if (!cleanApiKey) {
      showToast('请输入 API Key', 'error');
      return;
    }
    if (cleanModels.length === 0) {
      showToast('请输入至少一个模型名称', 'error');
      return;
    }

    setSaving(true);
    try {
      const providerId = providerIdFromUrl(cleanApiUrl, provider);
      const profileKey = provider === '自定义' ? providerId : provider.toLowerCase().replace(/\s+/g, '_');
      const primaryModel = cleanModels[0];
      const modelRef = `${providerId}/${primaryModel}`;
      const providerConfig = {
        baseUrl: cleanApiUrl,
        apiKey: cleanApiKey,
        api: 'openai-completions',
        models: cleanModels.map(modelDefinition),
      };

      const profilesResp = await configApi.read(AUTH_PROFILES_PATH, { models: { providers: {} } });
      const profiles = (profilesResp.data as any) || {};
      profiles.models = profiles.models || { providers: {} };
      profiles.models.providers = profiles.models.providers || {};
      profiles.models.providers[profileKey] = {
        id: profileKey,
        name: provider,
        baseUrl: cleanApiUrl,
        apiKey: cleanApiKey,
        models: cleanModels,
      };
      profiles.models.primary = profileKey;
      await configApi.write(AUTH_PROFILES_PATH, profiles);

      const catalogResp = await configApi.read('data/.openclaw/agents/main/agent/models.json', { providers: {} });
      const catalog = (catalogResp.data as any) || {};
      catalog.providers = catalog.providers || {};
      catalog.providers[providerId] = providerConfig;
      await configApi.write('data/.openclaw/agents/main/agent/models.json', catalog);

      const openclawResp = await configApi.read('data/.openclaw/openclaw.json', { plugins: {} });
      const openclaw = (openclawResp.data as any) || {};
      openclaw.models = openclaw.models || { mode: 'merge', providers: {} };
      openclaw.models.mode = 'merge';
      openclaw.models.providers = openclaw.models.providers || {};
      openclaw.models.providers[providerId] = providerConfig;
      openclaw.agents = openclaw.agents || { defaults: {} };
      openclaw.agents.defaults = openclaw.agents.defaults || {};
      openclaw.agents.defaults.model = { primary: modelRef };
      openclaw.agents.defaults.models = openclaw.agents.defaults.models || {};
      openclaw.agents.defaults.models[modelRef] = { alias: primaryModel };
      await configApi.write('data/.openclaw/openclaw.json', openclaw);

      showToast('模型配置已保存', 'success');
      onSaved?.();
      onClose();
    } catch {
      showToast('保存失败，请检查配置', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" />
      <div
        className="relative bg-surface rounded-lg shadow-xl w-full max-w-lg mx-4 p-6 max-h-[80vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold text-text">模型配置</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text text-xl">&times;</button>
        </div>

        <div className="space-y-4">
          <div>
            <FieldLabel text="提供商" />
            <select
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="w-full px-3 py-2 rounded-md border border-border bg-surface-alt text-text text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            >
              {Object.keys(PROVIDERS).map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </div>

          <div>
            <FieldLabel text="API 地址" />
            <Input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="https://api.example.com/v1" />
          </div>

          <div>
            <FieldLabel text="API Key" />
            <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." />
          </div>

          <div>
            <FieldLabel text="模型" />
            <Input
              value={modelText}
              onChange={(e) => setModelText(e.target.value)}
              placeholder="例如 kimi-k2.5，多个模型用逗号分隔"
              list="api-model-presets"
            />
            <datalist id="api-model-presets">
              {presetModels.map((item) => <option key={item} value={item} />)}
            </datalist>
            <p className="mt-1 text-xs text-text-muted">
              可手动输入任意模型名；多个模型用逗号、空格或换行分隔。第一个模型会作为默认模型。
            </p>
          </div>

          {modelIds.length > 0 && (
            <div className="rounded-md border border-border bg-surface-alt px-3 py-2 text-xs text-text-muted">
              将写入 {modelIds.length} 个模型：{modelIds.join(', ')}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <Button onClick={handleSave} variant="primary" disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </Button>
            <Button onClick={onClose} variant="quiet">取消</Button>
          </div>
        </div>
      </div>
    </div>
  );
};
