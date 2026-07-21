#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readLauncherPhoneConfigByDevice, uploadImageBuffer } from './openclaw-phone-secure.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const DEFAULT_IMAGE_MODEL = 'gpt-image-2';
const DEFAULT_SIZE = '1024x1024';
const DEFAULT_ALBUM = process.env.OPENCLAW_PHONE_ALBUM || 'OpenClaw';
const DEFAULT_OUT_DIR = path.join(PROJECT_ROOT, 'data', 'generated-images');
const MAX_COUNT = 4;
const REQUEST_TIMEOUT_MS = 180_000;

function usage() {
  return `
OpenClaw image-to-phone CLI

Usage:
  npm run phone:image -- --prompt "a clean product icon..."
  npm run phone:image -- --mode edit --reference-image ./input.png --prompt "make it cyberpunk"
  npm run phone:image -- --image ./output.png

Options:
  -p, --prompt <text>          Prompt for AI image generation
  -i, --image <path>           Upload an existing local image instead of generating
  --mode <generate|edit>       Image mode. Default: generate
  --reference-image <path>     Input image for image-to-image editing
  --mask <path>                Optional mask image for image editing APIs
  --image-base-url <url>       Image API base URL. Env: OPENCLAW_IMAGE_BASE_URL
  --image-api-key <key>        Image API key. Env: OPENCLAW_IMAGE_API_KEY or OPENAI_API_KEY
  --image-model <model>        Image model. Default/env: OPENCLAW_IMAGE_MODEL or ${DEFAULT_IMAGE_MODEL}
  --size <size>                Image size. Default: ${DEFAULT_SIZE}
  --count <n>                  Number of images to generate. Default: 1, max: ${MAX_COUNT}
  --out-dir <path>             Directory for generated images. Default: data/generated-images
  --device-id <id>             Optional. Select one configured APKClaw device from launcher
  --phone-url <url>            Optional. Defaults to launcher Phone Control config, then env
  --phone-token <token>        Optional. Defaults to launcher Phone Control config, then env
  --album <name>               Phone gallery album. Default: ${DEFAULT_ALBUM}
  --filename <name>            Filename to use on phone when uploading one image
  --no-upload                  Generate/save locally but do not upload to phone
  --json                       Print machine-readable JSON summary
  -h, --help                   Show help

Config fallback:
  Image API config is also read from ./imgapi_config.json when present.
`.trim();
}

function parseArgs(argv) {
  const args = {
    prompt: '',
    image: '',
    mode: 'generate',
    referenceImage: '',
    mask: '',
    imageBaseUrl: '',
    imageApiKey: '',
    imageModel: '',
    size: DEFAULT_SIZE,
    count: 1,
    outDir: DEFAULT_OUT_DIR,
    deviceId: '',
    phoneUrl: '',
    phoneToken: '',
    album: DEFAULT_ALBUM,
    filename: '',
    upload: true,
    json: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (!value || value.startsWith('--')) {
        throw new Error(`Missing value for ${arg}`);
      }
      i += 1;
      return value;
    };

    switch (arg) {
      case '-h':
      case '--help':
        args.help = true;
        break;
      case '-p':
      case '--prompt':
        args.prompt = next();
        break;
      case '-i':
      case '--image':
        args.image = next();
        break;
      case '--mode':
        args.mode = next().toLowerCase();
        break;
      case '--reference-image':
      case '--input-image':
      case '--edit-image':
        args.referenceImage = next();
        break;
      case '--mask':
        args.mask = next();
        break;
      case '--image-base-url':
        args.imageBaseUrl = next();
        break;
      case '--image-api-key':
        args.imageApiKey = next();
        break;
      case '--image-model':
        args.imageModel = next();
        break;
      case '--size':
        args.size = next();
        break;
      case '--count':
        args.count = Number.parseInt(next(), 10);
        break;
      case '--out-dir':
        args.outDir = path.resolve(next());
        break;
      case '--device-id':
        args.deviceId = next();
        break;
      case '--phone-url':
        args.phoneUrl = next();
        break;
      case '--phone-token':
        args.phoneToken = next();
        break;
      case '--album':
        args.album = next();
        break;
      case '--filename':
        args.filename = next();
        break;
      case '--no-upload':
        args.upload = false;
        break;
      case '--json':
        args.json = true;
        break;
      default:
        if (!arg.startsWith('-') && !args.prompt) {
          args.prompt = arg;
        } else {
          throw new Error(`Unknown option: ${arg}`);
        }
    }
  }

  if (!Number.isFinite(args.count) || args.count < 1) args.count = 1;
  args.count = Math.min(MAX_COUNT, Math.floor(args.count));
  if (!['generate', 'edit'].includes(args.mode)) {
    throw new Error(`Invalid --mode: ${args.mode}. Use generate or edit.`);
  }
  if (args.referenceImage && args.image) {
    throw new Error('Use either --image for direct upload or --reference-image for image editing, not both.');
  }
  if (args.referenceImage) args.mode = 'edit';
  return args;
}

async function readJsonIfExists(filePath) {
  try {
    const text = await fs.readFile(filePath, 'utf8');
    return JSON.parse(text);
  } catch (error) {
    if (error?.code === 'ENOENT') return {};
    throw new Error(`Failed to read ${filePath}: ${error.message}`);
  }
}

async function resolveConfig(args) {
  const imageConfig = await readJsonIfExists(path.join(PROJECT_ROOT, 'imgapi_config.json'));
  const launcherPhone = await readLauncherPhoneConfigByDevice(args.deviceId);
  return {
    ...args,
    imageBaseUrl: firstNonEmpty(
      args.imageBaseUrl,
      process.env.OPENCLAW_IMAGE_BASE_URL,
      imageConfig.baseUrl,
      imageConfig.url
    ),
    imageApiKey: firstNonEmpty(
      args.imageApiKey,
      process.env.OPENCLAW_IMAGE_API_KEY,
      process.env.OPENAI_API_KEY,
      imageConfig.apiKey
    ),
    imageModel: firstNonEmpty(args.imageModel, process.env.OPENCLAW_IMAGE_MODEL, imageConfig.model, DEFAULT_IMAGE_MODEL),
    phoneUrl: firstNonEmpty(args.phoneUrl, process.env.OPENCLAW_PHONE_BASE_URL, process.env.APKCLAW_BASE_URL, launcherPhone.phoneUrl),
    phoneToken: firstNonEmpty(args.phoneToken, process.env.OPENCLAW_PHONE_TOKEN, process.env.APKCLAW_TOKEN, launcherPhone.phoneToken),
    deviceId: args.deviceId || launcherPhone.id || '',
  };
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function imageGenerationEndpoint(baseUrl) {
  const clean = baseUrl.replace(/\/+$/, '');
  return clean.endsWith('/v1') ? `${clean}/images/generations` : `${clean}/v1/images/generations`;
}

function imageEditEndpoint(baseUrl) {
  const clean = baseUrl.replace(/\/+$/, '');
  return clean.endsWith('/v1') ? `${clean}/images/edits` : `${clean}/v1/images/edits`;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

async function generateImages(config) {
  if (!config.imageBaseUrl) throw new Error('Missing image API base URL. Use --image-base-url or OPENCLAW_IMAGE_BASE_URL.');
  if (!config.prompt.trim()) throw new Error('Missing prompt. Use --prompt.');

  const response = await fetchWithTimeout(imageGenerationEndpoint(config.imageBaseUrl), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(config.imageApiKey ? { Authorization: `Bearer ${config.imageApiKey}` } : {}),
    },
    body: JSON.stringify({
      model: config.imageModel || DEFAULT_IMAGE_MODEL,
      prompt: config.prompt,
      n: config.count,
      size: config.size || DEFAULT_SIZE,
    }),
  });

  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`Image API returned non-JSON response: HTTP ${response.status}`);
  }

  if (!response.ok) {
    const message = payload?.error?.message || payload?.message || `HTTP ${response.status}`;
    throw new Error(`Image generation failed: ${message}`);
  }

  const buffers = await extractImageBuffers(payload);
  if (!buffers.length) throw new Error('Image API returned no image data.');
  return buffers.slice(0, config.count);
}

async function editImages(config) {
  if (!config.imageBaseUrl) throw new Error('Missing image API base URL. Use --image-base-url or OPENCLAW_IMAGE_BASE_URL.');
  if (!config.prompt.trim()) throw new Error('Missing edit prompt. Use --prompt.');
  if (!config.referenceImage) throw new Error('Missing reference image. Use --reference-image <path>.');

  const referencePath = path.resolve(config.referenceImage);
  const body = new FormData();
  body.append('model', config.imageModel || DEFAULT_IMAGE_MODEL);
  body.append('prompt', config.prompt);
  body.append('n', String(config.count));
  body.append('size', config.size || DEFAULT_SIZE);
  body.append('image', await fileBlob(referencePath), path.basename(referencePath));

  if (config.mask) {
    const maskPath = path.resolve(config.mask);
    body.append('mask', await fileBlob(maskPath), path.basename(maskPath));
  }

  const response = await fetchWithTimeout(imageEditEndpoint(config.imageBaseUrl), {
    method: 'POST',
    headers: {
      ...(config.imageApiKey ? { Authorization: `Bearer ${config.imageApiKey}` } : {}),
    },
    body,
  });

  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`Image edit API returned non-JSON response: HTTP ${response.status}`);
  }

  if (!response.ok) {
    const message = payload?.error?.message || payload?.message || `HTTP ${response.status}`;
    throw new Error(`Image edit failed: ${message}`);
  }

  const buffers = await extractImageBuffers(payload);
  if (!buffers.length) throw new Error('Image edit API returned no image data.');
  return buffers.slice(0, config.count);
}

async function fileBlob(filePath) {
  const data = await fs.readFile(filePath);
  return new Blob([data], { type: mimeForPath(filePath) });
}

async function extractImageBuffers(payload) {
  const items = collectImageItems(payload);

  const buffers = [];
  for (const item of items) {
    if (typeof item?.b64_json === 'string' && item.b64_json.trim()) {
      buffers.push(Buffer.from(stripDataUrlPrefix(item.b64_json), 'base64'));
    } else if (typeof item?.url === 'string' && item.url.trim()) {
      const response = await fetchWithTimeout(item.url, {}, 60_000);
      if (!response.ok) throw new Error(`Failed to download generated image URL: HTTP ${response.status}`);
      buffers.push(Buffer.from(await response.arrayBuffer()));
    } else if (typeof item === 'string' && item.trim()) {
      if (/^https?:\/\//i.test(item.trim())) {
        const response = await fetchWithTimeout(item.trim(), {}, 60_000);
        if (!response.ok) throw new Error(`Failed to download generated image URL: HTTP ${response.status}`);
        buffers.push(Buffer.from(await response.arrayBuffer()));
      } else {
        buffers.push(Buffer.from(stripDataUrlPrefix(item), 'base64'));
      }
    }
  }
  return buffers;
}

function collectImageItems(payload) {
  const items = [];
  if (Array.isArray(payload?.data)) items.push(...payload.data);
  else if (payload?.data && typeof payload.data === 'object') items.push(payload.data);

  if (Array.isArray(payload?.images)) items.push(...payload.images);
  else if (payload?.images && typeof payload.images === 'object') items.push(payload.images);

  if (Array.isArray(payload?.output)) items.push(...payload.output);
  return items;
}

function stripDataUrlPrefix(value) {
  const index = value.indexOf(',');
  return value.startsWith('data:') && index >= 0 ? value.slice(index + 1) : value;
}

async function saveGeneratedImages(buffers, config) {
  await fs.mkdir(config.outDir, { recursive: true });
  const saved = [];
  const prefix = config.mode === 'edit' ? 'openclaw-image-edit' : 'openclaw-image';
  for (let i = 0; i < buffers.length; i += 1) {
    const filename = buffers.length === 1
      ? `${prefix}-${timestamp()}.png`
      : `${prefix}-${timestamp()}-${i + 1}.png`;
    const filePath = path.join(config.outDir, filename);
    await fs.writeFile(filePath, buffers[i]);
    saved.push(filePath);
  }
  return saved;
}

async function uploadImage(filePath, config, index = 0) {
  if (!config.phoneUrl) throw new Error('Missing phone URL. Use --phone-url or OPENCLAW_PHONE_BASE_URL.');
  if (!config.phoneToken) throw new Error('Missing phone token. Use --phone-token or OPENCLAW_PHONE_TOKEN.');

  const filename = config.filename && index === 0 ? sanitizeFilename(config.filename) : path.basename(filePath);
  const data = await fs.readFile(filePath);
  return uploadImageBuffer(config, data, filename, mimeForPath(filePath));
}

function mimeForPath(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.webp') return 'image/webp';
  return 'image/png';
}

function sanitizeFilename(value) {
  return value.replace(/[\\/:*?"<>|\p{C}]/gu, '_').replace(/_+/g, '_').replace(/^[_\s.]+|[_\s.]+$/g, '') || `openclaw-image-${timestamp()}.png`;
}

function timestamp() {
  return new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '').replace('T', '-');
}

function log(config, message) {
  if (!config.json) console.log(message);
}

async function main() {
  const parsed = parseArgs(process.argv.slice(2));
  if (parsed.help) {
    console.log(usage());
    return;
  }

  const config = await resolveConfig(parsed);
  const localImages = [];

  if (config.image) {
    localImages.push(path.resolve(config.image));
  } else if (config.mode === 'edit') {
    log(config, `Editing ${config.count} image(s) with ${config.imageModel || DEFAULT_IMAGE_MODEL}...`);
    const buffers = await editImages(config);
    const saved = await saveGeneratedImages(buffers, config);
    localImages.push(...saved);
    for (const filePath of saved) log(config, `Saved: ${filePath}`);
  } else {
    log(config, `Generating ${config.count} image(s) with ${config.imageModel || DEFAULT_IMAGE_MODEL}...`);
    const buffers = await generateImages(config);
    const saved = await saveGeneratedImages(buffers, config);
    localImages.push(...saved);
    for (const filePath of saved) log(config, `Saved: ${filePath}`);
  }

  const uploads = [];
  if (config.upload) {
    for (let i = 0; i < localImages.length; i += 1) {
      log(config, `Uploading to phone gallery: ${path.basename(localImages[i])}`);
      uploads.push(await uploadImage(localImages[i], config, i));
    }
  }

  const summary = {
    ok: true,
    generated: config.image ? 0 : localImages.length,
    localImages,
    uploaded: uploads.length,
    uploads,
  };

  if (config.json) {
    console.log(JSON.stringify(summary, null, 2));
  } else {
    console.log(`Done. local=${localImages.length}, uploaded=${uploads.length}`);
    for (const upload of uploads) {
      console.log(`Phone: ${upload.relativePath || upload.uri || JSON.stringify(upload)}`);
    }
  }
}

main().catch((error) => {
  console.error(`ERROR: ${error?.message || error}`);
  process.exitCode = 1;
});
