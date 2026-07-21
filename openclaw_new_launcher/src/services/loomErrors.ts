import { parseErrorText } from './api';

export class LoomClientError extends Error {
  code?: string;
  action?: string;
  detail?: unknown;

  constructor(message: string, options: { code?: string; action?: string; detail?: unknown } = {}) {
    super(message);
    this.name = 'LoomClientError';
    this.code = options.code;
    this.action = options.action;
    this.detail = options.detail;
  }
}

export function normalizeLoomError(error: unknown, fallback = 'LOOM request failed'): LoomClientError {
  if (error instanceof LoomClientError) return error;
  const record = error && typeof error === 'object' ? error as Record<string, unknown> : {};
  const message = parseErrorText(error) || parseErrorText(record.message) || parseErrorText(record.error) || fallback;
  return new LoomClientError(message, {
    code: typeof record.code === 'string' ? record.code : undefined,
    action: typeof record.action === 'string' ? record.action : undefined,
    detail: record.detail,
  });
}

export function loomErrorText(error: unknown, fallback?: string): string {
  return normalizeLoomError(error, fallback).message;
}
