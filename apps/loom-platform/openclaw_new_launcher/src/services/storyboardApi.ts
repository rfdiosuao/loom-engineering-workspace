import { api } from './api';
import type {
  StoryboardParamConfig,
  StoryboardProject,
} from '../components/storyboard/storyboardTypes';

export interface StoryboardParamConfigResponse {
  config: StoryboardParamConfig;
}

export interface StoryboardImportResult {
  ok: boolean;
  optionCount: number;
  warnings: { missing: string[] };
  backfilled: StoryboardParamConfig;
}

export interface StoryboardGenerateResult {
  stage: 'script' | 'storyboard' | 'videoPrompt';
  result: string;
  rawText: string;
}

export const storyboardApi = {
  getParamConfig: (): Promise<StoryboardParamConfigResponse> =>
    api('/api/storyboard/param-config'),
  importParamConfig: (config: unknown): Promise<StoryboardImportResult> =>
    api('/api/storyboard/import-param-config', 'POST', { config }),
  generate: (params: {
    stage: 'script' | 'storyboard' | 'videoPrompt';
    project: StoryboardProject;
  }): Promise<StoryboardGenerateResult> =>
    api('/api/storyboard/generate', 'POST', params),
};
