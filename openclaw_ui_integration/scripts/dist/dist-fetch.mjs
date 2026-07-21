// Runner: install layers from a manifest (the node-side counterpart of the
// Rust bootstrap; usable for layers that download AFTER node exists, e.g.
// optional on-demand layers like luminode-desktop).
//
// Usage:
//   node scripts/dist/dist-fetch.mjs \
//     --manifest <url-or-path> \
//     --install-root <dir that contains OpenClawFiles> \
//     [--include required]            # default
//     [--include required,luminode-desktop]   # also pull an optional layer
//
// SECURITY: pass a manifest from a TRUSTED source (verified HTTPS endpoint or a
// signed file). Mirrors are only for speed; layer bytes are sha256-verified.

import fs from 'node:fs';
import { download, installFromManifest } from './dist-lib.mjs';
import os from 'node:os';
import path from 'node:path';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith('--')) { args[argv[i].slice(2)] = argv[i + 1]; i += 1; }
  }
  return args;
}

async function loadManifest(ref) {
  if (/^https?:\/\//i.test(ref)) {
    const tmp = path.join(os.tmpdir(), `openclaw-manifest-${Date.now()}.json`);
    await download(ref, tmp);
    const json = JSON.parse(fs.readFileSync(tmp, 'utf8'));
    fs.rmSync(tmp, { force: true });
    return json;
  }
  return JSON.parse(fs.readFileSync(ref, 'utf8'));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.manifest || !args['install-root']) {
    console.error('Usage: dist-fetch.mjs --manifest <url|path> --install-root <dir> [--include required[,id...]]');
    process.exit(1);
  }
  const manifest = await loadManifest(args.manifest);
  const include = (args.include || 'required').split(',').map((s) => s.trim()).filter(Boolean);
  const results = await installFromManifest(manifest, {
    installRoot: args['install-root'],
    include,
    onProgress: (e) => {
      if (e.phase === 'download') process.stdout.write(`  ${e.layer}: downloading…\n`);
      else if (e.phase === 'verified') process.stdout.write(`  ${e.layer}: verified ✓\n`);
      else if (e.phase === 'installed') process.stdout.write(`  ${e.layer}: installed ✓\n`);
      else if (e.phase === 'skip') process.stdout.write(`  ${e.layer}: already present, skip\n`);
    },
  });
  const installed = results.filter((r) => r.installed).length;
  const skipped = results.filter((r) => r.skipped).length;
  console.log(`\nDone. installed=${installed} skipped=${skipped} total=${results.length}`);
}

main().catch((err) => { console.error('dist-fetch failed:', err.message); process.exit(1); });
