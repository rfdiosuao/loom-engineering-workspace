import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const launcherRoot = path.resolve(__dirname, '..', '..');
const scriptPath = path.join(launcherRoot, 'scripts', 'openclaw-image-phone.mjs');
const source = fs.readFileSync(scriptPath, 'utf8');

test('phone image CLI saves generated files into the shared local material library', () => {
  assert.match(source, /DEFAULT_OUT_DIR\s*=\s*path\.join\(PROJECT_ROOT,\s*'data',\s*'generated-images'\)/);
});

test('phone image CLI reports the shared material library directory in JSON summaries', () => {
  assert.match(source, /libraryDirectory:\s*config\.outDir/);
});

test('protected package resolves the shared data root outside _up_', () => {
  assert.match(source, /path\.basename\(resourceRoot\)\s*===\s*'_up_'/);
  assert.match(source, /path\.dirname\(resourceRoot\)/);
});

test('phone image CLI records persistent metadata sidecars', () => {
  assert.match(source, /source:\s*'cli'/);
  assert.match(source, /`\$\{filePath\}\.json`/);
});
