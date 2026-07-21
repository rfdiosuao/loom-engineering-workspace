import React from 'react';

// Module-level snapshot cache shared across mounts. Lazy pages unmount on
// navigation, so without this every revisit re-hits the bridge and shows a
// "读取中…" spinner. With a cacheKey, useAsync becomes stale-while-revalidate:
// a revisit renders the last data instantly and refreshes in the background.
const snapshotCache = new Map<string, { data: unknown; at: number }>();

export interface UseAsyncOptions {
  /** Enables cross-mount caching. Use a stable per-view key, e.g. "license". */
  cacheKey?: string;
  /** Within this window a revisit skips the fetch entirely. Default 8s. */
  ttlMs?: number;
}

export function useAsync<T>(loader: () => Promise<T>, deps: React.DependencyList, options: UseAsyncOptions = {}) {
  const { cacheKey, ttlMs = 8000 } = options;
  const cached = cacheKey ? (snapshotCache.get(cacheKey) as { data: T; at: number } | undefined) : undefined;
  const cachedFresh = cached ? Date.now() - cached.at < ttlMs : false;

  const [data, setData] = React.useState<T | null>(cached ? cached.data : null);
  // No spinner when we already have something to show.
  const [loading, setLoading] = React.useState(!cached);
  const [error, setError] = React.useState<string | null>(null);
  const [tick, setTick] = React.useState(0);

  const refresh = React.useCallback(() => setTick((value) => value + 1), []);

  React.useEffect(() => {
    // Fresh cache + not a manual refresh -> serve cache, skip the network.
    if (cacheKey && cachedFresh && tick === 0) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    // Only block the UI with a spinner when there's nothing cached to show.
    if (!cached) setLoading(true);
    setError(null);
    loader()
      .then((value) => {
        if (cancelled) return;
        setData(value);
        if (cacheKey) snapshotCache.set(cacheKey, { data: value, at: Date.now() });
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, loading, error, refresh };
}
