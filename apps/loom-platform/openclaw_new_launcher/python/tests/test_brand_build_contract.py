from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


LAUNCHER_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = LAUNCHER_ROOT / "python"
PLATFORM_ROOT = LAUNCHER_ROOT.parent
APPS_ROOT = PLATFORM_ROOT.parent
BRAND_BUILD_MODULE = PLATFORM_ROOT / "scripts" / "brand_build.py"
BUILD_HOOK = PLATFORM_ROOT / "scripts" / "build-brand.ps1"
ANDROID_GRADLE = APPS_ROOT / "loom-phone-agent" / "app" / "build.gradle.kts"
ANDROID_MANIFEST = (
    APPS_ROOT / "loom-phone-agent" / "app" / "src" / "main" / "AndroidManifest.xml"
)
PORTABLE_BUILD = PLATFORM_ROOT / "scripts" / "build-portable.ps1"

if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))


def _load_brand_build_module():
    spec = importlib.util.spec_from_file_location("loom_brand_build", BRAND_BUILD_MODULE)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load brand compiler: {BRAND_BUILD_MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _active_brand() -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "brandId": "northstar",
        "status": "active",
        "product": {
            "displayName": "Northstar AI Matrix",
            "shortName": "Northstar",
            "publisher": "Northstar Technology",
        },
        "positioning": {
            "category": "AI 手机矩阵执行平台",
            "promise": "一句话下任务，整组手机执行到结果。",
        },
        "desktop": {
            "productName": "Northstar AI Matrix",
            "binaryName": "northstar.exe",
            "identifier": "top.heang.oem.northstar",
            "windowTitle": "Northstar AI Matrix",
        },
        "phone": {
            "appName": "Northstar Agent Phone",
            "applicationId": "top.heang.oem.northstar.phone",
        },
        "urls": {
            "website": "https://northstar.cn",
            "apiBase": "https://api.northstar.cn",
            "licenseServer": "https://license.northstar.cn",
            "purchase": "https://northstar.cn/buy",
            "docs": "https://docs.northstar.cn",
            "support": "https://support.northstar.cn",
            "manifest": "https://download.northstar.cn/internal/latest.json",
        },
        "release": {
            "channel": "internal",
            "filePrefix": "northstar",
            "updateChannelId": "northstar-internal",
        },
        "assets": {"logo": "assets/logo.svg"},
    }


class BrandBuildContractTests(unittest.TestCase):
    def _brand_pack(self, root: Path, brand: dict[str, object] | None = None) -> Path:
        brand_root = root / "brand"
        _write_json(brand_root / "brand.json", brand or _active_brand())
        _write_json(
            brand_root / "copy.json",
            {
                "homeTitle": "Northstar AI Matrix",
                "taskPlaceholder": "描述业务目标，系统将拆解并交给手机矩阵执行",
                "supportLabel": "联系支持",
            },
        )
        _write_json(
            brand_root / "modules.json",
            {
                "enabled": ["agent-orchestration", "phone-matrix"],
                "locked": [],
                "hidden": ["experimental"],
            },
        )
        logo = brand_root / "assets" / "logo.svg"
        logo.parent.mkdir(parents=True, exist_ok=True)
        logo.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<rect width="64" height="64" rx="8" fill="#0b4a3e"/>'
            '<path d="M12 46 30 14l22 32z" fill="#fff"/></svg>',
            encoding="utf-8",
        )
        return brand_root

    def test_compiler_emits_one_source_of_truth_for_all_brand_surfaces(self) -> None:
        module = _load_brand_build_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            brand_root = self._brand_pack(root)
            output = root / "compiled"

            plan = module.compile_brand_pack(
                brand_path=str(brand_root),
                output_path=str(output),
                version="2.3.18",
                core_commit="a" * 40,
                factory_commit="b" * 40,
                release_ready=True,
            )

            self.assertEqual(plan["brandId"], "northstar")
            self.assertEqual(plan["desktop"]["mainBinaryName"], "northstar")
            self.assertEqual(plan["android"]["applicationId"], "top.heang.oem.northstar.phone")
            self.assertEqual(plan["update"]["channelId"], "northstar-internal")
            self.assertTrue(
                Path(plan["frontend"]["logoAsset"]).samefile(brand_root / "assets" / "logo.svg")
            )
            self.assertEqual(
                plan["frontend"]["bundledLogoRelativePath"],
                "oem-brand/brand-logo.svg",
            )

            tauri = json.loads((output / "tauri.brand.conf.json").read_text(encoding="utf-8"))
            self.assertEqual(tauri["productName"], "Northstar AI Matrix")
            self.assertEqual(tauri["mainBinaryName"], "northstar")
            self.assertEqual(tauri["identifier"], "top.heang.oem.northstar")
            self.assertEqual(tauri["app"]["windows"][0]["title"], "Northstar AI Matrix")
            self.assertIn("_up_/data/brand_profile.json", tauri["bundle"]["resources"].values())
            self.assertIn("_up_/data/desktop-update-brand.json", tauri["bundle"]["resources"].values())
            self.assertIn("_up_/data/oem-brand.json", tauri["bundle"]["resources"].values())

            profile = json.loads(
                (output / "runtime" / "brand_profile.json").read_text(encoding="utf-8")
            )
            self.assertEqual(profile["themeId"], "northstar")
            self.assertEqual(profile["displayName"], "Northstar AI Matrix")
            self.assertEqual(profile["nativeAgentName"], "Northstar AI Matrix 原生智能体")
            self.assertEqual(profile["modules"]["enabled"], ["agent-orchestration", "phone-matrix"])

            theme = json.loads(
                (output / "runtime" / "themes" / "northstar" / "theme.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(theme["brand"]["name"], "Northstar AI Matrix")
            self.assertEqual(theme["window"]["title"], "Northstar AI Matrix")

            update = json.loads(
                (output / "runtime" / "desktop-update-brand.json").read_text(encoding="utf-8")
            )
            self.assertEqual(update["product"], "northstar")
            self.assertEqual(update["channel"], "internal")
            self.assertEqual(update["manifestUrl"], "https://download.northstar.cn/internal/latest.json")
            self.assertEqual(update["filePrefix"], "northstar")

            oem_runtime = json.loads(
                (output / "runtime" / "oem-brand.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                oem_runtime,
                {
                    "schemaVersion": 1,
                    "brandId": "northstar",
                    "licenseServer": "https://license.northstar.cn",
                    "purchaseFallback": "https://northstar.cn/buy",
                    "supportFallback": "https://support.northstar.cn",
                },
            )

            environment = json.loads((output / "environment.json").read_text(encoding="utf-8"))
            self.assertEqual(
                environment["VITE_LOOM_BRAND_DISPLAY_NAME"], "Northstar AI Matrix"
            )
            self.assertNotIn("VITE_LOOM_BRAND_LOGO_DATA_URL", environment)
            self.assertEqual(
                environment["VITE_LOOM_BRAND_LOGO_URL"],
                "/oem-brand/brand-logo.svg",
            )
            environment_keys = "\n".join(environment)
            self.assertNotIn("API_KEY", environment_keys)
            self.assertNotIn("PRIVATE_KEY", environment_keys)
            self.assertNotIn("SECRET", environment_keys)

    def test_compiler_rejects_asset_traversal_and_secret_fields(self) -> None:
        module = _load_brand_build_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            brand = _active_brand()
            brand["assets"] = {"logo": "../outside.svg"}
            brand_root = self._brand_pack(root, brand)
            with self.assertRaisesRegex(ValueError, "asset|path|路径"):
                module.compile_brand_pack(
                    brand_path=str(brand_root),
                    output_path=str(root / "compiled-a"),
                    version="2.3.18",
                    core_commit="a" * 40,
                    factory_commit="b" * 40,
                    release_ready=True,
                )

            brand = _active_brand()
            brand["apiKey"] = "must-never-enter-a-brand-pack"
            brand_root = self._brand_pack(root / "second", brand)
            with self.assertRaisesRegex(ValueError, "secret|credential|密钥|敏感"):
                module.compile_brand_pack(
                    brand_path=str(brand_root),
                    output_path=str(root / "compiled-b"),
                    version="2.3.18",
                    core_commit="a" * 40,
                    factory_commit="b" * 40,
                    release_ready=True,
                )

    def test_release_compiler_rejects_demo_and_placeholder_urls(self) -> None:
        module = _load_brand_build_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            brand = _active_brand()
            brand["status"] = "demo"
            brand["urls"]["manifest"] = "https://download.northstar.invalid/latest.json"
            brand_root = self._brand_pack(root, brand)
            with self.assertRaisesRegex(ValueError, "active|placeholder|占位|发布"):
                module.compile_brand_pack(
                    brand_path=str(brand_root),
                    output_path=str(root / "compiled"),
                    version="2.3.18",
                    core_commit="a" * 40,
                    factory_commit="b" * 40,
                    release_ready=True,
                )

    def test_bundled_brand_profile_resolves_its_own_theme_before_stale_writable_themes(
        self,
    ) -> None:
        from core.paths import AppPaths
        from core.theme_manager import ThemeManager

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            writable_theme = root / "data" / "themes" / "northstar"
            bundled_data = root / "_up_" / "data"
            bundled_theme = bundled_data / "themes" / "northstar"
            writable_theme.mkdir(parents=True)
            bundled_theme.mkdir(parents=True)
            (writable_theme / "theme.json").write_text(
                json.dumps({"brand": {"name": "Stale LOOM"}}),
                encoding="utf-8",
            )
            (bundled_data / "brand_profile.json").write_text(
                json.dumps({"profile": "northstar", "themeId": "northstar"}),
                encoding="utf-8",
            )
            (bundled_theme / "theme.json").write_text(
                json.dumps({"brand": {"name": "Northstar AI Matrix"}}),
                encoding="utf-8",
            )

            current = ThemeManager(AppPaths(str(root))).get_current()

            self.assertEqual(current["brand"]["name"], "Northstar AI Matrix")

    def test_required_build_hook_and_downstream_parameter_contracts_exist(self) -> None:
        hook = BUILD_HOOK.read_text(encoding="utf-8")
        self.assertIn("[string]$BrandPath", hook)
        self.assertIn("[string]$OutputPath", hook)
        self.assertIn("[string]$Configuration", hook)
        self.assertIn('[ValidateSet("Release", "Debug")]', hook)
        self.assertIn('Complete OEM artifact builds require -Configuration Release', hook)
        self.assertIn("brand_build.py", hook)
        self.assertIn("tauri.brand.conf.json", hook)
        self.assertIn("bundledLogoRelativePath", hook)
        self.assertIn("Assert-GitWorktreeClean -Repository $WorkspaceRoot", hook)
        self.assertIn("assembleRelease", hook)
        self.assertIn("$androidBuildStartedAt", hook)
        self.assertIn("LastWriteTime -ge $androidBuildStartedAt", hook)
        self.assertIn("build-provenance.json", hook)

        gradle = ANDROID_GRADLE.read_text(encoding="utf-8")
        manifest = ANDROID_MANIFEST.read_text(encoding="utf-8")
        self.assertIn("OEM_APPLICATION_ID", gradle)
        self.assertIn("OEM_APP_NAME", gradle)
        self.assertIn("OEM_FILE_PREFIX", gradle)
        self.assertIn("OEM_RES_DIR", gradle)
        self.assertIn("${oemAppLabel}", manifest)
        self.assertIn("${oemAppIcon}", manifest)

        portable = PORTABLE_BUILD.read_text(encoding="utf-8")
        self.assertIn("[string]$ProductName", portable)
        self.assertIn("[string]$PackagePrefix", portable)
        self.assertIn("[string]$LauncherExeName", portable)

    def test_plan_only_hook_compiles_a_real_brand_pack_without_signing_material(self) -> None:
        powershell = shutil.which("powershell")
        if not powershell:
            self.skipTest("Windows PowerShell is unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            brand_root = self._brand_pack(root)
            output = root / "output"
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(BUILD_HOOK),
                    "-BrandPath",
                    str(brand_root),
                    "-OutputPath",
                    str(output),
                    "-Configuration",
                    "Debug",
                    "-FactoryCommit",
                    "b" * 40,
                    "-PlanOnly",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            plan = json.loads((output / "brand-build-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["brandId"], "northstar")
            self.assertFalse((output / "windows").exists())


if __name__ == "__main__":
    unittest.main()
