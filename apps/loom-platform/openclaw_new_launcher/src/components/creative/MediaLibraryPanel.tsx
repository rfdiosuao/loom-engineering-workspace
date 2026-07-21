import React from 'react';
import { convertFileSrc } from '@tauri-apps/api/core';
import { Button } from '../common';
import type { MediaAsset, MediaPhoneTransferResult, PhoneDeviceSummary } from '../../services/api';

interface MediaLibraryPanelProps {
  kind: 'all' | 'image' | 'video';
  assets: MediaAsset[];
  loading: boolean;
  error: string;
  hasMore: boolean;
  onKindChange: (kind: 'all' | 'image' | 'video') => void;
  onLoadMore: () => void;
  onRefresh: () => void;
  onReveal: (asset: MediaAsset) => void;
  onDelete: (asset: MediaAsset) => void;
  onUseForImage: (asset: MediaAsset) => void;
  onUseForVideo: (asset: MediaAsset) => void;
  phones: PhoneDeviceSummary[];
  transferringAssetId: string;
  transferResults: Record<string, MediaPhoneTransferResult>;
  onTransfer: (asset: MediaAsset, deviceIds: string[]) => void;
}

function localAssetUrl(path: string): string {
  try {
    return convertFileSrc(path);
  } catch {
    return path;
  }
}

export const MediaLibraryPanel: React.FC<MediaLibraryPanelProps> = ({
  kind,
  assets,
  loading,
  error,
  hasMore,
  onKindChange,
  onLoadMore,
  onRefresh,
  onReveal,
  onDelete,
  onUseForImage,
  onUseForVideo,
  phones,
  transferringAssetId,
  transferResults,
  onTransfer,
}) => {
  const [transferAssetId, setTransferAssetId] = React.useState('');
  const [selectedDeviceIds, setSelectedDeviceIds] = React.useState<string[]>([]);

  const toggleTransferPicker = (assetId: string) => {
    if (transferAssetId === assetId) {
      setTransferAssetId('');
      return;
    }
    setTransferAssetId(assetId);
    setSelectedDeviceIds(phones.map((phone) => phone.id));
  };

  const toggleDevice = (deviceId: string) => {
    setSelectedDeviceIds((current) => current.includes(deviceId)
      ? current.filter((id) => id !== deviceId)
      : [...current, deviceId]);
  };

  return <div>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="text-lg font-black text-text">本地素材库</h2>
        <p className="mt-1 text-xs leading-5 text-text-muted">UI 和 CLI 生成的图片、视频都会保存在这里，重启后仍可查看。</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div data-media-library-filter className="flex items-center gap-1 rounded-[8px] border border-border bg-surface-alt/50 p-1">
          {([
            ['all', '全部'],
            ['image', '图片'],
            ['video', '视频'],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`min-w-14 rounded-[6px] px-3 py-2 text-xs font-black transition-colors ${kind === value ? 'bg-accent text-white' : 'text-text-muted hover:bg-surface'}`}
              aria-pressed={kind === value}
              onClick={() => onKindChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <Button type="button" variant="quiet" onClick={onRefresh} disabled={loading}>{loading ? '刷新中...' : '刷新'}</Button>
      </div>
    </div>
    {error ? <div className="mt-4 rounded-[8px] border border-status-danger/25 bg-status-danger/8 px-3 py-2 text-sm text-status-danger">{error}</div> : null}
    {assets.length ? (
      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {assets.map((asset) => (
          <article key={asset.id} className="overflow-hidden rounded-[8px] border border-border bg-surface-alt/35">
            {asset.kind === 'image' ? (
              <img
                src={localAssetUrl(asset.path)}
                alt={asset.filename}
                className="w-full bg-surface object-contain"
                style={{ aspectRatio: asset.ratio ? asset.ratio.replace(':', ' / ') : '4 / 3' }}
                loading="lazy"
              />
            ) : (
              <video src={localAssetUrl(asset.path)} controls preload="metadata" className="aspect-video w-full bg-black" />
            )}
            <div className="p-3">
              <div className="truncate text-sm font-black text-text" title={asset.filename}>{asset.filename}</div>
              <div className="mt-1 flex gap-2 text-xs text-text-muted">
                <span>{asset.kind === 'image' ? '图片' : '视频'}</span>
                {asset.ratio ? <span>{asset.ratio}</span> : null}
                {asset.source ? <span>{asset.source === 'cli' ? 'CLI' : '工作台'}</span> : null}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {asset.kind === 'image' ? (
                  <>
                    <Button type="button" variant="quiet" onClick={() => onUseForImage(asset)}>用作图生图</Button>
                    <Button type="button" variant="quiet" onClick={() => onUseForVideo(asset)}>用作图生视频</Button>
                  </>
                ) : null}
                <Button type="button" variant="primary" onClick={() => toggleTransferPicker(asset.id)}>
                  传到手机
                </Button>
                <Button type="button" variant="quiet" onClick={() => onReveal(asset)}>打开位置</Button>
                <Button type="button" variant="danger" onClick={() => onDelete(asset)}>删除</Button>
              </div>
              {transferAssetId === asset.id ? (
                <div data-media-transfer-picker className="mt-3 border-t border-border pt-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-xs font-black text-text">选择接收手机</div>
                    {phones.length ? (
                      <button
                        type="button"
                        className="text-xs font-black text-accent"
                        onClick={() => setSelectedDeviceIds(selectedDeviceIds.length === phones.length ? [] : phones.map((phone) => phone.id))}
                      >
                        {selectedDeviceIds.length === phones.length ? '清空' : '全选'}
                      </button>
                    ) : null}
                  </div>
                  {phones.length ? (
                    <div className="mt-2 grid gap-2">
                      {phones.map((phone) => (
                        <label key={phone.id} className="flex min-w-0 cursor-pointer items-center gap-2 rounded-[6px] border border-border bg-surface px-3 py-2 text-xs">
                          <input
                            type="checkbox"
                            checked={selectedDeviceIds.includes(phone.id)}
                            onChange={() => toggleDevice(phone.id)}
                          />
                          <span className="min-w-0 flex-1 truncate font-black text-text">{phone.name || phone.id}</span>
                          <span className="shrink-0 text-text-muted">{phone.id}</span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-2 text-xs leading-5 text-text-muted">暂无已配置手机，请先在手机控制中添加设备。</div>
                  )}
                  <Button
                    type="button"
                    variant="primary"
                    className="mt-3 w-full"
                    disabled={!selectedDeviceIds.length || Boolean(transferringAssetId)}
                    onClick={() => onTransfer(asset, selectedDeviceIds)}
                  >
                    {transferringAssetId === asset.id ? '正在传输...' : `传输到 ${selectedDeviceIds.length} 台`}
                  </Button>
                </div>
              ) : null}
              {transferResults[asset.id] ? (
                <div
                  role="status"
                  className={`mt-3 rounded-[6px] border px-3 py-2 text-xs font-bold ${transferResults[asset.id].status === 'succeeded' ? 'border-status-success/25 bg-status-success/8 text-status-success' : 'border-status-danger/25 bg-status-danger/8 text-status-danger'}`}
                >
                  {transferResults[asset.id].message || '手机传输状态已更新'}
                </div>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    ) : !loading ? (
      <div className="mt-4 rounded-[8px] border border-dashed border-border px-4 py-10 text-center text-sm text-text-muted">暂无本地素材，完成一次生成后会自动出现在这里。</div>
    ) : null}
    {hasMore ? <Button type="button" variant="quiet" className="mt-4 w-full" onClick={onLoadMore} disabled={loading}>加载更多</Button> : null}
  </div>;
};
