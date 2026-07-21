export type ModuleKey =
  | '模块一' | '模块二' | '模块三' | '模块四' | '模块五'
  | '模块六' | '模块七' | '模块八' | '模块九';

export type AssetKind = '人物图' | '产品图' | '场景图';

/** option value: string for tag/radio/dropdown, boolean for toggle */
export type OptionValue = string | boolean;

/** module -> category -> selected option values */
export type StoryboardSelections = Partial<Record<ModuleKey, Record<string, OptionValue[]>>>;

export interface StoryboardTarget {
  category: string;
  object: string;
}

export interface StoryboardShot {
  num: number;
  time?: string;
  scene?: string;
  voice?: string;
  subtitle?: string;
  effect?: string;
  shotType?: string;
  camera?: string;
  transition?: string;
  bgm?: string;
  assetType?: '人物图' | '产品图' | '场景图' | '无' | string;
  shootTip?: string;
}

export interface StoryboardProject {
  projectId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  target: StoryboardTarget;
  selections: StoryboardSelections;
  script: { content: string; versions?: Array<{ content: string; savedAt: string }>; generatedAt?: string };
  storyboard: { shots: StoryboardShot[]; generatedAt?: string };
  assetPrompts?: { 人物图: string[]; 产品图: string[]; 场景图: string[] };
  /**
   * Per-prompt reference images, aligned by index with assetPrompts.
   * Each entry is the ReferenceImage's requestValue (data URL or asset path)
   * or null when no reference is attached.
   */
  assetReferences?: { 人物图: Array<string | null>; 产品图: Array<string | null>; 场景图: Array<string | null> };
  generatedAssets?: Array<{ shotNum: number; kind: string; mediaId?: string; path?: string; createdAt?: string }>;
  videoPrompt?: { content: string; generatedAt?: string };
  videoResult?: { path?: string; filename?: string; generatedAt?: string };
}

/** module -> category -> option -> prompt string (already backfilled, no nulls) */
export type StoryboardParamConfig = Partial<Record<ModuleKey, Record<string, Record<string, string>>>>;

export interface StoryboardProjectsIndexEntry {
  projectId: string;
  title: string;
  updatedAt: string;
}
