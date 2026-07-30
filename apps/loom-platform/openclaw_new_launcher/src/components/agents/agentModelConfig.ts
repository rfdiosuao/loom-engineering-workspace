import type { AgentModelConfigStatus } from '../../services/loomContracts';

export function resolveRefreshedModelDraft(
  currentDraft: string,
  status: Partial<AgentModelConfigStatus>,
): string {
  const draft = currentDraft.trim();
  const availableModels = (status.availableModels || [])
    .map((item) => item.trim())
    .filter(Boolean);

  if (status.managedBy === 'custom_provider' || availableModels.length === 0) {
    return draft || status.model || '';
  }

  const availableDraft = availableModels.find(
    (item) => item.toLocaleLowerCase() === draft.toLocaleLowerCase(),
  );
  if (availableDraft) return availableDraft;

  const configuredModel = (status.model || '').trim();
  const availableConfiguredModel = availableModels.find(
    (item) => item.toLocaleLowerCase() === configuredModel.toLocaleLowerCase(),
  );
  return availableConfiguredModel || availableModels[0] || '';
}
