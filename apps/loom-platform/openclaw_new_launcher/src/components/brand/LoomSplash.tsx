import React from 'react';
import { APP_DISPLAY_NAME } from '../../version';

const MIN_SPLASH_DURATION_MS = 2200;
const MAX_SPLASH_DURATION_MS = 6500;
const SPLASH_VIDEO_SRC = '/loom-motion/luming-splash-v2.mp4';
const SPLASH_POSTER_SRC = '/loom-motion/luming-splash-v2-poster.jpg';

export const LoomSplash: React.FC = () => {
  const [minElapsed, setMinElapsed] = React.useState(false);
  const [playbackComplete, setPlaybackComplete] = React.useState(false);
  const [visible, setVisible] = React.useState(true);

  React.useEffect(() => {
    const minTimer = window.setTimeout(() => setMinElapsed(true), MIN_SPLASH_DURATION_MS);
    const fallbackTimer = window.setTimeout(() => setVisible(false), MAX_SPLASH_DURATION_MS);
    return () => {
      window.clearTimeout(minTimer);
      window.clearTimeout(fallbackTimer);
    };
  }, []);

  React.useEffect(() => {
    if (!playbackComplete || !minElapsed) return undefined;
    const timer = window.setTimeout(() => setVisible(false), 180);
    return () => window.clearTimeout(timer);
  }, [playbackComplete, minElapsed]);

  if (!visible) return null;

  return (
    <div
      data-loom-splash
      className="loom-splash fixed inset-0 z-[99990] flex items-center justify-center bg-surface-deeper text-white"
      role="status"
      aria-live="polite"
      aria-label={`${APP_DISPLAY_NAME}启动中`}
    >
      <div className="flex flex-col items-center">
        <div className="loom-splash-orbit relative h-[300px] w-[300px] overflow-hidden rounded-[8px] bg-surface-deeper shadow-elevation-high">
          <video
            data-loom-splash-video
            className="h-full w-full object-cover"
            src={SPLASH_VIDEO_SRC}
            poster={SPLASH_POSTER_SRC}
            autoPlay
            muted
            playsInline
            preload="auto"
            onEnded={() => setPlaybackComplete(true)}
            onError={() => setPlaybackComplete(true)}
            aria-label={`${APP_DISPLAY_NAME}品牌启动动画`}
          />
        </div>
        <div className="mt-5 max-w-[380px] px-4 text-center text-[28px] font-black leading-tight text-white">
          {APP_DISPLAY_NAME}
        </div>
        <div className="mt-2 text-sm font-bold text-white/70">正在准备工作台</div>
        <div className="loom-splash-dots mt-4 flex items-center gap-1.5" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
};
