import React from 'react';

import { matrixApi, parseErrorText } from '../../services/api';
import type { MatrixScreen } from '../../types/matrix';
import type { MatrixDeviceView } from './matrixViewModel';
import {
  applyScreenResponse,
  nextScreenDueAt,
  pollIntervalForDevice,
  screenFailureBackoffMs,
  selectDueScreenRequests,
  type MatrixScreenFrame,
  type ScreenRequestOutcome,
  type ScreenScheduleCandidate,
} from './screenScheduler';

interface VisibleScreensState {
  frames: Readonly<Record<string, MatrixScreenFrame>>;
  errors: Readonly<Record<string, string>>;
  outcomes: Readonly<Record<string, ScreenRequestOutcome>>;
  inFlightCount: number;
  requestNow: (deviceId: string) => number;
}

function screenObjectUrl(screen: MatrixScreen): string | undefined {
  if (screen.notModified) return undefined;
  const raw = window.atob(screen.image);
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
  return URL.createObjectURL(new Blob([bytes], { type: screen.mime }));
}

function screenRefreshError(reason: unknown): string {
  const detail = parseErrorText(reason);
  return detail ? `画面刷新失败：${detail}` : '画面刷新失败，请重试';
}

export function useVisibleScreens(
  devices: MatrixDeviceView[],
  visibleDeviceIds: ReadonlySet<string>,
  focusedDeviceId?: string,
): VisibleScreensState {
  const [frames, setFrames] = React.useState<Record<string, MatrixScreenFrame>>({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [outcomes, setOutcomes] = React.useState<Record<string, ScreenRequestOutcome>>({});
  const [inFlightCount, setInFlightCount] = React.useState(0);
  const framesRef = React.useRef(frames);
  const dueAtRef = React.useRef(new Map<string, number>());
  const inFlightRef = React.useRef(new Set<string>());
  const immediateRequestRef = React.useRef(new Set<string>());
  const requestedGenerationRef = React.useRef(new Map<string, number>());
  const qualityGenerationRef = React.useRef(new Map<string, number>());
  const failureCountRef = React.useRef(new Map<string, number>());
  const devicesRef = React.useRef(devices);
  const visibleRef = React.useRef(visibleDeviceIds);
  const focusedRef = React.useRef(focusedDeviceId);
  framesRef.current = frames;
  devicesRef.current = devices;
  visibleRef.current = visibleDeviceIds;
  focusedRef.current = focusedDeviceId;

  const requestNow = React.useCallback((deviceId: string) => {
    const generation = (requestedGenerationRef.current.get(deviceId) ?? 0) + 1;
    requestedGenerationRef.current.set(deviceId, generation);
    qualityGenerationRef.current.set(deviceId, generation);
    if (inFlightRef.current.has(deviceId)) {
      immediateRequestRef.current.add(deviceId);
      return generation;
    }
    dueAtRef.current.set(deviceId, 0);
    return generation;
  }, []);

  React.useEffect(() => {
    if (focusedDeviceId) requestNow(focusedDeviceId);
  }, [focusedDeviceId, requestNow]);

  React.useEffect(() => {
    const knownIds = new Set(devices.map((device) => device.deviceId));
    const now = Date.now();
    for (const device of devices) {
      const interval = pollIntervalForDevice(device.status, focusedDeviceId === device.deviceId);
      const nextDueAt = interval === null ? Number.POSITIVE_INFINITY : now + interval;
      dueAtRef.current.set(device.deviceId, Math.min(dueAtRef.current.get(device.deviceId) ?? 0, nextDueAt));
    }
    setFrames((current) => {
      const next = { ...current };
      let changed = false;
      for (const [deviceId, frame] of Object.entries(current)) {
        if (knownIds.has(deviceId)) continue;
        URL.revokeObjectURL(frame.url);
        dueAtRef.current.delete(deviceId);
        failureCountRef.current.delete(deviceId);
        delete next[deviceId];
        changed = true;
      }
      return changed ? next : current;
    });
  }, [devices, focusedDeviceId]);

  React.useEffect(() => {
    let disposed = false;

    const finishCandidate = (candidate: ScreenScheduleCandidate, generation: number, succeeded: boolean) => {
      inFlightRef.current.delete(candidate.deviceId);
      if (qualityGenerationRef.current.get(candidate.deviceId) === generation) {
        qualityGenerationRef.current.delete(candidate.deviceId);
      }
      if (disposed) return;
      const latestDevice = devicesRef.current.find((device) => device.deviceId === candidate.deviceId);
      const interval = latestDevice
        ? pollIntervalForDevice(latestDevice.status, focusedRef.current === candidate.deviceId)
        : null;
      const failureCount = succeeded
        ? 0
        : (failureCountRef.current.get(candidate.deviceId) ?? 0) + 1;
      if (failureCount > 0) failureCountRef.current.set(candidate.deviceId, failureCount);
      else failureCountRef.current.delete(candidate.deviceId);
      dueAtRef.current.set(
        candidate.deviceId,
        nextScreenDueAt(
          Date.now(),
          interval,
          immediateRequestRef.current.delete(candidate.deviceId),
          screenFailureBackoffMs(failureCount),
        ),
      );
    };

    const fetchScreens = async (candidates: ScreenScheduleCandidate[]) => {
      const generations = new Map(candidates.map((candidate) => [
        candidate.deviceId,
        requestedGenerationRef.current.get(candidate.deviceId) ?? 0,
      ]));
      for (const candidate of candidates) inFlightRef.current.add(candidate.deviceId);
      const succeededDeviceIds = new Set<string>();
      setInFlightCount(inFlightRef.current.size);
      try {
        const response = await matrixApi.screens(candidates.map((candidate) => ({
          deviceId: candidate.deviceId,
          knownHash: framesRef.current[candidate.deviceId]?.hash,
          focused: candidate.focused
            || qualityGenerationRef.current.get(candidate.deviceId) === generations.get(candidate.deviceId),
        })));
        if (disposed) return;
        const screens = new Map(response.screens.map((screen) => [screen.deviceId, screen]));
        const responseErrors = new Map(response.errors.map((error) => [error.deviceId, error]));
        let nextFrames = framesRef.current;
        const errorUpdates: Record<string, string | undefined> = {};
        const outcomeUpdates: Record<string, ScreenRequestOutcome> = {};
        for (const candidate of candidates) {
          const generation = generations.get(candidate.deviceId) ?? 0;
          const screen = screens.get(candidate.deviceId);
          try {
            if (!screen) {
              const detail = responseErrors.get(candidate.deviceId)?.error || 'Screenshot response missing';
              throw new Error(detail);
            }
            const current = nextFrames[candidate.deviceId];
            const nextUrl = screenObjectUrl(screen);
            const update = applyScreenResponse(current, screen, nextUrl);
            if (update.revokeUrl) URL.revokeObjectURL(update.revokeUrl);
            nextFrames = { ...nextFrames, [candidate.deviceId]: update.frame };
            succeededDeviceIds.add(candidate.deviceId);
            errorUpdates[candidate.deviceId] = undefined;
            if (generation > 0) outcomeUpdates[candidate.deviceId] = { generation };
          } catch (reason) {
            const error = screenRefreshError(reason);
            errorUpdates[candidate.deviceId] = error;
            if (generation > 0) outcomeUpdates[candidate.deviceId] = { generation, error };
          }
        }
        framesRef.current = nextFrames;
        setFrames(nextFrames);
        setErrors((current) => {
          const next = { ...current };
          for (const [deviceId, error] of Object.entries(errorUpdates)) {
            if (error) next[deviceId] = error;
            else delete next[deviceId];
          }
          return next;
        });
        if (Object.keys(outcomeUpdates).length) {
          setOutcomes((current) => ({ ...current, ...outcomeUpdates }));
        }
      } catch (reason) {
        if (!disposed) {
          const error = screenRefreshError(reason);
          setErrors((current) => ({
            ...current,
            ...Object.fromEntries(candidates.map((candidate) => [candidate.deviceId, error])),
          }));
          setOutcomes((current) => {
            const next = { ...current };
            for (const candidate of candidates) {
              const generation = generations.get(candidate.deviceId) ?? 0;
              if (generation > 0) next[candidate.deviceId] = { generation, error };
            }
            return next;
          });
        }
      } finally {
        for (const candidate of candidates) {
          finishCandidate(
            candidate,
            generations.get(candidate.deviceId) ?? 0,
            succeededDeviceIds.has(candidate.deviceId),
          );
        }
        if (!disposed) setInFlightCount(inFlightRef.current.size);
      }
    };

    const tick = () => {
      const now = Date.now();
      const candidates = devicesRef.current.map((device): ScreenScheduleCandidate => ({
        deviceId: device.deviceId,
        status: device.status,
        visible: visibleRef.current.has(device.deviceId) || focusedRef.current === device.deviceId,
        focused: focusedRef.current === device.deviceId,
        dueAt: dueAtRef.current.get(device.deviceId) ?? 0,
      }));
      const due = selectDueScreenRequests(candidates, inFlightRef.current, now, document.visibilityState === 'visible');
      const focused = due.filter((candidate) => candidate.focused);
      if (focused.length) void fetchScreens(focused);
      const background = due.filter((candidate) => !candidate.focused);
      for (let index = 0; index < background.length; index += 6) {
        void fetchScreens(background.slice(index, index + 6));
      }
    };

    const timer = window.setInterval(tick, 120);
    tick();
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);

  React.useEffect(() => () => {
    for (const frame of Object.values(framesRef.current)) URL.revokeObjectURL(frame.url);
  }, []);

  return { frames, errors, outcomes, inFlightCount, requestNow };
}
