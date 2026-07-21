import type React from 'react';

interface BotInstallConsoleProps {
  commandSummary: string;
  commandLog: string[];
  outputRef: React.RefObject<HTMLPreElement>;
  onClear: () => void;
}

export const BotInstallConsole: React.FC<BotInstallConsoleProps> = ({
  commandSummary,
  commandLog,
  outputRef,
  onClear,
}) => (
  <div className="flex min-h-[360px] min-w-0 flex-col overflow-hidden rounded-xl border border-border bg-terminal-bg shadow-inner lg:min-h-[520px]">
    <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border bg-terminal-header px-4 py-3">
      <div className="min-w-0">
        <div className="text-[11px] font-bold uppercase tracking-[0.22em] text-accent">Install Console</div>
        <div className="mt-1 whitespace-pre-wrap break-all font-mono text-xs text-text-subtle">{commandSummary}</div>
      </div>
      <button
        onClick={onClear}
        className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-text-muted transition hover:bg-hover hover:text-text"
      >
        清空
      </button>
    </div>
    <pre
      ref={outputRef}
      className="min-h-0 flex-1 overflow-auto whitespace-pre px-4 py-4 font-mono text-[11px] leading-[1.1] text-terminal-text [tab-size:2]"
    >
      {commandLog.length > 0
        ? commandLog.join('')
        : '点击安装后，这里会实时显示命令行输出。\n如果输出二维码、验证码或登录链接，客户可以直接在这里扫码/复制。'}
    </pre>
  </div>
);
