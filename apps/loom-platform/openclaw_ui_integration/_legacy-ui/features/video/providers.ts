import type { VideoMode } from '../../types';

export type VideoProviderId = 'dashscope' | 'seedance' | 'agnes' | 'custom';

export interface VideoModelDefinition {
  id: string;
  label: string;
  modes: VideoMode[];
  description?: string;
}

export interface VideoProviderDefinition {
  id: VideoProviderId;
  label: string;
  description: string;
  apiBase: string;
  authLabel: string;
  authPlaceholder: string;
  docsUrl?: string;
  supportsImageInput: boolean;
  supportsTextInput: boolean;
  models: VideoModelDefinition[];
}

export const VIDEO_PROVIDERS: VideoProviderDefinition[] = [
  {
    id: 'dashscope',
    label: '阿里云 DashScope / 快乐马',
    description: '当前默认视频服务，适合快速接入和稳定交付。',
    apiBase: 'https://dashscope.aliyuncs.com/api/v1',
    authLabel: 'DashScope API Key',
    authPlaceholder: 'sk-... 或 DashScope Key',
    docsUrl: 'https://help.aliyun.com/zh/dashscope',
    supportsImageInput: true,
    supportsTextInput: true,
    models: [
      { id: 'happyhorse-1.0-t2v', label: '快乐马 文生视频', modes: ['t2v'] },
      { id: 'happyhorse-1.0-i2v', label: '快乐马 图生视频', modes: ['i2v'] },
    ],
  },
  {
    id: 'seedance',
    label: '火山引擎 Seedance',
    description: '更适合未来扩展的视频生成供应商，支持更丰富的模型组合。',
    apiBase: 'https://ark.cn-beijing.volces.com',
    authLabel: '火山引擎 API Key',
    authPlaceholder: '输入火山引擎 API Key',
    docsUrl: 'https://www.volcengine.com/docs/82379/1520757?lang=zh',
    supportsImageInput: true,
    supportsTextInput: true,
    models: [
      { id: 'doubao-seedance-2-0-pro-260215', label: 'Seedance 2.0 Pro', modes: ['t2v', 'i2v'] },
      { id: 'doubao-seedance-2-0-fast-260128', label: 'Seedance 2.0 Fast', modes: ['t2v', 'i2v'] },
      { id: 'doubao-seedance-1-5-pro-251215', label: 'Seedance 1.5 Pro', modes: ['t2v', 'i2v'] },
    ],
  },
  {
    id: 'agnes',
    label: 'Agnes Video V2.0',
    description: 'Agnes 异步视频任务接口，适合使用 Agnes 图像同源 Key 直接生成视频。',
    apiBase: 'https://apihub.agnes-ai.com/v1',
    authLabel: 'Agnes API Key',
    authPlaceholder: '输入 Agnes API Key',
    docsUrl: 'https://agnes-ai.com/doc/agnes-video-v20',
    supportsImageInput: true,
    supportsTextInput: true,
    models: [
      { id: 'agnes-video-v2.0', label: 'Agnes Video V2.0', modes: ['t2v', 'i2v'] },
    ],
  },
  {
    id: 'custom',
    label: '自定义兼容服务',
    description: '保留给 Seedance 兼容网关或私有部署。',
    apiBase: '',
    authLabel: '访问密钥',
    authPlaceholder: '输入自定义服务密钥',
    supportsImageInput: true,
    supportsTextInput: true,
    models: [],
  },
];

const PROVIDER_BY_ID = new Map(VIDEO_PROVIDERS.map((provider) => [provider.id, provider]));

export function getVideoProvider(providerId: VideoProviderId): VideoProviderDefinition {
  return PROVIDER_BY_ID.get(providerId) || VIDEO_PROVIDERS[0];
}

export function getDefaultVideoModel(providerId: VideoProviderId, mode: VideoMode): string {
  const provider = getVideoProvider(providerId);
  const candidate = provider.models.find((model) => model.modes.includes(mode)) || provider.models[0];
  return candidate?.id || '';
}
