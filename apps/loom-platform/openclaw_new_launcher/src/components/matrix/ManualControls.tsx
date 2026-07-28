import React from 'react';

import type { MatrixControlRequest } from '../../types/matrix';
import { Button } from '../common';

export type MatrixManualAction = MatrixControlRequest extends infer Request
  ? Request extends unknown
    ? Omit<Request, 'leaseId' | 'clientCommandId'>
    : never
  : never;

interface ManualControlsProps {
  enabled: boolean;
  busy: boolean;
  disabledMessage?: string;
  onAction: (action: MatrixManualAction) => void;
}

export const ManualControls: React.FC<ManualControlsProps> = ({ enabled, busy, disabledMessage, onAction }) => {
  const [text, setText] = React.useState('');
  const disabled = !enabled || busy;
  const systemActions: Array<[MatrixManualAction['action'], string, string]> = [
    ['back', '←', '返回'],
    ['home', '⌂', '主页'],
    ['recent', '▣', '最近任务'],
    ['screenshot', '▤', '截图'],
    ['rotate', '↻', '旋转'],
  ];

  return (
    <div data-matrix-manual-controls className="border-t border-border p-2.5">
      <div className="grid grid-cols-5 gap-1.5">
        {systemActions.map(([action, glyph, label]) => (
          <button
            key={action}
            type="button"
            disabled={disabled}
            onClick={() => onAction({ action } as MatrixManualAction)}
            title={label}
            aria-label={label}
            className="h-8 rounded-[5px] border border-border bg-surface text-sm font-bold text-text hover:border-info disabled:cursor-not-allowed disabled:bg-disabled disabled:text-disabled-text"
          >
            {glyph}
          </button>
        ))}
      </div>
      <div className="mt-2 flex gap-1.5">
        <input
          value={text}
          onChange={(event) => setText(event.target.value)}
          disabled={!enabled}
          placeholder="输入到当前设备"
          className="min-w-0 flex-1 rounded-[5px] border border-border bg-input px-2 py-1.5 text-[10px] text-text outline-none focus:border-[var(--color-focus)] focus:ring-2 focus:ring-[var(--color-focus-soft)] disabled:bg-disabled disabled:text-disabled-text"
        />
        <Button
          variant="quiet"
          disabled={disabled || !text}
          onClick={() => {
            onAction({ action: 'input_text', text });
            setText('');
          }}
          className="!rounded-[5px] !px-2.5 !py-1 !text-[10px]"
        >
          输入
        </Button>
      </div>
      {!enabled ? <div className="mt-2 text-[9px] text-status-warning" role="status">{disabledMessage || '取得人工租约后可发送触控和系统命令'}</div> : null}
    </div>
  );
};
