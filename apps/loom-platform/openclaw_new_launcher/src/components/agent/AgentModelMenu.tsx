import { Check, ChevronDown, Settings2, Star } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { AgentModelSummary, AgentSession } from '../../types/agent';
import { agentModelSelectionState } from './agentViewModel';

interface AgentModelMenuProps {
  session: AgentSession | null;
  models: AgentModelSummary[];
  defaultModelId?: string;
  disabled?: boolean;
  onSelectModel: (modelId?: string) => Promise<void>;
  onSetDefaultModel: (modelId: string) => Promise<void>;
  onManageModels: () => void;
}

export function AgentModelMenu({
  session,
  models,
  defaultModelId,
  disabled,
  onSelectModel,
  onSetDefaultModel,
  onManageModels,
}: AgentModelMenuProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const availableModels = useMemo(() => models.filter((model) => model.available), [models]);
  const {
    usesAccountDefault,
    effectiveModelId: selectedModelId,
    effectiveModelName,
  } = agentModelSelectionState(session?.modelId, defaultModelId, availableModels);

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

  const selectModel = async (modelId?: string) => {
    if (busy || modelId === session?.modelId) {
      setOpen(false);
      return;
    }
    setBusy(true);
    try {
      await onSelectModel(modelId);
      setOpen(false);
    } finally {
      setBusy(false);
    }
  };

  const setDefaultModel = async () => {
    if (!selectedModelId || busy || selectedModelId === defaultModelId) return;
    setBusy(true);
    try {
      await onSetDefaultModel(selectedModelId);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-label="选择模型"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        className="flex h-10 max-w-[220px] items-center gap-1.5 rounded-[7px] px-2.5 text-xs font-semibold text-text-muted hover:bg-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="truncate">
          {usesAccountDefault && effectiveModelName ? `默认 · ${effectiveModelName}` : effectiveModelName || '选择模型'}
        </span>
        <ChevronDown size={14} className="shrink-0" aria-hidden="true" />
      </button>

      {open ? (
        <div className="absolute bottom-12 right-0 z-30 w-[300px] overflow-hidden rounded-[8px] border border-border-strong bg-surface shadow-[0_18px_50px_rgba(5,25,22,0.22)]">
          <div className="border-b border-border px-3 py-2.5">
            <div className="text-xs font-black text-text">当前对话模型</div>
            <div className="mt-0.5 text-[11px] text-text-subtle">
              {usesAccountDefault ? '跟随麓鸣默认模型' : '仅影响当前对话'}
            </div>
          </div>

          <div className="max-h-56 overflow-y-auto p-1.5">
            <button
              type="button"
              aria-pressed={usesAccountDefault}
              onClick={() => void selectModel(undefined)}
              className="flex min-h-9 w-full items-center gap-2 rounded-[6px] px-2.5 py-1.5 text-left hover:bg-hover"
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center text-accent">
                {usesAccountDefault ? <Check size={16} aria-hidden="true" /> : null}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs font-semibold text-text">跟随默认模型</span>
              {defaultModelId ? (
                <span className="max-w-28 shrink-0 truncate text-[10px] font-semibold text-text-subtle">
                  {availableModels.find((model) => model.modelId === defaultModelId)?.name || defaultModelId}
                </span>
              ) : null}
            </button>

            {availableModels.length ? availableModels.map((model) => {
              const selected = !usesAccountDefault && model.modelId === selectedModelId;
              return (
                <button
                  key={model.modelId}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => void selectModel(model.modelId)}
                  className="flex min-h-10 w-full items-center gap-2 rounded-[6px] px-2.5 py-2 text-left hover:bg-hover"
                >
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center text-accent">
                    {selected ? <Check size={16} aria-hidden="true" /> : null}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-semibold text-text">{model.name}</span>
                  {model.modelId === defaultModelId ? (
                    <span className="shrink-0 text-[10px] font-semibold text-text-subtle">默认</span>
                  ) : null}
                </button>
              );
            }) : (
              <div className="px-3 py-5 text-center text-xs text-text-muted">暂无可用文本模型</div>
            )}
          </div>

          <div className="border-t border-border p-1.5">
            <button
              type="button"
              disabled={!selectedModelId || busy || selectedModelId === defaultModelId}
              onClick={() => void setDefaultModel()}
              className="flex min-h-10 w-full items-center gap-2 rounded-[6px] px-2.5 text-left text-xs font-semibold text-text-muted hover:bg-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-45"
            >
              <Star size={15} aria-hidden="true" />
              <span>{selectedModelId === defaultModelId ? '已是麓鸣默认模型' : '设为麓鸣默认模型'}</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onManageModels();
              }}
              className="flex min-h-10 w-full items-center gap-2 rounded-[6px] px-2.5 text-left text-xs font-semibold text-text-muted hover:bg-hover hover:text-text"
            >
              <Settings2 size={15} aria-hidden="true" />
              <span>管理模型</span>
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
