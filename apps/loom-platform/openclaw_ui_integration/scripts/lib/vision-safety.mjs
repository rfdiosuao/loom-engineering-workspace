const MUTATING_ACTIONS = new Set(['tap', 'long_press', 'longpress', 'swipe', 'drag']);

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
  const action = String(plan?.action || plan?.type || '').toLowerCase();
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
  body.action = String(plan.action || plan.type || '').toLowerCase();
  if (body.action === 'longpress') body.action = 'long_press';
  body.visualize = plan.visualize !== false;
  body.traceId = plan.traceId || `vision_${Date.now()}`;
  return body;
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
  return ['targetLabel', 'target_label', 'label', 'reason', 'intent', 'description', 'targetDescription', 'target_description']
    .some((key) => typeof plan?.[key] === 'string' && plan[key].trim());
}

function collectMetadata(value) {
  const parts = [];
  const seen = new WeakSet();
  const stack = [{ item: value, key: '' }];
  let visited = 0;

  while (stack.length && visited < 1000) {
    const { item, key } = stack.pop();
    visited += 1;
    if (item == null) continue;
    if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean') {
      if (!key || METADATA_KEYS.has(key)) parts.push(String(item));
      continue;
    }
    if (Array.isArray(item)) {
      if (seen.has(item)) continue;
      seen.add(item);
      for (let i = item.length - 1; i >= 0; i -= 1) stack.push({ item: item[i], key });
      continue;
    }
    if (typeof item === 'object') {
      if (seen.has(item)) continue;
      seen.add(item);
      const entries = Object.entries(item);
      for (let i = entries.length - 1; i >= 0; i -= 1) {
        const [childKey, childValue] = entries[i];
        if (METADATA_KEYS.has(childKey)) stack.push({ item: childValue, key: childKey });
      }
    }
  }
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
