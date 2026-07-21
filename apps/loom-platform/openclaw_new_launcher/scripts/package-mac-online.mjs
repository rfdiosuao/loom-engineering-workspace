import { execFileSync, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectDir = path.resolve(scriptDir, "..");
const repoDir = path.resolve(projectDir, "..");
const releaseDir = path.join(repoDir, "release");
const packageJson = JSON.parse(fs.readFileSync(path.join(projectDir, "package.json"), "utf8"));

const LAYERS = [
  { id: "node", title: "Node.js 运行时", installPath: "OpenClawFiles/node", required: true },
  { id: "openclaw-deps", title: "OpenClaw 依赖", installPath: "OpenClawFiles/node_modules", required: true },
  { id: "python-runtime", title: "Python 运行时", installPath: "OpenClawFiles/_up_/python-runtime", required: true },
  { id: "luminode-desktop", title: "Luminode 桌面组件", installPath: "OpenClawFiles/agents/luminode-desktop", required: false },
];

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) continue;
    const key = item.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      args[key] = "1";
      continue;
    }
    args[key] = next;
    index += 1;
  }
  return args;
}

function run(command, args, options = {}) {
  console.log(`$ ${[command, ...args].join(" ")}`);
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? repoDir,
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
    cwd: options.cwd ?? repoDir,
    env: { ...process.env, ...(options.env ?? {}) },
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
}

function copyDir(source, target) {
  if (!fs.existsSync(source)) return false;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  run("ditto", [source, target], { cwd: repoDir });
  return true;
}

function copyFileIfExists(source, target) {
  if (!fs.existsSync(source)) return false;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
  return true;
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

function writeText(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, value);
}

function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  return hash.digest("hex");
}

function tarCreate(srcDir, outFile) {
  const srcAbs = path.resolve(srcDir);
  const outAbs = path.resolve(outFile);
  fs.mkdirSync(path.dirname(outAbs), { recursive: true });
  run("tar", ["-czf", path.basename(outAbs), "-C", path.dirname(srcAbs), path.basename(srcAbs)], {
    cwd: path.dirname(outAbs),
  });
}

function latestCompleteStage() {
  if (!fs.existsSync(releaseDir)) return "";
  const prefix = `OpenClaw-Mac-Complete-v${packageJson.version}`;
  const candidates = fs
    .readdirSync(releaseDir)
    .filter((name) => name.startsWith(prefix))
    .map((name) => path.join(releaseDir, name))
    .filter((item) => fs.statSync(item).isDirectory() && fs.existsSync(path.join(item, "OpenClaw.app")) && fs.existsSync(path.join(item, "OpenClawFiles")))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  return candidates[0] || "";
}

function detectOwner() {
  if (process.env.GITHUB_REPOSITORY) return process.env.GITHUB_REPOSITORY;
  try {
    const value = output("gh", ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], { cwd: repoDir });
    if (value) return value;
  } catch {
    // Fall through to the project default used for current lumi releases.
  }
  return "rfdiosuao/lumi";
}

function portableManifestPath(stageDir) {
  return path.join(stageDir, "OpenClawFiles", "data", ".openclaw", "dist-cache", "manifest.json");
}

function makeGithubMirrors(owner, tag) {
  const releaseBase = `https://github.com/${owner}/releases/download/${tag}/`;
  return [
    `https://ghproxy.com/${releaseBase}`,
    releaseBase,
  ];
}

function createOnlinePayload(sourceStage, stageDir, appSource) {
  const sourcePayload = path.join(sourceStage, "OpenClawFiles");
  const targetPayload = path.join(stageDir, "OpenClawFiles");

  copyDir(appSource, path.join(stageDir, "OpenClaw.app"));

  for (const rel of [
    "_up_/python",
    "_up_/data",
    "data",
    "openclaw-workspace",
    "scripts",
  ]) {
    copyDir(path.join(sourcePayload, rel), path.join(targetPayload, rel));
  }

  for (const rel of ["start.js", "package.json", "package-lock.json"]) {
    copyFileIfExists(path.join(sourcePayload, rel), path.join(targetPayload, rel));
  }

  for (const rel of [
    "data/.openclaw/dist-cache/layers",
    "data/generated-images",
    "data/storyboards/assets",
    "data/logs",
    "agents",
  ]) {
    fs.mkdirSync(path.join(targetPayload, rel), { recursive: true });
  }
}

function signAppBundle(appPath) {
  if (process.platform !== "darwin" || process.env.OPENCLAW_SKIP_CODESIGN === "1") {
    return;
  }
  run("codesign", ["--force", "--deep", "--sign", "-", appPath], { cwd: repoDir });
  run("codesign", ["--verify", "--deep", "--strict", "--verbose=2", appPath], { cwd: repoDir });
}

function writeReadme(stageDir, tag, owner) {
  writeText(
    path.join(stageDir, "README-在线包说明.txt"),
    `lumi Mac 在线包

使用方式：
1. 解压 zip 后保持 OpenClaw.app 和 OpenClawFiles 在同一个文件夹。
2. 双击 OpenClaw.app 启动，首次启动会从 GitHub Release 下载并校验运行时组件。
3. 下载完成后会写入 OpenClawFiles，后续启动不会重复下载。

发布信息：
- GitHub 仓库：${owner}
- Release：${tag}
- manifest：OpenClawFiles/data/.openclaw/dist-cache/manifest.json

注意：
- 在线包需要可写目录，不建议直接在只读 DMG 中运行。
- 全量离线包仍然可以作为无网环境的兜底版本。
`,
  );
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (process.platform !== "darwin" || os.arch() !== "arm64") {
    throw new Error("This packager currently builds macOS arm64 packages only.");
  }

  const version = args.version || packageJson.version;
  const owner = args.owner || detectOwner();
  const tag = args.tag || `lumi-desktop-v${version}`;
  const packageBase = args.name || `lumi-mac-v${version}-online`;
  const sourceStage = path.resolve(args.source || latestCompleteStage());
  if (!sourceStage || !fs.existsSync(path.join(sourceStage, "OpenClawFiles")) || !fs.existsSync(path.join(sourceStage, "OpenClaw.app"))) {
    throw new Error("Missing complete Mac package. Run `npm run package:mac:complete` first, or pass --source <complete-stage>.");
  }
  const appSource = path.resolve(args["app-source"] || path.join(sourceStage, "OpenClaw.app"));
  if (!fs.existsSync(appSource)) {
    throw new Error(`OpenClaw.app not found: ${appSource}`);
  }

  const stageDir = path.join(releaseDir, packageBase);
  const layersDir = path.join(releaseDir, `${packageBase}-layers`);
  const zipPath = path.join(releaseDir, `${packageBase}.zip`);
  const dmgPath = path.join(releaseDir, `${packageBase}.dmg`);
  fs.rmSync(stageDir, { recursive: true, force: true });
  fs.rmSync(layersDir, { recursive: true, force: true });
  fs.rmSync(zipPath, { force: true });
  fs.rmSync(dmgPath, { force: true });
  fs.mkdirSync(stageDir, { recursive: true });
  fs.mkdirSync(layersDir, { recursive: true });

  createOnlinePayload(sourceStage, stageDir, appSource);
  signAppBundle(path.join(stageDir, "OpenClaw.app"));

  const manifest = {
    schemaVersion: 1,
    product: "openclaw-launcher",
    platform: "macos-arm64",
    version,
    tag,
    generatedAt: new Date().toISOString(),
    mirrors: makeGithubMirrors(owner, tag),
    layers: [],
  };

  for (const layer of LAYERS) {
    const srcDir = path.join(sourceStage, layer.installPath);
    if (!fs.existsSync(srcDir)) {
      console.warn(`skip ${layer.id}: ${srcDir} not found`);
      continue;
    }
    const file = `lumi-mac-arm64-${layer.id}.tar.gz`;
    const outFile = path.join(layersDir, file);
    tarCreate(srcDir, outFile);
    const sha256 = sha256File(outFile);
    const size = fs.statSync(outFile).size;
    manifest.layers.push({ ...layer, file, sha256, size });
    console.log(`${layer.id}: ${(size / 1048576).toFixed(1)} MB sha256=${sha256.slice(0, 12)}...`);
  }

  const manifestName = "manifest-macos-arm64.json";
  writeJson(path.join(layersDir, manifestName), manifest);
  writeJson(portableManifestPath(stageDir), manifest);
  writeReadme(stageDir, tag, owner);

  run("ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", stageDir, zipPath], { cwd: path.dirname(stageDir) });
  const zipSha = sha256File(zipPath);
  writeText(path.join(releaseDir, `${packageBase}.zip.sha256.txt`), `${zipSha}  ${path.basename(zipPath)}\n`);

  if (args.dmg === "1" || process.env.OPENCLAW_ONLINE_DMG === "1") {
    run("hdiutil", ["create", "-volname", "lumi Mac Online", "-srcfolder", stageDir, "-ov", "-format", "UDZO", dmgPath], { cwd: repoDir });
    const dmgSha = sha256File(dmgPath);
    writeText(path.join(releaseDir, `${packageBase}.dmg.sha256.txt`), `${dmgSha}  ${path.basename(dmgPath)}\n`);
  }

  const uploadCommand = [
    "gh",
    "release",
    "upload",
    tag,
    path.relative(repoDir, zipPath),
    path.relative(repoDir, path.join(releaseDir, `${packageBase}.zip.sha256.txt`)),
    path.relative(repoDir, path.join(layersDir, "*.tar.gz")),
    path.relative(repoDir, path.join(layersDir, manifestName)),
    "--repo",
    owner,
    "--clobber",
  ].join(" ");
  writeText(path.join(layersDir, "upload-assets.txt"), `${uploadCommand}\n`);

  console.log(JSON.stringify({
    stageDir,
    zipPath,
    layersDir,
    manifestPath: path.join(layersDir, manifestName),
    cachedManifestPath: portableManifestPath(stageDir),
    appSource,
    tag,
    owner,
    uploadCommand,
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
