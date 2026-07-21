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

function fmtMB(n: number): string {
  return `${(n / 1048576).toFixed(1)}MB`;
}

export function SetupGate() {
  const [active, setActive] = React.useState(false);
  const [layers, setLayers] = React.useState<LayerInfo[]>([]);
  const [prog, setProg] = React.useState<Progress | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);
  const [retrying, setRetrying] = React.useState(false);

  React.useEffect(() => {
    if (typeof window === 'undefined' || !(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) {
      return;
    }
    let cancelled = false;
    const unlisteners: Array<() => void> = [];
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        const subs = await Promise.all([
          listen('dist://start', (e) => {
            setActive(true);
            setDone(false);
            setError(null);
            setLayers(((e.payload as { layers?: LayerInfo[] }).layers) || []);
          }),
          listen('dist://progress', (e) => setProg(e.payload as Progress)),
          listen('dist://done', () => {
            setDone(true);
            window.setTimeout(() => setActive(false), 900);
          }),
          listen('dist://error', (e) => {
            const message = String((e.payload as { message?: string } | null)?.message || '组件下载失败');
            setActive(true);
            setError(message);
          }),
        ]);
        if (cancelled) {
          subs.forEach((u) => u());
          return;
        }
        unlisteners.push(...subs);
      } catch {
        // event API unavailable — overlay simply never shows.
      }
    })();
    return () => {
      cancelled = true;
      unlisteners.forEach((u) => u());
    };
  }, []);

  const retrySetup = React.useCallback(async () => {
    setActive(true);
    setRetrying(true);
    setDone(false);
    setProg(null);
    setError(null);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke<string>('retry_distribution_setup');
      setDone(true);
      window.setTimeout(() => setActive(false), 900);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause || '组件补全失败'));
    } finally {
      setRetrying(false);
    }
  }, []);

  if (!active) return null;

  const pct = prog && prog.total > 0 ? Math.min(100, Math.round((prog.downloaded / prog.total) * 100)) : 0;
  const phaseLabel = prog?.phase === 'verify' ? '校验中' : prog?.phase === 'install' ? '安装中' : '下载中';

  const overlay: React.CSSProperties = {
    position: 'fixed', inset: 0, zIndex: 99999,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'rgba(7,27,36,0.90)', backdropFilter: 'blur(8px)',
  };
  const card: React.CSSProperties = {
    width: 'min(420px, 86vw)', padding: '26px 28px', borderRadius: 14,
    background: '#fffaf0', border: '1px solid rgba(8,35,48,0.12)',
    boxShadow: '0 24px 70px rgba(0,0,0,0.34)', color: '#1b211e',
    fontFamily: '-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif',
  };
  const bar: React.CSSProperties = { height: 8, borderRadius: 999, background: 'rgba(8,35,48,0.10)', overflow: 'hidden', marginTop: 14 };
  const fill: React.CSSProperties = { height: '100%', width: `${pct}%`, background: 'linear-gradient(90deg,#0B4A3E,#37D5A3)', transition: 'width .2s ease' };

  return (
    <div style={overlay}>
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {!done && !error ? <span className="loom-activity-ring" style={{ color: '#0B4A3E' }} /> : null}
          <div style={{ fontSize: 17, fontWeight: 900 }}>{done ? '组件已就绪' : error ? '组件安装受阻' : `正在准备 ${APP_DISPLAY_NAME}`}</div>
        </div>
        <div style={{ marginTop: 6, fontSize: 13, color: '#6b6357' }}>
          首次启动需要补齐运行组件，完成后会自动进入启动器。
        </div>
        {error ? (
          <div style={{ marginTop: 18, fontSize: 13, color: '#c84b5f', lineHeight: 1.6 }}>
            下载失败：{error}
            <br />请检查网络后直接重试；连续失败时再改用全量离线包。
            <div style={{ marginTop: 14 }}>
              <button
                type="button"
                onClick={() => void retrySetup()}
                disabled={retrying}
                style={{
                  minWidth: 112, height: 40, border: 0, borderRadius: 6,
                  background: '#0B4A3E', color: '#fff', fontWeight: 800, cursor: retrying ? 'wait' : 'pointer',
                }}
              >
                {retrying ? '正在补全...' : '重试补全'}
              </button>
            </div>
          </div>
        ) : done ? (
          <div style={{ marginTop: 18, fontSize: 14, color: '#0B8C6E', fontWeight: 800 }}>正在进入 {APP_DISPLAY_NAME}...</div>
        ) : prog ? (
          <>
            <div style={{ marginTop: 18, fontSize: 13, fontWeight: 700 }}>
              [{prog.index}/{prog.count}] {prog.title} · {phaseLabel}
            </div>
            <div className="loom-scan-line" style={bar}><div style={fill} /></div>
            <div style={{ marginTop: 8, fontSize: 12, color: '#756b5b' }}>
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
