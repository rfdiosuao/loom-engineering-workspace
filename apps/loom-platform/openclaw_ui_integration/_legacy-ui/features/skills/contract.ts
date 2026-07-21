export type SkillRuntime = 'frontend' | 'bridge' | 'openclaw-plugin' | 'external';

export interface SkillConfigField {
  key: string;
  label: string;
  type: 'text' | 'password' | 'select' | 'boolean' | 'number';
  required?: boolean;
  options?: Array<{ label: string; value: string }>;
  placeholder?: string;
}

export interface SkillModuleContract {
  id: string;
  name: string;
  version: string;
  description?: string;
  category: string;
  icon?: string;
  runtime: SkillRuntime;
  requiresLicense?: boolean;
  requiresService?: boolean;
  configFields?: SkillConfigField[];
  nav?: {
    label: string;
    desc?: string;
    group: string;
    accent?: boolean;
  };
}

export interface SkillInstallState {
  skillId: string;
  installed: boolean;
  enabled: boolean;
  version?: string;
  lastError?: string;
}

export interface LocalSkillItem extends SkillModuleContract {
  source: 'uploaded' | 'openclaw-extensions' | 'node-modules' | string;
  sourceLabel: string;
  path: string;
  installed: boolean;
  enabled: boolean;
  writable: boolean;
  installedAt?: string;
}
