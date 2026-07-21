const SAFE_TOOL_ID = /^[a-z0-9_.-]+$/;

const TOOL_LABELS = Object.freeze({
  open_app: '打开应用',
  get_screen_info: '读取当前页面',
  tap: '点击页面元素',
  click: '点击页面元素',
  input_text: '输入文本',
  type_text: '输入文本',
  swipe: '滚动查找内容',
  scroll_to_find: '滚动查找内容',
  system_key: '执行系统按键',
  press_key: '执行系统按键',
  screenshot: '截取当前页面',
  take_screenshot: '截取当前页面',
  finish: '整理执行结果',
  collect_list_items: '收集页面列表',
  wait_element: '等待页面元素',
});

export function progressLogFromEvents(events, limit = 3) {
  const items = [];
  for (const event of Array.isArray(events) ? events : []) {
    const item = progressItemFromEvent(event);
    if (!item) continue;
    const previous = items.at(-1);
    if (!previous || progressKey(previous) !== progressKey(item)) items.push(item);
  }
  return items.slice(-safeLimit(limit));
}

export function normalizeProgressLog(progressLog, events, limit = 3) {
  const existing = [];
  for (const item of Array.isArray(progressLog) ? progressLog : []) {
    const safe = sanitizeProgressItem(item);
    if (safe) existing.push(safe);
  }
  if (existing.length) return existing.slice(-safeLimit(limit));
  return progressLogFromEvents(events, limit);
}

export function withProgressLogsInSseEvent(event) {
  if (!event || typeof event !== 'object' || !event.data || typeof event.data !== 'object') return event;
  const tasks = Array.isArray(event.data.tasks) ? event.data.tasks : null;
  if (!tasks) return event;
  return {
    ...event,
    data: {
      ...event.data,
      tasks: tasks.map((task) => {
        if (!task || typeof task !== 'object') return task;
        const fallbackEvents = Array.isArray(task.events)
          ? task.events
          : task?.agentReport?.lastEvent
            ? [task.agentReport.lastEvent]
            : [];
        const progressLog = normalizeProgressLog(task.progressLog, fallbackEvents);
        return progressLog.length ? { ...task, progressLog } : task;
      }),
    },
  };
}

function progressItemFromEvent(event) {
  if (!event || typeof event !== 'object') return null;
  const eventType = String(event.type || '').trim().toLowerCase();
  const round = safeRound(event.round);
  const toolId = safeToolId(event.toolId);
  const time = safeTime(event.time);
  let type = '';
  let text = '';

  if (eventType === 'loop_start') {
    type = 'thinking';
    text = stageText(round, '分析下一步');
  } else if (eventType === 'tool_call') {
    type = 'tool';
    text = stageText(round, toolLabel(toolId));
  } else if (eventType === 'tool_result') {
    if (event.success !== false) return null;
    type = 'error';
    text = stageText(round, `${toolLabel(toolId)}失败`);
  } else if (eventType === 'complete' || eventType === 'success') {
    type = 'success';
    text = '任务执行完成';
  } else if (eventType === 'error' || eventType === 'failed') {
    type = 'error';
    text = '任务执行失败，请查看电脑端诊断';
  } else if (eventType === 'timeout') {
    type = 'error';
    text = '任务执行超时，请查看电脑端诊断';
  } else if (eventType === 'cancelled' || eventType === 'canceled') {
    type = 'status';
    text = '任务已取消';
  } else if (eventType === 'system_dialog_blocked') {
    type = 'error';
    text = '系统弹窗阻止了任务执行';
  } else if (eventType === 'submitted' || eventType === 'queued') {
    type = 'status';
    text = '任务已进入执行队列';
  } else if (eventType === 'running') {
    type = 'status';
    text = '任务正在执行';
  } else if (eventType === 'cancel_requested') {
    type = 'status';
    text = '正在取消任务';
  } else if (eventType === 'template_fallback') {
    type = 'status';
    text = '正在切换执行方案';
  } else {
    return null;
  }

  return progressItem({ round, type, toolId: eventType.startsWith('tool_') ? toolId : '', text, time });
}

function sanitizeProgressItem(item) {
  if (!item || typeof item !== 'object') return null;
  const round = safeRound(item.round);
  const type = String(item.type || '').trim().toLowerCase();
  const toolId = safeToolId(item.toolId);
  const time = safeTime(item.time);
  let text = '';
  if (type === 'thinking') text = stageText(round, '分析下一步');
  else if (type === 'tool') text = stageText(round, toolLabel(toolId));
  else if (type === 'success') text = '任务执行完成';
  else if (type === 'error') text = toolId ? stageText(round, `${toolLabel(toolId)}失败`) : '任务执行异常，请查看电脑端诊断';
  else if (type === 'status') text = safeStatusText(item.text);
  else return null;
  return progressItem({ round, type, toolId, text, time });
}

function progressItem({ round, type, toolId, text, time }) {
  return {
    round,
    type,
    ...(toolId ? { toolId } : {}),
    text,
    ...(time !== undefined ? { time } : {}),
  };
}

function stageText(round, action) {
  return round > 0 ? `第 ${round} 阶段：${action}` : action;
}

function toolLabel(toolId) {
  return TOOL_LABELS[toolId] || '执行手机操作';
}

function safeStatusText(text) {
  const value = String(text || '');
  const allowed = new Set(['任务已取消', '任务已进入执行队列', '任务正在执行', '正在取消任务', '正在切换执行方案']);
  return allowed.has(value) ? value : '任务状态已更新';
}

function safeToolId(value) {
  const normalized = String(value || '').trim().toLowerCase().slice(0, 80);
  return SAFE_TOOL_ID.test(normalized) ? normalized : '';
}

function safeRound(value) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
}

function safeTime(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function safeLimit(value) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? Math.max(1, Math.min(20, parsed)) : 3;
}

function progressKey(item) {
  return `${item.type}|${item.toolId || ''}|${item.text}`;
}
