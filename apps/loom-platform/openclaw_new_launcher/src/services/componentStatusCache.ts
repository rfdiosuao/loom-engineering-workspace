import type { ComponentSnapshot } from './api';

const COMPONENT_STATUS_CACHE_KEY = 'loom.components.snapshot.v1';
const COMPONENT_STATUS_CACHE_SCHEMA = 'loom.component-status-cache.v1';

interface ComponentStatusCacheEnvelope {
  schema: typeof COMPONENT_STATUS_CACHE_SCHEMA;
  snapshot: ComponentSnapshot;
}

let memorySnapshot: ComponentSnapshot | null = null;

function getStorage(): Storage | null {
  if (typeof window === 'undefined') return null;

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isComponentSnapshot(value: unknown): value is ComponentSnapshot {
  if (!value || typeof value !== 'object') return false;
  return Array.isArray((value as { components?: unknown }).components);
}

export function loadCachedComponentSnapshot(): ComponentSnapshot | null {
  if (memorySnapshot) return memorySnapshot;

  const storage = getStorage();
  if (!storage) return null;

  try {
    const raw = storage.getItem(COMPONENT_STATUS_CACHE_KEY);
    if (!raw) return null;

    const envelope = JSON.parse(raw) as Partial<ComponentStatusCacheEnvelope>;
    if (
      envelope.schema !== COMPONENT_STATUS_CACHE_SCHEMA ||
      !isComponentSnapshot(envelope.snapshot)
    ) {
      storage.removeItem(COMPONENT_STATUS_CACHE_KEY);
      return null;
    }

    memorySnapshot = envelope.snapshot;
    return memorySnapshot;
  } catch {
    storage.removeItem(COMPONENT_STATUS_CACHE_KEY);
    return null;
  }
}

export function saveCachedComponentSnapshot(snapshot: ComponentSnapshot): ComponentSnapshot {
  memorySnapshot = snapshot;

  const storage = getStorage();
  if (!storage) return snapshot;

  const envelope: ComponentStatusCacheEnvelope = {
    schema: COMPONENT_STATUS_CACHE_SCHEMA,
    snapshot,
  };

  try {
    storage.setItem(COMPONENT_STATUS_CACHE_KEY, JSON.stringify(envelope));
  } catch {
    // Memory caching still prevents repeated detection during this app session.
  }

  return snapshot;
}

export function clearCachedComponentSnapshot(): void {
  memorySnapshot = null;

  try {
    getStorage()?.removeItem(COMPONENT_STATUS_CACHE_KEY);
  } catch {
    // The in-memory cache has already been cleared.
  }
}
