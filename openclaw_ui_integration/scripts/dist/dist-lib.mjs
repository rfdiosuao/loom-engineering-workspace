// Distribution toolkit core — zero npm deps (Node built-ins + system `tar`).
//
// This is the REFERENCE implementation of the layered download/verify/atomic-
// install logic. The same algorithm is what the Rust bootstrap (OpenClaw.exe)
// should implement for the <100MB online installer, because Node itself is a
// downloaded layer (chicken-and-egg: can't use Node to fetch Node). For layers
// that download AFTER node exists (deps / luminode), this script can run as-is
// via the bundled node.
//
// Security model (the one thing that must not be skipped):
//   - Every archive is verified against the sha256 pinned in the manifest.
//   - Mirrors only provide SPEED, never TRUST. A mirror that returns wrong
//     bytes fails verification and we fall through to the next mirror.
//   - The manifest itself must be fetched over verified HTTPS (or signed);
//     see verifyManifestTrust() and DISTRIBUTION.md.

import crypto from 'node:crypto';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';
import http from 'node:http';
import { spawnSync } from 'node:child_process';
import { pipeline } from 'node:stream/promises';

export function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('error', reject);
    stream.on('data', (chunk) => hash.update(chunk));
    stream.on('end', () => resolve(hash.digest('hex')));
  });
}

// Create a .tar.gz of `srcDir` using the system tar. The `-f` argument is kept
// relative (cwd = output dir) so Windows GNU tar doesn't read "C:\…" as a
// remote host:path; works the same with the Windows built-in bsdtar.
export function tarCreate(srcDir, outFile) {
  const parent = path.dirname(path.resolve(srcDir));
  const base = path.basename(path.resolve(srcDir));
  const outAbs = path.resolve(outFile);
  fs.mkdirSync(path.dirname(outAbs), { recursive: true });
  const res = spawnSync('tar', ['-czf', path.basename(outAbs), '-C', parent, base], {
    cwd: path.dirname(outAbs), stdio: 'pipe', encoding: 'utf8',
  });
  if (res.status !== 0) throw new Error(`tar create failed for ${srcDir}: ${res.stderr || res.error}`);
  return outFile;
}

// Extract a .tar.gz into `destParent` (the archive's top dir is preserved).
export function tarExtract(archive, destParent) {
  const archiveAbs = path.resolve(archive);
  const destAbs = path.resolve(destParent);
  fs.mkdirSync(destAbs, { recursive: true });
  const res = spawnSync('tar', ['-xzf', path.basename(archiveAbs), '-C', destAbs], {
    cwd: path.dirname(archiveAbs), stdio: 'pipe', encoding: 'utf8',
  });
  if (res.status !== 0) throw new Error(`tar extract failed for ${archive}: ${res.stderr || res.error}`);
}

// Download url -> destFile. Supports http(s) and local file:// / plain paths
// (so the same code path works for offline mirrors and tests).
export async function download(url, destFile, { timeoutMs = 60_000 } = {}) {
  fs.mkdirSync(path.dirname(destFile), { recursive: true });
  if (!/^https?:\/\//i.test(url)) {
    const src = url.startsWith('file://') ? new URL(url) : url;
    await fsp.copyFile(src, destFile);
    return destFile;
  }
  await new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, (res) => {
      if (res.statusCode && res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        download(new URL(res.headers.location, url).toString(), destFile, { timeoutMs }).then(resolve, reject);
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error(`http_${res.statusCode} for ${url}`));
        return;
      }
      pipeline(res, fs.createWriteStream(destFile)).then(resolve, reject);
    });
    req.setTimeout(timeoutMs, () => req.destroy(new Error(`timeout ${url}`)));
    req.on('error', reject);
  });
  return destFile;
}

function markerPath(installRoot, layer) {
  return path.join(installRoot, layer.installPath, '.layer.json');
}

export async function isLayerInstalled(installRoot, layer) {
  try {
    const raw = await fsp.readFile(markerPath(installRoot, layer), 'utf8');
    const marker = JSON.parse(raw);
    return marker.sha256 === layer.sha256;
  } catch {
    return false;
  }
}

// Resolve the candidate URLs for a layer across mirrors (each mirror is a base).
function layerUrls(mirrors, layer) {
  return mirrors.map((base) => base.replace(/\/?$/, '/') + layer.file);
}

// Download (trying mirrors in order), verify sha256, extract to a temp dir, then
// atomically swap into place. Throws if no mirror yields the pinned sha256.
export async function installLayer(layer, { mirrors, installRoot, cacheDir, onProgress = () => {} }) {
  if (await isLayerInstalled(installRoot, layer)) {
    onProgress({ layer: layer.id, phase: 'skip', message: 'already installed' });
    return { layer: layer.id, installed: false, skipped: true };
  }
  fs.mkdirSync(cacheDir, { recursive: true });
  const archive = path.join(cacheDir, layer.file);
  let lastError = null;
  let verified = false;
  for (const url of layerUrls(mirrors, layer)) {
    try {
      onProgress({ layer: layer.id, phase: 'download', url });
      await download(url, archive);
      const actual = await sha256File(archive);
      if (actual !== layer.sha256) {
        lastError = new Error(`sha256 mismatch from ${url}: got ${actual.slice(0, 12)}… expected ${layer.sha256.slice(0, 12)}…`);
        continue; // a mirror served wrong/corrupt bytes — try the next one
      }
      verified = true;
      onProgress({ layer: layer.id, phase: 'verified', url });
      break;
    } catch (err) {
      lastError = err;
    }
  }
  if (!verified) throw new Error(`layer ${layer.id}: no trusted source. ${lastError?.message || ''}`);

  const target = path.join(installRoot, layer.installPath);
  const stageParent = path.join(cacheDir, `stage-${layer.id}-${Date.now()}`);
  try {
    tarExtract(archive, stageParent);
    // The archive's top dir is the basename of the original installPath.
    const staged = path.join(stageParent, path.basename(layer.installPath));
    const extractedRoot = fs.existsSync(staged) ? staged : stageParent;
    // Atomic-ish swap: move old aside, move new in, write marker, drop old.
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const backup = `${target}.old-${Date.now()}`;
    if (fs.existsSync(target)) fs.renameSync(target, backup);
    fs.renameSync(extractedRoot, target);
    await fsp.writeFile(
      markerPath(installRoot, layer),
      JSON.stringify({ id: layer.id, version: layer.version || null, sha256: layer.sha256, installedAt: new Date().toISOString() }, null, 2),
    );
    if (fs.existsSync(backup)) fs.rmSync(backup, { recursive: true, force: true });
    onProgress({ layer: layer.id, phase: 'installed' });
    return { layer: layer.id, installed: true, skipped: false };
  } finally {
    fs.rmSync(stageParent, { recursive: true, force: true });
    fs.rmSync(archive, { force: true });
  }
}

export async function installFromManifest(manifest, { installRoot, cacheDir = path.join(os.tmpdir(), 'openclaw-dist-cache'), include = ['required'], onProgress = () => {} }) {
  const wantOptional = include.includes('optional');
  const layers = manifest.layers.filter((l) => l.required || (wantOptional && include.includes(l.id)) || include.includes(l.id));
  const results = [];
  for (const layer of layers) {
    results.push(await installLayer(layer, { mirrors: manifest.mirrors, installRoot, cacheDir, onProgress }));
  }
  return results;
}
