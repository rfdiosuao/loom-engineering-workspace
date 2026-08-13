import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const testsDir = path.dirname(fileURLToPath(import.meta.url));
const launcherRoot = path.resolve(testsDir, "../..");
const releaseNotesPath = path.join(launcherRoot, "docs", "RELEASE_NOTES_2.4.14.md");

async function readJson(relativePath) {
  return JSON.parse(await readFile(path.join(launcherRoot, relativePath), "utf8"));
}

test("Desktop 2.4.14 has one consistent version and the exact 麓鸣 product name", async () => {
  const [packageJson, packageLock, tauriConfig, cargoToml, cargoLock] = await Promise.all([
    readJson("package.json"),
    readJson("package-lock.json"),
    readJson("src-tauri/tauri.conf.json"),
    readFile(path.join(launcherRoot, "src-tauri", "Cargo.toml"), "utf8"),
    readFile(path.join(launcherRoot, "src-tauri", "Cargo.lock"), "utf8"),
  ]);

  assert.equal(packageJson.version, "2.4.14");
  assert.equal(packageLock.version, "2.4.14");
  assert.equal(packageLock.packages[""].version, "2.4.14");
  assert.equal(tauriConfig.version, "2.4.14");
  assert.equal(tauriConfig.productName, "麓鸣");
  assert.equal(tauriConfig.app.windows[0].title, "麓鸣");
  assert.match(cargoToml, /^version = "2\.4\.14"$/m);
  assert.match(cargoLock, /\[\[package\]\]\s+name = "app"\s+version = "2\.4\.14"/m);
});

test("2.4.14 release notes state the DeepSeek Codex fix and preserve the phone boundary", async () => {
  const notes = await readFile(releaseNotesPath, "utf8");

  assert.match(notes, /麓鸣 Desktop `2\.4\.14`/);
  assert.match(notes, /LumiAgent `6\.67-stability`/);
  assert.match(notes, /versionCode `936`/);
  assert.match(notes, /本 Desktop 发布说明不声明或发布新的 Phone 构建/);
  assert.doesNotMatch(notes, /不修改或重新构建手机端/);
  assert.match(notes, /DeepSeek Responses API/);
  assert.match(notes, /deepseek-v4-flash/);
  assert.match(notes, /models\.json/);
  assert.match(notes, /历史会话/);
});
