import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { ImageResult, RouteKey, ToastMessage, TransportMode, VideoResult } from '../types';

export interface PreviewSettings {
  transportMode: TransportMode;
  bridgeBaseUrl: string;
  bridgeToken: string;
  proxyTarget: string;
  openaiProxy: string;
  phoneBaseUrl: string;
  phoneToken: string;
}

type StudioTab = 'image' | 'video';

export interface StudioSessionState {
  tab: StudioTab;
  imagePrompt: string;
  imageSize: string;
  imageCount: number;
  imageEditPath: string;
  imageReferenceName: string;
  imageStartedAt: number;
  videoPrompt: string;
  videoMode: string;
  videoResolution: string;
  videoDuration: number;
  videoRatio: string;
  videoImagePath: string;
  videoReferenceName: string;
  videoProgress: string;
  videoStartedAt: number;
  // Image and video generate independently, so each tracks its own busy flag
  // (lets them run at the same time).
  imageBusy: boolean;
  videoBusy: boolean;
  activeVideoJob: any | null;
  selectedImage: ImageResult | null;
  selectedVideo: VideoResult | null;
  imageHistory: ImageResult[];
  videoHistory: VideoResult[];
}

interface AppState {
  route: RouteKey;
  sidebarCollapsed: boolean;
  selectedPhoneId: string | null;
  settings: PreviewSettings;
  studio: StudioSessionState;
  toasts: ToastMessage[];
  navigate: (route: RouteKey) => void;
  toggleSidebar: () => void;
  setSelectedPhoneId: (id: string | null) => void;
  updateSettings: (patch: Partial<PreviewSettings>) => void;
  updateStudio: (patch: Partial<StudioSessionState> | ((state: StudioSessionState) => Partial<StudioSessionState>)) => void;
  pushToast: (toast: Omit<ToastMessage, 'id'>) => void;
  dismissToast: (id: string) => void;
  clearToasts: () => void;
}

const DEFAULT_SETTINGS: PreviewSettings = {
  transportMode: 'live',
  bridgeBaseUrl: '',
  bridgeToken: '',
  proxyTarget: '',
  openaiProxy: '',
  phoneBaseUrl: '',
  phoneToken: '',
};

const DEFAULT_STUDIO_SESSION: StudioSessionState = {
  tab: 'image',
  imagePrompt: '一个安静、克制、有玻璃质感的 OpenClaw 启动器界面，冷光、清晰排版、舒适的背景',
  imageSize: '1024x1024',
  imageCount: 1,
  imageEditPath: '',
  imageReferenceName: '',
  imageStartedAt: 0,
  videoPrompt: 'OpenClaw 启动器的轻微镜头运动，玻璃面板缓慢浮现，动效克制',
  videoMode: 't2v',
  videoResolution: '720P',
  videoDuration: 5,
  videoRatio: '16:9',
  videoImagePath: '',
  videoReferenceName: '',
  videoProgress: '',
  videoStartedAt: 0,
  imageBusy: false,
  videoBusy: false,
  activeVideoJob: null,
  selectedImage: null,
  selectedVideo: null,
  imageHistory: [],
  videoHistory: [],
};

const TOAST_DEDUPE_WINDOW_MS = 3000;

function safeId() {
  return `toast_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function toastCreatedAt(id: string): number {
  const value = Number(id.split('_')[1]);
  return Number.isFinite(value) ? value : 0;
}

export const usePreviewStore = create<AppState>()(
  persist(
    (set) => ({
      route: 'dashboard',
      sidebarCollapsed: false,
      selectedPhoneId: null,
      settings: DEFAULT_SETTINGS,
      studio: DEFAULT_STUDIO_SESSION,
      toasts: [],
      navigate: (route) => set({ route }),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setSelectedPhoneId: (selectedPhoneId) => set({ selectedPhoneId }),
      updateSettings: (patch) => set((state) => ({ settings: { ...state.settings, ...patch } })),
      updateStudio: (patch) =>
        set((state) => ({
          studio: {
            ...state.studio,
            ...(typeof patch === 'function' ? patch(state.studio) : patch),
          },
        })),
      pushToast: (toast) =>
        set((state) => {
          const now = Date.now();
          const duplicate = state.toasts.some(
            (item) =>
              item.tone === toast.tone &&
              item.title === toast.title &&
              (item.detail || '') === (toast.detail || '') &&
              now - toastCreatedAt(item.id) < TOAST_DEDUPE_WINDOW_MS,
          );
          if (duplicate) return state;
          return { toasts: [...state.toasts, { id: safeId(), ...toast }].slice(-5) };
        }),
      dismissToast: (id) =>
        set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
      clearToasts: () => set({ toasts: [] }),
    }),
    {
      name: 'openclaw-redesign-live',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        route: state.route,
        sidebarCollapsed: state.sidebarCollapsed,
        selectedPhoneId: state.selectedPhoneId,
        settings: state.settings,
      }),
    }
  )
);
