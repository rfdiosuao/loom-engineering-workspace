import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const rootDir = process.cwd();
const action = process.argv[2] || 'openai-browser';
const nodeExe = process.execPath;
const dataDir = process.env.OPENCLAW_HOME && path.basename(process.env.OPENCLAW_HOME) !== '.openclaw'
  ? process.env.OPENCLAW_HOME
  : path.join(rootDir, 'data');
const stateDir = process.env.OPENCLAW_STATE_DIR || path.join(dataDir, '.openclaw');
const configPath = process.env.OPENCLAW_CONFIG_PATH || path.join(stateDir, 'openclaw.json');
const OPENAI_OAUTH_FALLBACK_MS = process.env.OPENCLAW_OAUTH_MANUAL_FALLBACK_MS || '120000';
const OAUTH_PROXY_ENV_KEYS = [
  'OPENCLAW_OAUTH_PROXY',
  'HTTPS_PROXY',
  'HTTP_PROXY',
  'ALL_PROXY',
  'https_proxy',
  'http_proxy',
  'all_proxy',
];

function readArgValue(name) {
  const args = process.argv.slice(3);
  for (let index = 0; index < args.length; index += 1) {
    const value = args[index];
    if (value === name) return args[index + 1] || '';
    if (value.startsWith(`${name}=`)) return value.slice(name.length + 1);
  }
  return '';
}

function normalizeProxyUrl(value) {
  const trimmed = String(value || '').trim();
  if (!trimmed) return '';
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
}

function resolveOAuthProxy(env) {
  return normalizeProxyUrl(
    readArgValue('--proxy')
      || env.OPENCLAW_OAUTH_PROXY
      || env.HTTPS_PROXY
      || env.https_proxy
      || env.HTTP_PROXY
      || env.http_proxy
      || env.ALL_PROXY
      || env.all_proxy
      || '',
  );
}

function withOAuthEnv(env) {
  const proxy = resolveOAuthProxy(env);
  const next = {
    ...env,
    OPENCLAW_OAUTH_MANUAL_FALLBACK_MS: env.OPENCLAW_OAUTH_MANUAL_FALLBACK_MS || OPENAI_OAUTH_FALLBACK_MS,
  };
  if (!proxy) return next;
  return {
    ...next,
    OPENCLAW_OAUTH_PROXY: proxy,
    HTTPS_PROXY: proxy,
    HTTP_PROXY: proxy,
    ALL_PROXY: proxy,
    https_proxy: proxy,
    http_proxy: proxy,
    all_proxy: proxy,
  };
}

function firstExisting(candidates) {
  return candidates.find((candidate) => fs.existsSync(candidate)) || candidates[0];
}

function fail(message) {
  process.stderr.write(`[launcher] ${message}\n`);
  process.exit(1);
}

const openclawMjs = firstExisting([
  path.join(rootDir, 'node_modules', 'openclaw', 'openclaw.mjs'),
  path.join(rootDir, 'SystemData', '.core', 'node_modules', 'openclaw', 'openclaw.mjs'),
]);

if (!fs.existsSync(openclawMjs)) {
  fail(`OpenClaw runtime not found: ${openclawMjs}`);
}

function commandSpecForAction(selectedAction) {
  if (selectedAction === 'onboard') {
    return {
      slug: 'openclaw-onboard',
      title: 'OpenClaw onboard terminal',
      commandArgs: ['onboard'],
      intro: [
        'OpenClaw onboard will run automatically.',
        'Use this terminal to configure providers, auth, and runtime settings.',
        'Keep this window open until OpenClaw finishes saving the profile.',
      ],
    };
  }
  if (selectedAction === 'openai-device-code') {
    return {
      slug: 'openai-codex-login',
      title: 'OpenClaw OpenAI Codex login',
      commandArgs: ['models', 'auth', 'login', '--provider', 'openai', '--set-default', '--device-code'],
      intro: [
        'A browser login page should open automatically.',
        'After signing in, keep this window open until OpenClaw saves the auth profile.',
      ],
    };
  }
  if (selectedAction === 'openai-browser') {
    return {
      slug: 'openai-codex-login',
      title: 'OpenClaw OpenAI Codex login',
      commandArgs: ['models', 'auth', 'login', '--provider', 'openai', '--set-default', '--method', 'oauth'],
      intro: [
        'A browser login page should open automatically.',
        'After signing in, keep this window open until OpenClaw saves the auth profile.',
      ],
    };
  }
  fail(`Unknown auth action: ${selectedAction}`);
}

const commandSpec = commandSpecForAction(action);

function runtimeEnv() {
  const nodeDir = firstExisting([
    path.join(rootDir, 'node'),
    path.join(rootDir, 'SystemData', '.core', 'node'),
  ]);
  const binDir = firstExisting([
    path.join(rootDir, 'node_modules', '.bin'),
    path.join(rootDir, 'SystemData', '.core', 'node_modules', '.bin'),
  ]);
  const currentPath = process.env.Path || process.env.PATH || '';
  const nextPath = `${nodeDir}${path.delimiter}${binDir}${path.delimiter}${currentPath}`;
  return withOAuthEnv({
    ...process.env,
    PATH: nextPath,
    Path: nextPath,
    OPENCLAW_STATE_DIR: stateDir,
    OPENCLAW_CONFIG: configPath,
    OPENCLAW_CONFIG_PATH: configPath,
    OPENCLAW_HOME: dataDir,
    OPENCLAW_GATEWAY_PORT: process.env.OPENCLAW_GATEWAY_PORT || '18790',
    NO_COLOR: '1',
  });
}

function psQuote(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

function cmdQuote(value) {
  return `"${String(value).replace(/"/g, '""')}"`;
}

function shQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function windowsOAuthEnvLines(env) {
  return [
    `$env:OPENCLAW_OAUTH_MANUAL_FALLBACK_MS = ${psQuote(env.OPENCLAW_OAUTH_MANUAL_FALLBACK_MS || OPENAI_OAUTH_FALLBACK_MS)}`,
    ...OAUTH_PROXY_ENV_KEYS
      .filter((key) => env[key])
      .map((key) => `$env:${key} = ${psQuote(env[key])}`),
  ];
}

function unixOAuthEnvLines(env) {
  return [
    `export OPENCLAW_OAUTH_MANUAL_FALLBACK_MS=${shQuote(env.OPENCLAW_OAUTH_MANUAL_FALLBACK_MS || OPENAI_OAUTH_FALLBACK_MS)}`,
    ...OAUTH_PROXY_ENV_KEYS
      .filter((key) => env[key])
      .map((key) => `export ${key}=${shQuote(env[key])}`),
  ];
}

function tmpFile(extension) {
  const dir = path.join(stateDir, 'launcher-terminal');
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, `${commandSpec.slug}-${action}${extension}`);
}

function writeWindowsScript() {
  const scriptPath = tmpFile('.ps1');
  const env = runtimeEnv();
  const lines = [
    "$ErrorActionPreference = 'Continue'",
    `$env:OPENCLAW_STATE_DIR = ${psQuote(env.OPENCLAW_STATE_DIR)}`,
    `$env:OPENCLAW_CONFIG = ${psQuote(env.OPENCLAW_CONFIG)}`,
    `$env:OPENCLAW_CONFIG_PATH = ${psQuote(env.OPENCLAW_CONFIG_PATH)}`,
    `$env:OPENCLAW_HOME = ${psQuote(env.OPENCLAW_HOME)}`,
    `$env:OPENCLAW_GATEWAY_PORT = ${psQuote(env.OPENCLAW_GATEWAY_PORT)}`,
    `$env:NO_COLOR = ${psQuote(env.NO_COLOR)}`,
    ...windowsOAuthEnvLines(env),
    `$env:Path = ${psQuote(env.Path || env.PATH || '')}`,
    `Set-Location -LiteralPath ${psQuote(rootDir)}`,
    `Write-Host ${psQuote(commandSpec.title)}`,
    ...commandSpec.intro.map((line) => `Write-Host ${psQuote(line)}`),
    `Write-Host ${psQuote(`OpenAI OAuth proxy: ${env.OPENCLAW_OAUTH_PROXY ? 'configured' : 'not configured'}`)}`,
    `Write-Host ${psQuote(`OpenAI OAuth callback wait: ${env.OPENCLAW_OAUTH_MANUAL_FALLBACK_MS || OPENAI_OAUTH_FALLBACK_MS}ms`)}`,
    `& ${psQuote(nodeExe)} ${[openclawMjs, ...commandSpec.commandArgs].map(psQuote).join(' ')}`,
    '$exitCode = $LASTEXITCODE',
    "Write-Host ''",
    "if ($exitCode -ne 0) { Write-Host \"OpenClaw exited with code $exitCode\" -ForegroundColor Yellow }",
    "Read-Host 'Press Enter to close this window'",
    'exit $exitCode',
    '',
  ];
  fs.writeFileSync(scriptPath, lines.join('\r\n'), 'utf8');
  return scriptPath;
}

function writeUnixScript() {
  const scriptPath = tmpFile(os.platform() === 'darwin' ? '.command' : '.sh');
  const env = runtimeEnv();
  const lines = [
    '#!/bin/sh',
    `export OPENCLAW_STATE_DIR=${shQuote(env.OPENCLAW_STATE_DIR)}`,
    `export OPENCLAW_CONFIG=${shQuote(env.OPENCLAW_CONFIG)}`,
    `export OPENCLAW_CONFIG_PATH=${shQuote(env.OPENCLAW_CONFIG_PATH)}`,
    `export OPENCLAW_HOME=${shQuote(env.OPENCLAW_HOME)}`,
    `export OPENCLAW_GATEWAY_PORT=${shQuote(env.OPENCLAW_GATEWAY_PORT)}`,
    `export NO_COLOR=${shQuote(env.NO_COLOR)}`,
    ...unixOAuthEnvLines(env),
    `export PATH=${shQuote(env.PATH || '')}`,
    `cd ${shQuote(rootDir)} || exit 1`,
    `printf '%s\\n' ${shQuote(commandSpec.title)}`,
    ...commandSpec.intro.map((line) => `printf '%s\\n' ${shQuote(line)}`),
    `printf '%s\\n' ${shQuote(`OpenAI OAuth proxy: ${env.OPENCLAW_OAUTH_PROXY ? 'configured' : 'not configured'}`)}`,
    `printf '%s\\n' ${shQuote(`OpenAI OAuth callback wait: ${env.OPENCLAW_OAUTH_MANUAL_FALLBACK_MS || OPENAI_OAUTH_FALLBACK_MS}ms`)}`,
    `${shQuote(nodeExe)} ${[openclawMjs, ...commandSpec.commandArgs].map(shQuote).join(' ')}`,
    'code=$?',
    "printf '\\nOpenClaw exited with code %s\\n' \"$code\"",
    "printf '%s' 'Press Enter to close this window'",
    'read _',
    'exit "$code"',
    '',
  ];
  fs.writeFileSync(scriptPath, lines.join('\n'), 'utf8');
  fs.chmodSync(scriptPath, 0o755);
  return scriptPath;
}

function spawnDetached(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: rootDir,
    env: runtimeEnv(),
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
    ...options,
  });
  child.unref();
}

function openWindowsTerminal() {
  const scriptPath = writeWindowsScript();
  // 用 cmd 的 start 开一个独立的 PowerShell 窗口。
  // 注意:start 会把第一个带引号的参数当作"窗口标题";若标题含空格,再叠加 cmd /s 的
  // 引号处理,start 会把标题误当成要执行的文件 → "Windows 找不到文件 ...标题..."。
  // 因此这里用空标题 ""(start 的标题占位),并把参数按数组交给 spawn(由 node 负责转义,
  // 路径含空格也安全),去掉会重写引号的 /s。
  spawnDetached('cmd.exe', [
    '/c',
    'start',
    '',
    'powershell.exe',
    '-NoExit',
    '-NoProfile',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    scriptPath,
  ]);
  return scriptPath;
}

function openMacTerminal() {
  const scriptPath = writeUnixScript();
  spawnDetached('open', [scriptPath]);
  return scriptPath;
}

function openLinuxTerminal() {
  const scriptPath = writeUnixScript();
  const candidates = [
    ['x-terminal-emulator', ['-e', scriptPath]],
    ['gnome-terminal', ['--', scriptPath]],
    ['konsole', ['-e', scriptPath]],
    ['xfce4-terminal', ['-e', scriptPath]],
    ['xterm', ['-e', scriptPath]],
  ];

  for (const [command, args] of candidates) {
    try {
      spawnDetached(command, args);
      return scriptPath;
    } catch {
      // Try the next terminal emulator.
    }
  }
  fail(`No terminal emulator found. Run this script manually: ${scriptPath}`);
}

let scriptPath;
if (process.platform === 'win32') {
  scriptPath = openWindowsTerminal();
} else if (process.platform === 'darwin') {
  scriptPath = openMacTerminal();
} else {
  scriptPath = openLinuxTerminal();
}

process.stdout.write(JSON.stringify({
  ok: true,
  action,
  scriptPath,
}) + '\n');
