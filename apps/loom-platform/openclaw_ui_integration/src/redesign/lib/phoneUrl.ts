const DEFAULT_PHONE_PORT = '9527';

export function cleanPhoneBaseUrlInput(value: unknown): string {
  return (typeof value === 'string' ? value.trim() : '')
    .replace(/[：﹕꞉]/g, ':')
    .replace(/[／⁄]/g, '/')
    .replace(/[。．｡]/g, '.')
    .replace(/\s+/g, '')
    .replace(/^http:\/(?!\/)/i, 'http://')
    .replace(/^https:\/(?!\/)/i, 'https://');
}

export function normalizePhoneBaseUrl(value: unknown): string {
  let text = cleanPhoneBaseUrlInput(value);
  if (!text) return '';

  if (text.startsWith('//')) text = `http:${text}`;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) text = `http://${text}`;

  try {
    const url = new URL(text);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      return '';
    }
    if (!url.hostname || isMalformedIpv4Like(url.hostname)) return '';
    url.username = '';
    url.password = '';
    if (!url.port && isLikelyLanHost(url.hostname)) {
      url.port = DEFAULT_PHONE_PORT;
    }
    url.pathname = '';
    url.search = '';
    url.hash = '';
    return url.toString().replace(/\/+$/, '');
  } catch {
    return '';
  }
}

export function displayPhoneBaseUrl(value: unknown): string {
  const normalized = normalizePhoneBaseUrl(value);
  const source = normalized || cleanPhoneBaseUrlInput(value);
  return source
    .replace(/^[a-z][a-z0-9+.-]*:\/\//i, '')
    .replace(/\/.*$/, '');
}

export function normalizeOrCleanPhoneBaseUrl(value: unknown): string {
  return normalizePhoneBaseUrl(value) || cleanPhoneBaseUrlInput(value).replace(/\/+$/, '');
}

function isLikelyLanHost(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (host === 'localhost' || host === '::1') return true;
  if (/^192\.168\.\d{1,3}\.\d{1,3}$/.test(host)) return true;
  if (/^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host)) return true;
  if (/^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/.test(host)) return true;
  return /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host);
}

function isMalformedIpv4Like(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (!/^[a-z0-9.-]+$/i.test(host)) return false;
  const parts = host.split('.');
  const hasOnlyDigitsAndDots = /^[\d.]+$/.test(host);
  if (hasOnlyDigitsAndDots) {
    return parts.length !== 4 || parts.some((part) => part === '' || Number(part) > 255);
  }
  if (parts.length !== 4) return false;
  const numericLikeParts = parts.filter((part) => /\d/.test(part));
  return numericLikeParts.length >= 3;
}
