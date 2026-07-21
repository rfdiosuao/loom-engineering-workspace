import assert from 'node:assert/strict';
import test from 'node:test';

import { compactReadSelectors, inspectVisionActionPlan, minimalActionForPhone, visionActionEndpointForBody } from '../lib/vision-safety.mjs';

test('minimalActionForPhone normalizes waitElement and preserves resourceId', () => {
  const body = minimalActionForPhone({
    action: 'waitElement',
    resourceId: 'com.example:id/done',
    timeoutMs: 1800,
  });

  assert.equal(body.action, 'wait_element');
  assert.equal(body.resourceId, 'com.example:id/done');
  assert.equal(body.timeoutMs, 1800);
});

test('compactReadSelectors preserves direct action bodies from observe_fast', () => {
  const selectors = compactReadSelectors([
    {
      nodeId: 'node-1',
      label: 'Search',
      actionBody: {
        action: 'clickDescription',
        contentDescription: 'Search',
      },
    },
    {
      nodeId: 'node-2',
      label: 'Done',
      actionBody: {
        action: 'click_element',
        resourceId: 'com.example:id/done',
      },
    },
  ]);

  assert.equal(selectors.length, 2);
  assert.equal(selectors[0].actionBody.action, 'click_description');
  assert.equal(selectors[0].actionBody.contentDescription, 'Search');
  assert.equal(selectors[1].actionBody.action, 'click_element');
  assert.equal(selectors[1].actionBody.resourceId, 'com.example:id/done');
});

test('compactReadSelectors preserves selector refs and prefers click_ref when available', () => {
  const selectors = compactReadSelectors([
    {
      ref: 'ref_87cc51d8e03b9a25',
      nodeId: 'node-1',
      label: 'Display',
      actionBody: {
        action: 'clickText',
        ref: 'ref_87cc51d8e03b9a25',
        text: 'Display',
      },
    },
  ]);

  assert.equal(selectors.length, 1);
  assert.equal(selectors[0].ref, 'ref_87cc51d8e03b9a25');
  assert.equal(selectors[0].actionBody.action, 'click_ref');
  assert.equal(selectors[0].actionBody.ref, 'ref_87cc51d8e03b9a25');
  assert.equal(selectors[0].actionBody.targetLabel, 'Display');
  assert.equal(visionActionEndpointForBody(selectors[0].actionBody, 'observe_fast'), '/api/lumi/agent/action_fast');
});

test('click_text selectors are routed to action_fast instead of raw vision action', () => {
  const body = minimalActionForPhone({
    action: 'click_text',
    text: 'Allow',
    targetLabel: 'Allow button',
    reason: 'accept screen recording prompt',
  });

  assert.equal(body.action, 'click_text');
  assert.equal(visionActionEndpointForBody(body, 'observe_fast'), '/api/lumi/agent/action_fast');
});

test('click_text selector actions still pass through sensitive target safety', () => {
  const allowed = inspectVisionActionPlan({ action: 'click_text', text: 'Allow' });
  const blocked = inspectVisionActionPlan({ action: 'click_text', text: 'payment' });

  assert.equal(allowed.allowed, true);
  assert.equal(allowed.category, 'labeled_target');
  assert.equal(blocked.allowed, false);
  assert.equal(blocked.category, 'sensitive_target');
});

test('click_ref selector aliases use action_fast and keep safety metadata', () => {
  const body = minimalActionForPhone({
    action: 'selectorClick',
    ref: 'ref_safe_display',
    targetLabel: 'Display',
  });
  const blocked = inspectVisionActionPlan({ action: 'click_ref', ref: 'ref_danger', targetLabel: 'payment' });

  assert.equal(body.action, 'click_ref');
  assert.equal(visionActionEndpointForBody(body, 'observe_fast'), '/api/lumi/agent/action_fast');
  assert.equal(inspectVisionActionPlan(body).allowed, true);
  assert.equal(blocked.allowed, false);
  assert.equal(blocked.category, 'sensitive_target');
});

test('click_ref without target metadata stays blocked in strict vision safety mode', () => {
  const result = inspectVisionActionPlan({ action: 'click_ref', ref: 'ref_unknown_target' });

  assert.equal(result.allowed, false);
  assert.equal(result.category, 'unknown_target');
});

test('camelCase selector actions use the same safety normalization as routing', () => {
  const blocked = inspectVisionActionPlan({ action: 'clickText', text: 'payment' });

  assert.equal(blocked.allowed, false);
  assert.equal(blocked.category, 'sensitive_target');
});
