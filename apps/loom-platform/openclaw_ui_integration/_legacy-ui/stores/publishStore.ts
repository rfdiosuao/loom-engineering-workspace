import { create } from 'zustand';
import { DEFAULT_PUBLISH_DRAFT, type PublishDraft } from '../services/publish';

interface PublishHandoffState {
  draftSeed: PublishDraft | null;
  setDraftSeed: (draft: PublishDraft | null) => void;
  clearDraftSeed: () => void;
}

export const usePublishHandoffStore = create<PublishHandoffState>((set) => ({
  draftSeed: null,
  setDraftSeed: (draftSeed) => set({ draftSeed }),
  clearDraftSeed: () => set({ draftSeed: null }),
}));

export function getDefaultPublishDraftSeed(): PublishDraft {
  return {
    ...DEFAULT_PUBLISH_DRAFT,
    assets: [],
  };
}
