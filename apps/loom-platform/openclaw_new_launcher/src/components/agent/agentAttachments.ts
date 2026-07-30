import type { AgentAttachmentMetadata } from '../../stores/agentStore';

export const MAX_AGENT_ATTACHMENT_COUNT = 8;
export const MAX_AGENT_ATTACHMENT_TOTAL_BYTES = 16 * 1024 * 1024;

const MAX_TEXT_BYTES = 1024 * 1024;
const MAX_TEXT_CHARS = 32_768;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const TEXT_APPLICATION_TYPES = new Set([
  'application/json',
  'application/ld+json',
  'application/javascript',
  'application/xml',
  'application/yaml',
  'application/x-yaml',
]);
const IMAGE_TYPES_BY_EXTENSION: Record<string, string> = {
  gif: 'image/gif',
  jpeg: 'image/jpeg',
  jpg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
};

function fileExtension(name: string): string {
  return name.split('.').pop()?.toLowerCase() || '';
}

function readableTextType(file: File): string | null {
  const type = file.type.toLowerCase();
  if (type.startsWith('text/') || TEXT_APPLICATION_TYPES.has(type)) {
    return type || 'text/plain';
  }
  return /\.(?:txt|md|markdown|csv|tsv|json|jsonl|xml|ya?ml|log)$/i.test(file.name)
    ? 'text/plain'
    : null;
}

function readableImageType(file: File): string | null {
  const type = file.type.toLowerCase();
  if (Object.values(IMAGE_TYPES_BY_EXTENSION).includes(type)) return type;
  return IMAGE_TYPES_BY_EXTENSION[fileExtension(file.name)] || null;
}

function bytesToBase64(bytes: Uint8Array): string {
  const chunkSize = 0x8000;
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

async function textAttachment(file: File, type: string): Promise<AgentAttachmentMetadata> {
  const loaded = await file.slice(0, MAX_TEXT_BYTES).text();
  const content = loaded.slice(0, MAX_TEXT_CHARS);
  const truncated = file.size > MAX_TEXT_BYTES || loaded.length > MAX_TEXT_CHARS;
  return {
    name: file.name,
    size: file.size,
    type,
    kind: 'text',
    lastModified: file.lastModified,
    content,
    truncated,
    contentTruncated: truncated,
  };
}

async function imageAttachment(file: File, type: string): Promise<AgentAttachmentMetadata> {
  if (file.size > MAX_IMAGE_BYTES) {
    throw new Error(`${file.name} 超过 8 MB，请压缩后重试`);
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  return {
    name: file.name,
    size: file.size,
    type,
    kind: 'image',
    lastModified: file.lastModified,
    dataUrl: `data:${type};base64,${bytesToBase64(bytes)}`,
  };
}

export async function prepareAgentAttachments(
  files: readonly File[],
): Promise<AgentAttachmentMetadata[]> {
  if (files.length > MAX_AGENT_ATTACHMENT_COUNT) {
    throw new Error(`一次最多添加 ${MAX_AGENT_ATTACHMENT_COUNT} 个附件`);
  }
  const totalBytes = files.reduce((total, file) => total + file.size, 0);
  if (totalBytes > MAX_AGENT_ATTACHMENT_TOTAL_BYTES) {
    throw new Error('附件总大小不能超过 16 MB');
  }

  return Promise.all(files.map(async (file) => {
    const textType = readableTextType(file);
    if (textType) return textAttachment(file, textType);
    const imageType = readableImageType(file);
    if (imageType) return imageAttachment(file, imageType);
    throw new Error(`暂不支持 ${file.name}；请选择图片、TXT、Markdown、CSV、JSON、XML 或 YAML 文件`);
  }));
}
