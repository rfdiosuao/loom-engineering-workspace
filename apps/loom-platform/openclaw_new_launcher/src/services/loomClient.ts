import {
  accountApi,
  agentApi,
  componentApi,
  diagnosticsApi,
  jobApi,
  matrixApi,
  phoneApi,
  processApi,
  realtimeApi,
  waitForProcessReady,
  wireApi,
} from './api';
import { normalizeLoomError } from './loomErrors';

async function call<T>(request: () => Promise<T>, fallback: string): Promise<T> {
  try {
    return await request();
  } catch (error) {
    throw normalizeLoomError(error, fallback);
  }
}

export const loomClient = {
  account: {
    current: () => call(() => accountApi.current(), 'Failed to read account state'),
    sendEmailCode: (params: Parameters<typeof accountApi.sendEmailCode>[0]) =>
      call(() => accountApi.sendEmailCode(params), 'Failed to send email code'),
    loginWithEmailCode: (params: Parameters<typeof accountApi.loginWithEmailCode>[0]) =>
      call(() => accountApi.loginWithEmailCode(params), 'Failed to login with email code'),
    register: (params: Parameters<typeof accountApi.register>[0]) =>
      call(() => accountApi.register(params), 'Failed to register account'),
    login: (params: Parameters<typeof accountApi.login>[0]) =>
      call(() => accountApi.login(params), 'Failed to login account'),
    bindTicket: (params: Parameters<typeof accountApi.bindTicket>[0]) =>
      call(() => accountApi.bindTicket(params), 'Failed to bind account ticket'),
    sync: () => call(() => accountApi.sync(), 'Failed to sync account models'),
    subscription: () => call(() => accountApi.subscription(), 'Failed to read subscription'),
    selectModels: (params: Parameters<typeof accountApi.selectModels>[0]) =>
      call(() => accountApi.selectModels(params), 'Failed to save model selection'),
    logout: () => call(() => accountApi.logout(), 'Failed to logout account'),
  },
  wire: {
    current: () => call(() => wireApi.current(), 'Failed to read model wire config'),
    sync: () => call(() => wireApi.sync(), 'Failed to sync model wire config'),
    custom: (params: Parameters<typeof wireApi.custom>[0]) =>
      call(() => wireApi.custom(params), 'Failed to apply custom model provider'),
    verify: () => call(() => wireApi.verify(), 'Failed to verify model wire config'),
    rollback: () => call(() => wireApi.rollback(), 'Failed to rollback model wire config'),
  },
  components: componentApi,
  diagnostics: diagnosticsApi,
  jobs: {
    get: (jobId: Parameters<typeof jobApi.get>[0]) => call(() => jobApi.get(jobId), 'Failed to read job status'),
    list: (limit?: Parameters<typeof jobApi.list>[0]) => call(() => jobApi.list(limit), 'Failed to list jobs'),
  },
  process: {
    start: () => call(() => processApi.start(), 'Failed to start local service'),
    stop: () => call(() => processApi.stop(), 'Failed to stop local service'),
    status: () => call(() => processApi.status(), 'Failed to read local service status'),
    waitForReady: (options?: Parameters<typeof waitForProcessReady>[0]) =>
      call(() => waitForProcessReady(options), 'Local service did not become ready'),
  },
  phone: phoneApi,
  agent: agentApi,
  matrix: matrixApi,
  realtime: realtimeApi,
};

export type LoomClient = typeof loomClient;
