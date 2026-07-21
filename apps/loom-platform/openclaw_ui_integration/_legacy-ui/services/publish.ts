export type PublishPlatformId = 'x' | 'xiaohongshu' | 'douyin' | 'wechat' | 'custom';
export type PublishTransportMode = 'direct' | 'reverse';
export type PublishContentType = 'text' | 'image' | 'video' | 'mixed';
export type PublishAssetKind = 'image' | 'video';

export interface PublishAsset {
  id: string;
  kind: PublishAssetKind;
  name: string;
  mime: string;
  dataUrl: string;
  size?: number;
  sourcePath?: string;
  uploadedPath?: string;
  uploadedRelativePath?: string;
}

export interface PublishDraft {
  platformId: PublishPlatformId;
  transportMode: PublishTransportMode;
  contentType: PublishContentType;
  title: string;
  body: string;
  hashtags: string[];
  assets: PublishAsset[];
  phoneAlbum: string;
  sendToPhoneAlbum: boolean;
  selectedDeviceId: string;
  reverseRelayUrl: string;
  reverseRelayToken: string;
  reverseChannelId: string;
  notes: string;
}

export interface PublishMediaRef {
  kind: PublishAssetKind;
  name: string;
  mime?: string;
  size?: number;
  sourcePath?: string;
  uploadedPath?: string;
  uploadedRelativePath?: string;
  album?: string;
}

export interface PublishPlatformSpec {
  id: PublishPlatformId;
  label: string;
  shortLabel: string;
  appName: string;
  description: string;
  defaultContentType: PublishContentType;
  preferredAssetKinds: PublishAssetKind[];
  defaultHashtags: string[];
  allowsTextOnly: boolean;
  promptHint: string;
}

export interface ReversePublishPacket {
  schema: 'openclaw.publish.packet.v1';
  createdAt: string;
  platformId: PublishPlatformId;
  platformLabel: string;
  contentType: PublishContentType;
  title: string;
  body: string;
  hashtags: string[];
  notes: string;
  transport: PublishTransportMode;
  relayUrl: string;
  channelId: string;
  album: string;
  media: PublishMediaRef[];
}

export const DEFAULT_PUBLISH_ALBUM = 'OpenClaw Publish';

export const PUBLISH_PLATFORMS: PublishPlatformSpec[] = [
  {
    id: 'x',
    label: 'X / Twitter',
    shortLabel: 'X',
    appName: 'X',
    description: '短帖、图片、视频都可以发，优先控制标题和附件顺序。',
    defaultContentType: 'mixed',
    preferredAssetKinds: ['image', 'video'],
    defaultHashtags: ['OpenClaw'],
    allowsTextOnly: true,
    promptHint: '先打开 X 的发帖入口，再填正文和附件；如果有多张图，按顺序添加。',
  },
  {
    id: 'xiaohongshu',
    label: '小红书',
    shortLabel: '小红书',
    appName: '小红书',
    description: '图文种草、标题和话题很重要，优先检查封面和正文排版。',
    defaultContentType: 'image',
    preferredAssetKinds: ['image', 'video'],
    defaultHashtags: ['OpenClaw', 'AI创作'],
    allowsTextOnly: false,
    promptHint: '优先使用图文发布入口，先确认标题，再填正文、话题和封面，发布前必须看预览。',
  },
  {
    id: 'douyin',
    label: '抖音',
    shortLabel: '抖音',
    appName: '抖音',
    description: '短视频优先，适合视频封面、标题、配文和发布确认。',
    defaultContentType: 'video',
    preferredAssetKinds: ['video', 'image'],
    defaultHashtags: ['OpenClaw', 'AI视频'],
    allowsTextOnly: false,
    promptHint: '优先进入视频发布入口，确保视频、封面、标题和描述都正确，再提交发布。',
  },
  {
    id: 'wechat',
    label: '微信朋友圈',
    shortLabel: '微信',
    appName: '微信',
    description: '朋友圈发帖、图片/视频配文和可见性检查。',
    defaultContentType: 'mixed',
    preferredAssetKinds: ['image', 'video'],
    defaultHashtags: ['OpenClaw'],
    allowsTextOnly: true,
    promptHint: '优先找朋友圈发布入口，检查可见性、定位和分组后再发布。',
  },
  {
    id: 'custom',
    label: '自定义平台',
    shortLabel: '自定义',
    appName: '目标应用',
    description: '未知或新平台，保留通用发布步骤。',
    defaultContentType: 'mixed',
    preferredAssetKinds: ['image', 'video'],
    defaultHashtags: [],
    allowsTextOnly: true,
    promptHint: '按照目标应用的发布入口执行，先确认发布草稿页，再处理媒体和说明。',
  },
];

export const DEFAULT_PUBLISH_DRAFT: PublishDraft = {
  platformId: 'xiaohongshu',
  transportMode: 'direct',
  contentType: 'image',
  title: '',
  body: '',
  hashtags: [],
  assets: [],
  phoneAlbum: DEFAULT_PUBLISH_ALBUM,
  sendToPhoneAlbum: true,
  selectedDeviceId: '',
  reverseRelayUrl: '',
  reverseRelayToken: '',
  reverseChannelId: '',
  notes: '',
};

export function getPublishPlatform(platformId: PublishPlatformId): PublishPlatformSpec {
  return PUBLISH_PLATFORMS.find((item) => item.id === platformId) || PUBLISH_PLATFORMS[PUBLISH_PLATFORMS.length - 1];
}

export function getDefaultPublishDraft(platformId: PublishPlatformId = 'xiaohongshu'): PublishDraft {
  const platform = getPublishPlatform(platformId);
  return {
    ...DEFAULT_PUBLISH_DRAFT,
    platformId,
    contentType: platform.defaultContentType,
    hashtags: [...platform.defaultHashtags],
  };
}

export function normalizeHashtagInput(value: string | string[]): string[] {
  const source = Array.isArray(value) ? value : String(value || '').split(/[\n,，\s]+/);
  return source
    .map((item) => String(item || '').trim())
    .map((item) => item.replace(/^#+/, ''))
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index)
    .slice(0, 12);
}

export function formatHashtags(hashtags: string[]): string {
  return normalizeHashtagInput(hashtags).map((tag) => `#${tag}`).join(' ');
}

export function contentTypeLabel(contentType: PublishContentType): string {
  switch (contentType) {
    case 'text':
      return '纯文本';
    case 'image':
      return '图文';
    case 'video':
      return '视频';
    default:
      return '图文混合';
  }
}

export function platformLabel(platformId: PublishPlatformId): string {
  return getPublishPlatform(platformId).label;
}

function assetLabel(asset: PublishMediaRef, index: number): string {
  const location = asset.uploadedRelativePath || asset.uploadedPath || asset.sourcePath || '未上传';
  return `${index + 1}. ${asset.kind} / ${asset.name} / ${location}`;
}

export function buildPublishPrompt(draft: PublishDraft, mediaRefs: PublishMediaRef[]): string {
  const platform = getPublishPlatform(draft.platformId);
  const hashtags = normalizeHashtagInput(draft.hashtags);
  const lines = [
    '你现在执行的是 OpenClaw 平台发布任务。',
    '不要重新生成图片或视频，只使用已经准备好的标题、正文和素材。',
    `目标平台: ${platform.label}`,
    `发布入口: ${platform.appName}`,
    `内容类型: ${contentTypeLabel(draft.contentType)}`,
    draft.title.trim() ? `标题: ${draft.title.trim()}` : '标题: 无',
    draft.body.trim() ? `正文: ${draft.body.trim()}` : '正文: 无',
    hashtags.length ? `话题: ${formatHashtags(hashtags)}` : '话题: 无',
    draft.notes.trim() ? `补充要求: ${draft.notes.trim()}` : '',
    '已准备素材:',
    mediaRefs.length ? mediaRefs.map(assetLabel).join('\n') : '- 无素材，执行文本发布。',
    '',
    '执行要求:',
    platform.promptHint,
    '- 先进入应用的发帖/创作入口，再检查当前页面标题。',
    '- 媒体有顺序时必须按顺序添加，封面需要时先确认封面。',
    '- 发布前检查预览、可见性、@、定位、草稿状态和平台提示。',
    '- 只在确认内容正确后才提交发布。',
    '- 完成后返回当前页面、是否提交成功、草稿状态和失败原因。',
  ];
  return lines.filter(Boolean).join('\n');
}

export function buildReversePublishPacket(draft: PublishDraft, mediaRefs: PublishMediaRef[]): ReversePublishPacket {
  const platform = getPublishPlatform(draft.platformId);
  return {
    schema: 'openclaw.publish.packet.v1',
    createdAt: new Date().toISOString(),
    platformId: draft.platformId,
    platformLabel: platform.label,
    contentType: draft.contentType,
    title: draft.title.trim(),
    body: draft.body.trim(),
    hashtags: normalizeHashtagInput(draft.hashtags),
    notes: draft.notes.trim(),
    transport: draft.transportMode,
    relayUrl: draft.reverseRelayUrl.trim(),
    channelId: draft.reverseChannelId.trim(),
    album: draft.phoneAlbum.trim() || DEFAULT_PUBLISH_ALBUM,
    media: mediaRefs.map((asset) => ({
      kind: asset.kind,
      name: asset.name,
      mime: asset.mime,
      size: asset.size,
      sourcePath: asset.sourcePath,
      uploadedPath: asset.uploadedPath,
      uploadedRelativePath: asset.uploadedRelativePath,
      album: asset.album,
    })),
  };
}
