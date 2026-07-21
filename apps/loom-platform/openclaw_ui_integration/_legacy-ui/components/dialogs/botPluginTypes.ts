export const OPENCLAW_CONFIG_PATH = 'data/.openclaw/openclaw.json';

export type PluginStatus = 'unknown' | 'installed' | 'missing' | 'error';
export type BotChannelKey = 'feishu' | 'weixin' | 'dingtalk';

export interface InstallStep {
  label: string;
  displayCommand: string;
  commandName: string;
  fallbackCommandName: string;
  args: string[];
  successMessage: string;
}

export interface BotChannel {
  key: BotChannelKey;
  configKey: string;
  legacyConfigKey?: string;
  title: string;
  description: string;
  pluginName: string;
  packageName: string;
  packagePaths: string[];
  installSteps: InstallStep[];
  idLabel: string;
  idPlaceholder: string;
  secretLabel: string;
  secretPlaceholder: string;
  docsUrl?: string;
  docsLabel?: string;
  manualConfig: boolean;
}
