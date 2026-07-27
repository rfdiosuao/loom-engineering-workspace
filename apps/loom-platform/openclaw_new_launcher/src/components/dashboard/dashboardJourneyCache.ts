const JOURNEY_CACHE_KEY = 'loom.dashboard.last-verified-journey.v1';
const JOURNEY_CACHE_SCHEMA = 'loom.dashboard.last-verified-journey.v1';

export interface LastVerifiedJourney {
  verifiedAt: string;
  textModel: string;
  readyAgentIds: string[];
}

interface JourneyCacheEnvelope {
  schema: typeof JOURNEY_CACHE_SCHEMA;
  value: LastVerifiedJourney;
}

function storage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isLastVerifiedJourney(value: unknown): value is LastVerifiedJourney {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<LastVerifiedJourney>;
  return typeof candidate.verifiedAt === 'string'
    && Number.isFinite(Date.parse(candidate.verifiedAt))
    && typeof candidate.textModel === 'string'
    && candidate.textModel.trim().length > 0
    && Array.isArray(candidate.readyAgentIds)
    && candidate.readyAgentIds.every((id) => typeof id === 'string' && id.length > 0);
}

export function loadLastVerifiedJourney(): LastVerifiedJourney | null {
  const target = storage();
  if (!target) return null;
  try {
    const raw = target.getItem(JOURNEY_CACHE_KEY);
    if (!raw) return null;
    const envelope = JSON.parse(raw) as Partial<JourneyCacheEnvelope>;
    if (envelope.schema !== JOURNEY_CACHE_SCHEMA || !isLastVerifiedJourney(envelope.value)) {
      target.removeItem(JOURNEY_CACHE_KEY);
      return null;
    }
    return envelope.value;
  } catch {
    target.removeItem(JOURNEY_CACHE_KEY);
    return null;
  }
}

export function saveLastVerifiedJourney(value: LastVerifiedJourney): LastVerifiedJourney {
  if (!isLastVerifiedJourney(value)) return value;
  try {
    storage()?.setItem(JOURNEY_CACHE_KEY, JSON.stringify({
      schema: JOURNEY_CACHE_SCHEMA,
      value,
    } satisfies JourneyCacheEnvelope));
  } catch {
    // A successful live response still remains available in React state.
  }
  return value;
}
