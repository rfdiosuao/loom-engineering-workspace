import React from 'react';

import { matrixApi, parseErrorText } from '../../services/api';
import { openRealtimeStream } from '../../services/realtimeStream';
import type { MatrixEvent, MatrixStatusSnapshot } from '../../types/matrix';
import { deriveMatrixStreamPresentation, mergeMatrixEvents, mergeMatrixSnapshot } from './matrixViewModel';

interface MatrixStreamState {
  snapshot: MatrixStatusSnapshot | null;
  events: MatrixEvent[];
  loading: boolean;
  connected: boolean;
  reconnecting: boolean;
  error: string;
  refresh: () => Promise<void>;
}

export function useMatrixStream(enabled: boolean): MatrixStreamState {
  const [snapshot, setSnapshot] = React.useState<MatrixStatusSnapshot | null>(null);
  const [events, setEvents] = React.useState<MatrixEvent[]>([]);
  const [syncHealthy, setSyncHealthy] = React.useState(false);
  const [syncError, setSyncError] = React.useState('');
  const [transportConnected, setTransportConnected] = React.useState(false);
  const [transportReconnecting, setTransportReconnecting] = React.useState(false);
  const [transportError, setTransportError] = React.useState('');

  const loadSnapshot = React.useCallback(async (): Promise<number> => {
    if (!enabled) return 0;
    try {
      const [status, watch] = await Promise.all([matrixApi.status(), matrixApi.watch()]);
      setSnapshot((current) => mergeMatrixSnapshot(current, status));
      setEvents((current) => mergeMatrixEvents(current, watch.events || []));
      setSyncHealthy(true);
      setSyncError('');
      return Math.max(0, ...(watch.events || []).map((event) => event.seq || 0));
    } catch (reason) {
      setSyncHealthy(false);
      setSyncError(parseErrorText(reason) || '矩阵状态刷新失败');
      throw reason;
    }
  }, [enabled]);

  const refresh = React.useCallback(async () => {
    await loadSnapshot();
  }, [loadSnapshot]);

  React.useEffect(() => {
    if (!enabled) {
      setTransportConnected(false);
      setTransportReconnecting(false);
      setTransportError('');
      return undefined;
    }
    const controller = new AbortController();
    let disposed = false;
    let refreshTimer = 0;

    const scheduleRefresh = () => {
      if (disposed || refreshTimer) return;
      refreshTimer = window.setTimeout(() => {
        refreshTimer = 0;
        if (!disposed) void refresh().catch(() => undefined);
      }, 80);
    };

    const connect = async () => {
      setTransportConnected(false);
      setTransportReconnecting(true);
      setTransportError('');
      try {
        const afterSeq = await loadSnapshot();
        if (disposed) return;
        await openRealtimeStream({
          topic: 'matrix',
          afterSeq,
          signal: controller.signal,
          onEvent: (event) => {
            const data = event.data as Record<string, unknown>;
            const matrixEvent: MatrixEvent = {
              ...data,
              eventId: event.eventId,
              seq: event.seq,
              timestamp: event.timestamp,
              type: event.type,
            };
            setEvents((current) => mergeMatrixEvents(current, [matrixEvent]));
            scheduleRefresh();
          },
          onSequenceGap: async () => {
            setSyncHealthy(false);
            setSyncError('矩阵事件序号不连续，正在补收最新状态');
            return loadSnapshot();
          },
          onConnectionState: (state) => {
            if (disposed) return;
            const connected = state.status === 'connected';
            setTransportConnected(connected);
            setTransportReconnecting(!connected);
            setTransportError(connected ? '' : state.error || '');
          },
        });
        if (!disposed) {
          setTransportConnected(false);
          setTransportReconnecting(false);
        }
      } catch (reason) {
        if (disposed) return;
        setTransportConnected(false);
        setTransportReconnecting(true);
        setTransportError(parseErrorText(reason) || '矩阵实时流连接失败，正在重连');
      }
    };

    void connect();
    const fallbackTimer = window.setInterval(() => {
      if (!disposed) void refresh().catch(() => undefined);
    }, 8_000);

    return () => {
      disposed = true;
      controller.abort();
      window.clearInterval(fallbackTimer);
      if (refreshTimer) window.clearTimeout(refreshTimer);
    };
  }, [enabled, loadSnapshot, refresh]);

  const presentation = deriveMatrixStreamPresentation({
    enabled,
    hasSnapshot: snapshot !== null,
    syncHealthy,
    syncError,
    transportConnected,
    transportReconnecting,
    transportError,
  });
  return { snapshot, events, ...presentation, refresh };
}
