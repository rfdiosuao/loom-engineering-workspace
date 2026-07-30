import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveRefreshedModelDraft } from './agentModelConfig';

test('refreshed managed catalog replaces a removed stale model draft', () => {
  const draft = resolveRefreshedModelDraft('gpt-5.6-luna', {
    componentId: 'codex-desktop',
    supported: true,
    configured: false,
    status: 'failed',
    availableModels: ['glm-5.2-coding', 'doubao-seed-2.0-code'],
  });

  assert.equal(draft, 'glm-5.2-coding');
});

test('refreshed managed catalog preserves a still available model with canonical casing', () => {
  const draft = resolveRefreshedModelDraft('GLM-5.2-CODING', {
    componentId: 'codex-desktop',
    supported: true,
    configured: true,
    status: 'configured',
    availableModels: ['glm-5.2-coding'],
  });

  assert.equal(draft, 'glm-5.2-coding');
});

test('custom provider draft is not replaced by the previous managed catalog', () => {
  const draft = resolveRefreshedModelDraft('private-model', {
    componentId: 'claude-code',
    supported: true,
    configured: true,
    status: 'configured',
    managedBy: 'custom_provider',
    availableModels: ['old-managed-model'],
  });

  assert.equal(draft, 'private-model');
});
