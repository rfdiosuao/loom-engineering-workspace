#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..');
const OUT_ROOT = path.join(ROOT, 'build', 'protected-resources');
const PYTHON_OUT = path.join(OUT_ROOT, 'python');
const SCRIPTS_OUT = path.join(OUT_ROOT, 'scripts');

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    stdio: 'inherit',
  });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed with exit ${result.status}`);
  }
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function walk(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...await walk(fullPath));
    } else if (entry.isFile()) {
      files.push(fullPath);
    }
  }
  return files;
}

function shouldSkipScript(relativePath) {
  const normalized = relativePath.replaceAll('\\', '/');
  return normalized.includes('/tests/')
    || normalized.endsWith('.test.mjs')
    || normalized === 'stage-protected-release.mjs'
    || normalized === 'package-mac-complete.mjs'
    || normalized === 'package-mac-online.mjs';
}

async function stagePython() {
  const python = process.env.PYTHON || 'python';
  run(python, [
    path.join('scripts', 'stage-protected-python.py'),
    '--source',
    path.join(ROOT, 'python'),
    '--target',
    PYTHON_OUT,
  ]);
}

async function stageScripts() {
  let JavaScriptObfuscator;
  try {
    const module = await import('javascript-obfuscator');
    JavaScriptObfuscator = module.default || module;
  } catch {
    throw new Error('javascript-obfuscator is required. Run npm install before protected packaging.');
  }

  await fs.rm(SCRIPTS_OUT, { recursive: true, force: true });
  await fs.mkdir(SCRIPTS_OUT, { recursive: true });
  const files = await walk(path.join(ROOT, 'scripts'));
  let copied = 0;
  let obfuscated = 0;
  for (const filePath of files) {
    const relativePath = path.relative(path.join(ROOT, 'scripts'), filePath);
    if (shouldSkipScript(relativePath)) continue;
    const destination = path.join(SCRIPTS_OUT, relativePath);
    await fs.mkdir(path.dirname(destination), { recursive: true });
    if (filePath.endsWith('.mjs')) {
      const original = await fs.readFile(filePath, 'utf8');
      const shebang = original.startsWith('#!') ? `${original.slice(0, original.indexOf('\n')).trimEnd()}\n` : '';
      const body = shebang ? original.slice(original.indexOf('\n') + 1) : original;
      const result = JavaScriptObfuscator.obfuscate(body, {
        compact: true,
        controlFlowFlattening: false,
        deadCodeInjection: false,
        identifierNamesGenerator: 'hexadecimal',
        renameGlobals: false,
        stringArray: true,
        stringArrayThreshold: 0.25,
        target: 'node',
      });
      await fs.writeFile(destination, `${shebang}${result.getObfuscatedCode()}`, 'utf8');
      obfuscated += 1;
    } else {
      await fs.copyFile(filePath, destination);
      copied += 1;
    }
  }
  return { copied, obfuscated };
}

async function main() {
  await fs.rm(OUT_ROOT, { recursive: true, force: true });
  await fs.mkdir(OUT_ROOT, { recursive: true });
  await stagePython();
  const scripts = await stageScripts();
  const manifest = {
    schema: 'loom.protected_release.v1',
    python: await exists(path.join(PYTHON_OUT, 'loom_cli.py')),
    scripts,
  };
  await fs.writeFile(
    path.join(OUT_ROOT, 'protected-release-manifest.json'),
    `${JSON.stringify(manifest, null, 2)}\n`,
    'utf8',
  );
  console.log(JSON.stringify(manifest));
}

main().catch((error) => {
  console.error(error?.message || error);
  process.exitCode = 1;
});
