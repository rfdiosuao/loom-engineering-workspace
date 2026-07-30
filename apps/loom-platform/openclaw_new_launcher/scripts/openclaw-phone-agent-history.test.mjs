import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';

test('phone Agent history is partitioned by verified runtime account and session', async () => {
  const {
    appendHistory,
    historyOwnerFromVerifiedStore,
    historyPathForOwner,
    readHistory,
  } = await import('./openclaw-phone-agent.mjs');

  const ownerA = historyOwnerFromVerifiedStore({
    source: 'bridge-runtime',
    accountId: 'account-a',
    entitlementLease: {
      accountId: 'account-a',
      sessionBinding: 'session-a',
    },
  });
  const ownerB = historyOwnerFromVerifiedStore({
    source: 'bridge-runtime',
    accountId: 'account-b',
    entitlementLease: {
      accountId: 'account-b',
      sessionBinding: 'session-b',
    },
  });
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-phone-history-'));
  const basePath = path.join(root, 'phone-agent-history.jsonl');

  try {
    assert.ok(ownerA);
    assert.ok(ownerB);
    assert.notEqual(
      historyPathForOwner(ownerA, basePath),
      historyPathForOwner(ownerB, basePath),
    );

    await appendHistory(
      { command: 'run', promptPreview: 'account-a-private-prompt' },
      ownerA,
      basePath,
    );
    await appendHistory(
      { command: 'run', promptPreview: 'account-b-private-prompt' },
      ownerB,
      basePath,
    );
    await fs.writeFile(
      basePath,
      `${JSON.stringify({ promptPreview: 'legacy-ownerless-prompt' })}\n`,
      'utf8',
    );

    const rowsA = await readHistory(20, ownerA, basePath);
    const rowsB = await readHistory(20, ownerB, basePath);

    assert.deepEqual(rowsA.map((row) => row.promptPreview), ['account-a-private-prompt']);
    assert.deepEqual(rowsB.map((row) => row.promptPreview), ['account-b-private-prompt']);
    assert.equal(JSON.stringify(rowsA).includes('account-b-private-prompt'), false);
    assert.equal(JSON.stringify(rowsB).includes('account-a-private-prompt'), false);
    assert.equal(JSON.stringify(rowsA).includes('legacy-ownerless-prompt'), false);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('phone Agent history rejects unverified or incomplete runtime identity', async () => {
  const {
    historyOwnerFromVerifiedStore,
    readHistory,
  } = await import('./openclaw-phone-agent.mjs');

  assert.equal(historyOwnerFromVerifiedStore({
    source: 'disk-config',
    accountId: 'account-a',
    entitlementLease: {
      accountId: 'account-a',
      sessionBinding: 'session-a',
    },
  }), null);
  assert.equal(historyOwnerFromVerifiedStore({
    source: 'bridge-runtime',
    accountId: 'account-a',
    entitlementLease: {
      accountId: 'account-b',
      sessionBinding: 'session-a',
    },
  }), null);
  assert.equal(historyOwnerFromVerifiedStore({
    source: 'bridge-runtime',
    accountId: 'account-a',
    entitlementLease: {
      accountId: 'account-a',
      sessionBinding: '',
    },
  }), null);

  await assert.rejects(
    () => readHistory(20, null),
    /phone_history_identity_required/,
  );
});
