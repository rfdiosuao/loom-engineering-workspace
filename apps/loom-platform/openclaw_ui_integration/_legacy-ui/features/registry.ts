import type { NavItem } from '../types/theme';

export type FeatureAction =
  | { type: 'page' }
  | { type: 'dialog'; dialog: 'api' | 'feishu' | 'weixin' | 'dingtalk' }
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

export const FEATURE_DEFINITIONS: FeatureDefinition[] = [
  { key: 'dashboard', label: '系统状态总览', desc: '系统状态总览', icon: 'HOME', group: '工作台', action: { type: 'page' } },
  { key: 'terminal', label: '服务日志', desc: '查看运行状态', icon: 'LOG', group: '工作台', action: { type: 'page' } },
  { key: 'storyboard', label: '广告视频', desc: '分镜/首尾帧/九宫格', icon: 'AD', group: '工作台', accent: true, requiresLicense: true, action: { type: 'page' } },
  { key: 'image', label: 'AI 生图', desc: '生成/编辑图片', icon: 'IMG', group: '工作台', accent: true, requiresLicense: true, action: { type: 'page' } },
  { key: 'video', label: 'AI 视频', desc: '多模型视频生成', icon: 'VID', group: '工作台', accent: true, requiresLicense: true, action: { type: 'page' } },
  { key: 'phone', label: '手机控制', desc: '连接 APKClaw', icon: 'PH', group: '工作台', accent: true, requiresLicense: true, action: { type: 'page' } },
  { key: 'publish', label: '平台发布', desc: '手机发布图文/视频', icon: 'PUB', group: '工作台', accent: true, requiresLicense: true, action: { type: 'page' } },
  { key: 'desktop', label: '桌面控制', desc: '桌面代理控制', icon: 'PC', group: '工作台', accent: true, requiresLicense: true, action: { type: 'page' } },
  { key: 'license', label: '授权码', desc: '在线激活解锁', icon: 'LIC', group: '配置', action: { type: 'page' } },
  { key: 'api', label: 'API 配置', desc: '设置模型密钥', icon: 'KEY', group: '配置', action: { type: 'dialog', dialog: 'api' } },
  { key: 'feishu', label: '飞书机器人', desc: '绑定消息通道', icon: 'BOT', group: '配置', action: { type: 'dialog', dialog: 'feishu' } },
  { key: 'weixin', label: '微信机器人', desc: '扫码绑定微信', icon: 'WX', group: '配置', action: { type: 'dialog', dialog: 'weixin' } },
  { key: 'dingtalk', label: '钉钉机器人', desc: '扫码绑定钉钉', icon: 'DD', group: '配置', action: { type: 'dialog', dialog: 'dingtalk' } },
  { key: 'skills', label: 'Skills', desc: '安装/启用能力模块', icon: 'SK', group: '扩展', action: { type: 'page' } },
  { key: 'web', label: '网页界面', desc: '打开本地控制台', icon: 'WEB', group: '维护', action: { type: 'external', url: 'http://127.0.0.1:18790' } },
  { key: 'diagnostics', label: '环境诊断', desc: '检查/修复启动环境', icon: 'FIX', group: '维护', accent: true, action: { type: 'page' } },
  { key: 'update', label: '检查更新', desc: '更新 OpenClaw', icon: 'UP', group: '维护', action: { type: 'command', command: 'update' } },
  { key: 'help', label: '帮助文档', desc: '查看使用说明', icon: 'DOC', group: '维护', action: { type: 'external', url: 'https://heang.top/docs.html' } },
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
    .filter((item) => item?.key && item.key !== 'delivery')
    .map((item) => {
      const known = FEATURE_BY_KEY.get(item.key);
      if (!known || known.visible === false) return null;
      return {
        key: known.key,
        label: item.label || known.label,
        desc: item.desc ?? known.desc,
        icon: item.icon || known.icon,
        group: item.group || known.group,
        accent: item.accent ?? known.accent,
      };
    })
    .filter(Boolean) as NavItem[];

  const byKey = new Map(normalized.map((item) => [item.key, item]));
  return DEFAULT_FEATURE_NAV_ITEMS.map((item) => byKey.get(item.key) || item);
}
