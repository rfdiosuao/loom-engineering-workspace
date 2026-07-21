import { create } from 'zustand';
import { type License } from '../types';
import { type ThemeConfig, type NavItem } from '../types/theme';
import {
  DEFAULT_NAV_ITEMS,
  type BuiltinThemeMode,
  getBuiltinTheme,
  getStoredThemeMode,
} from '../theme/default';
import {
  type AppLanguage,
  getStoredAppLanguage,
  persistAppLanguage,
} from '../i18n/language';
import { licenseApi } from '../services/api';
import {
  CHECKING_LICENSE_GATE,
  type LicenseGateSnapshot,
  normalizeLicenseGate,
  withLicenseCheckTimeout,
} from '../components/license/licenseGate';
import { getDevLicenseFixture } from '../components/license/licenseVisualFixture';

export interface FeatureNavigationContext {
  campaignId?: string;
  deviceId?: string;
  runId?: string;
  source?: 'agent' | 'matrix' | 'external';
}

interface AppState {
  currentPage: string;
  navigationContexts: Record<string, FeatureNavigationContext>;
  serviceRunning: boolean;
  serviceStatus: 'idle' | 'starting' | 'running' | 'stopping' | 'stopped';
  phoneAgentStatus: 'idle' | 'queued' | 'running' | 'success' | 'error' | 'cancelled' | 'offline';
  phoneAgentTaskId: string | null;
  phoneAgentSummary: string;
  phoneAgentProgress: string;
  phoneAgentUpdatedAt: string | null;
  isAuthorized: boolean;
  isLicenseChecking: boolean;
  licenseInfo: License | null;
  licenseGate: LicenseGateSnapshot;
  apiConfigured: boolean;
  themeConfig: ThemeConfig | null;
  themeMode: BuiltinThemeMode;
  language: AppLanguage;
  navItems: NavItem[];

  setCurrentPage: (page: string) => void;
  openFeature: (key: string, context?: FeatureNavigationContext) => void;
  consumeNavigationContext: (key: string) => FeatureNavigationContext | null;
  setServiceRunning: (running: boolean) => void;
  setServiceStatus: (status: AppState['serviceStatus']) => void;
  setPhoneAgentSnapshot: (snapshot: Partial<Pick<AppState, 'phoneAgentStatus' | 'phoneAgentTaskId' | 'phoneAgentSummary' | 'phoneAgentProgress' | 'phoneAgentUpdatedAt'>>) => void;
  setApiConfigured: (configured: boolean) => void;
  setLicenseChecking: (checking: boolean) => void;
  setThemeConfig: (config: ThemeConfig | null) => void;
  setThemeMode: (mode: BuiltinThemeMode) => void;
  setLanguage: (language: AppLanguage) => void;
  setNavItems: (items: NavItem[]) => void;
  checkLicense: () => Promise<void>;
}

const initialThemeMode = getStoredThemeMode();
const initialLanguage = getStoredAppLanguage();
let licenseCheckGeneration = 0;

export const useAppStore = create<AppState>((set) => ({
  currentPage: 'dashboard',
  navigationContexts: {},
  serviceRunning: false,
  serviceStatus: 'idle',
  phoneAgentStatus: 'idle',
  phoneAgentTaskId: null,
  phoneAgentSummary: '',
  phoneAgentProgress: '',
  phoneAgentUpdatedAt: null,
  isAuthorized: false,
  isLicenseChecking: true,
  licenseInfo: null,
  licenseGate: CHECKING_LICENSE_GATE,
  apiConfigured: false,
  themeConfig: getBuiltinTheme(initialThemeMode),
  themeMode: initialThemeMode,
  language: initialLanguage,
  navItems: DEFAULT_NAV_ITEMS,

  setCurrentPage: (currentPage) => set({ currentPage }),
  openFeature: (key, context) => set((state) => {
    const navigationContexts = { ...state.navigationContexts };
    if (context) navigationContexts[key] = context;
    else delete navigationContexts[key];
    return { currentPage: key, navigationContexts };
  }),
  consumeNavigationContext: (key) => {
    let consumed: FeatureNavigationContext | null = null;
    set((state) => {
      consumed = state.navigationContexts[key] ?? null;
      if (!consumed) return state;
      const navigationContexts = { ...state.navigationContexts };
      delete navigationContexts[key];
      return { navigationContexts };
    });
    return consumed;
  },
  setServiceRunning: (serviceRunning) => set({ serviceRunning }),
  setServiceStatus: (serviceStatus) => set({ serviceStatus }),
  setPhoneAgentSnapshot: (snapshot) => set((state) => ({ ...state, ...snapshot })),
  setApiConfigured: (apiConfigured) => set({ apiConfigured }),
  setThemeConfig: (themeConfig) => set({ themeConfig }),
  setThemeMode: (themeMode) => set({ themeMode }),
  setLanguage: (language: AppLanguage) => {
    persistAppLanguage(language);
    set({ language });
  },
  setNavItems: (navItems) => set({ navItems }),
  setLicenseChecking: (val: boolean) => set({ isLicenseChecking: val }),
  checkLicense: async () => {
    const checkGeneration = ++licenseCheckGeneration;
    const fixture = getDevLicenseFixture();
    if (fixture) {
      set({
        isAuthorized: fixture.authorized,
        licenseInfo: fixture.license,
        licenseGate: fixture,
        isLicenseChecking: false,
      });
      return;
    }
    set({ isLicenseChecking: true, licenseGate: CHECKING_LICENSE_GATE });
    try {
      const [response, config] = await withLicenseCheckTimeout(Promise.allSettled([
        licenseApi.current(),
        licenseApi.clientConfig(),
      ]));
      const current = response.status === 'fulfilled' ? response.value : null;
      const clientConfig = config.status === 'fulfilled' ? config.value : null;
      const licenseGate = normalizeLicenseGate({
        response: current,
        config: clientConfig,
        error: response.status === 'rejected' ? response.reason : undefined,
        configUnavailable: config.status === 'rejected',
      });
      if (checkGeneration !== licenseCheckGeneration) return;
      set({
        isAuthorized: licenseGate.authorized,
        licenseInfo: licenseGate.license,
        licenseGate,
        isLicenseChecking: false,
      });
      if (!licenseGate.authorized) {
        try { localStorage.removeItem('openclaw_auth'); } catch { /* ignore */ }
      }
    } catch (error) {
      if (checkGeneration !== licenseCheckGeneration) return;
      const licenseGate = normalizeLicenseGate({ error });
      set({ isAuthorized: false, licenseInfo: null, licenseGate, isLicenseChecking: false });
      try { localStorage.removeItem('openclaw_auth'); } catch { /* ignore */ }
    }
  },
}));
