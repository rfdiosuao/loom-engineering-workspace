import packageJson from '../package.json';

function buildValue(key: string, fallback: string): string {
  const buildEnvironment = (import.meta as ImportMeta & {
    env?: Record<string, unknown>;
  }).env ?? {};
  const value = String(buildEnvironment[key] ?? '').trim();
  return value || fallback;
}

export const APP_VERSION = packageJson.version;
export const APP_DISPLAY_NAME = buildValue('VITE_LOOM_BRAND_DISPLAY_NAME', '麓鸣AI矩阵获客工作台');
export const APP_DISPLAY_SUBTITLE = buildValue('VITE_LOOM_BRAND_SUBTITLE', '手机矩阵获客与自动化总控');
export const APP_NATIVE_AGENT_NAME = `${APP_DISPLAY_NAME} 原生智能体`;
export const APP_BRAND_LOGO_URL = buildValue('VITE_LOOM_BRAND_LOGO_URL', '');
export const APP_BRAND_LOGO_DATA_URL = buildValue('VITE_LOOM_BRAND_LOGO_DATA_URL', '');
export const APP_HOME_TITLE = buildValue('VITE_LOOM_BRAND_HOME_TITLE', `开始使用${APP_DISPLAY_NAME}`);
export const APP_TASK_PLACEHOLDER = buildValue('VITE_LOOM_BRAND_TASK_PLACEHOLDER', '输入任务或问题');
export const APP_SUPPORT_LABEL = buildValue('VITE_LOOM_BRAND_SUPPORT_LABEL', '联系支持');
export const APP_HIDDEN_MODULES = new Set(
  buildValue('VITE_LOOM_BRAND_HIDDEN_MODULES', '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean),
);
