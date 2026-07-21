import crypto from 'node:crypto';
import path from 'node:path';

export function phoneFrameCacheKey(config = {}) {
  const identity = JSON.stringify({
    device: String(config.deviceId || config.phoneUrl || 'default').trim().toLowerCase().replace(/\/+$/, ''),
    format: String(config.format || 'jpeg').toLowerCase(),
    quality: Number(config.quality || 82),
    maxLongSide: Number(config.maxLongSide || 1600),
    overlayGrid: config.overlayGrid !== false,
    gridColumns: Number(config.gridColumns || 6),
    gridRows: Number(config.gridRows || 12),
  });
  return crypto.createHash('sha256').update(identity, 'utf8').digest('hex').slice(0, 16);
}

export function phoneFrameCachePath(outputDir, config = {}) {
  const extension = String(config.format || 'jpeg').toLowerCase() === 'png' ? 'png' : 'jpg';
  return path.join(outputDir, `latest-fast-frame-${phoneFrameCacheKey(config)}.${extension}`);
}

export function phoneFrameMetadataPath(cachePath) {
  return `${cachePath}.json`;
}

export function phoneFrameOutputPath(outputDir, config = {}, extension = 'jpg') {
  const safeExtension = String(extension || 'jpg').toLowerCase() === 'png' ? 'png' : 'jpg';
  return path.join(
    outputDir,
    `vision-frame-${Date.now()}-${process.pid}-${phoneFrameCacheKey(config)}.${safeExtension}`,
  );
}
