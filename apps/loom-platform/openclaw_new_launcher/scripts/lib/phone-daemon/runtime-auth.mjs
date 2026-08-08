import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { normalizePhoneUrl } from '../../openclaw-phone-secure.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..');
const RUNTIME_PATH = path.join(PROJECT_ROOT, 'data', '.openclaw', 'runtime', 'phone-daemon.json');

function sha256Hex(value) {
  return crypto.createHash('sha256').update(String(value || ''), 'utf8').digest('hex');
}

export async function createRuntimeState(port, identity = {}) {
  const accountId = String(identity.accountId || '').trim();
  const configDigest = String(identity.configDigest || '').trim();
  if (!accountId || !/^[a-f0-9]{64}$/i.test(configDigest)) {
    const error = new Error('phone_daemon_runtime_authorization_required');
    error.code = 'phone_daemon_runtime_authorization_required';
    throw error;
  }
  const runtime = {
    schema: 'loom.phone_daemon.runtime.v1',
    pid: process.pid,
    port,
    token: crypto.randomBytes(32).toString('base64url'),
    accountId,
    configDigest: configDigest.toLowerCase(),
    startedAt: new Date().toISOString(),
  };
  await fs.mkdir(path.dirname(RUNTIME_PATH), { recursive: true });
  await fs.writeFile(
    RUNTIME_PATH,
    `${JSON.stringify(runtime, null, 2)}\n`,
    { encoding: 'utf8', mode: 0o600 },
  );
  return runtime;
}

export async function readRuntimeState() {
  return JSON.parse(await fs.readFile(RUNTIME_PATH, 'utf8'));
}

export async function removeRuntimeStateIfOwned(runtime) {
  try {
    const current = await readRuntimeState();
    if (current?.pid !== runtime?.pid || current?.token !== runtime?.token) return false;
    await fs.unlink(RUNTIME_PATH);
    return true;
  } catch {
    return false;
  }
}

export function daemonAuthHeaders(runtime) {
  return { 'X-LOOM-PHONE-DAEMON-TOKEN': runtime?.token || '' };
}

export function isAuthorized(request, runtime) {
  if (!runtime?.token) return false;
  const provided = request?.headers?.['x-loom-phone-daemon-token'];
  if (typeof provided !== 'string') return false;
  const expectedBytes = Buffer.from(runtime.token, 'utf8');
  const providedBytes = Buffer.from(provided, 'utf8');
  return (
    expectedBytes.length === providedBytes.length
    && crypto.timingSafeEqual(expectedBytes, providedBytes)
  );
}

export function authorizedConfigForRequest(requestConfig, authorizedStore) {
  const request = requestConfig && typeof requestConfig === 'object'
    ? { ...requestConfig }
    : {};
  const devices = Array.isArray(authorizedStore?.devices) ? authorizedStore.devices : [];
  const requestedDeviceId = String(
    request.deviceId
    || authorizedStore?.selectedDeviceId
    || (devices.length === 1 ? devices[0]?.id : '')
    || '',
  ).trim();
  const authorizedDevice = devices.find((device) => (
    String(device?.id || '').trim() === requestedDeviceId
  ));
  if (!authorizedDevice) {
    const error = new Error('phone_daemon_device_unauthorized');
    error.code = 'phone_daemon_device_unauthorized';
    error.errorCode = error.code;
    error.retryable = false;
    error.details = { deviceId: requestedDeviceId };
    throw error;
  }

  for (const key of [
    'id',
    'baseUrl',
    'phoneUrl',
    'token',
    'phoneToken',
    'launcherId',
    'lumiLauncherId',
    'launcherSecret',
    'lumiLauncherSecret',
    'album',
    'tags',
    'priority',
    'source',
  ]) {
    delete request[key];
  }
  return {
    ...request,
    id: authorizedDevice.id,
    deviceId: authorizedDevice.id,
    phoneUrl: authorizedDevice.phoneUrl,
    phoneToken: authorizedDevice.phoneToken,
    lumiLauncherId: authorizedDevice.lumiLauncherId || '',
    lumiLauncherSecret: authorizedDevice.lumiLauncherSecret || '',
    album: authorizedDevice.album || '',
    tags: Array.isArray(authorizedDevice.tags) ? [...authorizedDevice.tags] : [],
    priority: Number(authorizedDevice.priority || 0),
    source: 'bridge-runtime',
  };
}

export function deviceKeyFromConfig(config) {
  const normalizedUrl = normalizePhoneUrl(config?.phoneUrl || '');
  const tokenHash = sha256Hex(config?.phoneToken || '');
  return sha256Hex(`${normalizedUrl}:${tokenHash}`).slice(0, 24);
}
