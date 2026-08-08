import 'tsx/esm';

import assert from 'node:assert/strict';
import test from 'node:test';

import * as setupGate from './SetupGate.tsx';

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
type Snapshot = {
  revision: number;
  runId: number;
  status: 'idle' | 'running' | 'done' | 'error';
  layers: LayerInfo[];
  progress: Progress | null;
  error: string | null;
};
type ViewState = Snapshot & {
  active: boolean;
  done: boolean;
  retrying: boolean;
};
type EventName = 'dist://start' | 'dist://progress' | 'dist://done' | 'dist://error';
type Unlisten = () => void;
type Handler = (event: { payload: Snapshot }) => void;
type Dependencies = {
  listen: (event: EventName, handler: Handler) => Promise<Unlisten>;
  invoke: <T>(command: string) => Promise<T>;
  setTimer: (callback: () => void, delayMs: number) => unknown;
  clearTimer: (handle: unknown) => void;
  onChange: (state: ViewState) => void;
};
type Lifecycle = {
  connect: () => Promise<void>;
  retry: () => Promise<void>;
  dispose: () => void;
  getState: () => ViewState;
};
type CreateLifecycle = (dependencies: Dependencies) => Lifecycle;

const createLifecycle = (setupGate as unknown as {
  createSetupGateLifecycle?: CreateLifecycle;
}).createSetupGateLifecycle;

function requireLifecycle(): CreateLifecycle {
  assert.equal(typeof createLifecycle, 'function');
  return createLifecycle as CreateLifecycle;
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function snapshot(
  revision: number,
  runId: number,
  status: Snapshot['status'],
  overrides: Partial<Omit<Snapshot, 'revision' | 'runId' | 'status'>> = {},
): Snapshot {
  return {
    revision,
    runId,
    status,
    layers: [],
    progress: null,
    error: null,
    ...overrides,
  };
}

function createBus() {
  const names: EventName[] = ['dist://start', 'dist://progress', 'dist://done', 'dist://error'];
  const handlers = new Map<EventName, Set<Handler>>(names.map((name) => [name, new Set()]));
  const unlistenCalls = new Map<EventName, number>(names.map((name) => [name, 0]));
  return {
    listen: async (event: EventName, handler: Handler): Promise<Unlisten> => {
      handlers.get(event)?.add(handler);
      let active = true;
      return () => {
        if (!active) return;
        active = false;
        unlistenCalls.set(event, (unlistenCalls.get(event) || 0) + 1);
        handlers.get(event)?.delete(handler);
      };
    },
    emit(event: EventName, payload: Snapshot) {
      for (const handler of [...(handlers.get(event) || [])]) handler({ payload });
    },
    handlerCount(event: EventName) {
      return handlers.get(event)?.size || 0;
    },
    unlistenCount(event: EventName) {
      return unlistenCalls.get(event) || 0;
    },
  };
}

function createManualScheduler() {
  let nextHandle = 1;
  const active = new Set<number>();
  const callbacks = new Map<number, () => void>();
  let clearCalls = 0;
  return {
    setTimer(callback: () => void) {
      const handle = nextHandle++;
      active.add(handle);
      callbacks.set(handle, callback);
      return handle;
    },
    clearTimer(handle: unknown) {
      clearCalls += 1;
      active.delete(handle as number);
    },
    callback(handle: number) {
      return callbacks.get(handle);
    },
    handles() {
      return [...callbacks.keys()];
    },
    isActive(handle: number) {
      return active.has(handle);
    },
    clearCallCount() {
      return clearCalls;
    },
  };
}

function noTimer() {
  return {
    setTimer: () => 1,
    clearTimer: () => undefined,
  };
}

test('subscribes all distribution events before querying the snapshot', async () => {
  const create = requireLifecycle();
  const registrations: Array<ReturnType<typeof deferred<Unlisten>>> = [];
  let queryCalls = 0;
  const lifecycle = create({
    listen: () => {
      const registration = deferred<Unlisten>();
      registrations.push(registration);
      return registration.promise;
    },
    invoke: async <T,>(command: string) => {
      assert.equal(command, 'get_distribution_setup_snapshot');
      queryCalls += 1;
      return snapshot(0, 0, 'idle') as T;
    },
    ...noTimer(),
    onChange: () => undefined,
  });

  const connecting = lifecycle.connect();
  assert.equal(registrations.length, 4);
  assert.equal(queryCalls, 0);
  registrations.slice(0, 3).forEach((registration) => registration.resolve(() => undefined));
  await Promise.resolve();
  assert.equal(queryCalls, 0);
  registrations[3].resolve(() => undefined);
  await connecting;
  assert.equal(queryCalls, 1);
  lifecycle.dispose();
});

test('reconciles an event lost before listener readiness from the snapshot', async () => {
  const create = requireLifecycle();
  const names: EventName[] = ['dist://start', 'dist://progress', 'dist://done', 'dist://error'];
  const handlers = new Map<EventName, Set<Handler>>(names.map((name) => [name, new Set()]));
  const registrations: Array<{
    event: EventName;
    handler: Handler;
    deferred: ReturnType<typeof deferred<Unlisten>>;
  }> = [];
  const changes: ViewState[] = [];
  const lifecycle = create({
    listen: (event, handler) => {
      const pending = deferred<Unlisten>();
      registrations.push({ event, handler, deferred: pending });
      return pending.promise;
    },
    invoke: async <T,>() => snapshot(3, 1, 'running', {
      layers: [{ id: 'node', title: 'Node.js', size: 10 }],
    }) as T,
    ...noTimer(),
    onChange: (state) => changes.push(state),
  });

  const connecting = lifecycle.connect();
  for (const registration of registrations) {
    handlers.get(registration.event)?.add(registration.handler);
    registration.deferred.resolve(() => handlers.get(registration.event)?.delete(registration.handler));
  }
  await connecting;

  assert.equal(lifecycle.getState().revision, 3);
  assert.equal(lifecycle.getState().status, 'running');
  assert.equal(lifecycle.getState().active, true);
  assert.equal(changes[changes.length - 1]?.revision, 3);
  lifecycle.dispose();
});

test('ignores a stale query that resolves after a newer live event', async () => {
  const create = requireLifecycle();
  const bus = createBus();
  const query = deferred<Snapshot>();
  const changes: ViewState[] = [];
  const lifecycle = create({
    listen: bus.listen,
    invoke: async <T,>() => query.promise as Promise<T>,
    ...noTimer(),
    onChange: (state) => changes.push(state),
  });

  const connecting = lifecycle.connect();
  await Promise.resolve();
  await Promise.resolve();
  bus.emit('dist://error', snapshot(2, 1, 'error', { error: 'offline' }));
  query.resolve(snapshot(1, 1, 'running'));
  await connecting;

  assert.equal(lifecycle.getState().revision, 2);
  assert.equal(lifecycle.getState().status, 'error');
  assert.equal(lifecycle.getState().error, 'offline');
  assert.equal(changes.filter((state) => state.revision === 1).length, 0);
  lifecycle.dispose();
});

test('cleans every fulfilled listener when one registration fails', async () => {
  const create = requireLifecycle();
  const unlistenCalls = [0, 0, 0, 0];
  const lateRegistration = deferred<Unlisten>();
  const registrations: Array<Promise<Unlisten>> = [
    Promise.resolve(() => { unlistenCalls[0] += 1; }),
    lateRegistration.promise,
    Promise.resolve(() => { unlistenCalls[2] += 1; }),
    Promise.reject(new Error('listener unavailable')),
  ];
  let listenIndex = 0;
  let queryCalls = 0;
  const lifecycle = create({
    listen: () => registrations[listenIndex++],
    invoke: async <T,>() => {
      queryCalls += 1;
      return snapshot(0, 0, 'idle') as T;
    },
    ...noTimer(),
    onChange: () => undefined,
  });

  const connecting = lifecycle.connect();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();

  assert.deepEqual(unlistenCalls, [1, 0, 1, 0]);
  assert.equal(queryCalls, 0);
  lateRegistration.resolve(() => { unlistenCalls[1] += 1; });
  await connecting;
  assert.deepEqual(unlistenCalls, [1, 1, 1, 0]);
  lifecycle.dispose();
  assert.deepEqual(unlistenCalls, [1, 1, 1, 0]);
});

test('late listener resolution after dispose unlistens exactly once', async () => {
  const create = requireLifecycle();
  const registrations: Array<ReturnType<typeof deferred<Unlisten>>> = [];
  const unlistenCalls = [0, 0, 0, 0];
  let queryCalls = 0;
  const lifecycle = create({
    listen: () => {
      const registration = deferred<Unlisten>();
      registrations.push(registration);
      return registration.promise;
    },
    invoke: async <T,>() => {
      queryCalls += 1;
      return snapshot(0, 0, 'idle') as T;
    },
    ...noTimer(),
    onChange: () => undefined,
  });

  const connecting = lifecycle.connect();
  lifecycle.dispose();
  registrations.forEach((registration, index) => {
    registration.resolve(() => { unlistenCalls[index] += 1; });
  });
  await connecting;
  lifecycle.dispose();

  assert.deepEqual(unlistenCalls, [1, 1, 1, 1]);
  assert.equal(queryCalls, 0);
});

test('StrictMode-style remount keeps only the second generation active', async () => {
  const create = requireLifecycle();
  const firstRegistrations: Array<ReturnType<typeof deferred<Unlisten>>> = [];
  const firstUnlistenCalls = [0, 0, 0, 0];
  let firstQueries = 0;
  const first = create({
    listen: () => {
      const registration = deferred<Unlisten>();
      firstRegistrations.push(registration);
      return registration.promise;
    },
    invoke: async <T,>() => {
      firstQueries += 1;
      return snapshot(1, 1, 'running') as T;
    },
    ...noTimer(),
    onChange: () => assert.fail('disposed generation changed state'),
  });
  const firstConnect = first.connect();
  first.dispose();

  const bus = createBus();
  let secondQueries = 0;
  const changes: ViewState[] = [];
  const second = create({
    listen: bus.listen,
    invoke: async <T,>() => {
      secondQueries += 1;
      return snapshot(2, 2, 'running') as T;
    },
    ...noTimer(),
    onChange: (state) => changes.push(state),
  });
  await second.connect();

  firstRegistrations.forEach((registration, index) => {
    registration.resolve(() => { firstUnlistenCalls[index] += 1; });
  });
  await firstConnect;

  assert.deepEqual(firstUnlistenCalls, [1, 1, 1, 1]);
  assert.equal(firstQueries, 0);
  assert.equal(secondQueries, 1);
  assert.equal(changes[changes.length - 1]?.revision, 2);
  for (const event of ['dist://start', 'dist://progress', 'dist://done', 'dist://error'] as EventName[]) {
    assert.equal(bus.handlerCount(event), 1);
  }
  second.dispose();
});

test('duplicate and older revisions are idempotent', async () => {
  const create = requireLifecycle();
  const bus = createBus();
  const changes: ViewState[] = [];
  const lifecycle = create({
    listen: bus.listen,
    invoke: async <T,>() => snapshot(0, 0, 'idle') as T,
    ...noTimer(),
    onChange: (state) => changes.push(state),
  });
  await lifecycle.connect();

  bus.emit('dist://start', snapshot(5, 2, 'running'));
  bus.emit('dist://done', snapshot(5, 2, 'done'));
  bus.emit('dist://error', snapshot(4, 1, 'error', { error: 'stale' }));

  assert.equal(lifecycle.getState().revision, 5);
  assert.equal(lifecycle.getState().status, 'running');
  assert.equal(changes.filter((state) => state.revision === 5).length, 1);
  lifecycle.dispose();
});

test('an old done timer cannot hide a newer run', async () => {
  const create = requireLifecycle();
  const bus = createBus();
  const scheduler = createManualScheduler();
  const lifecycle = create({
    listen: bus.listen,
    invoke: async <T,>() => snapshot(0, 0, 'idle') as T,
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
    onChange: () => undefined,
  });
  await lifecycle.connect();

  bus.emit('dist://done', snapshot(5, 1, 'done'));
  const [doneHandle] = scheduler.handles();
  assert.equal(scheduler.isActive(doneHandle), true);
  bus.emit('dist://start', snapshot(6, 2, 'running'));
  assert.equal(scheduler.isActive(doneHandle), false);
  scheduler.callback(doneHandle)?.();

  assert.equal(lifecycle.getState().revision, 6);
  assert.equal(lifecycle.getState().status, 'running');
  assert.equal(lifecycle.getState().active, true);
  assert.ok(scheduler.clearCallCount() >= 1);
  lifecycle.dispose();
});

test('dispose clears timers and blocks late query, event, and retry completions', async () => {
  const create = requireLifecycle();
  const pendingQueryBus = createBus();
  const pendingQuery = deferred<Snapshot>();
  const queryRequested = deferred<void>();
  const lateQueryChanges: ViewState[] = [];
  const pendingQueryLifecycle = create({
    listen: pendingQueryBus.listen,
    invoke: async <T,>() => {
      queryRequested.resolve();
      return pendingQuery.promise as Promise<T>;
    },
    ...noTimer(),
    onChange: (state) => lateQueryChanges.push(state),
  });
  const pendingConnection = pendingQueryLifecycle.connect();
  await queryRequested.promise;
  pendingQueryLifecycle.dispose();
  pendingQuery.resolve(snapshot(4, 1, 'running'));
  await pendingConnection;
  assert.equal(lateQueryChanges.length, 0);

  const bus = createBus();
  const scheduler = createManualScheduler();
  const retry = deferred<unknown>();
  const changes: ViewState[] = [];
  const lifecycle = create({
    listen: bus.listen,
    invoke: async <T,>(command: string) => {
      if (command === 'get_distribution_setup_snapshot') return snapshot(0, 0, 'idle') as T;
      return retry.promise as Promise<T>;
    },
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
    onChange: (state) => changes.push(state),
  });
  await lifecycle.connect();
  bus.emit('dist://done', snapshot(5, 1, 'done'));
  const [doneHandle] = scheduler.handles();
  const retryPromise = lifecycle.retry();
  lifecycle.dispose();
  const changesAtDispose = changes.length;

  scheduler.callback(doneHandle)?.();
  bus.emit('dist://start', snapshot(6, 2, 'running'));
  retry.resolve(undefined);
  await retryPromise;

  assert.equal(changes.length, changesAtDispose);
  assert.equal(scheduler.isActive(doneHandle), false);
});

test('retry is single-flight and allows a later retry after settlement', async () => {
  const create = requireLifecycle();
  const bus = createBus();
  const retries: Array<ReturnType<typeof deferred<unknown>>> = [];
  let retryCalls = 0;
  const lifecycle = create({
    listen: bus.listen,
    invoke: async <T,>(command: string) => {
      if (command === 'get_distribution_setup_snapshot') return snapshot(0, 0, 'idle') as T;
      assert.equal(command, 'retry_distribution_setup');
      retryCalls += 1;
      const pending = deferred<unknown>();
      retries.push(pending);
      return pending.promise as Promise<T>;
    },
    ...noTimer(),
    onChange: () => undefined,
  });
  await lifecycle.connect();

  const first = lifecycle.retry();
  const duplicate = lifecycle.retry();
  assert.equal(retryCalls, 1);
  retries[0].resolve(undefined);
  await Promise.all([first, duplicate]);

  const second = lifecycle.retry();
  assert.equal(retryCalls, 2);
  retries[1].resolve(undefined);
  await second;
  lifecycle.dispose();
});

test('mount reconciliation is read-only and never starts bootstrap', async () => {
  const create = requireLifecycle();
  const bus = createBus();
  const commands: string[] = [];
  const lifecycle = create({
    listen: bus.listen,
    invoke: async <T,>(command: string) => {
      commands.push(command);
      return snapshot(0, 0, 'idle') as T;
    },
    ...noTimer(),
    onChange: () => undefined,
  });

  await lifecycle.connect();

  assert.deepEqual(commands, ['get_distribution_setup_snapshot']);
  lifecycle.dispose();
});

test('connect is idempotent across concurrent and repeated calls', async () => {
  const create = requireLifecycle();
  const bus = createBus();
  let listenCalls = 0;
  let queryCalls = 0;
  const lifecycle = create({
    listen: async (event, handler) => {
      listenCalls += 1;
      return bus.listen(event, handler);
    },
    invoke: async <T,>() => {
      queryCalls += 1;
      return snapshot(0, 0, 'idle') as T;
    },
    ...noTimer(),
    onChange: () => undefined,
  });

  await Promise.all([lifecycle.connect(), lifecycle.connect()]);
  await lifecycle.connect();

  assert.equal(listenCalls, 4);
  assert.equal(queryCalls, 1);
  lifecycle.dispose();
});
