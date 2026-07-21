#!/usr/bin/env node

import path from 'node:path';
import {
  readLauncherPhoneConfigByDevice,
  uploadMediaFile,
} from './openclaw-phone-secure.mjs';

const IMAGE_MIME = Object.freeze({
  '.gif': 'image/gif',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
});

const VIDEO_MIME = Object.freeze({
  '.m4v': 'video/x-m4v',
  '.mov': 'video/quicktime',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
});

function usage() {
  return `Usage:
  node scripts/openclaw-media-phone.mjs [--device-id <id>] --image <path> [--image <path> ...] [--video <path> ...] [--json]

Uploads existing image/video files to the selected APKClaw gallery. It never submits an Agent task.`;
}

function parseArgs(argv) {
  const args = { deviceId: '', images: [], videos: [], json: false, help: false };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === '--device-id') args.deviceId = requiredValue(argv, ++index, token);
    else if (token === '--image') args.images.push(requiredValue(argv, ++index, token));
    else if (token === '--video') args.videos.push(requiredValue(argv, ++index, token));
    else if (token === '--json') args.json = true;
    else if (token === '--help' || token === '-h') args.help = true;
    else throw new Error(`Unknown option: ${token}`);
  }
  return args;
}

function requiredValue(argv, index, option) {
  const value = String(argv[index] || '').trim();
  if (!value || value.startsWith('--')) throw new Error(`${option} requires a value.`);
  return value;
}

function mimeFor(kind, filePath) {
  const extension = path.extname(filePath).toLowerCase();
  return kind === 'video'
    ? VIDEO_MIME[extension] || 'video/mp4'
    : IMAGE_MIME[extension] || 'image/png';
}

function safeErrorMessage(error, secrets) {
  let message = String(error?.message || error || 'Phone media upload failed.');
  for (const secret of secrets) {
    if (secret) message = message.split(secret).join('[redacted]');
  }
  return message.slice(0, 500);
}

function safeJson(value, secrets) {
  let serialized = JSON.stringify(value);
  for (const secret of secrets) {
    if (secret) serialized = serialized.split(secret).join('[redacted]');
  }
  return serialized;
}

function publicUpload(kind, filePath) {
  return {
    kind,
    filename: path.basename(filePath),
  };
}

function publicFailure(kind, filePath, error, secrets) {
  return {
    ...publicUpload(kind, filePath),
    errorCode: safeErrorMessage(String(error?.errorCode || error?.code || 'media_upload_failed'), secrets).slice(0, 80),
    message: safeErrorMessage(error, secrets),
  };
}

async function main() {
  let args;
  let configSecrets = [];
  try {
    args = parseArgs(process.argv.slice(2));
    if (args.help) {
      process.stdout.write(`${usage()}\n`);
      return;
    }
    const config = await readLauncherPhoneConfigByDevice(args.deviceId);
    configSecrets = [config.phoneToken, config.lumiLauncherSecret].filter(Boolean);
    const result = await uploadFiles(args, config);
    if (args.json) process.stdout.write(`${safeJson(result, configSecrets)}\n`);
    else if (result.ok) process.stdout.write(`Uploaded ${result.uploadedCount} file(s).\n`);
    else process.stderr.write(`${result.message}\n`);
    if (!result.ok) process.exitCode = 1;
  } catch (error) {
    const failure = {
      ok: false,
      errorCode: safeErrorMessage(String(error?.errorCode || error?.code || 'media_upload_failed'), configSecrets).slice(0, 80),
      message: safeErrorMessage(error, configSecrets),
    };
    if (args?.json) process.stdout.write(`${safeJson(failure, configSecrets)}\n`);
    else process.stderr.write(`${failure.message}\n`);
    process.exitCode = 1;
  }
}

async function uploadFiles(args, config) {
  if (!args.images.length && !args.videos.length) {
    throw new Error('Provide at least one --image or --video file.');
  }
  const uploads = [];
  const failed = [];
  for (const filePath of args.images) {
    try {
      await uploadMediaFile(config, filePath, path.basename(filePath), mimeFor('image', filePath), 'image');
      uploads.push(publicUpload('image', filePath));
    } catch (error) {
      failed.push(publicFailure('image', filePath, error, [config.phoneToken, config.lumiLauncherSecret]));
    }
  }
  for (const filePath of args.videos) {
    try {
      await uploadMediaFile(config, filePath, path.basename(filePath), mimeFor('video', filePath), 'video');
      uploads.push(publicUpload('video', filePath));
    } catch (error) {
      failed.push(publicFailure('video', filePath, error, [config.phoneToken, config.lumiLauncherSecret]));
    }
  }
  const totalCount = args.images.length + args.videos.length;
  if (failed.length) {
    return {
      ok: false,
      errorCode: uploads.length ? 'media_upload_partial_failure' : failed[0]?.errorCode || 'media_upload_failed',
      message: uploads.length
        ? 'Some generated media could not be imported into the phone gallery.'
        : failed[0]?.message || 'Generated media could not be imported into the phone gallery.',
      deviceId: String(config.id || args.deviceId || '').slice(0, 80),
      album: String(config.album || 'LOOM').slice(0, 80),
      uploadedCount: uploads.length,
      totalCount,
      uploaded: uploads,
      failed,
    };
  }
  return {
    ok: true,
    deviceId: String(config.id || args.deviceId || '').slice(0, 80),
    album: String(config.album || 'LOOM').slice(0, 80),
    uploadedCount: uploads.length,
    totalCount,
    uploaded: uploads,
  };
}

await main();
