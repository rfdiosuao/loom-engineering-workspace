// One-command OpenClaw version publish: rebuild the `openclaw-deps` layer for a
// given OpenClaw version, smoke-check it, update the manifest (sha256/size/
// version), and (optionally) upload both to the GitHub release. The other
// layers (node / python-runtime / luminode) are untouched.
//
// Usage:
//   node scripts/dist/update-openclaw-layer.mjs \
//     --version 2026.6.5 \
//     --manifest ../../release/_dist-layers-v2.0.6/manifest.json \
//     --out-dir  ../../release/_dist-layers-v2.0.6 \
//     [--repo rfdiosuao/openclaw-runtime-layers --release-tag v2.0.6]   # to upload
//
// Without --repo/--release-tag it only builds + updates the manifest locally and
// prints the gh commands to run.

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { sha256File, tarCreate } from './dist-lib.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const NPM = process.platform === 'win32' ? 'npm.cmd' : 'npm';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith('--')) { args[argv[i].slice(2)] = argv[i + 1]; i += 1; }
  }
  return args;
}

function resolveRel(p) {
  return path.isAbsolute(p) ? p : path.resolve(HERE, p);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const version = args.version;
  if (!version) {
    console.error('Required: --version <e.g. 2026.6.5>');
    process.exit(1);
  }
  const manifestPath = resolveRel(args.manifest || '../../../release/_dist-layers-v2.0.6/manifest.json');
  const outDir = resolveRel(args['out-dir'] || path.dirname(manifestPath));
  const larkSpec = args.lark || '@larksuite/openclaw-lark@latest';
  const weixinSpec = args.weixin || '@tencent-weixin/openclaw-weixin@latest';

  // 1) Fresh install into a temp workdir — same flags as build-portable.ps1.
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'openclaw-deps-'));
  fs.writeFileSync(
    path.join(work, 'package.json'),
    JSON.stringify({ name: 'openclaw-runtime', version: '0.0.0', private: true }, null, 2),
  );
  console.log(`[1/5] npm install openclaw@${version} (+plugins) -> ${work}`);
  // shell:true is required on Windows — Node refuses to execFile a .cmd directly.
  execFileSync(
    NPM,
    ['install', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund', '--save-exact',
      `openclaw@${version}`, larkSpec, weixinSpec],
    { cwd: work, stdio: 'inherit', shell: true },
  );

  // 2) Smoke gate — the layout the launcher/bridge depends on must exist.
  const nm = path.join(work, 'node_modules');
  const mustExist = [
    'openclaw/openclaw.mjs',
    '@larksuite/openclaw-lark/package.json',
    '@tencent-weixin/openclaw-weixin/package.json',
  ];
  for (const rel of mustExist) {
    if (!fs.existsSync(path.join(nm, rel))) {
      throw new Error(`smoke check failed: missing node_modules/${rel} — OpenClaw layout changed, do NOT publish`);
    }
  }
  const installed = JSON.parse(fs.readFileSync(path.join(nm, 'openclaw', 'package.json'), 'utf8')).version;
  if (installed !== version) {
    throw new Error(`smoke check: installed openclaw ${installed} != requested ${version}`);
  }
  console.log(`[2/5] smoke gate OK — openclaw ${installed}, plugins present`);

  // 3) Tar the node_modules into the openclaw-deps layer.
  const tarPath = path.join(outDir, 'openclaw-deps.tar.gz');
  console.log(`[3/5] tar -> ${tarPath}`);
  tarCreate(nm, tarPath);
  const sha256 = await sha256File(tarPath);
  const size = fs.statSync(tarPath).size;
  console.log(`[3/5] sha256=${sha256.slice(0, 16)}…  size=${(size / 1048576).toFixed(1)}MB`);

  // 4) Update the manifest's openclaw-deps entry in place.
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const layer = manifest.layers.find((l) => l.id === 'openclaw-deps');
  if (!layer) throw new Error(`manifest has no openclaw-deps layer: ${manifestPath}`);
  layer.sha256 = sha256;
  layer.size = size;
  layer.version = version;
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  console.log(`[4/5] manifest updated: ${manifestPath}`);

  // 5) Upload (or print the commands).
  fs.rmSync(work, { recursive: true, force: true });
  if (args.repo && args['release-tag']) {
    console.log(`[5/5] uploading to ${args.repo} ${args['release-tag']}…`);
    execFileSync('gh', ['release', 'upload', args['release-tag'], tarPath, manifestPath,
      '--repo', args.repo, '--clobber'], { stdio: 'inherit' });
    console.log('[5/5] published ✓');
  } else {
    console.log('[5/5] local build done. To publish:');
    console.log(`  gh release upload <tag> "${tarPath}" "${manifestPath}" --repo <owner/repo> --clobber`);
  }
}

main().catch((err) => { console.error('update-openclaw-layer failed:', err.message); process.exit(1); });
