import React from 'react';
import claudeLogo from '../../assets/agents/claude-color.svg';
import codexLogo from '../../assets/agents/codex-color.svg';
import hermesLogo from '../../assets/agents/hermesagent.svg';
import openclawLogo from '../../assets/agents/openclaw-color.svg';
import opencodeLogo from '../../assets/agents/opencode.svg';

const AGENT_LOGOS: Record<string, string> = {
  'codex-desktop': codexLogo,
  'claude-code': claudeLogo,
  opencode: opencodeLogo,
  'openclaw-companion': openclawLogo,
  hermes: hermesLogo,
};

const AGENT_LABELS: Record<string, string> = {
  'codex-desktop': 'Codex',
  'claude-code': 'Claude Code',
  opencode: 'opencode',
  'openclaw-companion': 'OpenClaw',
  hermes: 'Hermes',
};

export const AgentLogo: React.FC<{ id: string; size?: 'normal' | 'large'; className?: string }> = ({
  id,
  size = 'normal',
  className = '',
}) => {
  const logo = AGENT_LOGOS[id];
  const label = AGENT_LABELS[id] || id;
  const boxSize = size === 'large' ? 'h-14 w-14 rounded-[18px] p-2.5' : 'h-10 w-10 rounded-[14px] p-2';
  const classes = `agent-logo flex shrink-0 items-center justify-center border border-border/80 bg-surface shadow-[0_14px_30px_rgba(0,0,0,0.14)] ${boxSize} ${className}`;

  if (!logo) {
    return (
      <div className={classes} aria-hidden="true">
        <span className="text-sm font-black text-accent">{label.slice(0, 1).toUpperCase()}</span>
      </div>
    );
  }

  return (
    <div className={classes}>
      <img src={logo} alt={`${label} logo`} className="h-full w-full object-contain" draggable={false} />
    </div>
  );
};
