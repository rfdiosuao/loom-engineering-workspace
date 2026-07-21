// Publish step: package each runtime layer from a built OpenClawFiles tree into
// a .tar.gz, compute its sha256, and emit manifest.json ready to upload to a
// GitHub Release (or any static host).
//
// Usage:
//   node scripts/dist/build-layers.mjs \
//     --source <path-to-OpenClawFiles> \
//     --out    <output-dir> \
//     --version 2.0.6 \
//     --tag    v2.0.6 \
//     [--owner you/repo]
//
// Then: gh release create <tag> <out>/*.tar.gz <out>/manifest.json
//
// Layer set is declared below. installPath is RELATIVE to the install root
// (the folder that contains OpenClawFiles) so the manifest is host-agnostic.

import fs from 'node:fs';
import path from 'node:path';
import { sha256File, tarCreate } from './dist-lib.mjs';

const LAYERS = [
  { id: 'node',             title: 'Node.js 运行时',       installPath: 'OpenClawFiles/node',                  required: true },
  { id: 'openclaw-deps',    title: 'OpenClaw 依赖',        installPath: 'OpenClawFiles/node_modules',          required: true },
  { id: 'python-runtime',   title: 'Python 运行时',        installPath: 'OpenClawFiles/_up_/python-runtime',   required: true },
  { id: 'luminode-desktop', title: '桌面控制 Agent（可选）', installPath: 'OpenClawFiles/agents/luminode-desktop', required: false },
];

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith('--')) { args[argv[i].slice(2)] = argv[i + 1]; i += 1; }
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const source = args.source;
  const out = args.out || 'dist-layers';
  const version = args.version || '0.0.0';
  const tag = args.tag || `v${version}`;
  const owner = args.owner || '<OWNER>/<REPO>';
  if (!source || !fs.existsSync(source)) {
    console.error('Error: --source must point at a built OpenClawFiles parent (the install root).');
    process.exit(1);
  }
  fs.mkdirSync(out, { recursive: true });

  const releaseBase = `https://github.com/${owner}/releases/download/${tag}/`;
  const manifest = {
    schemaVersion: 1,
    product: 'openclaw-launcher',
    version,
    tag,
    generatedAt: new Date().toISOString(),
    // Mirrors are tried in order; first to return bytes matching the pinned
    // sha256 wins. Replace/extend with your OSS/CDN. ghproxy accelerates GitHub
    // in CN. Order them fastest-first per your audience.
    mirrors: [
      `https://ghproxy.com/${releaseBase}`,
      releaseBase,
      `https://<your-oss-or-cdn>/openclaw/${tag}/`,
    ],
    layers: [],
  };

  for (const layer of LAYERS) {
    const srcDir = path.join(source, layer.installPath);
    if (!fs.existsSync(srcDir)) {
      console.warn(`skip ${layer.id}: ${srcDir} not found`);
      continue;
    }
    const file = `${layer.id}.tar.gz`;
    const outFile = path.join(out, file);
    process.stdout.write(`packaging ${layer.id} … `);
    tarCreate(srcDir, outFile);
    const sha256 = await sha256File(outFile);
    const size = fs.statSync(outFile).size;
    manifest.layers.push({ ...layer, file, sha256, size });
    console.log(`${(size / 1048576).toFixed(1)} MB  sha256=${sha256.slice(0, 12)}…`);
  }

  fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`\nWrote ${path.join(out, 'manifest.json')} (${manifest.layers.length} layers).`);
  console.log(`Next: gh release create ${tag} ${out}/*.tar.gz ${out}/manifest.json`);
}

main().catch((err) => { console.error(err); process.exit(1); });
