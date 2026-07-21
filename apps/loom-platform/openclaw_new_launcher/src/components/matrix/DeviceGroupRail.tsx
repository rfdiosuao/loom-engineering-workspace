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
  <aside data-matrix-group-rail className="min-h-0 overflow-auto border-r border-white/[0.08] bg-[#081620] p-2">
    <div className="px-1 pb-2 text-[9px] font-black tracking-[0.2em] text-cyan-200/60">DEVICE GROUPS</div>
    <div className="space-y-1">
      {groups.map((group) => {
        const selectedCount = group.deviceIds.filter((deviceId) => selectedIds.has(deviceId)).length;
        const allSelected = Boolean(group.deviceIds.length) && selectedCount === group.deviceIds.length;
        return (
          <div key={group.id} className={`rounded-[6px] border ${activeGroupId === group.id ? 'border-cyan-300/35 bg-cyan-300/10' : 'border-transparent hover:border-white/10 hover:bg-white/[0.03]'} ${group.abnormal ? 'text-rose-100' : 'text-slate-200'}`}>
            <button type="button" onClick={() => onGroupChange(group.id)} className="flex w-full items-center justify-between gap-2 px-2 py-2 text-left">
              <span className="truncate text-[11px] font-bold">{group.label}</span>
              <span className="text-[9px] text-slate-500">{selectedCount}/{group.deviceIds.length}</span>
            </button>
            <label className="flex cursor-pointer items-center gap-1.5 border-t border-white/[0.06] px-2 py-1.5 text-[9px] text-slate-500">
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
    <div className="mt-3 border-t border-white/[0.08] px-1 pt-3 text-[10px] text-slate-500">搜索结果 {searchResultCount}</div>
  </aside>
);
