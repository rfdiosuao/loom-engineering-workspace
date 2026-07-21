import 'tsx/esm';

import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';

const { useAppStore } = await import('./appStore.ts');

beforeEach(() => {
  useAppStore.setState({ currentPage: 'dashboard', navigationContexts: {} });
});

test('openFeature stores context for one atomic destination consume', () => {
  const context = {
    campaignId: 'cmp_1',
    deviceId: 'P01',
    runId: 'run_1',
    source: 'agent' as const,
  };

  useAppStore.getState().openFeature('workbench', context);

  assert.equal(useAppStore.getState().currentPage, 'workbench');
  assert.deepEqual(useAppStore.getState().consumeNavigationContext('workbench'), context);
  assert.equal(useAppStore.getState().consumeNavigationContext('workbench'), null);
});

test('navigation contexts remain isolated by destination', () => {
  const matrixContext = { campaignId: 'cmp_1', source: 'agent' as const };
  const agentContext = { runId: 'run_2', source: 'matrix' as const };

  useAppStore.getState().openFeature('workbench', matrixContext);
  useAppStore.getState().openFeature('agent', agentContext);

  assert.deepEqual(useAppStore.getState().consumeNavigationContext('workbench'), matrixContext);
  assert.deepEqual(useAppStore.getState().consumeNavigationContext('agent'), agentContext);
});

test('opening a destination without context clears its stale deep link', () => {
  useAppStore.getState().openFeature('workbench', { campaignId: 'cmp_old', source: 'agent' });

  useAppStore.getState().openFeature('workbench');

  assert.equal(useAppStore.getState().currentPage, 'workbench');
  assert.equal(useAppStore.getState().consumeNavigationContext('workbench'), null);
});

test('navigation context accepts an omitted source and external entry points', () => {
  const contextWithoutSource = { campaignId: 'cmp_internal' };
  const externalContext = { runId: 'run_external', source: 'external' as const };

  useAppStore.getState().openFeature('workbench', contextWithoutSource);
  assert.deepEqual(useAppStore.getState().consumeNavigationContext('workbench'), contextWithoutSource);

  useAppStore.getState().openFeature('agent', externalContext);
  assert.deepEqual(useAppStore.getState().consumeNavigationContext('agent'), externalContext);
});
