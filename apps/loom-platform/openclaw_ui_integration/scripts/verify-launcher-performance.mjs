import fs from 'node:fs/promises';
import path from 'node:path';
import { gzipSync } from 'node:zlib';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const args = new Map();

for (let index = 2; index < process.argv.length; index += 1) {
  const raw = process.argv[index];
  if (!raw.startsWith('--')) continue;
  const [key, inlineValue] = raw.slice(2).split('=');
  const next = process.argv[index + 1];
  if (inlineValue !== undefined) {
    args.set(key, inlineValue);
  } else if (next && !next.startsWith('--')) {
    args.set(key, next);
    index += 1;
  } else {
    args.set(key, 'true');
  }
}

const distDir = path.resolve(root, args.get('dist') || 'dist');
const maxTotalJsKb = Number(args.get('max-total-js-kb') || 900);
const maxLargestJsKb = Number(args.get('max-largest-js-kb') || 300);
const maxTotalGzipKb = Number(args.get('max-total-gzip-kb') || 320);
const reportPath = path.resolve(root, args.get('output') || path.join('data', 'logs', 'launcher-performance-smoke.json'));

async function exists(target) {
  try {
    await fs.access(target);
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
    } else {
      files.push(fullPath);
    }
  }
  return files;
}

if (!await exists(distDir)) {
  throw new Error(`dist directory not found: ${path.relative(root, distDir)}. Run npm run build first.`);
}

const files = await walk(distDir);
const assets = [];

for (const file of files) {
  const bytes = await fs.readFile(file);
  assets.push({
    file: path.relative(root, file).replaceAll('\\', '/'),
    ext: path.extname(file).toLowerCase(),
    bytes: bytes.length,
    gzipBytes: gzipSync(bytes).length,
  });
}

const jsAssets = assets.filter((asset) => asset.ext === '.js');
const cssAssets = assets.filter((asset) => asset.ext === '.css');
const totalJsBytes = jsAssets.reduce((sum, asset) => sum + asset.bytes, 0);
const totalJsGzipBytes = jsAssets.reduce((sum, asset) => sum + asset.gzipBytes, 0);
const largestJs = jsAssets.reduce((largest, asset) => (asset.bytes > largest.bytes ? asset : largest), { file: null, bytes: 0, gzipBytes: 0 });
const issues = [];

if (totalJsBytes / 1024 > maxTotalJsKb) {
  issues.push(`total JS ${(totalJsBytes / 1024).toFixed(1)}KB > ${maxTotalJsKb}KB`);
}
if (largestJs.bytes / 1024 > maxLargestJsKb) {
  issues.push(`largest JS ${(largestJs.bytes / 1024).toFixed(1)}KB > ${maxLargestJsKb}KB (${largestJs.file})`);
}
if (totalJsGzipBytes / 1024 > maxTotalGzipKb) {
  issues.push(`gzip JS ${(totalJsGzipBytes / 1024).toFixed(1)}KB > ${maxTotalGzipKb}KB`);
}

const measureScript = path.join(root, 'scripts', 'measure-cold-start.ps1');
const report = {
  verifiedAt: new Date().toISOString(),
  dist: path.relative(root, distDir).replaceAll('\\', '/'),
  budgets: {
    maxTotalJsKb,
    maxLargestJsKb,
    maxTotalGzipKb,
  },
  totals: {
    files: assets.length,
    jsFiles: jsAssets.length,
    cssFiles: cssAssets.length,
    totalJsKb: Number((totalJsBytes / 1024).toFixed(1)),
    totalJsGzipKb: Number((totalJsGzipBytes / 1024).toFixed(1)),
    totalCssKb: Number((cssAssets.reduce((sum, asset) => sum + asset.bytes, 0) / 1024).toFixed(1)),
    largestJs: {
      file: largestJs.file,
      kb: Number((largestJs.bytes / 1024).toFixed(1)),
      gzipKb: Number((largestJs.gzipBytes / 1024).toFixed(1)),
    },
  },
  coldStart: {
    scriptExists: await exists(measureScript),
    command: 'npm run measure:cold-start -- --root <portable-root> --budget-ms 30000 --output-path data/logs/cold-start.json',
  },
  issues,
};

await fs.mkdir(path.dirname(reportPath), { recursive: true });
await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

if (issues.length) {
  throw new Error(`performance smoke failed: ${issues.join('; ')}`);
}

console.log(`[performance-smoke] ok js=${report.totals.totalJsKb}KB gzip=${report.totals.totalJsGzipKb}KB largest=${report.totals.largestJs.kb}KB report=${path.relative(root, reportPath)}`);
