import React from 'react';

import { Button, TextArea } from '../common';

interface MatrixCommandBarProps {
  prompt: string;
  selectedCount: number;
  dispatching: boolean;
  stopping: boolean;
  canStop: boolean;
  result: string;
  onPromptChange: (value: string) => void;
  onDispatch: () => void;
  onEmergencyStop: () => void;
  onOpenAdvanced: () => void;
}

export const MatrixCommandBar: React.FC<MatrixCommandBarProps> = ({
  prompt,
  selectedCount,
  dispatching,
  stopping,
  canStop,
  result,
  onPromptChange,
  onDispatch,
  onEmergencyStop,
  onOpenAdvanced,
}) => (
  <section data-matrix-command-bar className="border-b border-white/[0.08] bg-[#0A1B26] px-3 py-2.5">
    <div className="grid grid-cols-[minmax(280px,1fr)_auto] items-end gap-2">
      <label className="min-w-0">
        <span className="sr-only">矩阵任务</span>
        <TextArea
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          rows={2}
          placeholder="输入要在已选设备上执行的真实任务"
          className="min-h-[58px] !rounded-[6px] !border-white/10 !bg-[#06131C] !px-3 !py-2 !text-xs !leading-5 !text-slate-100"
        />
      </label>
      <div className="flex items-center gap-2 pb-0.5">
        <span className="whitespace-nowrap text-[11px] font-bold text-slate-400">作用于 {selectedCount} 台</span>
        <Button variant="quiet" onClick={onOpenAdvanced} className="!rounded-[6px] !px-2.5 !py-2 !text-xs" title="任务高级参数">
          高级参数
        </Button>
        <Button variant="primary" onClick={onDispatch} disabled={dispatching || !selectedCount || !prompt.trim()} className="!rounded-[6px] !px-4 !py-2 !text-xs">
          {dispatching ? '下发中...' : '下发任务'}
        </Button>
        <Button
          data-matrix-emergency-stop
          variant="danger"
          onClick={onEmergencyStop}
          disabled={stopping || !canStop}
          className="!rounded-[6px] !px-3 !py-2 !text-xs"
          title={canStop ? '紧急停止作用范围内的活动任务' : '当前没有运行中或排队任务'}
        >
          {stopping ? '急停中...' : '急停'}
        </Button>
      </div>
    </div>
    {result ? <div data-matrix-action-result className="mt-1.5 text-[11px] font-semibold text-cyan-100">{result}</div> : null}
  </section>
);
