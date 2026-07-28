import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import postcss from 'postcss';
import tailwindcss from 'tailwindcss';

// @ts-expect-error The executable Tailwind JavaScript config has no declaration file.
import tailwindConfig from '../../tailwind.config.js';
import { DARK_THEME, LIGHT_THEME } from './default.ts';

type ThemeColors = typeof LIGHT_THEME.colors;

function relativeLuminance(color: string): number {
  assert.match(color, /^#[0-9a-f]{6}$/i, `contrast token must be a six-digit hex color: ${color}`);
  const channels = [1, 3, 5].map((offset) => Number.parseInt(color.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((value) => (
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  ));
  return (0.2126 * linear[0]) + (0.7152 * linear[1]) + (0.0722 * linear[2]);
}

function contrastRatio(foreground: string, background: string): number {
  const foregroundLuminance = relativeLuminance(foreground);
  const backgroundLuminance = relativeLuminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

async function compiledTailwindDeclarations(): Promise<Map<string, Map<string, string>>> {
  const result = await postcss([tailwindcss(tailwindConfig as never)]).process('@tailwind utilities;', {
    from: new URL('../styles/index.css', import.meta.url).pathname,
  });
  const rules = new Map<string, Map<string, string>>();
  result.root.walkRules((rule) => {
    for (const selector of rule.selectors) {
      const declarations = rules.get(selector) ?? new Map<string, string>();
      rule.walkDecls((declaration) => {
        declarations.set(declaration.prop, declaration.value);
      });
      rules.set(selector, declarations);
    }
  });
  return rules;
}

test('Tailwind compilation emits canonical semantic token selectors', async () => {
  const rules = await compiledTailwindDeclarations();
  const expected = [
    ['.border-info', 'border-color', 'var(--color-info-border)'],
    ['.bg-info-soft', 'background-color', 'var(--color-info-soft)'],
    ['.text-info-ink', 'color', 'var(--color-info-ink)'],
    ['.border-status-success', 'border-color', 'var(--color-success-border)'],
    ['.bg-status-success-soft', 'background-color', 'var(--color-success-soft)'],
    ['.text-status-success-ink', 'color', 'var(--color-success-ink)'],
    ['.disabled\\:text-disabled:disabled', 'color', 'var(--color-disabled-text)'],
    ['.ring-focus', '--tw-ring-color', 'var(--color-focus)'],
  ] as const;

  for (const [selector, property, value] of expected) {
    assert.equal(rules.get(selector)?.get(property), value, `${selector} must emit ${property}: ${value}`);
  }
  assert.match(rules.get('.ring-2')?.get('--tw-ring-shadow') ?? '', /\b2px\b/);
  assert.match(
    rules.get('.bg-status-danger\\/10')?.get('background-color') ?? '',
    /color-mix\(in srgb, var\(--color-danger\) 10%, transparent\)/,
  );
  for (const declarations of rules.values()) {
    for (const value of declarations.values()) assert.doesNotMatch(value, /NaN%/);
  }
});

test('light and dark semantic text pairs meet WCAG AA for normal text', () => {
  const pairs: Array<[keyof ThemeColors, keyof ThemeColors]> = [
    ['text', 'surface'],
    ['text_muted', 'surface'],
    ['text_subtle', 'surface'],
    ['disabled_text', 'disabled'],
    ['accent_ink', 'accent'],
    ['info_ink', 'info_soft'],
    ['success_ink', 'success_soft'],
    ['warning_ink', 'warning_soft'],
    ['danger_ink', 'danger_soft'],
    ['selected_ink', 'selected'],
  ];

  for (const [themeName, theme] of [['light', LIGHT_THEME], ['dark', DARK_THEME]] as const) {
    for (const [foregroundKey, backgroundKey] of pairs) {
      const ratio = contrastRatio(theme.colors[foregroundKey], theme.colors[backgroundKey]);
      assert.ok(
        ratio >= 4.5,
        `${themeName} ${foregroundKey}/${backgroundKey} contrast is ${ratio.toFixed(2)}:1`,
      );
    }
  }
});

test('UI high-risk reliability gates include the color artifact and contrast contract', () => {
  const manifest = JSON.parse(readFileSync(
    new URL('../../../../../packages/contracts/reliability-gates.v1.json', import.meta.url),
    'utf8',
  )) as {
    gates: Array<{
      id: string;
      domain: string;
      risk: string;
      command: { executable: string; arguments: string[] };
    }>;
    incidentMappings: Array<{ type: string; gateIds: string[] }>;
  };
  const gate = manifest.gates.find((candidate) => candidate.id === 'ui.color.contracts');
  const uiIncident = manifest.incidentMappings.find(
    (mapping) => mapping.type === 'ui_false_success_or_unactionable_error',
  );

  assert.ok(gate, 'missing ui.color.contracts reliability gate');
  assert.equal(gate.domain, 'ui');
  assert.equal(gate.risk, 'high');
  assert.equal(gate.command.executable, 'npm');
  assert.ok(gate.command.arguments.includes('test:ui-color-contracts'));
  assert.ok(uiIncident?.gateIds.includes('ui.color.contracts'));
});
