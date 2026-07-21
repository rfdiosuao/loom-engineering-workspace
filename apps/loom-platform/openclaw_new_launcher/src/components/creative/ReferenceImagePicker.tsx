import React from 'react';
import { Button, showToast } from '../common';
import { readReferenceFile, type ReferenceImage } from './mediaPresets';

interface ReferenceImagePickerProps {
  value: ReferenceImage | null;
  latest: ReferenceImage | null;
  onChange: (value: ReferenceImage | null) => void;
}

export const ReferenceImagePicker: React.FC<ReferenceImagePickerProps> = ({ value, latest, onChange }) => {
  const inputRef = React.useRef<HTMLInputElement | null>(null);

  const onFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      onChange(await readReferenceFile(file));
    } catch (error) {
      showToast(error instanceof Error ? error.message : '读取参考图失败', 'error');
    }
  };

  return (
    <div data-reference-image-picker className="rounded-[8px] border border-border bg-surface-alt/35 p-3">
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        aria-label="上传参考图"
        onChange={onFileChange}
      />
      <div className="flex min-w-0 items-center gap-3">
        {value ? (
          <img src={value.previewUrl} alt="当前参考图" className="h-16 w-16 shrink-0 rounded-[6px] border border-border object-cover" />
        ) : (
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-[6px] border border-dashed border-border text-xs text-text-subtle">参考图</div>
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-black text-text">{value?.label || '选择一张图片作为生成参考'}</div>
          <div className="mt-1 text-xs leading-5 text-text-muted">PNG、JPG、WebP，最大 20 MB</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button type="button" variant="quiet" onClick={() => inputRef.current?.click()}>上传图片</Button>
            <Button type="button" variant="quiet" onClick={() => latest && onChange(latest)} disabled={!latest}>最近生成</Button>
            {value ? <Button type="button" variant="quiet" onClick={() => onChange(null)}>移除</Button> : null}
          </div>
        </div>
      </div>
    </div>
  );
};
