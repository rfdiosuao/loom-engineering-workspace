import React from 'react';

import type { MatrixDeviceGroup } from './matrixViewModel';

interface DeviceGroupRailProps {
  groups: MatrixDeviceGroup[];
  activeGroupId: string;
  selectedIds: ReadonlySet<string>;
  searchResultCount: number;
  onGroupChange: (groupId: string) => void;
  onSelectGroup: (deviceIds: string[], selected: boolean) => void;
}

export const DeviceGroupRail: React.FC<DeviceGroupRailProps> = ({
  groups,
  activeGroupId,
  selectedIds,
  searchResultCount,
  onGroupChange,
  onSelectGroup,
}) => (
  <aside data-matrix-group-rail className="min-h-0 overflow-auto border-r border-border bg-surface-alt p-2">
    <div className="px-1 pb-2 text-[9px] font-black tracking-[0.2em] text-text-subtle">DEVICE GROUPS</div>
    <div className="space-y-1">
      {groups.map((group) => {
        const selectedCount = group.deviceIds.filter((deviceId) => selectedIds.has(deviceId)).length;
        const allSelected = Boolean(group.deviceIds.length) && selectedCount === group.deviceIds.length;
        return (
          <div key={group.id} className={`rounded-[6px] border ${activeGroupId === group.id ? 'border-border-strong bg-selected text-selected-ink' : 'border-transparent text-text hover:border-border hover:bg-hover'} ${group.abnormal ? 'text-status-danger' : ''}`}>
            <button type="button" onClick={() => onGroupChange(group.id)} className="flex w-full items-center justify-between gap-2 px-2 py-2 text-left">
              <span className="truncate text-[11px] font-bold">{group.label}</span>
              <span className="text-[9px] text-text-subtle">{selectedCount}/{group.deviceIds.length}</span>
            </button>
            <label className="flex cursor-pointer items-center gap-1.5 border-t border-border px-2 py-1.5 text-[9px] text-text-muted">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={(event) => onSelectGroup(group.deviceIds, event.target.checked)}
              />
              选择整组
            </label>
          </div>
        );
      })}
    </div>
    <div className="mt-3 border-t border-border px-1 pt-3 text-[10px] text-text-muted">搜索结果 {searchResultCount}</div>
  </aside>
);
