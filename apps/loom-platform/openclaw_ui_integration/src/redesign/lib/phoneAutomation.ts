export type AutomationPackId = 'xianyu' | 'generic';
export type AutomationRunMode = 'dry-run' | 'safe';
export type AutomationLogStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped';
export type AutomationRiskLevel = 'low' | 'medium' | 'high';

export interface AutomationTemplateVariable {
  key: string;
  label: string;
  value: string;
}

export interface AutomationTemplate {
  id: string;
  packId: AutomationPackId;
  title: string;
  description: string;
  appName: string;
  mode: AutomationRunMode;
  riskLevel: AutomationRiskLevel;
  enabled: boolean;
  requiresManualConfirmation: boolean;
  tags: string[];
  variables: AutomationTemplateVariable[];
  prompt: string;
  updatedAt: string;
}

export interface AutomationSchedule {
  id: string;
  label: string;
  templateId: string;
  deviceIds: string[];
  cadence: string;
  timeWindow: string;
  mode: AutomationRunMode;
  enabled: boolean;
  allowUnattended?: boolean;
  createdAt: string;
  updatedAt: string;
  nextRunHint: string;
}

export interface AutomationQueueItem {
  id: string;
  scheduleId?: string;
  templateId: string;
  deviceIds: string[];
  status: AutomationLogStatus;
  createdAt: string;
  updatedAt: string;
  mode: AutomationRunMode;
  result?: string;
}

export interface AutomationRunLog {
  id: string;
  queueId: string;
  scheduleId?: string;
  templateId: string;
  templateTitle: string;
  deviceId: string;
  deviceName: string;
  status: AutomationLogStatus;
  mode: AutomationRunMode;
  queuedAt: string;
  startedAt?: string;
  finishedAt?: string;
  result?: string;
  failureReason?: string;
  screenshotPath?: string;
}

export interface PhoneAutomationState {
  schema: 'openclaw.launcher.phone-automation.v1';
  updatedAt: string;
  templates: AutomationTemplate[];
  schedules: AutomationSchedule[];
  queue: AutomationQueueItem[];
  logs: AutomationRunLog[];
}

export const PHONE_AUTOMATION_CONFIG_PATH = 'data/.openclaw/launcher/phone-automation.json';
export const PHONE_AUTOMATION_LOCAL_KEY = 'openclaw.phone-automation.v1';

function nowIso() {
  return new Date().toISOString();
}

function idSuffix() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function builtInTemplate(
  input: Omit<AutomationTemplate, 'updatedAt'>,
): AutomationTemplate {
  return { ...input, updatedAt: nowIso() };
}

export function createAutomationId(prefix: string) {
  return `${prefix}-${idSuffix()}`;
}

export function builtInAutomationTemplates(): AutomationTemplate[] {
  return [
    builtInTemplate({
      id: 'xianyu-polish',
      packId: 'xianyu',
      title: '闲鱼一键擦亮',
      description: '固定执行：闲鱼、我的、我发布的、一键擦亮。',
      appName: '闲鱼',
      mode: 'safe',
      riskLevel: 'low',
      enabled: true,
      requiresManualConfirmation: false,
      tags: ['闲鱼', '擦亮', '低风险'],
      variables: [
        { key: 'maxRounds', label: '最大步骤', value: '8' },
      ],
      prompt:
        '固定链路，只做四步，最多 {{maxRounds}} 步。1 打开闲鱼。2 点击底部导航「我的」。3 点击「我发布的」。4 仅当「我发布的」页面或顶部管理区明确出现「一键擦亮/今日擦亮/擦亮/立即擦亮」时点击一次，随后立即读取截图和节点树并结束。不要进入曝光、赚曝光、超级曝光、发闲置、发布、签到、闲鱼币、消息、设置、客服、商品推荐、一键转卖、改价、下架、删除、聊天、支付、授权。遇到登录、验证码、风控、弹窗、页面不确定或未找到入口，立即停止并返回原因。结果只写：已点击、未出现入口、平台无反馈、已停止。',
    }),
    builtInTemplate({
      id: 'xianyu-checkin',
      packId: 'xianyu',
      title: '闲鱼签到',
      description: '领取明确可领取的签到奖励。',
      appName: '闲鱼',
      mode: 'safe',
      riskLevel: 'low',
      enabled: true,
      requiresManualConfirmation: false,
      tags: ['闲鱼', '签到', '低风险'],
      variables: [
        { key: 'rewardScope', label: '领取范围', value: '签到/领取奖励/扔骰子' },
      ],
      prompt:
        '打开闲鱼，进入签到或闲鱼币任务入口。只点击明确显示为「{{rewardScope}}」且不需要额外确认的日常按钮。不要点商品浏览任务、抽奖、支付、开通会员、授权协议、广告投放或发布入口。遇到「再点几个宝贝」「去发布」「去兑换」等会改变真实状态的任务，立即停止并截图。返回：已领取、已完成、未出现入口、已停止。',
    }),
    builtInTemplate({
      id: 'xianyu-listing-inspection',
      packId: 'xianyu',
      title: '闲鱼商品巡检',
      description: '只读检查商品状态和异常提示。',
      appName: '闲鱼',
      mode: 'dry-run',
      riskLevel: 'low',
      enabled: true,
      requiresManualConfirmation: false,
      tags: ['闲鱼', '只读', '低风险'],
      variables: [
        { key: 'scanItems', label: '巡检数量', value: '10' },
      ],
      prompt:
        '打开闲鱼，进入「我的」->「我发布的」，只读取最多 {{scanItems}} 个商品或服务的标题、状态、异常提示和待处理入口。不要点击发布、改价、删除、聊天、付款、投放、兑换或授权按钮。返回问题清单、风险提示和截图路径。',
    }),
    builtInTemplate({
      id: 'xianyu-message-snapshot',
      packId: 'xianyu',
      title: '闲鱼消息只读',
      description: '只读查看未读消息数量和会话摘要。',
      appName: '闲鱼',
      mode: 'dry-run',
      riskLevel: 'low',
      enabled: true,
      requiresManualConfirmation: false,
      tags: ['闲鱼', '消息', '只读'],
      variables: [
        { key: 'maxThreads', label: '会话数量', value: '5' },
      ],
      prompt:
        '打开闲鱼消息页，只读取未读数量和最多 {{maxThreads}} 个会话摘要。不要进入支付，不要点击发送，不要回复，不要复制隐私信息。返回会话数量、需要人工处理的摘要和截图路径。',
    }),
    builtInTemplate({
      id: 'xianyu-exposure',
      packId: 'xianyu',
      title: '闲鱼曝光 dry-run',
      description: '进入超级曝光页，停在投放确认前。',
      appName: '闲鱼',
      mode: 'dry-run',
      riskLevel: 'high',
      enabled: true,
      requiresManualConfirmation: true,
      tags: ['闲鱼', '曝光', '确认前'],
      variables: [
        { key: 'candidateCount', label: '候选数量', value: '5' },
      ],
      prompt:
        'dry-run。打开闲鱼，进入「我的」->「我发布的」，只点击顶部或商品管理区的「加曝光/超级曝光」入口。读取可用曝光、已加曝光次数、可投放商品，最多查看 {{candidateCount}} 个候选。若显示「暂无可加曝光的宝贝」，直接返回。禁止点击「开始曝光/确认使用/加曝光确认/去发布/去兑换/支付」。必须停在确认前并截图。',
    }),
    builtInTemplate({
      id: 'xianyu-earn-exposure',
      packId: 'xianyu',
      title: '赚曝光 dry-run',
      description: '只读取赚曝光任务列表。',
      appName: '闲鱼',
      mode: 'dry-run',
      riskLevel: 'medium',
      enabled: true,
      requiresManualConfirmation: true,
      tags: ['闲鱼', '赚曝光', '确认前'],
      variables: [
        { key: 'maxTasks', label: '任务数量', value: '6' },
      ],
      prompt:
        'dry-run。进入「超级曝光」后只打开「去赚曝光/赚曝光」面板，读取最多 {{maxTasks}} 个任务名称、奖励和按钮文案。不要点击「去发布/去兑换/领取/开启/9折开启/加曝光」。遇到兑换、发布、2人小刀、广告曝光或领取确认，立即停止并截图。',
    }),
    builtInTemplate({
      id: 'xianyu-publish-dry-run',
      packId: 'xianyu',
      title: '发闲置 dry-run',
      description: '验证发布入口，停在发布表单。',
      appName: '闲鱼',
      mode: 'dry-run',
      riskLevel: 'high',
      enabled: true,
      requiresManualConfirmation: true,
      tags: ['闲鱼', '上架', '确认前'],
      variables: [
        { key: 'listingType', label: '发布类型', value: '发闲置/发服务' },
      ],
      prompt:
        'dry-run。只验证「{{listingType}}」入口是否可达。可以进入发布表单并截图；进入表单后立即停止。禁止选择图片、上传素材、填写标题/描述/价格、选择分类、保存草稿或点击右上角「发布」。如果出现发布确认、授权、支付或风控页面，立即停止。',
    }),
    builtInTemplate({
      id: 'xianyu-bargain-dry-run',
      packId: 'xianyu',
      title: '2人小刀 dry-run',
      description: '只定位 2 人小刀入口。',
      appName: '闲鱼',
      mode: 'dry-run',
      riskLevel: 'high',
      enabled: true,
      requiresManualConfirmation: true,
      tags: ['闲鱼', '2人小刀', '确认前'],
      variables: [
        { key: 'maxCandidates', label: '候选数量', value: '3' },
      ],
      prompt:
        'dry-run。只在赚曝光任务中定位「2人小刀」入口和最多 {{maxCandidates}} 个候选商品。禁止点击「开启/9折开启/关闭/确认/改价/下架」。如果需要切换「只展示可开启宝贝」或改变商品状态，立即停止并截图。',
    }),
    builtInTemplate({
      id: 'xianyu-ad-exposure-dry-run',
      packId: 'xianyu',
      title: '广告曝光 dry-run',
      description: '只定位广告加曝光路径。',
      appName: '闲鱼',
      mode: 'dry-run',
      riskLevel: 'high',
      enabled: true,
      requiresManualConfirmation: true,
      tags: ['闲鱼', '广告曝光', '确认前'],
      variables: [
        { key: 'city', label: '城市', value: '当前定位城市' },
      ],
      prompt:
        'dry-run。只查找签到页或任务页中的广告加曝光入口，记录城市「{{city}}」、可选曝光项和确认按钮位置。禁止点击「加曝光/开始曝光/确认投放/支付/发布」。遇到弹窗、广告播放、投放确认或资源消耗提示，立即停止并截图。',
    }),
    builtInTemplate({
      id: 'generic-screen-check',
      packId: 'generic',
      title: '读屏诊断',
      description: '读取当前屏幕和可操作按钮。',
      appName: '任意应用',
      mode: 'dry-run',
      riskLevel: 'low',
      enabled: true,
      requiresManualConfirmation: false,
      tags: ['通用', '观察', '诊断'],
      variables: [
        { key: 'focus', label: '关注点', value: '当前页面是否可以安全继续' },
      ],
      prompt:
        '读取当前手机屏幕和节点树，判断 {{focus}}。不要点击或输入。返回页面标题、关键按钮、风险提示、下一步建议和截图路径。',
    }),
    builtInTemplate({
      id: 'generic-open-app-snapshot',
      packId: 'generic',
      title: '打开应用截图',
      description: '打开指定应用后截图。',
      appName: '任意应用',
      mode: 'safe',
      riskLevel: 'low',
      enabled: true,
      requiresManualConfirmation: false,
      tags: ['通用', '巡检', '截图'],
      variables: [
        { key: 'targetApp', label: '目标应用', value: '微信' },
      ],
      prompt:
        '打开 {{targetApp}}，只读取当前屏幕并截图。不要点击页面中的业务按钮，不要发送消息，不要授权，不要支付。返回当前页面、风险提示和截图路径。',
    }),
    builtInTemplate({
      id: 'generic-ad-watch-reward',
      packId: 'generic',
      title: '广告等待',
      description: '等待指定时长后关闭广告或领取奖励。',
      appName: '任意应用',
      mode: 'safe',
      riskLevel: 'medium',
      enabled: true,
      requiresManualConfirmation: false,
      tags: ['通用', '广告', '等待'],
      variables: [
        { key: 'minWatchSeconds', label: '最短观看秒数', value: '30' },
        { key: 'maxWatchSeconds', label: '最长等待秒数', value: '90' },
        { key: 'allowChainAds', label: '允许链式广告', value: 'false' },
        { key: 'maxChainCount', label: '最多链式次数', value: '0' },
        { key: 'rewardKeywords', label: '奖励按钮', value: '领取奖励/获得奖励/领取/完成/返回' },
      ],
      prompt:
        'OPENCLAW_AD_WATCH。处理当前广告或奖励等待页。最短等待 {{minWatchSeconds}} 秒，最长等待 {{maxWatchSeconds}} 秒；每 1-2 秒读取屏幕、节点树或截图，确认倒计时、跳过、关闭、领取奖励等状态。未达到最短等待前，不要点击「跳过/关闭/×/领取奖励」。达到最短等待后，只点击明确安全的「{{rewardKeywords}}」或关闭/返回按钮。链式广告策略：allowChainAds={{allowChainAds}}，maxChainCount={{maxChainCount}}；如果出现「再看一个/继续观看/双倍奖励」且未明确允许，选择不继续或关闭。禁止点击下载、安装、打开第三方应用、应用商店、支付、登录、授权、隐私协议。遇到未知弹窗、页面跳出目标应用、无倒计时且超过最长等待、黑屏或连续同屏无变化，立即停止并返回原因和截图路径。结果只写：completed、no_reward_button、chain_rejected、unsafe_prompt、app_escaped、stuck 或 unknown_overlay。',
    }),
  ];
}

export function createDefaultAutomationState(): PhoneAutomationState {
  const now = nowIso();
  return {
    schema: 'openclaw.launcher.phone-automation.v1',
    updatedAt: now,
    templates: builtInAutomationTemplates(),
    schedules: [],
    queue: [],
    logs: [],
  };
}

export function normalizeAutomationState(value: unknown): PhoneAutomationState {
  const defaults = createDefaultAutomationState();
  if (!value || typeof value !== 'object') return defaults;
  const raw = value as Partial<PhoneAutomationState>;
  const templates = mergeTemplates(Array.isArray(raw.templates) ? raw.templates : [], defaults.templates);
  const templateIds = new Set(templates.map((item) => item.id));
  const schedules = Array.isArray(raw.schedules)
    ? raw.schedules
        .map((item) => normalizeSchedule(item, templateIds))
        .filter(Boolean) as AutomationSchedule[]
    : [];
  const queue = Array.isArray(raw.queue)
    ? raw.queue
        .map((item) => normalizeQueueItem(item, templateIds))
        .filter(Boolean)
        .slice(-80) as AutomationQueueItem[]
    : [];
  const logs = Array.isArray(raw.logs)
    ? raw.logs
        .map((item) => normalizeRunLog(item, templateIds))
        .filter(Boolean)
        .slice(-200) as AutomationRunLog[]
    : [];
  return {
    schema: 'openclaw.launcher.phone-automation.v1',
    updatedAt: text(raw.updatedAt) || defaults.updatedAt,
    templates,
    schedules,
    queue,
    logs,
  };
}

function mergeTemplates(saved: unknown[], defaults: AutomationTemplate[]) {
  const byId = new Map(defaults.map((item) => [item.id, item]));
  for (const item of saved) {
    const normalized = normalizeTemplate(item);
    if (normalized) byId.set(normalized.id, { ...(byId.get(normalized.id) || {} as AutomationTemplate), ...normalized });
  }
  return Array.from(byId.values());
}

function normalizeTemplate(value: unknown): AutomationTemplate | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Partial<AutomationTemplate>;
  const id = text(raw.id);
  if (!id) return null;
  return {
    id,
    packId: raw.packId === 'generic' ? 'generic' : 'xianyu',
    title: text(raw.title) || id,
    description: text(raw.description),
    appName: text(raw.appName) || '任意应用',
    mode: raw.mode === 'safe' ? 'safe' : 'dry-run',
    riskLevel: normalizeRiskLevel(raw.riskLevel, raw.mode, raw.requiresManualConfirmation),
    enabled: raw.enabled !== false,
    requiresManualConfirmation: Boolean(raw.requiresManualConfirmation),
    tags: Array.isArray(raw.tags) ? raw.tags.map(text).filter(Boolean) : [],
    variables: Array.isArray(raw.variables)
      ? raw.variables.map((item) => ({
          key: text((item as AutomationTemplateVariable)?.key),
          label: text((item as AutomationTemplateVariable)?.label),
          value: text((item as AutomationTemplateVariable)?.value),
        })).filter((item) => item.key)
      : [],
    prompt: text(raw.prompt),
    updatedAt: text(raw.updatedAt) || nowIso(),
  };
}

function normalizeSchedule(value: unknown, templateIds: Set<string>): AutomationSchedule | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Partial<AutomationSchedule>;
  const id = text(raw.id);
  const templateId = text(raw.templateId);
  if (!id || !templateIds.has(templateId)) return null;
  return {
    id,
    label: text(raw.label) || '未命名计划',
    templateId,
    deviceIds: Array.isArray(raw.deviceIds) ? raw.deviceIds.map(text).filter(Boolean) : [],
    cadence: text(raw.cadence) || '手动',
    timeWindow: text(raw.timeWindow) || '不限',
    mode: raw.mode === 'safe' ? 'safe' : 'dry-run',
    enabled: raw.enabled !== false,
    allowUnattended: Boolean(raw.allowUnattended),
    createdAt: text(raw.createdAt) || nowIso(),
    updatedAt: text(raw.updatedAt) || nowIso(),
    nextRunHint: text(raw.nextRunHint) || '等待下一次触发',
  };
}

function normalizeQueueItem(value: unknown, templateIds: Set<string>): AutomationQueueItem | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Partial<AutomationQueueItem>;
  const id = text(raw.id);
  const templateId = text(raw.templateId);
  if (!id || !templateIds.has(templateId)) return null;
  return {
    id,
    scheduleId: text(raw.scheduleId) || undefined,
    templateId,
    deviceIds: Array.isArray(raw.deviceIds) ? raw.deviceIds.map(text).filter(Boolean) : [],
    status: normalizeStatus(raw.status),
    createdAt: text(raw.createdAt) || nowIso(),
    updatedAt: text(raw.updatedAt) || nowIso(),
    mode: raw.mode === 'safe' ? 'safe' : 'dry-run',
    result: text(raw.result) || undefined,
  };
}

function normalizeRunLog(value: unknown, templateIds: Set<string>): AutomationRunLog | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Partial<AutomationRunLog>;
  const id = text(raw.id);
  const templateId = text(raw.templateId);
  if (!id || !templateIds.has(templateId)) return null;
  return {
    id,
    queueId: text(raw.queueId) || 'manual',
    scheduleId: text(raw.scheduleId) || undefined,
    templateId,
    templateTitle: text(raw.templateTitle) || templateId,
    deviceId: text(raw.deviceId) || 'unknown',
    deviceName: text(raw.deviceName) || '未命名设备',
    status: normalizeStatus(raw.status),
    mode: raw.mode === 'safe' ? 'safe' : 'dry-run',
    queuedAt: text(raw.queuedAt) || nowIso(),
    startedAt: text(raw.startedAt) || undefined,
    finishedAt: text(raw.finishedAt) || undefined,
    result: text(raw.result) || undefined,
    failureReason: text(raw.failureReason) || undefined,
    screenshotPath: text(raw.screenshotPath) || undefined,
  };
}

function normalizeStatus(value: unknown): AutomationLogStatus {
  const status = text(value);
  if (status === 'running' || status === 'success' || status === 'failed' || status === 'skipped') return status;
  return 'pending';
}

function normalizeRiskLevel(
  value: unknown,
  mode?: AutomationRunMode,
  requiresManualConfirmation?: boolean,
): AutomationRiskLevel {
  const riskLevel = text(value);
  if (riskLevel === 'low' || riskLevel === 'medium' || riskLevel === 'high') return riskLevel;
  if (requiresManualConfirmation) return 'medium';
  return mode === 'safe' ? 'low' : 'low';
}

export function applyTemplateVariables(template: AutomationTemplate): string {
  return template.variables.reduce((prompt, item) => {
    const pattern = new RegExp(`{{\\s*${escapeRegExp(item.key)}\\s*}}`, 'g');
    return prompt.replace(pattern, item.value);
  }, template.prompt);
}

export function automationStatusLabel(status: AutomationLogStatus): string {
  switch (status) {
    case 'pending': return '待执行';
    case 'running': return '执行中';
    case 'success': return '成功';
    case 'failed': return '失败';
    case 'skipped': return '已跳过';
    default: return '未知';
  }
}

export function automationStatusTone(status: AutomationLogStatus): 'neutral' | 'ok' | 'warn' | 'danger' {
  switch (status) {
    case 'success': return 'ok';
    case 'failed': return 'danger';
    case 'skipped': return 'warn';
    default: return 'neutral';
  }
}

export function automationRiskLabel(riskLevel: AutomationRiskLevel): string {
  switch (riskLevel) {
    case 'low': return '低风险';
    case 'medium': return '需确认';
    case 'high': return '高风险';
    default: return '未知风险';
  }
}

export function automationRiskTone(riskLevel: AutomationRiskLevel): 'neutral' | 'ok' | 'warn' | 'danger' {
  switch (riskLevel) {
    case 'low': return 'ok';
    case 'medium': return 'warn';
    case 'high': return 'danger';
    default: return 'neutral';
  }
}

export function readCachedAutomationState(): PhoneAutomationState {
  try {
    return normalizeAutomationState(JSON.parse(localStorage.getItem(PHONE_AUTOMATION_LOCAL_KEY) || 'null'));
  } catch {
    return createDefaultAutomationState();
  }
}

export function writeCachedAutomationState(state: PhoneAutomationState) {
  try {
    localStorage.setItem(PHONE_AUTOMATION_LOCAL_KEY, JSON.stringify(state));
  } catch {
    // Local cache must never block task execution.
  }
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
