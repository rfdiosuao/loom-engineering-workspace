#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { normalizePhoneUrl, signedJsonRequest } from './openclaw-phone-secure.mjs';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const defaultRoot = path.resolve(scriptDir, '..');

function usage() {
  return `Usage:
  npm run openclaw:context -- --write
  node scripts/openclaw-context.mjs --root <portable-root> --write

Options:
  --root <path>          Launcher or OpenClawFiles root. Default: project root
  --device-id <id>       Optional. Select one configured APKClaw device for context defaults
  --phone-url <url>      Optional phone Agent base URL for this context refresh
  --phone-token <token>  Optional phone Agent token. Never written to context
  --phone-album <name>   Optional phone gallery album. Default: OpenClaw
  --probe                Probe /api/device/status when phone URL and token exist
  --write                Write data/.openclaw/workspace/runtime-context.json
  --json                 Print context JSON
  -h, --help             Show help
`;
}

function parseArgs(argv) {
  const args = {
    root: defaultRoot,
    deviceId: '',
    phoneUrl: process.env.OPENCLAW_PHONE_BASE_URL || '',
    phoneToken: process.env.OPENCLAW_PHONE_TOKEN || '',
    phoneAlbum: process.env.OPENCLAW_PHONE_ALBUM || 'OpenClaw',
    probe: false,
    write: false,
    json: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      i += 1;
      if (i >= argv.length) throw new Error(`Missing value for ${arg}`);
      return argv[i];
    };

    if (arg === '--root') args.root = next();
    else if (arg === '--device-id') args.deviceId = next();
    else if (arg === '--phone-url') args.phoneUrl = next();
    else if (arg === '--phone-token') args.phoneToken = next();
    else if (arg === '--phone-album') args.phoneAlbum = next();
    else if (arg === '--probe') args.probe = true;
    else if (arg === '--write') args.write = true;
    else if (arg === '--json') args.json = true;
    else if (arg === '-h' || arg === '--help') {
      process.stdout.write(usage());
      process.exit(0);
    } else {
      throw new Error(`Unknown option: ${arg}`);
    }
  }

  args.root = path.resolve(args.root);
  return args;
}

async function readJson(filePath, fallback = null) {
  try {
    return JSON.parse(await fs.readFile(filePath, 'utf8'));
  } catch {
    return fallback;
  }
}

async function pathExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function hasText(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function isConfiguredConfig(value) {
  return Boolean(value && typeof value === 'object' && Object.values(value).some(hasText));
}

async function readOpenClawVersion(root) {
  const candidates = [
    path.join(root, 'node_modules', 'openclaw', 'package.json'),
    path.join(root, 'SystemData', '.core', 'node_modules', 'openclaw', 'package.json'),
  ];
  for (const candidate of candidates) {
    const data = await readJson(candidate, null);
    if (data?.version) return String(data.version);
  }
  return 'unknown';
}

async function readPhoneConfig(root, requestedDeviceId = '') {
  const storePath = path.join(root, 'data', '.openclaw', 'launcher', 'phone-agents.json');
  const store = await readJson(storePath, {});
  const devices = Array.isArray(store?.devices) ? store.devices : [];
  if (devices.length) {
    const selected =
      (requestedDeviceId ? devices.find((device) => String(device?.id || '').trim() === requestedDeviceId) : undefined) ||
      (hasText(store?.selectedDeviceId)
        ? devices.find((device) => String(device?.id || '').trim() === String(store.selectedDeviceId).trim())
        : undefined) ||
      devices[0];
    return {
      source: storePath,
      selectedDeviceId: typeof selected?.id === 'string' ? selected.id.trim() : '',
      devices: devices.map((device) => ({
        id: hasText(device?.id) ? String(device.id).trim() : '',
        name: hasText(device?.name) ? String(device.name).trim() : '',
        tokenAvailable: hasText(device?.token),
        baseUrl: '',
        tags: Array.isArray(device?.tags)
          ? device.tags.map((tag) => String(tag || '').trim()).filter(Boolean)
          : [],
        lastSeenAt: hasText(device?.lastSeenAt) ? String(device.lastSeenAt).trim() : '',
      })),
      baseUrl: hasText(selected?.baseUrl) ? String(selected.baseUrl).trim() : '',
      tokenAvailable: hasText(selected?.token),
    };
  }

  const legacyPath = path.join(root, 'data', '.openclaw', 'launcher', 'phone-agent.json');
  const phoneConfig = await readJson(legacyPath, {});
  return {
    source: legacyPath,
    selectedDeviceId: hasText(phoneConfig?.id) ? String(phoneConfig.id).trim() : '',
    devices: hasText(phoneConfig?.baseUrl) || hasText(phoneConfig?.token)
      ? [
          {
            id: hasText(phoneConfig?.id) ? String(phoneConfig.id).trim() : '',
            name: hasText(phoneConfig?.name) ? String(phoneConfig.name).trim() : 'Android Phone',
            tokenAvailable: hasText(phoneConfig?.token),
            baseUrl: '',
            tags: [],
            lastSeenAt: '',
          },
        ]
      : [],
    baseUrl: hasText(phoneConfig?.baseUrl) ? String(phoneConfig.baseUrl).trim() : '',
    tokenAvailable: hasText(phoneConfig?.token),
  };
}

async function readDesktopConfig(root) {
  const desktopConfig = await readJson(path.join(root, 'data', '.openclaw', 'launcher', 'desktop-agent.json'), {});
  return {
    agentDir: hasText(desktopConfig?.agentDir) ? String(desktopConfig.agentDir).trim() : '',
    port: Number(desktopConfig?.port || 21900) || 21900,
    tokenAvailable: hasText(desktopConfig?.token),
    appType: hasText(desktopConfig?.appType) ? String(desktopConfig.appType).trim() : 'weixin',
  };
}

async function readPublishConfig(root) {
  const publishConfig = await readJson(path.join(root, 'data', '.openclaw', 'launcher', 'publish.json'), {});
  return {
    platformId: hasText(publishConfig?.platformId) ? String(publishConfig.platformId).trim() : 'xiaohongshu',
    transportMode: hasText(publishConfig?.transportMode) ? String(publishConfig.transportMode).trim() : 'direct',
    album: hasText(publishConfig?.phoneAlbum) ? String(publishConfig.phoneAlbum).trim() : 'OpenClaw Publish',
    selectedDeviceId: hasText(publishConfig?.selectedDeviceId) ? String(publishConfig.selectedDeviceId).trim() : '',
    reverseRelayUrl: hasText(publishConfig?.reverseRelayUrl) ? String(publishConfig.reverseRelayUrl).trim() : '',
    reverseChannelId: hasText(publishConfig?.reverseChannelId) ? String(publishConfig.reverseChannelId).trim() : '',
  };
}

async function probePhone(baseUrl, token) {
  if (!hasText(baseUrl) || !hasText(token)) return null;
  try {
    const url = `${normalizePhoneUrl(baseUrl)}/api/device/status`;
    const response = await fetch(url, {
      headers: {
        Accept: 'application/json',
        'X-AGENT-PHONE-TOKEN': token,
        'X-APKCLAW-TOKEN': token,
      },
    });
    if (response.status === 401) {
      return { ok: false, error: 'unauthorized', statusCode: 401 };
    }
    if (!response.ok) {
      return { ok: false, error: `http_${response.status}`, statusCode: response.status };
    }
    const payload = await response.json();
    const data = payload?.data && typeof payload.data === 'object' ? payload.data : payload;
    return {
      ok: true,
      statusCode: response.status,
      version: data?.version ?? null,
      versionCode: data?.versionCode ?? null,
      agentInitialized: Boolean(data?.agentInitialized),
      accessibilityRunning: Boolean(data?.accessibilityRunning),
      screenOn: data?.screenOn ?? null,
      deviceLocked: data?.deviceLocked ?? null,
    };
  } catch (error) {
    return { ok: false, error: error?.message || 'network_error' };
  }
}

async function probePhoneProfile(baseUrl, token) {
  if (!hasText(baseUrl) || !hasText(token)) return null;
  try {
    const payload = await signedJsonRequest(
      { phoneUrl: baseUrl, phoneToken: token },
      'GET',
      '/api/lumi/device/profile?includeApps=true&appLimit=40'
    );
    const data = payload?.data && typeof payload.data === 'object' ? payload.data : payload;
    return {
      ok: true,
      statusCode: 200,
      device: data?.device ?? null,
      currentScreen: data?.currentScreen ?? null,
      vision: data?.vision ?? null,
      capabilities: data?.capabilities ?? null,
    };
  } catch (error) {
    return { ok: false, error: error?.message || 'network_error' };
  }
}

async function buildContext(args) {
  const root = args.root;
  const packageJson = await readJson(path.join(root, 'package.json'), {});
  const launcherRuntime = await readJson(path.join(root, 'data', 'launcher_runtime.json'), {});
  const imageConfig = await readJson(path.join(root, 'imgapi_config.json'), {});
  const videoConfig = await readJson(path.join(root, 'video_config.json'), {});
  const phoneFileConfig = await readPhoneConfig(root, args.deviceId);
  const desktopFileConfig = await readDesktopConfig(root);
  const publishFileConfig = await readPublishConfig(root);
  const phoneUrl = args.phoneUrl || phoneFileConfig.baseUrl;
  const phoneAlbum = args.phoneAlbum || phoneFileConfig.album || 'OpenClaw';
  const tokenAvailable = hasText(args.phoneToken) || phoneFileConfig.tokenAvailable;
  const phoneProbe = args.probe ? await probePhone(phoneUrl, args.phoneToken) : null;
  const phoneProfile = args.probe ? await probePhoneProfile(phoneUrl, args.phoneToken) : null;
  const workspacePath = path.join(root, 'data', '.openclaw', 'workspace');

  return {
    schema: 'openclaw.launcher.runtime-context.v1',
    updatedAt: new Date().toISOString(),
    launcher: {
      name: 'OpenClaw Portable Launcher',
      version: String(launcherRuntime?.version || (packageJson?.name === 'openclaw-new-launcher' ? packageJson?.version : '') || 'unknown'),
      mode: 'usb-portable',
      root,
    },
    openclaw: {
      version: await readOpenClawVersion(root),
      configPath: path.join(root, 'data', '.openclaw', 'openclaw.json'),
      workspacePath,
    },
    workspace: {
      path: workspacePath,
      bootstrapFiles: ['AGENTS.md', 'SOUL.md', 'TOOLS.md', 'CAPABILITIES.md'],
      skillsPath: path.join(workspacePath, 'skills'),
    },
    paths: {
      generatedImages: path.join(root, 'data', 'generated-images'),
      phoneVideos: path.join(root, 'data', 'phone-videos'),
      scripts: path.join(root, 'scripts'),
      imageToPhoneCli: path.join(root, 'scripts', 'openclaw-image-phone.mjs'),
      phoneAgentCli: path.join(root, 'scripts', 'openclaw-phone-agent.mjs'),
      phoneFleetCli: path.join(root, 'scripts', 'openclaw-phone-fleet.mjs'),
      phoneVideoCli: path.join(root, 'scripts', 'openclaw-phone-video.mjs'),
      phonePublishCli: path.join(root, 'scripts', 'openclaw-publish-phone.mjs'),
      phoneGameCli: path.join(root, 'scripts', 'openclaw-phone-game.mjs'),
      phoneVerifier: path.join(root, 'scripts', 'verify-phone-agent.ps1'),
      coldStartBenchmarkCli: path.join(root, 'scripts', 'measure-cold-start.ps1'),
      phoneDemoCli: path.join(root, 'scripts', 'openclaw-phone-demo.mjs'),
      desktopAgentCli: path.join(root, 'scripts', 'openclaw-desktop-agent.mjs'),
    },
    capabilities: {
      imageGeneration: {
        available: true,
        configured: isConfiguredConfig(imageConfig),
        localOutputDir: path.join(root, 'data', 'generated-images'),
        cli: 'npm run phone:image',
        editCli: 'npm run phone:image:edit -- --reference-image <path> --prompt "<edit instruction>"',
      },
      videoGeneration: {
        available: true,
        configured: isConfiguredConfig(videoConfig),
      },
      platformPublish: {
        available: true,
        configured: Boolean(phoneUrl && tokenAvailable) || hasText(publishFileConfig.reverseRelayUrl),
        controlPolicy: 'launcher-cli-wrapper',
        directCli: 'npm run phone:publish -- --transport direct',
        reverseCli: 'npm run phone:publish -- --transport reverse',
        consumerEndpoint: '/api/lumi/publish/execute',
        defaultPlatform: publishFileConfig.platformId,
        defaultTransport: publishFileConfig.transportMode,
        defaultAlbum: publishFileConfig.album,
        selectedDeviceId: publishFileConfig.selectedDeviceId || null,
        reverseRelayUrl: publishFileConfig.reverseRelayUrl || null,
        reverseChannelId: publishFileConfig.reverseChannelId || null,
        tokenPolicy: 'never expose token; publish through launcher CLI or reverse packet only',
      },
      phoneAgent: {
        available: true,
        configured: hasText(phoneUrl) && tokenAvailable,
        controlPolicy: 'wrapper-only',
        agentCli: 'npm run phone:agent',
        fleetCli: 'npm run phone:fleet',
        imageCli: 'npm run phone:image',
        imageEditCli: 'npm run phone:image:edit -- --reference-image <path> --prompt "<edit instruction>"',
        visionCli: 'npm run phone:vision',
        videoDownloadDir: path.join(root, 'data', 'phone-videos'),
        videoCli: 'npm run phone:video',
        publishCli: 'npm run phone:publish',
        gameModeCli: 'npm run phone:game',
        shoppingDemoCli: 'npm run phone:demo:shopping -- --query "<search query>"',
        readDemoCli: 'npm run phone:demo:read',
        gameFallbackDemoCli: 'npm run phone:demo:game -- --goal "<goal>"',
        multiDevice: phoneFileConfig.devices.length > 1,
        defaultDeviceId: phoneFileConfig.selectedDeviceId || null,
        deviceCliArg: '--device-id <id>',
        fleetTargets: '--target <id|id,id|all>',
        defaultAlbum: phoneAlbum,
        galleryPath: `Pictures/${phoneAlbum}`,
        verifiedVersion: '6.26',
        verifiedVersionCode: 860,
        maxRoundsPerTask: 60,
        tokenSource: phoneFileConfig.source ? path.relative(root, phoneFileConfig.source).replace(/\\/g, '/') : 'data/.openclaw/launcher/phone-agent.json',
        tokenPolicy: 'never expose token; use launcher CLI helpers only',
      },
      desktopAgent: {
        available: true,
        configured: Boolean(desktopFileConfig.agentDir || desktopFileConfig.tokenAvailable),
        endpoint: 'launcher-bridge',
        configPath: 'data/.openclaw/launcher/desktop-agent.json',
        tokenAvailable: desktopFileConfig.tokenAvailable,
        controlPolicy: 'bridge-only',
        agentCli: 'npm run desktop:agent',
        replyCli: 'npm run desktop:reply',
        replyPolicy: 'observe first; send only with explicit --confirmed user approval',
        tokenPolicy: 'never expose token or Luminode port; call through launcher Bridge /api/desktop-agent/*',
        tools: [
          'desktop.status',
          'desktop.health',
          'desktop.start',
          'desktop.stop',
          'desktop.screenshot',
          'desktop.click',
          'desktop.type',
          'wechat.send',
          'wechat.unread',
          'desktop.reply.observe',
          'desktop.reply.once',
        ],
      },
      portableRuntime: {
        available: true,
        preferRelativePaths: true,
        coldStartBenchmarkCli: 'npm run measure:cold-start -- --root <portable-root>',
      },
      officeSkills: {
        available: true,
        skills: [
          'openclaw-meeting-notes',
          'openclaw-weekly-report',
          'openclaw-pdf-ocr',
          'openclaw-excel-analysis',
          'openclaw-presentation-builder',
          'openclaw-file-organizer',
        ],
        skillsPath: path.join(workspacePath, 'skills'),
      },
    },
    phone: {
      configured: hasText(phoneUrl) && tokenAvailable,
      connected: Boolean(phoneProbe?.ok),
      endpoint: 'launcher-cli-wrapper',
      baseUrl: null,
      tokenAvailable,
      configPath: phoneFileConfig.source ? path.relative(root, phoneFileConfig.source).replace(/\\/g, '/') : 'data/.openclaw/launcher/phone-agent.json',
      defaultDeviceId: phoneFileConfig.selectedDeviceId || null,
      devices: phoneFileConfig.devices,
      lastStatus: phoneProbe,
      lastProfile: phoneProfile,
      visionRecommended: phoneProfile?.vision?.recommended ?? null,
      visionMode: phoneProfile?.vision?.mode ?? null,
      visionReason: phoneProfile?.vision?.reason ?? null,
      visionConfidence: phoneProfile?.vision?.confidence ?? null,
      currentScreenPackage: phoneProfile?.currentScreen?.packageName ?? null,
    },
    desktop: {
      configured: Boolean(desktopFileConfig.agentDir || desktopFileConfig.tokenAvailable),
      endpoint: 'launcher-bridge',
      appType: desktopFileConfig.appType,
      agentDir: desktopFileConfig.agentDir || null,
      tokenAvailable: desktopFileConfig.tokenAvailable,
      configPath: 'data/.openclaw/launcher/desktop-agent.json',
    },
    policies: {
      autoSendGeneratedImagesToPhone: 'enabled_when_phone_configured',
      autoUploadPersonalFiles: false,
      screenRecordingRequiresExplicitIntent: true,
      neverExposeSecrets: true,
    },
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const context = await buildContext(args);
  const outputPath = path.join(args.root, 'data', '.openclaw', 'workspace', 'runtime-context.json');

  if (args.write) {
    await fs.mkdir(path.dirname(outputPath), { recursive: true });
    await fs.writeFile(outputPath, `${JSON.stringify(context, null, 2)}\n`, 'utf8');
  }

  if (args.json || !args.write) {
    process.stdout.write(`${JSON.stringify(context, null, 2)}\n`);
  } else {
    process.stdout.write(`Wrote ${outputPath}\n`);
  }
}

main().catch((error) => {
  console.error(error?.message || error);
  process.exit(1);
});
