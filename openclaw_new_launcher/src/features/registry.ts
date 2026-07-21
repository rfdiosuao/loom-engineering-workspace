import type { NavItem } from '../types/theme';

export type FeatureAction =
  | { type: 'page' }
  | { type: 'external'; url: string }
  | { type: 'command'; command: 'update' };

export interface FeatureDefinition {
  key: string;
  label: string;
  desc?: string;
  icon: string;
  group: string;
  accent?: boolean;
  requiresLicense?: boolean;
  action: FeatureAction;
  visible?: boolean;
}

const GROUP_CORE = 'LOOM';
const HIDDEN = false;

export const FEATURE_DEFINITIONS: FeatureDefinition[] = [
  { key: 'dashboard', label: '总览', desc: '状态 / 演示', icon: 'HOME', group: GROUP_CORE, action: { type: 'page' } },
  { key: 'agents', label: '安装', desc: '智能体运行时', icon: 'INS', group: GROUP_CORE, action: { type: 'page' } },
  { key: 'agent', label: '智能体', desc: '对话 / 编排 / 调试', icon: 'AGT', group: GROUP_CORE, action: { type: 'page' } },
  { key: 'creative', label: '创作', desc: '生图 / 生视频', icon: 'CRT', group: GROUP_CORE, action: { type: 'page' } },
  { key: 'acquisition', label: '获客', desc: '线索 / 草稿 / 跟进', icon: 'MATRIX', group: GROUP_CORE, accent: true, action: { type: 'page' } },
  { key: 'phone', label: '手机', desc: '连接 / 截图 / 读屏', icon: 'PHN', group: GROUP_CORE, action: { type: 'page' }, requiresLicense: true, visible: HIDDEN },
  { key: 'workbench', label: '工作台', desc: '手机矩阵 / 任务发布', icon: 'MATRIX', group: GROUP_CORE, action: { type: 'page' }, requiresLicense: true },
  { key: 'license', label: '模型账户', desc: '登录 / 模型', icon: 'ACC', group: GROUP_CORE, action: { type: 'page' } },
  { key: 'agentAccess', label: 'Agent 接入', desc: 'MCP / CLI / 提示词', icon: 'MCP', group: GROUP_CORE, action: { type: 'page' } },
  { key: 'capabilities', label: '其他', desc: '暂未开放', icon: 'CAP', group: GROUP_CORE, action: { type: 'page' }, visible: HIDDEN },
  { key: 'settings', label: '设置', desc: '系统设置', icon: 'SET', group: GROUP_CORE, action: { type: 'page' }, visible: HIDDEN },
  { key: 'models', label: '模型', desc: '模型选择', icon: 'MDL', group: GROUP_CORE, action: { type: 'page' }, visible: HIDDEN },
  { key: 'diagnostics', label: '诊断', desc: '环境 / 日志', icon: 'FIX', group: GROUP_CORE, action: { type: 'page' }, visible: HIDDEN },
  { key: 'terminal', label: '日志', desc: '运行日志', icon: 'LOG', group: GROUP_CORE, action: { type: 'page' }, visible: HIDDEN },
];

const FEATURE_BY_KEY = new Map(FEATURE_DEFINITIONS.map((feature) => [feature.key, feature]));

export const DEFAULT_FEATURE_NAV_ITEMS: NavItem[] = FEATURE_DEFINITIONS
  .filter((feature) => feature.visible !== false)
  .map(({ key, label, desc, icon, group, accent }) => ({ key, label, desc, icon, group, accent }));

export function getFeatureDefinition(key: string): FeatureDefinition | undefined {
  return FEATURE_BY_KEY.get(key);
}

export function isLicenseProtectedFeature(key: string): boolean {
  return Boolean(getFeatureDefinition(key)?.requiresLicense);
}

export function normalizeFeatureNavItems(items?: NavItem[]): NavItem[] {
  const source = Array.isArray(items) && items.length > 0 ? items : DEFAULT_FEATURE_NAV_ITEMS;
  const normalized = source
    .map((item) => {
      if (!item?.key) return null;
      const known = FEATURE_BY_KEY.get(item.key);
      if (!known || known.visible === false) return null;
      return {
        key: known.key,
        label: known.label,
        desc: known.desc,
        icon: known.icon,
        group: known.group,
        accent: known.accent,
      };
    })
    .filter(Boolean) as NavItem[];

  const byKey = new Map(normalized.map((item) => [item.key, item]));
  return DEFAULT_FEATURE_NAV_ITEMS.map((item) => byKey.get(item.key) || item);
}
