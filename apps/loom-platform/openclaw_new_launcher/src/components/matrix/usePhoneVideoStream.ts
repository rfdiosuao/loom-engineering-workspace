import React from 'react';

import { matrixApi, parseErrorText, resolveBridgeStreamUrl } from '../../services/api';
import { PhoneH264PacketParser, phoneVideoDecoderSupported } from './phoneVideoProtocol';

export type PhoneVideoStreamStatus =
  | 'idle'
  | 'permission_required'
  | 'connecting'
  | 'active'
  | 'degraded'
  | 'unsupported';

export interface PhoneVideoStreamView {
  status: PhoneVideoStreamStatus;
  message: string;
  transport: string;
  width: number;
  height: number;
  canvasRef: React.RefObject<HTMLCanvasElement>;
}

const RETRY_DELAY_MS = 1_200;

function waitForRetry(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const timer = window.setTimeout(resolve, RETRY_DELAY_MS);
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

function sessionId(deviceId: string): string {
  const suffix = typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `focus-${deviceId.replace(/[^A-Za-z0-9_.:-]/g, '-')}-${suffix}`.slice(0, 128);
}

function transportLabel(transport: string): string {
  return transport === 'usb-forward' ? 'USB 低延迟视频' : '局域网低延迟视频';
}

export function usePhoneVideoStream(deviceId?: string, online = false): PhoneVideoStreamView {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const [pageVisible, setPageVisible] = React.useState(() => document.visibilityState === 'visible');
  const [view, setView] = React.useState<Omit<PhoneVideoStreamView, 'canvasRef'>>({
    status: 'idle',
    message: '',
    transport: '',
    width: 0,
    height: 0,
  });

  React.useEffect(() => {
    const onVisibility = () => setPageVisible(document.visibilityState === 'visible');
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  React.useEffect(() => {
    if (!deviceId || !online || !pageVisible) {
      setView({ status: 'idle', message: '', transport: '', width: 0, height: 0 });
      return undefined;
    }
    if (!phoneVideoDecoderSupported()) {
      setView({
        status: 'unsupported',
        message: '当前 WebView 不支持 WebCodecs，已使用截图画面',
        transport: '',
        width: 0,
        height: 0,
      });
      return undefined;
    }

    const abort = new AbortController();
    const clientSessionId = sessionId(deviceId);
    let decoder: VideoDecoder | null = null;
    let activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    let receivedFrame = false;
    let decoderFailure: unknown;

    const run = async () => {
      while (!abort.signal.aborted) {
        try {
          const grant = await matrixApi.startPhoneStream(deviceId, {
            clientSessionId,
            fps: 15,
            maxLongSide: 1280,
            bitRate: 2_400_000,
          });
          if (abort.signal.aborted) break;
          const label = transportLabel(grant.transport);
          if (grant.state !== 'active' || !grant.ticket || !grant.streamUrl) {
            setView({
              status: grant.state === 'permission_required' ? 'permission_required' : 'degraded',
              message: grant.message || (grant.requiresUserConsent
                ? '请在手机确认屏幕共享授权；确认前继续显示截图'
                : '低延迟视频暂不可用，已继续显示截图'),
              transport: label,
              width: grant.width,
              height: grant.height,
            });
            await waitForRetry(abort.signal);
            continue;
          }

          setView({
            status: 'connecting',
            message: `${label}正在建立`,
            transport: label,
            width: grant.width,
            height: grant.height,
          });
          const url = await resolveBridgeStreamUrl(grant.streamUrl);
          const response = await fetch(url, {
            method: 'GET',
            headers: {
              Accept: 'application/vnd.luming.h264',
              Authorization: `Bearer ${grant.ticket}`,
            },
            cache: 'no-store',
            credentials: 'omit',
            redirect: 'error',
            referrerPolicy: 'no-referrer',
            signal: abort.signal,
          });
          if (!response.ok || !response.body) throw new Error(`视频通道返回 ${response.status}`);

          const parser = new PhoneH264PacketParser();
          receivedFrame = false;
          decoderFailure = undefined;
          decoder = new VideoDecoder({
            output: (frame) => {
              try {
                const canvas = canvasRef.current;
                if (!canvas) return;
                const width = frame.displayWidth || frame.codedWidth;
                const height = frame.displayHeight || frame.codedHeight;
                if (canvas.width !== width || canvas.height !== height) {
                  canvas.width = width;
                  canvas.height = height;
                }
                canvas.getContext('2d', { alpha: false })?.drawImage(frame, 0, 0, width, height);
                if (!receivedFrame) {
                  receivedFrame = true;
                  setView({
                    status: 'active',
                    message: `${label}已连接`,
                    transport: label,
                    width,
                    height,
                  });
                }
              } finally {
                frame.close();
              }
            },
            error: (reason) => {
              decoderFailure = reason;
              if (!abort.signal.aborted) void activeReader?.cancel(reason).catch(() => undefined);
            },
          });
          decoder.configure({
            codec: grant.codec || 'avc1.42E01F',
            optimizeForLatency: true,
            hardwareAcceleration: 'prefer-hardware',
          });
          activeReader = response.body.getReader();
          while (!abort.signal.aborted) {
            const { done, value } = await activeReader.read();
            if (done) break;
            for (const packet of parser.push(value)) {
              if (decoder.state !== 'configured') break;
              decoder.decode(new EncodedVideoChunk({
                type: packet.type,
                timestamp: packet.timestamp,
                data: packet.data,
              }));
            }
          }
          if (!abort.signal.aborted) throw decoderFailure || new Error('视频通道已断开');
        } catch (reason) {
          if (abort.signal.aborted) break;
          setView((current) => ({
            ...current,
            status: 'degraded',
            message: `${parseErrorText(reason) || '低延迟视频中断'}；已自动降级为截图`,
          }));
        } finally {
          activeReader = null;
          if (decoder) {
            try {
              decoder.close();
            } catch {
              // Decoder can already be closed after a platform error.
            }
            decoder = null;
          }
        }
        await waitForRetry(abort.signal);
      }
    };
    void run();
    return () => {
      abort.abort();
      void activeReader?.cancel().catch(() => undefined);
      if (decoder) {
        try {
          decoder.close();
        } catch {
          // Best-effort cleanup.
        }
      }
      void matrixApi.stopPhoneStream(deviceId).catch(() => undefined);
    };
  }, [deviceId, online, pageVisible]);

  return { ...view, canvasRef };
}
