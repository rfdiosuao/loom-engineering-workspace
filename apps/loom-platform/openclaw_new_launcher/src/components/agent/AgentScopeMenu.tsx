import { Check, ChevronDown, Search, Smartphone, Sparkles, Target, Users, Wifi } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { matrixApi, parseErrorText } from '../../services/api';
import type { AgentScope } from '../../types/agent';
import type { MatrixDeviceSummary } from '../../types/matrix';

interface AgentScopeMenuProps {
  mode: 'auto' | 'manual';
  scope: AgentScope;
  disabled?: boolean;
  onChange: (mode: 'auto' | 'manual', scope: AgentScope) => void;
}

const EMPTY_SCOPE: AgentScope = { deviceIds: [], groups: [], allOnline: false };

function deviceGroups(device: MatrixDeviceSummary): string[] {
  return Array.from(new Set([device.group, ...(device.groups || [])].filter((value): value is string => Boolean(value?.trim()))));
}

export function AgentScopeMenu({ mode, scope, disabled, onChange }: AgentScopeMenuProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [devices, setDevices] = useState<MatrixDeviceSummary[]>([]);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', closeOnOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError('');
    void matrixApi.status().then((snapshot) => {
      if (active) setDevices(snapshot.devices || []);
    }).catch((reason: unknown) => {
      if (active) setError(parseErrorText(reason) || '设备列表读取失败');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [open]);

  const groups = useMemo(() => (
    Array.from(new Set(devices.flatMap(deviceGroups))).sort((left, right) => left.localeCompare(right, 'zh-CN'))
  ), [devices]);
  const normalizedQuery = query.trim().toLowerCase();
  const visibleDevices = useMemo(() => devices.filter((device) => {
    if (!normalizedQuery) return true;
    return [device.deviceId, device.name, device.model, ...deviceGroups(device)]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedQuery));
  }), [devices, normalizedQuery]);

  const triggerLabel = mode === 'auto'
    ? '自动选择'
    : scope.allOnline
      ? '全部在线'
      : scope.groups.length
        ? `${scope.groups.length} 个设备组`
        : `${scope.deviceIds.length} 台设备`;

  const toggleDevice = (deviceId: string) => {
    const selected = scope.deviceIds.includes(deviceId);
    const deviceIds = selected ? scope.deviceIds.filter((id) => id !== deviceId) : [...scope.deviceIds, deviceId];
    onChange(deviceIds.length ? 'manual' : 'auto', deviceIds.length ? { deviceIds, groups: [], allOnline: false } : EMPTY_SCOPE);
    setOpen(false);
  };

  const toggleGroup = (group: string) => {
    const selected = scope.groups.includes(group);
    const groupsSelection = selected ? scope.groups.filter((item) => item !== group) : [...scope.groups, group];
    onChange(groupsSelection.length ? 'manual' : 'auto', groupsSelection.length ? { deviceIds: [], groups: groupsSelection, allOnline: false } : EMPTY_SCOPE);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-label="选择任务范围"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        className="flex h-10 max-w-[180px] items-center gap-1.5 rounded-[7px] px-2.5 text-xs font-semibold text-text-muted hover:bg-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Target size={15} className="shrink-0" aria-hidden="true" />
        <span className="truncate">{triggerLabel}</span>
        <ChevronDown size={14} className="shrink-0" aria-hidden="true" />
      </button>

      {open ? (
        <div className="absolute bottom-12 left-0 z-30 w-[340px] overflow-hidden rounded-[8px] border border-border-strong bg-surface shadow-[0_18px_50px_rgba(5,25,22,0.22)]">
          <div className="border-b border-border p-1.5">
            <button
              type="button"
              aria-pressed={mode === 'auto'}
              onClick={() => {
                onChange('auto', EMPTY_SCOPE);
                setOpen(false);
              }}
              className="flex min-h-11 w-full items-center gap-2.5 rounded-[6px] px-2.5 text-left hover:bg-hover"
            >
              <Sparkles size={16} className="shrink-0 text-accent" aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-bold text-text">自动选择</span>
                <span className="block truncate text-[11px] text-text-subtle">麓鸣根据任务内容匹配设备</span>
              </span>
              {mode === 'auto' ? <Check size={16} className="text-accent" aria-hidden="true" /> : null}
            </button>
            <button
              type="button"
              aria-pressed={mode === 'manual' && scope.allOnline}
              onClick={() => {
                onChange('manual', { deviceIds: [], groups: [], allOnline: true });
                setOpen(false);
              }}
              className="flex min-h-11 w-full items-center gap-2.5 rounded-[6px] px-2.5 text-left hover:bg-hover"
            >
              <Wifi size={16} className="shrink-0 text-text-muted" aria-hidden="true" />
              <span className="min-w-0 flex-1 text-xs font-bold text-text">全部在线设备</span>
              {mode === 'manual' && scope.allOnline ? <Check size={16} className="text-accent" aria-hidden="true" /> : null}
            </button>
          </div>

          <div className="border-b border-border px-3 py-2.5">
            <label className="flex h-9 items-center gap-2 rounded-[6px] border border-border bg-input px-2.5">
              <Search size={14} className="shrink-0 text-text-subtle" aria-hidden="true" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索设备"
                aria-label="搜索设备"
                className="min-w-0 flex-1 bg-transparent text-xs text-text outline-none placeholder:text-text-subtle"
              />
            </label>
          </div>

          <div className="max-h-[300px] overflow-y-auto p-1.5">
            {groups.length ? (
              <div className="mb-1 border-b border-border pb-1">
                <div className="px-2.5 py-1 text-[10px] font-bold text-text-subtle">设备组</div>
                {groups.map((group) => {
                  const selected = mode === 'manual' && scope.groups.includes(group);
                  return (
                    <button
                      key={group}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => toggleGroup(group)}
                      className="flex min-h-10 w-full items-center gap-2.5 rounded-[6px] px-2.5 text-left hover:bg-hover"
                    >
                      <Users size={15} className="shrink-0 text-text-muted" aria-hidden="true" />
                      <span className="min-w-0 flex-1 truncate text-xs font-semibold text-text">{group}</span>
                      <span className="text-[10px] text-text-subtle">{devices.filter((device) => deviceGroups(device).includes(group)).length}</span>
                      {selected ? <Check size={15} className="text-accent" aria-hidden="true" /> : null}
                    </button>
                  );
                })}
              </div>
            ) : null}

            <div className="px-2.5 py-1 text-[10px] font-bold text-text-subtle">设备</div>
            {loading ? <div className="px-3 py-5 text-center text-xs text-text-muted">正在读取设备...</div> : null}
            {!loading && error ? <div role="alert" className="px-3 py-5 text-center text-xs text-status-danger">{error}</div> : null}
            {!loading && !error && !visibleDevices.length ? (
              <div className="px-3 py-5 text-center text-xs text-text-muted">没有匹配的设备</div>
            ) : null}
            {!loading && !error ? visibleDevices.map((device) => {
              const selected = mode === 'manual' && scope.deviceIds.includes(device.deviceId);
              return (
                <button
                  key={device.deviceId}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => toggleDevice(device.deviceId)}
                  className="flex min-h-11 w-full items-center gap-2.5 rounded-[6px] px-2.5 text-left hover:bg-hover"
                >
                  <Smartphone size={15} className="shrink-0 text-text-muted" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-semibold text-text">{device.name || device.deviceId}</span>
                    <span className="block truncate text-[10px] text-text-subtle">{device.model || device.deviceId}</span>
                  </span>
                  <span className={`h-2 w-2 shrink-0 rounded-full ${device.online ? 'bg-status-success' : 'bg-text-subtle'}`} title={device.online ? '在线' : '离线'} />
                  {selected ? <Check size={15} className="text-accent" aria-hidden="true" /> : null}
                </button>
              );
            }) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
