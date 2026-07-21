// === Process ===
export interface ProcessStatus {
  running: boolean;
  pid: number | null;
}

// === License ===
export interface License {
  licensee: string;
  edition: string;
  expires: string | null;
  expiresAt?: string | null;
  features: string[];
  installId: string;
  deviceId?: string;
  deviceLimit?: number;
  signature: string;
  status?: string;
  code?: string;
  memberId?: string;
  plan?: string;
  memberMode?: boolean;
  issuedAt?: string | null;
  leaseExpiresAt?: string | null;
  gatewayBaseUrl?: string;
  gatewayImageBaseUrl?: string;
  gatewayVideoBaseUrl?: string;
  gatewayAccessToken?: string;
  gatewayToken?: string;
  gatewayImageAccessToken?: string;
  gatewayVideoAccessToken?: string;
  gatewayImageToken?: string;
  gatewayVideoToken?: string;
  gatewayDefaultModel?: string;
  gatewayImageModel?: string;
  gatewayVideoDraftModel?: string;
  gatewayVideoModel?: string;
  activationCodeLabel?: string;
  activationCodeLast8?: string;
  codeLabel?: string;
  gatewayModels?: string[];
  quotas?: {
    llm?: number;
    image?: number;
    video?: number;
    month?: number;
  };
  usage?: {
    llm?: number;
    image?: number;
    video?: number;
  };
}

export interface LicenseState {
  license: License | null;
  authorized: boolean;
}

// === Image ===
export interface ImageConfig {
  baseUrl: string;
  apiKey: string;
  gatewayMode?: 'member' | 'manual';
}

// === Video ===
export interface VideoConfig {
  providerId: VideoProviderId;
  apiBase: string;
  model: string;
  dashKey: string;
  gatewayMode?: 'member' | 'manual';
}

export type VideoProviderId = 'dashscope' | 'agnes' | 'seedance' | 'custom';

export type VideoMode = 't2v' | 'i2v';

export interface VideoGenerationParams {
  prompt: string;
  mode: VideoMode;
  providerId?: VideoProviderId;
  apiBase?: string;
  model?: string;
  resolution?: string;
  duration?: number;
  ratio?: string;
  image_path?: string;
}

// === Provider ===
export interface Provider {
  name: string;
  url: string;
  models: string[];
}

// === Update ===
export interface UpdateInfo {
  current: string;
  latest: string;
  hasUpdate: boolean;
}

// === API Response ===
export interface ApiResponse<T = unknown> {
  data?: T;
  error?: string;
  [key: string]: unknown;
}
