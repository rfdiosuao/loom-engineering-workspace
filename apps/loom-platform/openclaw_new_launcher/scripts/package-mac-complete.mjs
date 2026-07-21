import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectDir = path.resolve(scriptDir, "..");
const repoDir = path.resolve(projectDir, "..");
const packageJson = JSON.parse(fs.readFileSync(path.join(projectDir, "package.json"), "utf8"));

function run(command, args, options = {}) {
  console.log(`$ ${[command, ...args].join(" ")}`);
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? projectDir,
    env: { ...process.env, ...(options.env ?? {}) },
    stdio: options.stdio ?? "inherit",
    encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(`${command} exited with ${result.status}`);
  }
  return result.stdout ?? "";
}

function output(command, args, options = {}) {
  return execFileSync(command, args, {
    cwd: options.cwd ?? projectDir,
    env: { ...process.env, ...(options.env ?? {}) },
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function npmView(spec, field, fallback) {
  if (process.env[`SKIP_${spec.toUpperCase().replace(/[^A-Z0-9]/g, "_")}_VIEW`]) {
    return fallback;
  }
  try {
    return output("npm", ["view", spec, field]).split(/\s+/).at(-1) || fallback;
  } catch {
    return fallback;
  }
}

function copyDir(source, target) {
  if (!fs.existsSync(source)) {
    throw new Error(`Missing source: ${source}`);
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  run("ditto", [source, target], { cwd: repoDir });
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

function writeText(filePath, value, mode) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, value);
  if (mode) {
    fs.chmodSync(filePath, mode);
  }
}

function symlinkRelative(target, linkPath) {
  fs.rmSync(linkPath, { force: true, recursive: false });
  fs.symlinkSync(target, linkPath);
}

const openclawVersion = process.env.OPENCLAW_VERSION || npmView("openclaw", "version", "2026.5.18");
const larkVersion = process.env.OPENCLAW_LARK_VERSION || npmView("@larksuite/openclaw-lark", "version", "2026.5.13");
const weixinVersion = process.env.OPENCLAW_WEIXIN_VERSION || npmView("@tencent-weixin/openclaw-weixin", "version", "2.4.3");
const nodeRuntimeVersion = process.env.NODE_RUNTIME_VERSION || "22.19.0";
const releaseDate = process.env.RELEASE_DATE || new Date().toISOString().slice(0, 10).replaceAll("-", ".");
const packageName = `OpenClaw-Mac-Complete-v${packageJson.version}-openclaw-${openclawVersion}-${releaseDate}`;
const releaseDir = path.join(repoDir, "release");
const stageDir = path.join(releaseDir, packageName);
const payloadDir = path.join(stageDir, "OpenClawFiles");
const cacheDir = path.join(releaseDir, ".cache");
const appSource = process.env.APP_SOURCE || path.join(projectDir, "src-tauri", "target", "release", "bundle", "macos", "OpenClaw.app");
const resume = process.env.OPENCLAW_RESUME === "1";
const stagedApp = path.join(stageDir, "OpenClaw.app");

if (process.platform !== "darwin" || os.arch() !== "arm64") {
  throw new Error("This packager currently builds macOS arm64 packages only.");
}
if (!fs.existsSync(appSource) && !(resume && fs.existsSync(stagedApp))) {
  throw new Error(`OpenClaw.app not found: ${appSource}`);
}

if (!resume) {
  fs.rmSync(stageDir, { recursive: true, force: true });
}
fs.mkdirSync(payloadDir, { recursive: true });

if (!resume || !fs.existsSync(stagedApp)) {
  copyDir(appSource, stagedApp);
}

if (process.env.OPENCLAW_CLEAN_TAURI_TARGET === "1") {
  fs.rmSync(path.join(projectDir, "src-tauri", "target"), { recursive: true, force: true });
}

if (!resume) {
  copyDir(path.join(projectDir, "python"), path.join(payloadDir, "_up_", "python"));
  copyDir(path.join(projectDir, "scripts"), path.join(payloadDir, "scripts"));
  copyDir(path.join(projectDir, "openclaw-workspace"), path.join(payloadDir, "openclaw-workspace"));
  copyDir(path.join(projectDir, "data", "themes"), path.join(payloadDir, "data", "themes"));
  copyDir(path.join(projectDir, "data", "themes"), path.join(payloadDir, "_up_", "data", "themes"));
  copyDir(path.join(projectDir, "openclaw-workspace"), path.join(payloadDir, "data", ".openclaw", "workspace"));
}

for (const directory of [
  path.join(payloadDir, "data", ".openclaw", "launcher"),
  path.join(payloadDir, "data", ".openclaw", "extensions"),
  path.join(payloadDir, "data", ".openclaw", "skills"),
  path.join(payloadDir, "data", "generated-images"),
  path.join(payloadDir, "data", "storyboards", "assets"),
  path.join(payloadDir, "data", "logs"),
]) {
  fs.mkdirSync(directory, { recursive: true });
}

writeJson(path.join(payloadDir, "data", ".openclaw", "openclaw.json"), {
  gateway: {
    auth: { mode: "none" },
    bind: "loopback",
  },
  agents: {
    defaults: {
      workspace: "data/.openclaw/workspace",
      contextInjection: "always",
      bootstrapPromptTruncationWarning: "once",
    },
  },
});

writeJson(path.join(payloadDir, "package.json"), {
  name: "openclaw-mac-runtime",
  private: true,
  type: "module",
  version: packageJson.version,
  dependencies: {
    openclaw: openclawVersion,
    "@larksuite/openclaw-lark": larkVersion,
    "@tencent-weixin/openclaw-weixin": weixinVersion,
  },
});

writeText(
  path.join(payloadDir, "start.js"),
  `#!/usr/bin/env node
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const runtimeRoot = path.dirname(fileURLToPath(import.meta.url));
const cli = path.join(runtimeRoot, "node_modules", "openclaw", "openclaw.mjs");
const env = {
  ...process.env,
  OPENCLAW_HOME: process.env.OPENCLAW_HOME || path.join(runtimeRoot, "data"),
  OPENCLAW_STATE_DIR: process.env.OPENCLAW_STATE_DIR || path.join(runtimeRoot, "data", ".openclaw"),
  OPENCLAW_CONFIG_PATH: process.env.OPENCLAW_CONFIG_PATH || path.join(runtimeRoot, "data", ".openclaw", "openclaw.json"),
};

const args = [cli, "gateway", ...process.argv.slice(2)];
const child = spawn(process.execPath, args, {
  cwd: runtimeRoot,
  env,
  stdio: "inherit",
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
`,
  0o755,
);

const npmCacheDir = path.join(cacheDir, "npm");
if (!resume || !fs.existsSync(path.join(payloadDir, "node_modules", "openclaw", "openclaw.mjs"))) {
  run("npm", ["install", "--omit=dev", "--no-audit", "--no-fund", "--cache", npmCacheDir], { cwd: payloadDir });
}
fs.rmSync(npmCacheDir, { recursive: true, force: true });

const nodeArchiveName = `node-v${nodeRuntimeVersion}-darwin-arm64.tar.gz`;
const nodeDistBase = process.env.NODE_DIST_BASE || "https://nodejs.org/dist";
const nodeArchive = path.join(cacheDir, nodeArchiveName);
const nodeExtractRoot = path.join(cacheDir, `node-v${nodeRuntimeVersion}-darwin-arm64`);
const nodeDir = path.join(payloadDir, "node");
fs.mkdirSync(cacheDir, { recursive: true });
if (!resume || !fs.existsSync(path.join(nodeDir, "node"))) {
  if (!fs.existsSync(nodeArchive)) {
    run("curl", ["-fL", `${nodeDistBase}/v${nodeRuntimeVersion}/${nodeArchiveName}`, "-o", nodeArchive], { cwd: repoDir });
  }
  fs.rmSync(nodeExtractRoot, { recursive: true, force: true });
  run("tar", ["-xzf", nodeArchive, "-C", cacheDir], { cwd: repoDir });
  copyDir(nodeExtractRoot, nodeDir);
  symlinkRelative("bin/node", path.join(nodeDir, "node"));
  symlinkRelative("bin/npm", path.join(nodeDir, "npm"));
  symlinkRelative("bin/npx", path.join(nodeDir, "npx"));
  if (fs.existsSync(path.join(nodeDir, "bin", "corepack"))) {
    symlinkRelative("bin/corepack", path.join(nodeDir, "corepack"));
  }
  symlinkRelative("lib/node_modules", path.join(nodeDir, "node_modules"));
  fs.rmSync(nodeArchive, { force: true });
  fs.rmSync(nodeExtractRoot, { recursive: true, force: true });
}

const pythonRuntimeDir = path.join(payloadDir, "_up_", "python-runtime");
run("uv", ["venv", "--clear", "--relocatable", "--managed-python", "--python", "3.12", "--seed", "--link-mode", "copy", pythonRuntimeDir], { cwd: repoDir });
run("uv", ["pip", "install", "--python", path.join(pythonRuntimeDir, "bin", "python"), "--link-mode", "copy", "-r", path.join(projectDir, "python", "requirements.txt")], { cwd: repoDir });
writeText(path.join(pythonRuntimeDir, "python3"), "#!/bin/sh\nDIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\nexec \"$DIR/bin/python3\" \"$@\"\n", 0o755);
writeText(path.join(pythonRuntimeDir, "python"), "#!/bin/sh\nDIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\nexec \"$DIR/bin/python\" \"$@\"\n", 0o755);

const nodeVersion = output(path.join(nodeDir, "node"), ["--version"], { cwd: payloadDir });
const runtimeOpenClawVersion = output(path.join(nodeDir, "node"), ["-e", "console.log(require('./node_modules/openclaw/package.json').version)"], { cwd: payloadDir });
const pythonCheck = output(path.join(pythonRuntimeDir, "python3"), ["-c", "import fastapi, uvicorn, cryptography, PIL; print('ok')"], { cwd: payloadDir });
const openclawCliVersion = output(path.join(nodeDir, "node"), [path.join(payloadDir, "node_modules", "openclaw", "openclaw.mjs"), "--version"], { cwd: payloadDir });

const manifest = {
  name: packageName,
  createdAt: new Date().toISOString(),
  platform: "macos-arm64",
  launcherVersion: packageJson.version,
  openclawVersion: runtimeOpenClawVersion,
  openclawCliVersion,
  larkPluginVersion: larkVersion,
  weixinPluginVersion: weixinVersion,
  nodeRuntimeVersion: nodeVersion,
  pythonRuntime: "uv managed Python 3.12",
  pythonDependencyCheck: pythonCheck,
};
writeJson(path.join(stageDir, "manifest.json"), manifest);

writeText(
  path.join(stageDir, "README-安装说明.txt"),
  `OpenClaw Mac 完整包

版本信息：
- 启动器：${packageJson.version}
- OpenClaw：${runtimeOpenClawVersion}
- Node：${nodeVersion}
- Python：uv managed Python 3.12

使用方式：
1. 保持 OpenClaw.app 和 OpenClawFiles 在同一个目录。
2. 双击 OpenClaw.app 启动。
3. 如系统提示安全拦截，请在 系统设置 > 隐私与安全性 中允许打开。

注意：
- 这个包不包含你的 license.json、API Key、登录态或本机私有数据。
- OpenClawFiles/data 是运行期数据目录，启动器会在这里写入配置、日志和工作区。
`,
);

const dmgPath = path.join(releaseDir, `${packageName}.dmg`);
fs.rmSync(dmgPath, { force: true });
run("hdiutil", ["create", "-volname", "OpenClaw Mac Complete", "-srcfolder", stageDir, "-ov", "-format", "UDZO", dmgPath], { cwd: repoDir });
const sha256 = output("shasum", ["-a", "256", dmgPath], { cwd: repoDir });
writeText(path.join(releaseDir, `${packageName}.sha256.txt`), `${sha256}\n`);

console.log(JSON.stringify({ stageDir, dmgPath, sha256, manifest }, null, 2));
