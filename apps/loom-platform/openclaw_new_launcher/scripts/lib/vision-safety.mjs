const MUTATING_ACTIONS = new Set([
  'tap',
  'long_press',
  'longpress',
  'swipe',
  'drag',
  'click_ref',
  'click_text',
  'tap_text',
  'click_node',
  'tap_node',
  'click_element',
  'tap_element',
  'click_description',
  'tap_description',
  'input',
  'input_text',
  'scroll',
]);
const ACTION_FAST_ACTIONS = new Set([
  'back',
  'home',
  'open_app',
  'refresh',
  'wait_element',
  'click_ref',
  'click_text',
  'tap_text',
  'click_node',
  'tap_node',
  'click_element',
  'tap_element',
  'click_description',
  'tap_description',
  'input',
  'input_text',
  'scroll',
]);
const REF_PREFERRED_ACTIONS = new Set([
  'click_text',
  'tap_text',
  'click_node',
  'tap_node',
  'click_element',
  'tap_element',
  'click_description',
  'tap_description',
]);

export const VISION_SAFETY_KEYWORDS = [
  '支付',
  '付款',
  '收银台',
  '下单',
  '提交订单',
  '确认订单',
  '购买',
  '立即购买',
  '充值',
  '开通',
  '订阅',
  '转账',
  '提现',
  '红包',
  '银行卡',
  '密码',
  '验证码',
  '登录',
  '微信登录',
  'QQ登录',
  'qq登录',
  '授权登录',
  '账号授权',
  '账号绑定',
  '绑定手机',
  '实名认证',
  '人脸识别',
  '同意协议',
  '隐私政策',
  '用户协议',
  '同意并继续',
  '删除',
  '清除数据',
  '清空',
  '清理缓存',
  '格式化',
  '恢复出厂',
  '卸载',
  '注销账号',
  '退出登录',
  '退出游戏',
  '上报日志',
  '上传日志',
  'clear cache',
  'delete',
  'uninstall',
  'factory reset',
  'payment',
  'pay now',
  'purchase',
  'buy now',
  'checkout',
  'recharge',
  'subscribe',
  'login',
  'sign in',
  'authorize',
  'authorization',
  'bind account',
  'real-name',
  'real name',
  'privacy policy',
  'terms of service',
  'clear data',
  'upload logs',
  'report logs',
  'log out',
  'exit game',
];

const METADATA_KEYS = new Set([
  'targetLabel',
  'target_label',
  'label',
  'reason',
  'intent',
  'visualText',
  'visual_text',
  'ocrText',
  'ocr_text',
  'screenText',
  'screen_text',
  'description',
  'targetDescription',
  'target_description',
  'text',
  'targetText',
  'target_text',
  'contentDescription',
  'content_description',
  'resourceId',
  'resource_id',
  'nodeId',
  'node_id',
  'risk',
  'safetyNote',
  'safety_note',
]);

export function visionSafetyPolicy() {
  return {
    policy: 'openclaw_vision_safety_v1',
    defaultActionPath: 'OpenClaw visual plan -> APKClaw Agent safe_action -> verify with next frame',
    requiresTargetMetadata: true,
    blockedExamples: [
      'login/auth',
      'payment/purchase/recharge',
      'account binding/real-name',
      'delete/uninstall/reset',
      'clear cache/upload logs',
      'exit game/log out',
    ],
  };
}

export function inspectVisionActionPlan(plan, options = {}) {
  const action = normalizePhoneActionName(plan?.action || plan?.type || '');
  const strict = options.strict !== false;
  if (!action) {
    return blocked('missing_action', 'Missing action in visual plan.');
  }
  if (!MUTATING_ACTIONS.has(action)) {
    return allowed('non_mutating', action);
  }

  const metadata = collectMetadata(plan).toLowerCase();
  const matched = VISION_SAFETY_KEYWORDS.find((keyword) => metadata.includes(keyword.toLowerCase()));
  if (matched) {
    return blocked('sensitive_target', `Blocked sensitive visual target: ${matched}`, matched, metadata);
  }

  const hasTargetMetadata = hasAnyTargetMetadata(plan);
  if (strict && !hasTargetMetadata) {
    return blocked(
      'unknown_target',
      'Blocked visual action without targetLabel/reason metadata. Add targetLabel and reason, or explicitly use --allow-unknown-target for debugging only.',
      '',
      metadata
    );
  }

  return allowed(hasTargetMetadata ? 'labeled_target' : 'unknown_target', action, metadata);
}

export function buildGameModeAgentPrompt(goal, plan, frame = {}) {
  const action = String(plan.action || plan.type || '').toLowerCase();
  const targetLabel = String(plan.targetLabel || plan.target_label || plan.label || 'unknown target');
  const reason = String(plan.reason || plan.intent || 'OpenClaw visual guidance');
  const coordinateText = formatPlanCoordinates(plan);
  const foreground = frame?.currentScreen?.packageName ? `Expected foreground package: ${frame.currentScreen.packageName}.` : '';

  return [
    'OpenClaw game/vision mode visual guidance.',
    `User goal: ${goal || 'continue safely on the current game/canvas screen'}.`,
    foreground,
    '',
    'You are APKClaw, the phone-side executor. OpenClaw has inspected the screenshot and selected exactly one safe visual action.',
    `Action: ${action}.`,
    `Target label: ${targetLabel}.`,
    `Reason: ${reason}.`,
    coordinateText ? `Coordinates: ${coordinateText}.` : '',
    '',
    'Safety rules:',
    '- Do exactly one action, then observe again and finish.',
    '- Do not tap login, authorization, payment, purchase, recharge, account binding, delete, clear-cache, upload-log, log-out, or exit-game targets.',
    '- If the current foreground app no longer matches the expected target, stop and finish with a safety summary.',
    '- If the target is not visible or ambiguous, do not guess; finish with needs_vision.',
    '',
    'After the action, call get_screen_info once. If the screen exposes no nodes, still finish with what changed and say whether OpenClaw should capture another vision frame.',
  ].filter(Boolean).join('\n');
}

export function minimalActionForPhone(plan) {
  const body = { ...plan };
  body.action = normalizePhoneActionName(plan.action || plan.type || '');
  body.visualize = plan.visualize !== false;
  body.traceId = plan.traceId || `vision_${Date.now()}`;
  return body;
}

export function visionActionEndpointForBody(plan, fastPath = '') {
  if (String(fastPath || '').toLowerCase() === 'action_fast') {
    return '/api/lumi/agent/action_fast';
  }
  const action = normalizePhoneActionName(plan?.action || plan?.type || '');
  if (ACTION_FAST_ACTIONS.has(action)) {
    return '/api/lumi/agent/action_fast';
  }
  return '/api/lumi/vision/action';
}

export function compactReadSelectors(value, limit = 40) {
  const items = Array.isArray(value) ? value : [];
  const selectors = [];
  for (const item of items) {
    if (!item || typeof item !== 'object' || selectors.length >= limit) continue;
    const sourceBody = item.actionBody && typeof item.actionBody === 'object' ? item.actionBody : item;
    const actionBody = compactActionBody(sourceBody, item);
    if (!actionBody) continue;
    const ref = clipText(item.ref || item.selectorRef || item.selector_ref || actionBody.ref, 100);
    const selector = {
      nodeId: clipText(item.nodeId || item.node_id || item.id, 80),
      label: clipText(item.label || item.text || item.description || item.contentDescription || item.resourceId, 120),
      actionBody,
    };
    if (ref) selector.ref = ref;
    selectors.push(selector);
  }
  return selectors;
}

function compactActionBody(value, source = {}) {
  const item = value && typeof value === 'object' ? value : {};
  const parent = source && typeof source === 'object' ? source : {};
  let action = normalizePhoneActionName(item.action || item.type || item.name || parent.action || parent.type || parent.name || '');
  if (!action) return null;
  const ref = clipText(item.ref || item.selectorRef || item.selector_ref || parent.ref || parent.selectorRef || parent.selector_ref, 100);
  if (ref && REF_PREFERRED_ACTIONS.has(action)) action = 'click_ref';
  const body = { action };
  if (ref) body.ref = ref;
  const text = clipText(item.text || item.targetText || item.target_text || item.label || parent.text || parent.targetText || parent.target_text || parent.label, 160);
  if (text) body.text = text;
  const contentDescription = clipText(
    item.contentDescription
      || item.content_description
      || item.description
      || item.targetDescription
      || item.target_description
      || parent.contentDescription
      || parent.content_description
      || parent.description
      || parent.targetDescription
      || parent.target_description,
    160
  );
  if (contentDescription) body.contentDescription = contentDescription;
  const targetLabel = clipText(
    item.targetLabel
      || item.target_label
      || parent.targetLabel
      || parent.target_label
      || item.label
      || parent.label
      || text
      || contentDescription,
    160
  );
  if (targetLabel) body.targetLabel = targetLabel;
  const resourceId = clipText(item.resourceId || item.resource_id || item.viewId || item.view_id || parent.resourceId || parent.resource_id || parent.viewId || parent.view_id, 200);
  if (resourceId) body.resourceId = resourceId;
  const nodeId = clipText(item.nodeId || item.node_id || item.id || parent.nodeId || parent.node_id || parent.id, 100);
  if (nodeId) body.nodeId = nodeId;
  const direction = clipText(item.direction || parent.direction, 24);
  if (direction) body.direction = direction;
  if (Number.isFinite(Number(item.timeoutMs ?? parent.timeoutMs))) body.timeoutMs = Number(item.timeoutMs ?? parent.timeoutMs);
  if (Number.isFinite(Number(item.durationMs ?? parent.durationMs))) body.durationMs = Number(item.durationMs ?? parent.durationMs);
  return body;
}

function clipText(value, limit) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, limit);
}

function normalizePhoneActionName(value) {
  const action = String(value || '')
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase();
  if (action === 'longpress') return 'long_press';
  const aliases = {
    click_selector: 'click_ref',
    selector_click: 'click_ref',
    ref_click: 'click_ref',
    tap_ref: 'click_ref',
    wait_element: 'wait_element',
    wait_for_element: 'wait_element',
    wait_until_element: 'wait_element',
    wait_text: 'wait_element',
    wait_for_text: 'wait_element',
  };
  return aliases[action] || action;
}

function formatPlanCoordinates(plan) {
  const bits = [];
  if (plan.gridCell || plan.grid_cell) bits.push(`gridCell=${plan.gridCell || plan.grid_cell}`);
  if (Number.isFinite(Number(plan.x)) && Number.isFinite(Number(plan.y))) bits.push(`x=${Number(plan.x)}, y=${Number(plan.y)}`);
  if (Number.isFinite(Number(plan.nx)) && Number.isFinite(Number(plan.ny))) bits.push(`nx=${Number(plan.nx)}, ny=${Number(plan.ny)}`);
  if (plan.start || plan.from) bits.push(`start=${JSON.stringify(plan.start || plan.from)}`);
  if (plan.end || plan.to) bits.push(`end=${JSON.stringify(plan.end || plan.to)}`);
  return bits.join('; ');
}

function hasAnyTargetMetadata(plan) {
  if (!plan || typeof plan !== 'object') return false;
  for (const key of METADATA_KEYS) {
    if (typeof plan[key] === 'string' && plan[key].trim()) return true;
  }
  return false;
}

function collectMetadata(value) {
  const parts = [];
  const visit = (item, key = '') => {
    if (item == null) return;
    if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean') {
      if (!key || METADATA_KEYS.has(key)) parts.push(String(item));
      return;
    }
    if (Array.isArray(item)) {
      for (const child of item) visit(child, key);
      return;
    }
    if (typeof item === 'object') {
      for (const [childKey, childValue] of Object.entries(item)) {
        if (METADATA_KEYS.has(childKey)) visit(childValue, childKey);
      }
    }
  };
  visit(value);
  return parts.join(' ');
}

function allowed(category, action, metadata = '') {
  return {
    allowed: true,
    category,
    action,
    metadata,
    policy: visionSafetyPolicy(),
  };
}

function blocked(category, reason, matched = '', metadata = '') {
  return {
    allowed: false,
    category,
    reason,
    matched,
    metadata,
    policy: visionSafetyPolicy(),
  };
}
