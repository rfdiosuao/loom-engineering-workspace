import type { RouteKey } from '../types';

// Friendly, beginner-facing translation of a raw error.
//   title      – short human title ("电脑和手机的安全配对失效")
//   hint       – the single next step the user should take
//   diagnostic – the original machine text, kept for “复制诊断”
//   logRoute   – where “打开日志” should jump to
export interface FriendlyError {
  title: string;
  hint: string;
  diagnostic: string;
  logRoute?: RouteKey;
}

// Normalise any thrown value / API payload into a plain string we can match on.
export function errorText(err: unknown): string {
  if (err == null) return '';
  if (typeof err === 'string') return err;
  if (err instanceof Error) return err.message || String(err);
  if (typeof err === 'object') {
    const anyErr = err as Record<string, unknown>;
    for (const key of ['detail', 'message', 'error', 'msg', 'reason']) {
      const value = anyErr[key];
      if (typeof value === 'string' && value.trim()) return value;
    }
    try {
      return JSON.stringify(err);
    } catch {
      return String(err);
    }
  }
  return String(err);
}

function has(text: string, ...needles: string[]): boolean {
  const lower = text.toLowerCase();
  return needles.some((needle) => lower.includes(needle.toLowerCase()));
}

// Connectivity problems look the same everywhere (service offline, DNS, refused…).
function unreachable(text: string): boolean {
  return has(
    text,
    'econnrefused',
    'enotfound',
    'etimedout',
    'network',
    'failed to fetch',
    'connection refused',
    'connect timeout',
    'getaddrinfo',
    'socket hang up',
    'ehostunreach',
    '拒绝',
    '无法连接',
    '连接被',
  );
}

// Phone bridge / Lumi pairing errors. The single most important translation is
// the Lumi signature failure, which means the desktop⇄phone pairing is stale.
export function translatePhoneError(err: unknown): FriendlyError {
  const diagnostic = errorText(err);
  if (has(diagnostic, 'invalid lumi signature', 'lumi signature', 'signature mismatch', '签名')) {
    return {
      title: '电脑和手机的安全配对失效',
      hint: '请在手机控制台点“重新配对”，重新生成安全通道后再试。',
      diagnostic,
      logRoute: 'phone',
    };
  }
  if (has(diagnostic, '401', '403', 'unauthorized', 'forbidden', 'token')) {
    return {
      title: '手机连接令牌无效',
      hint: '令牌可能已过期，请重新复制手机端的连接令牌，或点“一键修复连接”。',
      diagnostic,
      logRoute: 'phone',
    };
  }
  if (has(diagnostic, 'apk', 'version', '版本')) {
    return {
      title: '手机端 APP 版本不匹配',
      hint: '请把手机上的 APKClaw 更新到最新版本后重试。',
      diagnostic,
      logRoute: 'phone',
    };
  }
  if (unreachable(diagnostic)) {
    return {
      title: '连不上手机',
      hint: '请确认手机和电脑在同一个网络，APKClaw 已打开，再点“一键修复连接”。',
      diagnostic,
      logRoute: 'phone',
    };
  }
  return {
    title: '手机操作失败',
    hint: '可点“一键修复连接”自动排查，或复制诊断给维护人员。',
    diagnostic,
    logRoute: 'phone',
  };
}

// License / activation errors → which of the four common causes it is.
export function translateLicenseError(err: unknown): FriendlyError {
  const diagnostic = errorText(err);
  if (has(diagnostic, 'already', 'bound', 'another device', 'device', '已绑定', '其他设备', 'in use', '被使用')) {
    return {
      title: '授权码已绑定其他设备',
      hint: '这张授权码已在别的电脑激活。请换一张授权码，或联系发卡方解绑。',
      diagnostic,
      logRoute: 'license',
    };
  }
  if (has(diagnostic, 'expire', 'expired', '过期', 'invalid date', 'time', '时间', 'clock')) {
    return {
      title: '本机时间异常或授权已过期',
      hint: '请检查电脑日期时间是否正确（自动同步网络时间），再重新授权。',
      diagnostic,
      logRoute: 'license',
    };
  }
  if (unreachable(diagnostic) || has(diagnostic, '5xx', '500', '502', '503', '504', 'server error', 'bad gateway')) {
    return {
      title: '连不上授权服务器',
      hint: '请检查网络后重试；若持续失败，可能是服务器临时维护。',
      diagnostic,
      logRoute: 'license',
    };
  }
  if (has(diagnostic, 'invalid', 'not found', '不存在', '无效', '错误', '404', 'unknown code')) {
    return {
      title: '授权码无效',
      hint: '请确认授权码是否输入完整、是否已被使用，建议直接复制粘贴。',
      diagnostic,
      logRoute: 'license',
    };
  }
  return {
    title: '授权失败',
    hint: '请重试，或复制诊断信息联系发卡方。',
    diagnostic,
    logRoute: 'license',
  };
}

// Image / video generation failures → which interface-level cause it is.
export function translateMediaError(err: unknown, kind: 'image' | 'video' = 'image'): FriendlyError {
  const diagnostic = errorText(err);
  const noun = kind === 'video' ? '视频' : '图像';
  if (has(diagnostic, '401', '403', 'unauthorized', 'forbidden', 'api key', 'apikey', 'invalid key', '密钥', 'incorrect api')) {
    return {
      title: 'API Key 不正确',
      hint: `请到统一设置里检查${noun}接口的 API Key 是否填对。`,
      diagnostic,
      logRoute: 'settings',
    };
  }
  if (has(diagnostic, 'model', '模型', 'not found model', 'no such model', 'does not exist', '不存在')) {
    return {
      title: '模型名不存在',
      hint: `请确认${noun}模型名称与服务商提供的一致（区分大小写）。`,
      diagnostic,
      logRoute: 'settings',
    };
  }
  if (has(diagnostic, 'timeout', 'timed out', '超时', 'queue', '排队', 'pending too long')) {
    return {
      title: '排队超时',
      hint: '服务商当前较忙，请稍后重试；视频生成耗时较长属正常。',
      diagnostic,
      logRoute: 'studio',
    };
  }
  if (has(diagnostic, 'no video', 'empty', '无返回', 'no result', 'no url', 'missing')) {
    return {
      title: `没有返回${noun}`,
      hint: '接口已响应但没有产物，可能是内容被拦截或额度不足，请稍后重试。',
      diagnostic,
      logRoute: 'studio',
    };
  }
  if (unreachable(diagnostic)) {
    return {
      title: `${noun}接口不可达`,
      hint: `请到统一设置检查${noun}接口地址，或确认网络是否正常。`,
      diagnostic,
      logRoute: 'settings',
    };
  }
  return {
    title: `${noun}生成失败`,
    hint: '请稍后重试，或复制诊断信息排查接口配置。',
    diagnostic,
    logRoute: 'studio',
  };
}

// Generic fallback for actions that don't have a dedicated classifier.
export function translateError(err: unknown): FriendlyError {
  const diagnostic = errorText(err);
  if (unreachable(diagnostic)) {
    return {
      title: '网络连接失败',
      hint: '请检查网络或本机服务是否运行后重试。',
      diagnostic,
      logRoute: 'service',
    };
  }
  return {
    title: '操作失败',
    hint: '请重试，或展开详情复制诊断信息。',
    diagnostic,
  };
}
