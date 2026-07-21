export interface MockResponse {
  value?: unknown;
  error?: string;
  delayMs?: number;
}

export interface TauriMockSeed {
  commands: Record<string, MockResponse>;
  routes: Record<string, MockResponse>;
}

export interface InvokeCall {
  command: string;
  args: Record<string, unknown>;
}

export interface ExternalOpenIntent {
  source: 'anchor' | 'window.open';
  url: string;
  target: string;
}

export interface TauriAuditState {
  calls: InvokeCall[];
  externalOpenIntents: ExternalOpenIntent[];
  unexpectedFailures: string[];
  eventSources: string[];
  registerCommand: (command: string, response: MockResponse) => void;
  registerRoute: (key: string, response: MockResponse) => void;
}

declare global {
  interface Window {
    __TAURI_AUDIT__: TauriAuditState;
    __TAURI_EVENT_PLUGIN_INTERNALS__: {
      unregisterListener: (event: string, eventId: number) => void;
    };
    __TAURI_INTERNALS__: {
      callbacks: Map<number, (data: unknown) => unknown>;
      convertFileSrc: (filePath: string, protocol?: string) => string;
      invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
      metadata: {
        currentWindow: { label: string };
        currentWebview: { windowLabel: string; label: string };
      };
      runCallback: (id: number, data: unknown) => unknown;
      transformCallback: (callback?: (data: unknown) => unknown, once?: boolean) => number;
      unregisterCallback: (id: number) => void;
    };
  }
}

export function installTauriIpcMock(seed: TauriMockSeed): void {
  const commands = new Map(Object.entries(seed.commands));
  const routes = new Map(Object.entries(seed.routes));
  const callbacks = new Map<number, (data: unknown) => unknown>();
  let nextCallbackId = 1;

  const clone = <T>(value: T): T => {
    if (value === undefined || value === null) return value;
    return JSON.parse(JSON.stringify(value)) as T;
  };

  const audit: TauriAuditState = {
    calls: [],
    externalOpenIntents: [],
    unexpectedFailures: [],
    eventSources: [],
    registerCommand: (command, response) => commands.set(command, clone(response)),
    registerRoute: (key, response) => routes.set(key, clone(response)),
  };

  const rejectUnexpected = (message: string): never => {
    audit.unexpectedFailures.push(message);
    throw new Error(message);
  };

  const resolveResponse = async (response: MockResponse): Promise<unknown> => {
    const delayMs = Math.max(0, Number(response.delayMs || 0));
    if (delayMs) await new Promise((resolve) => window.setTimeout(resolve, delayMs));
    if (response.error) throw new Error(response.error);
    return clone(response.value);
  };

  const invoke = async (command: string, args: Record<string, unknown> = {}): Promise<unknown> => {
    audit.calls.push({ command, args: clone(args) });

    if (command === 'proxy_request') {
      const method = String(args.method || 'GET').toUpperCase();
      const path = String(args.path || '');
      const key = `${method} ${path}`;
      const pathWithoutQuery = path.split('?', 1)[0];
      const response = routes.get(key) ?? routes.get(`${method} ${pathWithoutQuery}?*`);
      if (response === undefined) return rejectUnexpected(`Unregistered Tauri proxy route: ${key}`);
      return JSON.stringify(await resolveResponse(response));
    }

    const response = commands.get(command);
    if (response === undefined) return rejectUnexpected(`Unregistered Tauri invoke command: ${command}`);
    return resolveResponse(response);
  };

  const transformCallback = (callback?: (data: unknown) => unknown, once = false): number => {
    const id = nextCallbackId;
    nextCallbackId += 1;
    callbacks.set(id, (data) => {
      if (once) callbacks.delete(id);
      return callback?.(data);
    });
    return id;
  };

  class LocalEventSource extends EventTarget {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSED = 2;
    readonly CONNECTING = 0;
    readonly OPEN = 1;
    readonly CLOSED = 2;
    readonly url: string;
    readonly withCredentials = false;
    readyState = LocalEventSource.OPEN;
    onerror: ((event: Event) => unknown) | null = null;
    onmessage: ((event: MessageEvent) => unknown) | null = null;
    onopen: ((event: Event) => unknown) | null = null;

    constructor(url: string | URL) {
      super();
      this.url = String(url);
      audit.eventSources.push(this.url);
      queueMicrotask(() => this.onopen?.(new Event('open')));
    }

    close(): void {
      this.readyState = LocalEventSource.CLOSED;
    }
  }

  window.__TAURI_AUDIT__ = audit;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
    if (url.pathname === '/__loom_audit_stream') {
      const signal = init?.signal;
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          const close = () => {
            try { controller.close(); } catch { /* already closed */ }
          };
          if (signal?.aborted) close();
          else signal?.addEventListener('abort', close, { once: true });
        },
      });
      return Promise.resolve(new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }));
    }
    return nativeFetch(input, init);
  }) as typeof window.fetch;
  window.open = ((url?: string | URL, target = '', _features = '') => {
    audit.externalOpenIntents.push({
      source: 'window.open',
      url: String(url || ''),
      target,
    });
    return null;
  }) as typeof window.open;
  window.addEventListener('click', (event) => {
    const target = event.target;
    const anchor = target instanceof Element ? target.closest<HTMLAnchorElement>('a[href]') : null;
    if (!anchor) return;
    const url = new URL(anchor.href, window.location.href);
    if (!['http:', 'https:'].includes(url.protocol) || url.origin === window.location.origin) return;
    event.preventDefault();
    audit.externalOpenIntents.push({
      source: 'anchor',
      url: url.href,
      target: anchor.target || '',
    });
  }, true);
  window.__TAURI_INTERNALS__ = {
    callbacks,
    convertFileSrc: (filePath, protocol = 'asset') => `http://${protocol}.localhost/${encodeURIComponent(filePath)}`,
    invoke,
    metadata: {
      currentWindow: { label: 'main' },
      currentWebview: { windowLabel: 'main', label: 'main' },
    },
    runCallback: (id, data) => callbacks.get(id)?.(data),
    transformCallback,
    unregisterCallback: (id) => callbacks.delete(id),
  };
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = {
    unregisterListener: (_event, eventId) => callbacks.delete(eventId),
  };
  window.EventSource = LocalEventSource as unknown as typeof EventSource;
}
