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

export async function createRuntimeState(port) {
  const runtime = {
    schema: 'loom.phone_daemon.runtime.v1',
    pid: process.pid,
    port,
    token: crypto.randomBytes(32).toString('base64url'),
    startedAt: new Date().toISOString(),
  };
  await fs.mkdir(path.dirname(RUNTIME_PATH), { recursive: true });
  await fs.writeFile(RUNTIME_PATH, `${JSON.stringify(runtime, null, 2)}\n`, 'utf8');
  return runtime;
}

export async function readRuntimeState() {
  return JSON.parse(await fs.readFile(RUNTIME_PATH, 'utf8'));
}

export function daemonAuthHeaders(runtime) {
  return { 'X-LOOM-PHONE-DAEMON-TOKEN': runtime?.token || '' };
}

export function isAuthorized(request, runtime) {
  if (!runtime?.token) return false;
  return request?.headers?.['x-loom-phone-daemon-token'] === runtime.token;
}

export function deviceKeyFromConfig(config) {
  const normalizedUrl = normalizePhoneUrl(config?.phoneUrl || '');
  const tokenHash = sha256Hex(config?.phoneToken || '');
  return sha256Hex(`${normalizedUrl}:${tokenHash}`).slice(0, 24);
}
