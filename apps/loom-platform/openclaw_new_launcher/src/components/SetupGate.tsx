import React from 'react';

import { APP_DISPLAY_NAME } from '../version';

// First-run download overlay. Listens for the `dist://*` events the Rust
// bootstrap emits while it downloads + verifies the runtime layers. Renders
// nothing unless a download is actually happening (fresh online install), so
// it is invisible for the full/offline package.

type LayerInfo = { id: string; title: string; size: number };
type Progress = {
  id: string;
  title: string;
  phase: 'download' | 'verify' | 'install';
  downloaded: number;
  total: number;
  index: number;
  count: number;
};

export type DistributionSetupSnapshot = {
  revision: number;
  runId: number;
  status: 'idle' | 'running' | 'done' | 'error';
  layers: LayerInfo[];
  progress: Progress | null;
  error: string | null;
};

export type SetupGateViewState = DistributionSetupSnapshot & {
  active: boolean;
  done: boolean;
  retrying: boolean;
};

type DistributionEventName = 'dist://start' | 'dist://progress' | 'dist://done' | 'dist://error';
type Unlisten = () => void;
type DistributionEvent = { payload: DistributionSetupSnapshot };

export type SetupGateLifecycleDependencies = {
  listen: (
    event: DistributionEventName,
    handler: (event: DistributionEvent) => void,
  ) => Promise<Unlisten>;
  invoke: <T>(command: string) => Promise<T>;
  setTimer: (callback: () => void, delayMs: number) => unknown;
  clearTimer: (handle: unknown) => void;
  onChange: (state: SetupGateViewState) => void;
};

export type SetupGateLifecycle = {
  connect: () => Promise<void>;
  retry: () => Promise<void>;
  dispose: () => void;
  getState: () => SetupGateViewState;
};

const DISTRIBUTION_EVENTS: DistributionEventName[] = [
  'dist://start',
  'dist://progress',
  'dist://done',
  'dist://error',
];

function initialViewState(): SetupGateViewState {
  return {
    revision: -1,
    runId: 0,
    status: 'idle',
    layers: [],
    progress: null,
    error: null,
    active: false,
    done: false,
    retrying: false,
  };
}

function cloneViewState(state: SetupGateViewState): SetupGateViewState {
  return {
    ...state,
    layers: [...state.layers],
    progress: state.progress ? { ...state.progress } : null,
  };
}

export function createSetupGateLifecycle(
  dependencies: SetupGateLifecycleDependencies,
): SetupGateLifecycle {
  let state = initialViewState();
  let disposed = false;
  let connectPromise: Promise<void> | null = null;
  let retryPromise: Promise<void> | null = null;
  let doneTimer: unknown = null;
  const unlisteners = new Set<Unlisten>();

  const publish = (next: SetupGateViewState) => {
    if (disposed) return;
    state = next;
    dependencies.onChange(cloneViewState(state));
  };

  const safeUnlisten = (unlisten: Unlisten) => {
    try {
      unlisten();
    } catch {
      // Cleanup is best-effort; one bad listener must not leak the others.
    }
  };

  const cleanupListeners = () => {
    for (const unlisten of [...unlisteners]) {
      unlisteners.delete(unlisten);
      safeUnlisten(unlisten);
    }
  };

  const clearDoneTimer = () => {
    if (doneTimer === null) return;
    const timer = doneTimer;
    doneTimer = null;
    dependencies.clearTimer(timer);
  };

  const scheduleDoneTimer = (revision: number, runId: number) => {
    let timer: unknown = null;
    timer = dependencies.setTimer(() => {
      if (
        disposed
        || doneTimer !== timer
        || state.revision !== revision
        || state.runId !== runId
        || state.status !== 'done'
      ) {
        return;
      }
      doneTimer = null;
      publish({ ...state, active: false });
    }, 900);
    doneTimer = timer;
  };

  const applySnapshot = (snapshot: DistributionSetupSnapshot) => {
    if (disposed || snapshot.revision <= state.revision) return;
    clearDoneTimer();
    const next: SetupGateViewState = {
      revision: snapshot.revision,
      runId: snapshot.runId,
      status: snapshot.status,
      layers: [...snapshot.layers],
      progress: snapshot.progress ? { ...snapshot.progress } : null,
      error: snapshot.error,
      active: snapshot.status !== 'idle',
      done: snapshot.status === 'done',
      retrying: state.retrying,
    };
    publish(next);
    if (snapshot.status === 'done') {
      scheduleDoneTimer(snapshot.revision, snapshot.runId);
    }
  };

  const connect = (): Promise<void> => {
    if (connectPromise) return connectPromise;
    if (disposed) return Promise.resolve();

    connectPromise = (async () => {
      let registrationFailed = false;
      const failRegistration = () => {
        if (registrationFailed) return;
        registrationFailed = true;
        cleanupListeners();
      };
      const registrations = DISTRIBUTION_EVENTS.map((event) => {
        try {
          return Promise.resolve(
            dependencies.listen(event, (message) => applySnapshot(message.payload)),
          ).then((unlisten) => {
            if (disposed || registrationFailed) {
              safeUnlisten(unlisten);
              return null;
            }
            unlisteners.add(unlisten);
            return unlisten;
          }, (error) => {
            failRegistration();
            throw error;
          });
        } catch (error) {
          failRegistration();
          return Promise.reject(error);
        }
      });

      const settled = await Promise.allSettled(registrations);
      if (disposed) {
        cleanupListeners();
        return;
      }
      if (registrationFailed || settled.some((result) => result.status === 'rejected')) {
        cleanupListeners();
        return;
      }

      try {
        const snapshot = await dependencies.invoke<DistributionSetupSnapshot>(
          'get_distribution_setup_snapshot',
        );
        if (!disposed) applySnapshot(snapshot);
      } catch {
        // Live listeners remain authoritative if the one-time reconcile fails.
      }
    })();

    return connectPromise;
  };

  const retry = (): Promise<void> => {
    if (retryPromise) return retryPromise;
    if (disposed) return Promise.resolve();

    clearDoneTimer();
    publish({
      ...state,
      status: 'running',
      active: true,
      done: false,
      progress: null,
      error: null,
      retrying: true,
    });

    let invocation: Promise<unknown>;
    try {
      invocation = dependencies.invoke<unknown>('retry_distribution_setup');
    } catch (error) {
      invocation = Promise.reject(error);
    }

    const operation = Promise.resolve(invocation)
      .then(async () => {
        if (disposed) return;
        try {
          const snapshot = await dependencies.invoke<DistributionSetupSnapshot>(
            'get_distribution_setup_snapshot',
          );
          if (!disposed) applySnapshot(snapshot);
        } catch {
          // The persisted event snapshot is still reconciled by live listeners.
        }
      })
      .catch((cause) => {
        if (disposed) return;
        publish({
          ...state,
          status: 'error',
          active: true,
          done: false,
          error: cause instanceof Error
            ? cause.message
            : String(cause || '组件补全失败'),
        });
      })
      .finally(() => {
        retryPromise = null;
        if (!disposed && state.retrying) {
          publish({ ...state, retrying: false });
        }
      });
    retryPromise = operation;
    return operation;
  };

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    clearDoneTimer();
    cleanupListeners();
  };

  return {
    connect,
    retry,
    dispose,
    getState: () => cloneViewState(state),
  };
}

function fmtMB(n: number): string {
  return `${(n / 1048576).toFixed(1)}MB`;
}

export function SetupGate() {
  const [view, setView] = React.useState<SetupGateViewState>(initialViewState);
  const lifecycleRef = React.useRef<SetupGateLifecycle | null>(null);

  React.useEffect(() => {
    if (typeof window === 'undefined' || !(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) {
      return;
    }
    let cancelled = false;
    let lifecycle: SetupGateLifecycle | null = null;
    void (async () => {
      try {
        const [{ listen }, { invoke }] = await Promise.all([
          import('@tauri-apps/api/event'),
          import('@tauri-apps/api/core'),
        ]);
        if (cancelled) return;
        lifecycle = createSetupGateLifecycle({
          listen: (event, handler) => listen<DistributionSetupSnapshot>(event, handler),
          invoke: <T,>(command: string) => invoke<T>(command),
          setTimer: (callback, delayMs) => window.setTimeout(callback, delayMs),
          clearTimer: (handle) => window.clearTimeout(handle as number),
          onChange: setView,
        });
        lifecycleRef.current = lifecycle;
        await lifecycle.connect();
      } catch {
        // event API unavailable — overlay simply never shows.
      }
    })();
    return () => {
      cancelled = true;
      lifecycle?.dispose();
      if (lifecycleRef.current === lifecycle) lifecycleRef.current = null;
    };
  }, []);

  const retrySetup = React.useCallback(() => {
    return lifecycleRef.current?.retry() || Promise.resolve();
  }, []);

  const {
    active,
    layers,
    progress: prog,
    error,
    done,
    retrying,
  } = view;

  if (!active) return null;

  const pct = prog && prog.total > 0 ? Math.min(100, Math.round((prog.downloaded / prog.total) * 100)) : 0;
  const phaseLabel = prog?.phase === 'verify' ? '校验中' : prog?.phase === 'install' ? '安装中' : '下载中';

  const overlay: React.CSSProperties = {
    position: 'fixed', inset: 0, zIndex: 99999,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'var(--color-overlay)', backdropFilter: 'blur(8px)',
  };
  const card: React.CSSProperties = {
    width: 'min(420px, 86vw)', padding: '26px 28px', borderRadius: 8,
    background: 'var(--color-surface)', border: '1px solid var(--color-border)',
    boxShadow: 'var(--elevation-high)', color: 'var(--color-text)',
    fontFamily: '-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif',
  };
  const bar: React.CSSProperties = { height: 8, borderRadius: 999, background: 'var(--color-disabled)', overflow: 'hidden', marginTop: 14 };
  const fill: React.CSSProperties = { height: '100%', width: `${pct}%`, background: 'var(--color-info)', transition: 'width var(--motion-standard) var(--motion-ease-out)' };

  return (
    <div style={overlay} role="dialog" aria-modal="true" aria-labelledby="setup-gate-title" aria-busy={!done && !error}>
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {!done && !error ? <span className="loom-activity-ring" style={{ color: 'var(--color-info)' }} /> : null}
          <div id="setup-gate-title" style={{ fontSize: 17, fontWeight: 900 }}>{done ? '组件已就绪' : error ? '组件安装受阻' : `正在准备 ${APP_DISPLAY_NAME}`}</div>
        </div>
        <div style={{ marginTop: 6, fontSize: 13, color: 'var(--color-text-muted)' }}>
          首次启动需要补齐运行组件，完成后会自动进入启动器。
        </div>
        {error ? (
          <div style={{ marginTop: 18, fontSize: 13, color: 'var(--color-danger)', lineHeight: 1.6 }} role="alert" aria-live="assertive">
            下载失败：{error}
            <br />请检查网络后直接重试；连续失败时再改用全量离线包。
            <div style={{ marginTop: 14 }}>
              <button
                type="button"
                onClick={() => void retrySetup()}
                disabled={retrying}
                style={{
                  minWidth: 112, height: 40, border: 0, borderRadius: 6,
                  background: 'var(--color-accent)', color: 'var(--color-accent-ink)', fontWeight: 800, cursor: retrying ? 'wait' : 'pointer',
                }}
              >
                {retrying ? '正在补全...' : '重试补全'}
              </button>
            </div>
          </div>
        ) : done ? (
          <div style={{ marginTop: 18, fontSize: 14, color: 'var(--color-success)', fontWeight: 800 }} role="status" aria-live="polite">正在进入 {APP_DISPLAY_NAME}...</div>
        ) : prog ? (
          <>
            <div style={{ marginTop: 18, fontSize: 13, fontWeight: 700 }}>
              [{prog.index}/{prog.count}] {prog.title} · {phaseLabel}
            </div>
            <div className="loom-scan-line" style={bar}><div style={fill} /></div>
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--color-text-muted)' }}>
              {prog.total > 0 ? `${fmtMB(prog.downloaded)} / ${fmtMB(prog.total)}（${pct}%）` : phaseLabel}
            </div>
          </>
        ) : (
          <div style={{ marginTop: 18, fontSize: 13 }}>准备 {layers.length} 个组件...</div>
        )}
      </div>
    </div>
  );
}
