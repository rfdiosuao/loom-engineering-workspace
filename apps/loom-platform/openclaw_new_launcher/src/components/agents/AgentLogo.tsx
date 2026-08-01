import React from 'react';
import { Claude, Gemini, Goose, Grok, OpenAI } from '@lobehub/icons';
import hermesLogo from '../../assets/agents/hermesagent.svg';
import openclawLogo from '../../assets/agents/openclaw-color.svg';
import opencodeLogo from '../../assets/agents/opencode.svg';

const AGENT_LOGOS: Record<string, string> = {
  opencode: opencodeLogo,
  'openclaw-companion': openclawLogo,
  hermes: hermesLogo,
};

type LobeIconComponent = React.ComponentType<{
  'aria-label'?: string;
  className?: string;
  role?: string;
  size?: number | string;
}>;

const LOBE_AGENT_LOGOS: Record<string, LobeIconComponent> = {
  'codex-desktop': OpenAI,
  'chatgpt-desktop': OpenAI,
  'codex-cli': OpenAI,
  'claude-code': Claude.Color,
  'grok-build': Grok,
  goose: Goose,
  'gemini-cli': Gemini.Color,
};

const AGENT_LABELS: Record<string, string> = {
  'codex-desktop': 'Codex',
  'chatgpt-desktop': 'ChatGPT',
  'codex-cli': 'Codex CLI',
  'claude-code': 'Claude Code',
  opencode: 'opencode',
  'openclaw-companion': 'OpenClaw',
  hermes: 'Hermes',
  'grok-build': 'Grok Build',
  pi: 'Pi',
  goose: 'Goose',
  'gemini-cli': 'Gemini CLI',
};

export const AgentLogo: React.FC<{ id: string; size?: 'normal' | 'large'; className?: string }> = ({
  id,
  size = 'normal',
  className = '',
}) => {
  const logo = AGENT_LOGOS[id];
  const LobeLogo = LOBE_AGENT_LOGOS[id];
  const label = AGENT_LABELS[id] || id;
  const boxSize = size === 'large' ? 'h-14 w-14 rounded-[18px] p-2.5' : 'h-10 w-10 rounded-[14px] p-2';
  const classes = `agent-logo flex shrink-0 items-center justify-center border border-border/80 bg-surface shadow-[0_14px_30px_rgba(0,0,0,0.14)] ${boxSize} ${className}`;

  if (LobeLogo) {
    return (
      <div className={classes}>
        <LobeLogo aria-label={`${label} logo`} className="h-full w-full" role="img" size="100%" />
      </div>
    );
  }

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
