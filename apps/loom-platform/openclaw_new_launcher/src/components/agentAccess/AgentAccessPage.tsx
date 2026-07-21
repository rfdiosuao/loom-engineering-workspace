import React from 'react';
import { Button, showToast } from '../common';
import {
  buildMcpJson,
  buildOneShotAgentPrompt,
  CLI_SMOKE,
  LUMING_SKILL_LIBRARY_FALLBACK_URL,
  LUMING_SKILL_LIBRARY_PATH,
  LUMING_SKILL_LIBRARY_URL,
  LUMING_SKILL_LIBRARY_SHA256,
  MCP_CONFIG_PATH,
  MCP_SMOKE,
} from './agentPrompt';

async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    showToast('复制失败，请手动选择文本', 'error');
    return false;
  }
}

const CopyBlock = ({ title, desc, value }: { title: string; desc: string; value: string }) => {
  const [copied, setCopied] = React.useState(false);
  const handleCopy = async () => {
    if (!await copyText(value)) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
  <section className="border-t border-border/70 py-4 last:border-b">
    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div className="min-w-0">
        <h2 className="text-sm font-black text-text">{title}</h2>
        <div className="mt-1 text-xs leading-5 text-text-muted">{desc}</div>
      </div>
      <Button variant="quiet" onClick={() => void handleCopy()}>{copied ? '已复制' : '复制'}</Button>
    </div>
  </section>
  );
};

const CopyOnlyBlock = ({ title, desc, value }: { title: string; desc: string; value: string }) => {
  const [copied, setCopied] = React.useState(false);
  const handleCopy = async () => {
    if (!await copyText(value)) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
  <section data-agent-one-shot-copy className="rounded-[8px] border border-accent/25 bg-accent/[0.07] p-5">
    <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
      <div>
        <h2 className="text-lg font-black text-text">{title}</h2>
        <div className="mt-1 text-sm leading-6 text-text-muted">{desc}</div>
        <div className="mt-2 text-xs font-bold text-accent">提示词正文不会在页面展示。</div>
      </div>
      <Button variant="primary" onClick={() => void handleCopy()}>{copied ? '已复制' : '复制接入提示词'}</Button>
    </div>
  </section>
  );
};

export const AgentAccessPage = () => {
  const mcpJson = buildMcpJson();
  const oneShotAgentPrompt = buildOneShotAgentPrompt(mcpJson);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface">
      <header className="shrink-0 border-b border-border/70 bg-surface px-8 py-7">
        <div className="text-[11px] font-bold tracking-[0.18em] text-accent">AGENT ACCESS</div>
        <h1 className="mt-2 text-[30px] font-black leading-tight text-text">Agent 接入</h1>
        <div className="mt-2 max-w-[760px] text-sm leading-6 text-text-muted">
          复制一条提示词，让任意本地 Agent 先识别真实宿主，再通过 LOOM CLI/MCP 接入全部能力。
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-8 py-7">
        <div className="mx-auto grid w-full max-w-[1120px] gap-5">
          <CopyOnlyBlock
            title="一条提示词接入"
            desc="支持 Codex、Claude Code、CodeBuddy、WorkBuddy 与其他 Agent；不会把未知宿主误写成 Codex。"
            value={oneShotAgentPrompt}
          />

          <details className="border-y border-border/70 py-4">
            <summary className="cursor-pointer text-sm font-black text-text">高级配置</summary>
            <div className="mt-3">
              <CopyBlock
                title="Skill 位置"
                desc="只安装 luming-phone-agent；目标目录必须由真实宿主决定，WorkBuddy 使用官方导入入口。"
                value={`统一 Skill 路径模板\n${LUMING_SKILL_LIBRARY_PATH}\n\n国内主源\n${LUMING_SKILL_LIBRARY_URL}\n\nGitHub 备用源\n${LUMING_SKILL_LIBRARY_FALLBACK_URL}\n\nSHA256\n${LUMING_SKILL_LIBRARY_SHA256}`}
              />
              <CopyBlock
                title="MCP 配置"
                desc={`保存或合并到 ${MCP_CONFIG_PATH}；WorkBuddy 使用项目 .workbuddy/mcp.json，其他宿主按官方位置。`}
                value={mcpJson}
              />
              <CopyBlock
                title="CLI 验证"
                desc="用于确认 LOOM CLI 和 MCP 入口能正常启动。"
                value={`${CLI_SMOKE}\n${MCP_SMOKE}`}
              />
            </div>
          </details>
        </div>
      </main>
    </div>
  );
};
