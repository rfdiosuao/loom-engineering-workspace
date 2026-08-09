import assert from 'node:assert/strict';
import test from 'node:test';

import { createSingleFlight, resolvePhoneMatrixAccess } from './phoneMatrixAccess';

test('deduplicates concurrent entitlement refreshes and allows a later retry', async () => {
  let calls = 0;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const refresh = createSingleFlight(async () => {
    calls += 1;
    await gate;
    return calls;
  });

  const first = refresh();
  const duplicate = refresh();
  assert.strictEqual(duplicate, first);
  assert.equal(calls, 1);

  release();
  assert.equal(await first, 1);
  assert.equal(await duplicate, 1);
  assert.equal(await refresh(), 2);
});

test('refreshes a stale unauthorized snapshot before checking the phone feature', async () => {
  let authorized = false;
  let featureChecks = 0;

  const result = await resolvePhoneMatrixAccess({
    refreshLicense: async () => {
      authorized = true;
    },
    readLicense: () => ({ authorized }),
    checkFeature: async () => {
      featureChecks += 1;
      return { authorized: true };
    },
  });

  assert.deepEqual(result, { authorized: true, featureChecked: true });
  assert.equal(featureChecks, 1);
});

test('keeps refreshed unauthorized accounts fail-closed without checking the feature', async () => {
  let featureChecks = 0;

  const result = await resolvePhoneMatrixAccess({
    refreshLicense: async () => {},
    readLicense: () => ({ authorized: false }),
    checkFeature: async () => {
      featureChecks += 1;
      return { authorized: true };
    },
  });

  assert.deepEqual(result, { authorized: false, featureChecked: false });
  assert.equal(featureChecks, 0);
});

test('keeps an authorized license fail-closed when matrix.devices is denied', async () => {
  const result = await resolvePhoneMatrixAccess({
    refreshLicense: async () => {},
    readLicense: () => ({ authorized: true }),
    checkFeature: async () => ({ authorized: false }),
  });

  assert.deepEqual(result, { authorized: false, featureChecked: true });
});

test('propagates license refresh failures without attempting the feature check', async () => {
  let featureChecks = 0;

  await assert.rejects(
    resolvePhoneMatrixAccess({
      refreshLicense: async () => {
        throw new Error('bridge unavailable');
      },
      readLicense: () => ({ authorized: true }),
      checkFeature: async () => {
        featureChecks += 1;
        return { authorized: true };
      },
    }),
    /bridge unavailable/,
  );
  assert.equal(featureChecks, 0);
});
