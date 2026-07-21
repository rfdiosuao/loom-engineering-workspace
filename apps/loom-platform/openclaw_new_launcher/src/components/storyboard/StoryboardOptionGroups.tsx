import React from 'react';
import { FieldLabel } from '../common';
import type { OptionGroup, StoryboardStep } from './storyboardSteps';
import type { StoryboardSelections } from './storyboardTypes';

interface Props {
  step: StoryboardStep;
  selections: StoryboardSelections;
  onSelectionChange: (module: StoryboardStep['module'], category: string, values: Array<string | boolean>) => void;
}

function optionsFor(group: OptionGroup): string[] {
  // Options are built into the step metadata (source of truth, always visible).
  // param-config.json only carries optional system-prompt hints per option, used
  // by the backend context builder; it does NOT decide option visibility here.
  return group.options ?? [];
}

function selectedValues(
  selections: StoryboardSelections,
  module: OptionGroup['module'],
  category: string,
): Array<string | boolean> {
  return selections[module]?.[category] ?? [];
}

function toggleArrayValue(current: Array<string | boolean>, value: string | boolean, multi: boolean): Array<string | boolean> {
  if (!multi) {
    return current.includes(value) ? [] : [value];
  }
  return current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value];
}

export const StoryboardOptionGroups: React.FC<Props> = ({ step, selections, onSelectionChange }) => {
  if (!step.optionGroups.length) {
    return null;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {step.optionGroups.map((group) => {
        const options = optionsFor(group);
        const selected = selectedValues(selections, group.module, group.category);
        if (group.control === 'dropdown') {
          return (
            <label key={group.category} className="block">
              <FieldLabel text={group.label} />
              <select
                className="w-full rounded-xl border border-border bg-input px-3 py-2 text-sm text-text"
                value={(selected[0] as string) || ''}
                onChange={(event) => onSelectionChange(group.module, group.category, event.target.value ? [event.target.value] : [])}
              >
                <option value="">请选择...</option>
                {options.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
              {group.hint ? <div className="mt-1 text-xs text-text-muted">{group.hint}</div> : null}
            </label>
          );
        }
        if (group.control === 'toggle') {
          const on = selected.includes(true);
          return (
            <div key={group.category} className="flex items-center justify-between rounded-xl border border-border bg-surface-alt/40 px-4 py-3">
              <div>
                <div className="text-sm font-semibold text-text">{group.label}</div>
                {group.hint ? <div className="mt-0.5 text-xs text-text-muted">{group.hint}</div> : null}
              </div>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => onSelectionChange(group.module, group.category, [!on])}
                className={`h-6 w-11 rounded-full transition ${on ? 'bg-accent' : 'bg-border'}`}
              >
                <span className={`block h-5 w-5 translate-x-0.5 rounded-full bg-white transition ${on ? 'translate-x-5' : ''}`} />
              </button>
            </div>
          );
        }
        if (group.control === 'radio') {
          return (
            <div key={group.category}>
              <FieldLabel text={group.label} />
              <div className="flex flex-wrap gap-2">
                {options.map((option) => {
                  const active = selected.includes(option);
                  return (
                    <button
                      key={option}
                      type="button"
                      onClick={() => onSelectionChange(group.module, group.category, toggleArrayValue(selected, option, false))}
                      className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${active ? 'border-accent bg-accent-soft text-accent' : 'border-border bg-surface text-text-muted'}`}
                    >{option}</button>
                  );
                })}
              </div>
            </div>
          );
        }
        // default: tag (multi or single)
        return (
          <div key={group.category}>
            <FieldLabel text={group.label} />
            <div className="flex flex-wrap gap-2">
              {options.map((option) => {
                const active = selected.includes(option);
                return (
                  <button
                    key={option}
                    type="button"
                    onClick={() => onSelectionChange(group.module, group.category, toggleArrayValue(selected, option, Boolean(group.multi)))}
                    className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${active ? 'border-accent bg-accent-soft text-accent' : 'border-border bg-surface text-text-muted'}`}
                  >{option}</button>
                );
              })}
            </div>
            {group.hint ? <div className="mt-1 text-xs text-text-muted">{group.hint}</div> : null}
          </div>
        );
      })}
    </div>
  );
};
