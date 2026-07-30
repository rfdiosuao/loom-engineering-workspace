import crypto from 'node:crypto';
import fs from 'node:fs';

const {
  privateKey: TEST_ENTITLEMENT_PRIVATE_KEY,
  publicKey: TEST_ENTITLEMENT_PUBLIC_KEY,
} = crypto.generateKeyPairSync('ed25519');

export const TEST_ENTITLEMENT_PUBLIC_KEY_B64 = TEST_ENTITLEMENT_PUBLIC_KEY
  .export({ format: 'der', type: 'spki' })
  .subarray(-32)
  .toString('base64');
export const TEST_RELAY_PRODUCER_TOKEN = 'model-session-account-node-test';

function installedTestInstallId() {
  try {
    return fs.readFileSync(new URL('../../data/install_id.txt', import.meta.url), 'utf8').trim();
  } catch {
    return 'install-node-test';
  }
}

function canonicalJson(value) {
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

function sign(payload) {
  return crypto
    .sign(null, Buffer.from(canonicalJson(payload), 'utf8'), TEST_ENTITLEMENT_PRIVATE_KEY)
    .toString('base64');
}

export function authorizedPhoneRuntime(runtime, options = {}) {
  const nowSec = Number(options.nowSec || Math.floor(Date.now() / 1000));
  const entitlementExpiresAt = Number(
    options.entitlementExpiresAt || nowSec + 3600,
  );
  const entitlementOfflineGraceUntil = Number(
    options.entitlementOfflineGraceUntil || nowSec + 7200,
  );
  const phoneSeatExpiresAt = Number(
    options.phoneSeatExpiresAt || nowSec + 3600,
  );
  const accountId = String(options.accountId || 'account-node-test');
  const installId = String(
    options.installId
    || options.localInstallId
    || installedTestInstallId(),
  );
  const hostDeviceId = String(options.hostDeviceId || 'host-node-test');
  const entitlementVersion = Number(options.entitlementVersion || 1);
  const producerToken = String(
    options.producerToken || TEST_RELAY_PRODUCER_TOKEN,
  );
  const devices = Array.isArray(runtime?.devices) ? runtime.devices : [];
  const phoneDeviceIds = devices
    .map((device) => String(
      device?.entitlementDeviceId
      || device?.deviceInstanceId
      || device?.id
      || '',
    ).trim())
    .filter(Boolean);
  const entitlementLease = {
    schema: 'loom.entitlement_lease.v1',
    accountId,
    sessionBinding: crypto
      .createHash('sha256')
      .update(Buffer.concat([
        Buffer.from('loom-entitlement-session-v1\0', 'utf8'),
        Buffer.from(producerToken, 'utf8'),
      ]))
      .digest('hex'),
    installId,
    deviceId: hostDeviceId,
    hostDeviceId,
    plan: 'activated',
    source: 'authorization_code',
    features: ['matrix.devices'],
    limits: {
      devices: 1000,
      concurrentTasks: 8,
      unlimitedDevices: options.unlimitedDevices !== false,
    },
    issuedAt: nowSec - 60,
    expiresAt: entitlementExpiresAt,
    offlineGraceUntil: entitlementOfflineGraceUntil,
    entitlementVersion,
    keyId: 'openclaw-ed25519-v1',
  };
  entitlementLease.signature = sign(entitlementLease);
  const phoneSeatLease = {
    schema: 'loom.phone_seat_lease.v1',
    accountId,
    installId,
    hostDeviceId,
    phoneDeviceIds,
    limit: 1000,
    issuedAt: nowSec - 60,
    expiresAt: phoneSeatExpiresAt,
    entitlementVersion,
    keyId: 'openclaw-ed25519-v1',
  };
  phoneSeatLease.signature = sign(phoneSeatLease);
  return {
    ...runtime,
    entitlementLease,
    phoneSeatLease,
  };
}

export function phoneRuntimeTestEnv(runtime, options = {}) {
  const producerToken = String(
    options.producerToken || TEST_RELAY_PRODUCER_TOKEN,
  );
  return {
    LOOM_PHONE_RUNTIME_CONFIG_JSON: JSON.stringify(authorizedPhoneRuntime(runtime, options)),
    LOOM_PHONE_RELAY_PRODUCER_TOKEN: producerToken,
    LOOM_PHONE_RUNTIME_AUTH_TEST_ONLY: '1',
    LOOM_PHONE_RUNTIME_AUTH_TEST_PUBLIC_KEY_B64: TEST_ENTITLEMENT_PUBLIC_KEY_B64,
  };
}
