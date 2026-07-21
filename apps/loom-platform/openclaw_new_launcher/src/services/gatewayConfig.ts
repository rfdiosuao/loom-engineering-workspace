import { licenseApi } from './api';

export type GatewayMode = 'member' | 'manual';

export interface GatewayDefaults {
  baseUrl: string;
  imageBaseUrl: string;
  videoBaseUrl: string;
  apiKey: string;
  imageApiKey: string;
  videoApiKey: string;
  defaultModel: string;
  imageModel: string;
  videoDraftModel: string;
  hasGateway: boolean;
}

export interface GatewayStoredConfig {
  mode: GatewayMode | null;
  baseUrl: string;
  apiKey: string;
}

function normalizeText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === 'object' ? value as Record<string, any> : {};
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const text = normalizeText(value);
    if (text) return text;
  }
  return '';
}

export function normalizeGatewayMode(value: unknown): GatewayMode | null {
  if (value === 'member' || value === 'manual') return value;
  if (value === true) return 'member';
  if (value === false) return 'manual';
  const normalized = normalizeText(value).toLowerCase();
  if (!normalized) return null;
  if (['member', 'managed', 'auto', 'gateway', 'member-mode', 'member_mode'].includes(normalized)) return 'member';
  if (['manual', 'local', 'custom', 'local-mode', 'local_mode'].includes(normalized)) return 'manual';
  return null;
}

export function readGatewayStoredConfig(data: unknown): GatewayStoredConfig {
  const source = data && typeof data === 'object' ? (data as Record<string, unknown>) : {};
  return {
    mode: normalizeGatewayMode(source.gatewayMode ?? source.managedMode),
    baseUrl: normalizeText(source.baseUrl),
    apiKey: normalizeText(source.apiKey),
  };
}

export async function readMemberGatewayDefaults(): Promise<GatewayDefaults> {
  const resp = await licenseApi.current();
  const sources = [
    asRecord((resp as any).member),
    asRecord((resp as any).gatewayProfile),
    asRecord(resp.license),
  ];
  const gateways = sources.map((source) => asRecord(source.gateway));
  const baseUrl = firstText(
    ...sources.flatMap((source, index) => [
      source.gatewayBaseUrl,
      source.gatewayUrl,
      source.baseUrl,
      source.url,
      gateways[index].gatewayBaseUrl,
      gateways[index].baseUrl,
      gateways[index].url,
    ]),
  );
  const imageBaseUrl = firstText(
    ...sources.flatMap((source, index) => [
      source.gatewayImageBaseUrl,
      source.imageBaseUrl,
      source.imageUrl,
      source.gatewayBaseUrl,
      gateways[index].gatewayImageBaseUrl,
      gateways[index].imageBaseUrl,
      gateways[index].imageUrl,
      gateways[index].gatewayBaseUrl,
    ]),
    baseUrl,
  );
  const videoBaseUrl = firstText(
    ...sources.flatMap((source, index) => [
      source.gatewayVideoBaseUrl,
      source.videoBaseUrl,
      source.videoUrl,
      source.gatewayBaseUrl,
      gateways[index].gatewayVideoBaseUrl,
      gateways[index].videoBaseUrl,
      gateways[index].videoUrl,
      gateways[index].gatewayBaseUrl,
    ]),
    baseUrl,
  );
  const apiKey = firstText(
    ...sources.flatMap((source, index) => [
      source.gatewayAccessToken,
      source.gatewayToken,
      source.apiKey,
      source.memberToken,
      source.token,
      gateways[index].gatewayAccessToken,
      gateways[index].gatewayToken,
      gateways[index].accessToken,
      gateways[index].apiKey,
      gateways[index].token,
    ]),
  );
  const imageApiKey = firstText(
    ...sources.flatMap((source, index) => [
      source.gatewayImageAccessToken,
      source.gatewayImageToken,
      source.imageApiKey,
      source.imageToken,
      gateways[index].gatewayImageAccessToken,
      gateways[index].gatewayImageToken,
      gateways[index].imageAccessToken,
      gateways[index].imageToken,
      gateways[index].imageApiKey,
    ]),
    apiKey,
  );
  const videoApiKey = firstText(
    ...sources.flatMap((source, index) => [
      source.gatewayVideoAccessToken,
      source.gatewayVideoToken,
      source.videoApiKey,
      source.videoToken,
      gateways[index].gatewayVideoAccessToken,
      gateways[index].gatewayVideoToken,
      gateways[index].videoAccessToken,
      gateways[index].videoToken,
      gateways[index].videoApiKey,
    ]),
    apiKey,
  );
  const defaultModel = firstText(...sources.flatMap((source, index) => [
    source.gatewayDefaultModel,
    source.defaultModel,
    source.model,
    gateways[index].gatewayDefaultModel,
    gateways[index].defaultModel,
    gateways[index].model,
  ]));
  const imageModel = firstText(...sources.flatMap((source, index) => [
    source.gatewayImageModel,
    source.imageModel,
    gateways[index].gatewayImageModel,
    gateways[index].imageModel,
  ]));
  const videoDraftModel = firstText(...sources.flatMap((source, index) => [
    source.gatewayVideoDraftModel,
    source.videoDraftModel,
    source.gatewayVideoModel,
    source.videoModel,
    gateways[index].gatewayVideoDraftModel,
    gateways[index].videoDraftModel,
    gateways[index].gatewayVideoModel,
    gateways[index].videoModel,
  ]));

  return {
    baseUrl,
    imageBaseUrl,
    videoBaseUrl,
    apiKey,
    imageApiKey,
    videoApiKey,
    defaultModel,
    imageModel,
    videoDraftModel,
    hasGateway: Boolean(baseUrl && apiKey),
  };
}
