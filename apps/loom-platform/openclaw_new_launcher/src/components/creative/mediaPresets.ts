export type ImageMode = 't2i' | 'i2i';
export type VideoMode = 't2v' | 'i2v';

export interface ReferenceImage {
  requestValue: string;
  previewUrl: string;
  label: string;
  source: 'upload' | 'library';
}

export const IMAGE_RATIO_PRESETS = [
  { ratio: '1:1', size: '1024x1024' },
  { ratio: '3:4', size: '1152x1536' },
  { ratio: '4:3', size: '1536x1152' },
  { ratio: '9:16', size: '1152x2048' },
  { ratio: '16:9', size: '2048x1152' },
  { ratio: '5:2', size: '2560x1024' },
] as const;

export type ImageRatioPreset = (typeof IMAGE_RATIO_PRESETS)[number];

export function imageSizeForRatio(ratio?: string): string {
  return IMAGE_RATIO_PRESETS.find((preset) => preset.ratio === ratio)?.size || IMAGE_RATIO_PRESETS[0].size;
}

export function cssAspectRatio(ratio?: string): string {
  const normalized = IMAGE_RATIO_PRESETS.find((preset) => preset.ratio === ratio)?.ratio || '1:1';
  const [width, height] = normalized.split(':');
  return `${width} / ${height}`;
}

export function validateReferenceFile(file: Pick<File, 'type' | 'size'>): string {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    return '仅支持 PNG、JPG、WebP 图片';
  }
  if (file.size > 20 * 1024 * 1024) {
    return '参考图不能超过 20 MB';
  }
  return '';
}

export function readReferenceFile(file: File): Promise<ReferenceImage> {
  return new Promise((resolve, reject) => {
    const error = validateReferenceFile(file);
    if (error) {
      reject(new Error(error));
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('读取参考图失败'));
    reader.onload = () => {
      const requestValue = typeof reader.result === 'string' ? reader.result : '';
      if (!requestValue) {
        reject(new Error('读取参考图失败'));
        return;
      }
      resolve({ requestValue, previewUrl: requestValue, label: file.name, source: 'upload' });
    };
    reader.readAsDataURL(file);
  });
}
