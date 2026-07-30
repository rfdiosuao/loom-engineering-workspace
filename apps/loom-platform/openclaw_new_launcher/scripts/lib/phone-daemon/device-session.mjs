import {
  QUEUE_KIND,
  cancellationRequested,
  cancelledPhoneCommandResult,
  commandQueueKind,
  fixedFastPathPlan,
  probeFastPathReadyStatus,
  runPhoneCommand,
  syncPhoneEvents,
} from '../phone-command-core.mjs';
import { LimitQueue, SerialQueue } from './queue.mjs';

const DEFAULT_READ_TO_ACTION_SETTLE_MS = 0;
const DEFAULT_READ_TO_ACTION_MAX_WAIT_MS = 2_000;
const READ_TO_ACTION_POLL_MS = 25;
const DEFAULT_READY_STATUS_TTL_MS = 3_000;

export class DeviceSession {
  constructor(deviceKey, options = {}) {
    this.deviceKey = deviceKey;
    this.createdAt = Date.now();
    this.lastUsedAt = 0;
    this.actionQueue = new SerialQueue();
    this.readQueue = new LimitQueue(options.readConcurrency || 4);
    this.screenshotQueue = new LimitQueue(options.screenshotConcurrency || 2);
    this.eventQueue = new SerialQueue();
    this.lastReadCompletedAt = 0;
    this.readToActionSettleMs = positiveFiniteNumber(options.readToActionSettleMs, DEFAULT_READ_TO_ACTION_SETTLE_MS);
    this.readToActionMaxWaitMs = positiveFiniteNumber(options.readToActionMaxWaitMs, DEFAULT_READ_TO_ACTION_MAX_WAIT_MS);
    this.readyStatusTtlMs = positiveFiniteNumber(options.readyStatusTtlMs, DEFAULT_READY_STATUS_TTL_MS);
    this.readyStatusCache = null;
    this.coalescedActions = new Map();
    this.events = [];
    this.stopping = false;
    this.operationSequence = 0;
    this.activeOperations = new Map();
    this.shutdownPromise = null;
  }

  run(config, lifecycle = {}) {
    if (this.stopping) {
      const result = daemonStoppingResult(config);
      lifecycle.onResult?.(result);
      return Promise.resolve(result);
    }
    this.lastUsedAt = Date.now();
    const kind = commandQueueKind(config);
    const plan = fixedFastPathPlan(config);
    const coalescingKey = kind === QUEUE_KIND.ACTION ? actionCoalescingKey(plan) : '';
    const queue =
      kind === QUEUE_KIND.READ ? this.readQueue :
      kind === QUEUE_KIND.SCREENSHOT ? this.screenshotQueue :
      this.actionQueue;
    lifecycle.onQueued?.({
      queueKind: kind,
      queueDepth: queue.depth,
    });
    const execute = async (operationConfig) => {
      if (await cancellationRequested(
        operationConfig.cancelFile,
        operationConfig.cancelSignal,
      )) {
        const result = cancelledPhoneCommandResult(operationConfig);
        lifecycle.onResult?.(result);
        return result;
      }
      try {
        const authorizedConfig = typeof lifecycle.authorize === 'function'
          ? await lifecycle.authorize(operationConfig)
          : operationConfig;
        lifecycle.onRunning?.({
          queueKind: kind,
        });
        const commandConfig = {
          ...authorizedConfig,
          cancelSignal: operationConfig.cancelSignal,
        };
        if (plan) {
          commandConfig.fastPathReadyStatus = await this.fastPathReadyStatus(commandConfig);
        }
        if (kind === QUEUE_KIND.ACTION) {
          const guarded = await this.waitForReadToActionQuiet();
          if (guarded) {
            commandConfig.forceActionPairingRefreshOnAuthFailure = true;
          }
        }
        const result = await runPhoneCommand(commandConfig);
        lifecycle.onResult?.(result);
        return result;
      } catch (error) {
        this.clearReadyStatusOnError(error);
        lifecycle.onError?.(error);
        throw error;
      } finally {
        if (kind === QUEUE_KIND.READ || kind === QUEUE_KIND.SCREENSHOT) {
          this.lastReadCompletedAt = Date.now();
        }
      }
    };
    if (coalescingKey) {
      const existing = this.coalescedActions.get(coalescingKey);
      if (existing) return existing;
      const operation = this.createOperation('run', config);
      const promise = this.trackOperation(
        operation,
        queue.enqueue(() => executeOperation(execute, operation, config)),
      );
      this.coalescedActions.set(coalescingKey, promise);
      promise.finally(() => {
        if (this.coalescedActions.get(coalescingKey) === promise) {
          this.coalescedActions.delete(coalescingKey);
        }
      }).catch(() => {});
      return promise;
    }
    const operation = this.createOperation('run', config);
    return this.trackOperation(
      operation,
      queue.enqueue(() => executeOperation(execute, operation, config)),
    );
  }

  syncEvents(config, onEvent, lifecycle = {}) {
    if (this.stopping) {
      return Promise.resolve({
        ok: true,
        cancelled: true,
        stoppedBy: 'daemon_shutdown',
        eventCount: 0,
        executionMayContinue: false,
      });
    }
    this.lastUsedAt = Date.now();
    lifecycle.onQueued?.({
      queueKind: 'events',
      queueDepth: this.eventQueue.depth,
    });
    const operation = this.createOperation('events', config);
    return this.trackOperation(operation, this.eventQueue.enqueue(async () => {
      try {
        const authorizedConfig = typeof lifecycle.authorize === 'function'
          ? await lifecycle.authorize({
            ...config,
            cancelSignal: operation.controller.signal,
          })
          : {
            ...config,
            cancelSignal: operation.controller.signal,
          };
        lifecycle.onRunning?.({
          queueKind: 'events',
        });
        const summary = await syncPhoneEvents({
          ...authorizedConfig,
          cancelSignal: operation.controller.signal,
        }, onEvent);
        lifecycle.onResult?.(summary);
        return summary;
      } catch (error) {
        lifecycle.onError?.(error);
        throw error;
      }
    }));
  }

  createOperation(kind, config) {
    const id = `${kind}-${++this.operationSequence}`;
    const operation = {
      id,
      kind,
      controller: new AbortController(),
      config,
      promise: null,
      settlement: null,
    };
    this.activeOperations.set(id, operation);
    return operation;
  }

  trackOperation(operation, promise) {
    operation.promise = promise;
    promise.then(
      (value) => {
        operation.settlement = { status: 'fulfilled', value };
      },
      (reason) => {
        operation.settlement = { status: 'rejected', reason };
      },
    ).finally(() => {
      this.activeOperations.delete(operation.id);
    });
    return promise;
  }

  shutdown(options = {}) {
    if (this.shutdownPromise) return this.shutdownPromise;
    this.stopping = true;
    const operations = [...this.activeOperations.values()];
    for (const operation of operations) {
      operation.controller.abort('phone_daemon_shutdown');
    }
    this.shutdownPromise = this.finishShutdown(
      operations,
      positiveFiniteNumber(options.timeoutMs, 4_000),
    );
    return this.shutdownPromise;
  }

  async finishShutdown(operations, timeoutMs) {
    const completedWithinDeadline = await settleWithin(
      operations.map((operation) => operation.promise).filter(Boolean),
      timeoutMs,
    );
    const indeterminate = operations.filter((operation) => (
      !operation.settlement
      || operation.settlement.status === 'rejected'
      || resultMayContinue(operation.settlement.value)
    ));
    const drained = (
      completedWithinDeadline
      && this.activeOperations.size === 0
      && indeterminate.length === 0
    );
    return {
      ok: drained,
      stopped: true,
      drained,
      requestedOperations: operations.length,
      unfinishedOperations: this.activeOperations.size,
      indeterminateOperations: indeterminate.length,
      executionMayContinue: !drained,
      outcomeIndeterminate: !drained,
    };
  }

  async waitForReadToActionQuiet() {
    if (this.readToActionSettleMs <= 0) return false;
    const startedAt = Date.now();
    let guarded = false;
    while (true) {
      const now = Date.now();
      const elapsedMs = now - startedAt;
      const remainingBudgetMs = this.readToActionMaxWaitMs - elapsedMs;
      if (remainingBudgetMs <= 0) return guarded;

      const readDepth = this.readQueue.depth + this.screenshotQueue.depth;
      const remainingSettleMs = this.lastReadCompletedAt
        ? this.lastReadCompletedAt + this.readToActionSettleMs - now
        : 0;
      if (readDepth <= 0 && remainingSettleMs <= 0) return guarded;

      const nextPollMs = readDepth > 0
        ? READ_TO_ACTION_POLL_MS
        : Math.min(READ_TO_ACTION_POLL_MS, Math.max(1, remainingSettleMs));
      guarded = true;
      await delay(Math.min(nextPollMs, remainingBudgetMs));
    }
  }

  async fastPathReadyStatus(config) {
    const now = Date.now();
    if (this.readyStatusCache && this.readyStatusCache.expiresAt > now) {
      return this.readyStatusCache.status;
    }
    const status = await probeFastPathReadyStatus(config);
    this.readyStatusCache = {
      status,
      expiresAt: Date.now() + this.readyStatusTtlMs,
    };
    return status;
  }

  clearReadyStatusOnError(error) {
    const message = String(error?.message || error || '');
    if (/device_offline|accessibility_|agent_not_initialized|phone_locked/i.test(message)) {
      this.readyStatusCache = null;
    }
  }

  rememberEvent(event) {
    this.events.push({ receivedAt: new Date().toISOString(), ...event });
    if (this.events.length > 200) this.events.splice(0, this.events.length - 200);
  }

  recentEvents(limit = 20) {
    return this.events.slice(-Math.max(0, Math.min(200, Number(limit) || 20)));
  }

  status() {
    return {
      deviceKey: this.deviceKey,
      createdAt: new Date(this.createdAt).toISOString(),
      lastUsedAt: this.lastUsedAt ? new Date(this.lastUsedAt).toISOString() : '',
      queues: {
        actionDepth: this.actionQueue.depth,
        readDepth: this.readQueue.depth,
        screenshotDepth: this.screenshotQueue.depth,
        eventDepth: this.eventQueue.depth,
      },
      recentEventCount: this.events.length,
      stopping: this.stopping,
      activeOperations: this.activeOperations.size,
    };
  }
}

async function executeOperation(execute, operation, config) {
  if (operation.controller.signal.aborted) {
    return cancelledPhoneCommandResult({
      ...config,
      cancelSignal: operation.controller.signal,
    });
  }
  return execute({
    ...config,
    cancelSignal: operation.controller.signal,
  });
}

function daemonStoppingResult(config = {}) {
  return {
    ...cancelledPhoneCommandResult(config),
    error: 'daemon_stopping',
    errorCode: 'daemon_stopping',
  };
}

function resultMayContinue(value) {
  return (
    value?.executionMayContinue === true
    || value?.outcomeIndeterminate === true
    || value?.final?.executionMayContinue === true
    || value?.final?.outcomeIndeterminate === true
  );
}

function settleWithin(promises, timeoutMs) {
  if (!promises.length) return Promise.resolve(true);
  return new Promise((resolve) => {
    let finished = false;
    const timer = setTimeout(() => {
      if (finished) return;
      finished = true;
      resolve(false);
    }, Math.max(1, timeoutMs));
    timer.unref?.();
    Promise.allSettled(promises).then(() => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      resolve(true);
    });
  });
}

function positiveFiniteNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function actionCoalescingKey(plan) {
  if (!plan || plan.kind !== QUEUE_KIND.ACTION) return '';
  const action = String(plan.body?.action || '');
  if (action === 'open_app') {
    const packageName = String(plan.body?.packageName || '').trim();
    return packageName ? `open_app:${packageName}` : '';
  }
  if (action === 'home') return 'home';
  return '';
}
