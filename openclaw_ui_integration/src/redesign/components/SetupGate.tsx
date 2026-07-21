import React from 'react';

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

function fmtSpeed(bytesPerSec: number): string {
  if (!Number.isFinite(bytesPerSec) || bytesPerSec <= 0) return '';
  if (bytesPerSec >= 1048576) return `${(bytesPerSec / 1048576).toFixed(1)}MB/s`;
  return `${(bytesPerSec / 1024).toFixed(0)}KB/s`;
}

export function SetupGate() {
  const [active, setActive] = React.useState(false);
  const [layers, setLayers] = React.useState<LayerInfo[]>([]);
  const [prog, setProg] = React.useState<Progress | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);
  const [speed, setSpeed] = React.useState(0);
  const [source, setSource] = React.useState<{ host: string; mirror: number; mirrors: number } | null>(null);
  const lastSampleRef = React.useRef<{ downloaded: number; time: number } | null>(null);

  // Track downloaded-bytes delta between dist://progress events to derive a
  // live download speed (not provided by the backend event payload).
  const handleProgress = React.useCallback((next: Progress) => {
    setProg(next);
    const now = Date.now();
    const last = lastSampleRef.current;
    if (last && next.downloaded >= last.downloaded) {
      const deltaBytes = next.downloaded - last.downloaded;
      const deltaSec = (now - last.time) / 1000;
      if (deltaSec > 0.05) {
        setSpeed(deltaBytes / deltaSec);
        lastSampleRef.current = { downloaded: next.downloaded, time: now };
      }
    } else {
      lastSampleRef.current = { downloaded: next.downloaded, time: now };
    }
  }, []);

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
            setProg(null);
            setSpeed(0);
            setSource(null);
            lastSampleRef.current = null;
            setLayers(((e.payload as { layers?: LayerInfo[] }).layers) || []);
          }),
          listen('dist://source', (e) => {
            const p = e.payload as { host?: string; mirror?: number; mirrors?: number };
            setSource({ host: p.host || '', mirror: p.mirror || 1, mirrors: p.mirrors || 1 });
          }),
          listen('dist://progress', (e) => handleProgress(e.payload as Progress)),
          listen('dist://done', () => {
            setDone(true);
            setSpeed(0);
            window.setTimeout(() => setActive(false), 900);
          }),
          listen('dist://error', (e) => {
            setSpeed(0);
            setError((e.payload as { message?: string }).message || 'download_failed');
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
  }, [handleProgress]);

  if (!active) return null;

  const pct = prog && prog.total > 0 ? Math.min(100, Math.round((prog.downloaded / prog.total) * 100)) : 0;
  const phaseLabel = prog?.phase === 'verify' ? '校验中' : prog?.phase === 'install' ? '安装中' : '下载中';
  const totalSize = layers.reduce((sum, layer) => sum + (layer.size || 0), 0);
  const speedLabel = fmtSpeed(speed);

  const overlay: React.CSSProperties = {
    position: 'fixed', inset: 0, zIndex: 99999,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'rgba(5,5,16,0.86)', backdropFilter: 'blur(6px)',
  };
  const card: React.CSSProperties = {
    width: 'min(460px, 86vw)', padding: '28px 30px', borderRadius: 18,
    background: '#11151f', border: '1px solid rgba(255,255,255,0.08)',
    boxShadow: '0 24px 70px rgba(0,0,0,0.5)', color: '#e6edf3',
    fontFamily: '-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif',
  };
  const bar: React.CSSProperties = { height: 8, borderRadius: 6, background: 'rgba(255,255,255,0.08)', overflow: 'hidden', marginTop: 14 };
  const fill: React.CSSProperties = { height: '100%', width: `${pct}%`, background: 'linear-gradient(90deg,#58a6ff,#3fb950)', transition: 'width .2s ease' };

  return (
    <div style={overlay}>
      <div style={card}>
        <div style={{ fontSize: 17, fontWeight: 800 }}>正在安装 OpenClaw 组件</div>
        <div style={{ marginTop: 6, fontSize: 13, color: '#8b949e' }}>
          正在下载并校验组件文件，请保持联网；已安装的组件不会重复下载。
          {totalSize > 0 ? ` 共需下载约 ${fmtMB(totalSize)}。` : ''}
        </div>
        {error ? (
          <div style={{ marginTop: 18, fontSize: 13, color: '#ff7b72', lineHeight: 1.6 }}>
            下载失败：{error}
            <br />请检查网络连接后重试；如果反复失败，可改用全量离线包安装。
          </div>
        ) : done ? (
          <div style={{ marginTop: 18, fontSize: 14, color: '#3fb950', fontWeight: 700 }}>组件已就绪，正在启动…</div>
        ) : prog ? (
          <>
            <div style={{ marginTop: 18, fontSize: 13, fontWeight: 700 }}>
              [{prog.index}/{prog.count}] {prog.title} · {phaseLabel}
            </div>
            <div style={bar}><div style={fill} /></div>
            <div style={{ marginTop: 8, fontSize: 12, color: '#8b949e' }}>
              {prog.total > 0 ? `${fmtMB(prog.downloaded)} / ${fmtMB(prog.total)}（${pct}%）` : phaseLabel}
              {speedLabel && prog.phase === 'download' ? ` · ${speedLabel}` : ''}
            </div>
            {source && source.host ? (
              <div style={{ marginTop: 6, fontSize: 12, color: '#6e7681' }}>
                下载源：{source.host}
                {source.mirrors > 1 ? `（源 ${source.mirror}/${source.mirrors}${source.mirror > 1 ? '，已自动切换备用源' : ''}）` : ''}
              </div>
            ) : null}
          </>
        ) : (
          <div style={{ marginTop: 18, fontSize: 13 }}>
            准备下载 {layers.length} 个组件{totalSize > 0 ? `（约 ${fmtMB(totalSize)}）` : ''}…
          </div>
        )}
        <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: 12, color: '#6e7681' }}>
          不会删除 OpenClawFiles 和你已有的配置。
        </div>
      </div>
    </div>
  );
}
