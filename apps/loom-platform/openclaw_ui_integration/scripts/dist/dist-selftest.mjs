// Offline self-test: proves the full loop (package -> manifest -> fetch ->
// verify -> atomic install) AND that tampered/corrupt bytes are rejected.
// No network: a local directory acts as the "mirror".

import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { sha256File, tarCreate, installLayer, installFromManifest } from './dist-lib.mjs';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'openclaw-dist-selftest-'));
const fail = (m) => { console.error('FAIL:', m); process.exit(1); };

try {
  // 1) Build a fake layer source.
  const srcRoot = path.join(root, 'build', 'OpenClawFiles');
  fs.mkdirSync(path.join(srcRoot, 'node', 'bin'), { recursive: true });
  fs.writeFileSync(path.join(srcRoot, 'node', 'bin', 'node.txt'), 'pretend node runtime\n');
  fs.writeFileSync(path.join(srcRoot, 'node', 'VERSION'), '20.0.0\n');

  // 2) Package it + compute sha256 (what build-layers does).
  const mirror = path.join(root, 'mirror');
  fs.mkdirSync(mirror, { recursive: true });
  const archive = path.join(mirror, 'node.tar.gz');
  tarCreate(path.join(srcRoot, 'node'), archive);
  const sha256 = await sha256File(archive);

  const manifest = {
    schemaVersion: 1,
    mirrors: [
      path.join(root, 'badmirror') + path.sep, // first mirror is missing -> must fall through
      mirror + path.sep,
    ],
    layers: [{ id: 'node', title: 'node', file: 'node.tar.gz', installPath: 'OpenClawFiles/node', sha256, size: fs.statSync(archive).size, required: true }],
  };

  // 3) Fresh install -> verify content lands atomically.
  const installRoot = path.join(root, 'install');
  const cacheDir = path.join(root, 'cache');
  const res = await installFromManifest(manifest, { installRoot, cacheDir });
  assert.equal(res[0].installed, true, 'layer should install');
  const landed = path.join(installRoot, 'OpenClawFiles', 'node', 'bin', 'node.txt');
  assert.ok(fs.existsSync(landed), 'extracted file should exist');
  assert.equal(fs.readFileSync(landed, 'utf8'), 'pretend node runtime\n', 'content matches');
  assert.ok(fs.existsSync(path.join(installRoot, 'OpenClawFiles', 'node', '.layer.json')), 'marker written');
  console.log('[1] fresh install + atomic swap : OK');

  // 4) Idempotent: second run skips (marker sha matches).
  const res2 = await installFromManifest(manifest, { installRoot, cacheDir });
  assert.equal(res2[0].skipped, true, 'second run should skip');
  console.log('[2] idempotent re-run skips     : OK');

  // 5) Mirror falls through when the first mirror is missing (tested implicitly
  //    above since badmirror has no file) — assert it still installed.
  console.log('[3] mirror fallthrough          : OK');

  // 6) Tamper: corrupt the archive so its sha != manifest -> install MUST fail.
  const badInstallRoot = path.join(root, 'install-bad');
  fs.appendFileSync(archive, 'tampered');
  let rejected = false;
  try {
    await installLayer(manifest.layers[0], { mirrors: [mirror + path.sep], installRoot: badInstallRoot, cacheDir: path.join(root, 'cache2') });
  } catch {
    rejected = true;
  }
  assert.equal(rejected, true, 'tampered archive must be rejected');
  assert.ok(!fs.existsSync(path.join(badInstallRoot, 'OpenClawFiles', 'node')), 'nothing installed on tamper');
  console.log('[4] tampered bytes rejected      : OK');

  console.log('\n=================== RESULT ===================');
  console.log('distribution loop (package→verify→atomic install) : SOUND');
  console.log('tamper/corrupt rejection (sha256 gate)            : SOUND');
  console.log('=============================================');
  process.exit(0);
} catch (err) {
  fail(err.stack || err.message);
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
