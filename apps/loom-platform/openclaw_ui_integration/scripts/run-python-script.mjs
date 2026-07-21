#!/usr/bin/env node

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import process from 'node:process';

const [, , script, ...scriptArgs] = process.argv;

if (!script) {
  console.error('Usage: node scripts/run-python-script.mjs <script.py> [...args]');
  process.exit(2);
}

function uniqueCandidates(candidates) {
  const seen = new Set();
  return candidates.filter((candidate) => {
    const key = `${candidate.command}\0${candidate.args.join('\0')}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function wherePythonCandidates() {
  if (process.platform !== 'win32') return [];
  const result = spawnSync('where.exe', ['python'], { encoding: 'utf8' });
  if (result.status !== 0) return [];
  return String(result.stdout || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((command) => ({ command, args: [] }));
}

function resolvePython() {
  const candidates = uniqueCandidates([
    ...(process.env.PYTHON ? [{ command: process.env.PYTHON, args: [] }] : []),
    ...wherePythonCandidates(),
    ...(process.platform === 'win32' ? [{ command: 'py', args: ['-3'] }] : []),
    { command: 'python3', args: [] },
    { command: 'python', args: [] },
  ]);

  for (const candidate of candidates) {
    const probe = spawnSync(candidate.command, [...candidate.args, '--version'], { encoding: 'utf8' });
    if (probe.status === 0) return candidate;
  }
  return null;
}

const python = resolvePython();
if (!python) {
  console.error('Unable to find a working Python interpreter. Set PYTHON to a valid python executable.');
  process.exit(1);
}

const result = spawnSync(python.command, [...python.args, script, ...scriptArgs], { stdio: 'inherit' });
if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
