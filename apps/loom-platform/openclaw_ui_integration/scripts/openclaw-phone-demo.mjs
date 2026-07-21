#!/usr/bin/env node

import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');

function usage() {
  return `
OpenClaw phone demo wrapper

Usage:
  npm run phone:demo:shopping -- --query "拼多多 好玩又有性价比的商品"
  npm run phone:demo:read
  npm run phone:demo:game -- --goal "inspect current game/canvas screen safely"

Commands:
  shopping   Search products and collect at most 10 visible candidates
  read       Read-only screen summary with no mutations
  game       Visual fallback game/canvas inspection loop

Common options:
  --device-id <id>
  --phone-url <url>
  --phone-token <token>
  --json
`.trim();
}

function parseArgs(argv) {
  const args = {
    command: '',
    query: '',
    goal: '',
    deviceId: '',
    phoneUrl: '',
    phoneToken: '',
    json: false,
    help: false,
    passthrough: [],
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (!value || value.startsWith('--')) throw new Error(`Missing value for ${arg}`);
      i += 1;
      return value;
    };

    switch (arg) {
      case '-h':
      case '--help':
        args.help = true;
        break;
      case '--query':
        args.query = next();
        break;
      case '--goal':
        args.goal = next();
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
      case '--json':
        args.json = true;
        break;
      default:
        if (!arg.startsWith('-') && !args.command) {
          args.command = arg.toLowerCase();
        } else {
          args.passthrough.push(arg);
        }
    }
  }

  if (!args.command) args.command = 'shopping';
  return args;
}

function spawnNode(scriptPath, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [scriptPath, ...args], {
      cwd: PROJECT_ROOT,
      stdio: 'inherit',
      windowsHide: true,
    });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${path.basename(scriptPath)} exited with code ${code}`));
    });
  });
}

function commonArgs(args) {
  const result = [];
  if (args.deviceId) result.push('--device-id', args.deviceId);
  if (args.phoneUrl) result.push('--phone-url', args.phoneUrl);
  if (args.phoneToken) result.push('--phone-token', args.phoneToken);
  if (args.json) result.push('--json');
  return result;
}

async function runShopping(args) {
  const query = (args.query || '拼多多 好玩又有性价比的商品').trim();
  const prompt = [
    `Search for ${query}.`,
    'Collect at most 10 visible product candidates using collect_list_items target=product.',
    'Return title, price, store, visible rating/sales if present, and why each candidate looks cost-effective.',
    'Stop after one bounded collection pass and return results to OpenClaw.',
  ].join(' ');
  await spawnNode(path.join(PROJECT_ROOT, 'scripts', 'openclaw-phone-agent.mjs'), [
    'run',
    '--mode',
    'safe',
    '--prompt',
    prompt,
    ...commonArgs(args),
    ...args.passthrough,
  ]);
}

async function runRead(args) {
  const prompt = [
    '读取当前手机屏幕。',
    '不要点击、输入、滑动或切换 App。',
    '用中文说明当前页面标题、所在应用和三个最明显的可见入口，然后结束。',
  ].join(' ');
  await spawnNode(path.join(PROJECT_ROOT, 'scripts', 'openclaw-phone-agent.mjs'), [
    'run',
    '--mode',
    'observe',
    '--prompt',
    prompt,
    ...commonArgs(args),
    ...args.passthrough,
  ]);
}

async function runGame(args) {
  const goal = (args.goal || 'inspect the current game/canvas screen safely').trim();
  await spawnNode(path.join(PROJECT_ROOT, 'scripts', 'openclaw-phone-game.mjs'), [
    'run',
    '--goal',
    goal,
    ...commonArgs(args),
    ...args.passthrough,
  ]);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }

  if (args.command === 'shopping') {
    await runShopping(args);
    return;
  }

  if (args.command === 'read') {
    await runRead(args);
    return;
  }

  if (args.command === 'game') {
    await runGame(args);
    return;
  }

  throw new Error(`Unknown command: ${args.command}`);
}

main().catch((error) => {
  console.error(`ERROR: ${error?.message || error}`);
  process.exitCode = 1;
});
