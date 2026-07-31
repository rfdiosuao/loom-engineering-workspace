export type {
  AccountEntitlementSnapshot,
  AccountSnapshot,
  AccountSubscriptionSnapshot,
  AgentModelConfigStatus,
  BridgeJob,
  ComponentSnapshot,
  ComponentSummary,
  DiagnosticCheck,
  DiagnosticReport,
  DiagnosticStatus,
  PhoneConfigSnapshot,
  PhoneDeviceSummary,
  PhoneTaskMode,
  PhoneTaskProfile,
  ProviderCompatibilityProbe,
  WireSnapshot,
} from './api';

export * from '../types/agent';
export * from '../types/matrix';
export * from '../types/realtime';

export interface LoomBackendError {
  ok?: false;
  code?: string;
  message: string;
  detail?: unknown;
  action?: string;
}
