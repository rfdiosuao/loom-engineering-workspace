import { configApi, licenseApi } from './api';

const AUTH_PROFILES_PATH = 'data/.openclaw/agents/main/agent/auth-profiles.json';

/** True if any model provider has both an apiKey and a baseUrl configured. */
export function hasConfiguredApiProfile(data: unknown): boolean {
  const providers = (data as any)?.models?.providers;
  if (!providers || typeof providers !== 'object') return false;
  return Object.values(providers).some((provider: any) => {
    const apiKey = String(provider?.apiKey || '').trim();
    const baseUrl = String(provider?.baseUrl || provider?.url || '').trim();
    return apiKey.length > 0 && baseUrl.length > 0;
  });
}

/**
 * Whether the app has a usable model config — either a local provider profile,
 * or a license-provided gateway. Single source of truth shared by the sidebar
 * (App) and the dashboard status card so boot doesn't probe this twice.
 */
export async function detectApiConfigured(): Promise<boolean> {
  try {
    const resp = await configApi.read(AUTH_PROFILES_PATH, { models: { providers: {} } });
    if (hasConfiguredApiProfile(resp.data)) return true;
    const licenseResp = await licenseApi.current();
    const license = ((licenseResp as any).gatewayProfile || licenseResp.license || (licenseResp as any).member) as any;
    const gateway = license?.gateway || {};
    return Boolean(
      String(license?.gatewayBaseUrl || license?.gatewayUrl || license?.baseUrl || gateway?.baseUrl || gateway?.url || '').trim()
      && String(license?.gatewayAccessToken || license?.gatewayToken || license?.apiKey || license?.memberToken || gateway?.apiKey || gateway?.token || '').trim(),
    );
  } catch {
    return false;
  }
}
