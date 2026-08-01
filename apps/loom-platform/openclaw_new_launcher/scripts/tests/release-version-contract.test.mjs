import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const testsDir = path.dirname(fileURLToPath(import.meta.url));
const launcherRoot = path.resolve(testsDir, "../..");
const repositoryRoot = path.resolve(launcherRoot, "../../..");
const releaseNotesPath = path.join(repositoryRoot, "docs", "RELEASE_NOTES_2.4.3.md");

async function readJson(relativePath) {
  return JSON.parse(await readFile(path.join(launcherRoot, relativePath), "utf8"));
}

test("Desktop 2.4.3 has one consistent version and the exact 麓鸣 product name", async () => {
  const [packageJson, packageLock, tauriConfig, cargoToml, cargoLock] = await Promise.all([
    readJson("package.json"),
    readJson("package-lock.json"),
    readJson("src-tauri/tauri.conf.json"),
    readFile(path.join(launcherRoot, "src-tauri", "Cargo.toml"), "utf8"),
    readFile(path.join(launcherRoot, "src-tauri", "Cargo.lock"), "utf8"),
  ]);

  assert.equal(packageJson.version, "2.4.3");
  assert.equal(packageLock.version, "2.4.3");
  assert.equal(packageLock.packages[""].version, "2.4.3");
  assert.equal(tauriConfig.version, "2.4.3");
  assert.equal(tauriConfig.productName, "麓鸣");
  assert.equal(tauriConfig.app.windows[0].title, "麓鸣");
  assert.match(cargoToml, /^version = "2\.4\.3"$/m);
  assert.match(cargoLock, /\[\[package\]\]\s+name = "app"\s+version = "2\.4\.3"/m);
});

test("2.4.3 release notes state phone version and capability limits without fake claims", async () => {
  const notes = await readFile(releaseNotesPath, "utf8");

  assert.match(notes, /麓鸣 Desktop `2\.4\.3`/);
  assert.match(notes, /LumiAgent `6\.64-stability`/);
  assert.match(notes, /低延迟视频/);
  assert.match(notes, /Shizuku/);
  assert.match(notes, /PRoot\/Linux/);
  assert.match(notes, /未内置 PRoot/);
  assert.match(notes, /实体机验收/);
});
