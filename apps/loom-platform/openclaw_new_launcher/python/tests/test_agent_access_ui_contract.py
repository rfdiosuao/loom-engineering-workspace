from __future__ import annotations

import os
import hashlib
import re
import unittest
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AgentAccessUiContractTests(unittest.TestCase):
    def _page(self) -> str:
        page_path = os.path.join(ROOT, "src", "components", "agentAccess", "AgentAccessPage.tsx")
        with open(page_path, "r", encoding="utf-8") as handle:
            return handle.read()

    def _prompt_module(self) -> str:
        prompt_path = os.path.join(ROOT, "src", "components", "agentAccess", "agentPrompt.ts")
        with open(prompt_path, "r", encoding="utf-8") as handle:
            return handle.read()

    def _page_and_prompt(self) -> str:
        return self._page() + "\n" + self._prompt_module()

    def _bundled_library_path(self) -> str:
        return os.path.join(ROOT, "public", "skills", "luming-skills-library-20260721.zip")

    def _bundled_library_text(self) -> str:
        with zipfile.ZipFile(self._bundled_library_path()) as archive:
            return "\n".join(
                archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if name.endswith((".md", ".json", ".ps1"))
            )

    def _bundled_library_entry(self, name: str) -> str:
        with zipfile.ZipFile(self._bundled_library_path()) as archive:
            return archive.read(name).decode("utf-8")

    def test_agent_access_route_is_registered_and_available_without_matrix_license(self) -> None:
        registry_path = os.path.join(ROOT, "src", "features", "registry.ts")
        page_path = os.path.join(ROOT, "src", "features", "pages.tsx")

        with open(registry_path, "r", encoding="utf-8") as handle:
            registry = handle.read()
        with open(page_path, "r", encoding="utf-8") as handle:
            pages = handle.read()

        definition = re.search(r"\{\s*key:\s*'agentAccess'[^}]+\}", registry)
        self.assertIsNotNone(definition)
        self.assertNotIn("requiresLicense: true", definition.group(0))
        self.assertNotIn("visible: HIDDEN", definition.group(0))
        self.assertIn("agentAccess", pages)

    def test_agent_access_page_points_to_mcp_config(self) -> None:
        page = self._page_and_prompt()

        self.assertIn(".mcp.json", page)
        self.assertIn("loom_mcp.py", page)
        self.assertIn("LOOM_CLI", page)
        self.assertIn("LOOM_CLI_DIR", page)
        self.assertLess(page.count("<p"), 4)

    def test_agent_access_page_exposes_cross_platform_skill_bootstrap(self) -> None:
        page = self._page_and_prompt()

        self.assertIn("LUMING_SKILL_LIBRARY_PATH", page)
        self.assertIn("LUMING_SKILL_LIBRARY_URL", page)
        self.assertIn("LUMING_SKILL_LIBRARY_SHA256", page)
        self.assertIn("luming-skills-library-20260721.zip", page)
        self.assertIn("luming-phone-agent", page)
        self.assertNotIn("LOOM_COMMAND_BRAIN_SKILL_URLS", page)
        self.assertNotIn("LUMING_ACQUISITION_SKILL_URLS", page)
        self.assertIn("CODEX_HOME", page)
        self.assertIn("LOOM_CLI", page)
        self.assertIn("%USERPROFILE%\\\\.codex", page)
        self.assertIn("$HOME/.codex", page)
        self.assertIn("/Applications/LOOM.app/Contents/Resources", page)
        self.assertTrue(os.path.exists(self._bundled_library_path()))

    def test_agent_access_detects_the_real_host_before_persisting_configuration(self) -> None:
        prompt = self._prompt_module()

        for marker in [
            "HOST_KIND",
            "HOST_CAPABILITIES",
            "ACCESS_MODE",
            "Codex",
            "Claude Code",
            "CodeBuddy",
            "WorkBuddy",
            "unknown",
            "~/.claude/skills",
            "~/.codebuddy/skills",
            "~/.workbuddy/mcp.json",
            "<项目目录>/.workbuddy/mcp.json",
            "-Destination",
        ]:
            self.assertIn(marker, prompt)

        self.assertIn("不得把自己改称或伪装成 Codex", prompt)
        self.assertIn("不得创建 .codex、.claude、.codebuddy 或 .workbuddy", prompt)
        self.assertIn("不得声称已经完成接入", prompt)
        self.assertNotIn("自动发现 Codex Home", prompt)

    def test_bundled_installer_never_guesses_codex_as_the_agent_host(self) -> None:
        source = self._bundled_library_entry("scripts/install.ps1")

        self.assertIn("Destination is required", source)
        self.assertNotIn('Join-Path $env:USERPROFILE ".codex"', source)

    def test_agent_access_uses_domestic_primary_source_with_pinned_fallback(self) -> None:
        prompt = self._prompt_module()
        domestic_url = (
            "https://loom.heang.top/downloads/"
            "luming-skills-library-20260721-36D03E43.zip"
        )
        github_url = "https://raw.githubusercontent.com/rfdiosuao/loom-release-channel/"

        self.assertIn(domestic_url, prompt)
        self.assertIn("LUMING_SKILL_LIBRARY_FALLBACK_URL", prompt)
        self.assertIn(github_url, prompt)
        self.assertIn("fallbackUrl:", prompt)
        self.assertLess(prompt.index(domestic_url), prompt.index(github_url))

    def test_agent_access_declared_hash_matches_bundled_skill_library(self) -> None:
        prompt = self._prompt_module()
        with open(self._bundled_library_path(), "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest().upper()

        self.assertIn(digest, prompt)

    def test_bundle_contains_only_the_unified_loom_skill_distribution(self) -> None:
        skills_root = os.path.join(ROOT, "public", "skills")

        for legacy_name in [
            "loom-adb-forward-proxy-bypass",
            "loom-command-brain",
            "luming-acquisition-agent",
        ]:
            self.assertFalse(os.path.isfile(os.path.join(skills_root, legacy_name, "SKILL.md")))
        with zipfile.ZipFile(self._bundled_library_path()) as archive:
            manifest = archive.read("manifest.json").decode("utf-8")
        for legacy_name in [
            "loom-adb-forward-proxy-bypass",
            "loom-command-brain",
            "luming-acquisition-agent",
        ]:
            self.assertIn(legacy_name, manifest)

    def test_agent_access_page_documents_encoding_and_tool_fallback(self) -> None:
        page = self._page_and_prompt()

        self.assertIn("UTF-8", page)
        self.assertIn("<meta charset=\"UTF-8\">", page)
        self.assertIn("Computer Use", page)
        self.assertIn("Node REPL", page)
        self.assertIn("LOOM CLI/MCP", page)
        self.assertIn("wire_api = \"responses\"", page)
        self.assertNotIn("wire_api = \"chat\"", page)

    def test_codex_bootstrap_example_uses_managed_default_coding_model(self) -> None:
        prompt = self._prompt_module()

        self.assertIn('model = "glm-5.2-coding"', prompt)
        self.assertNotIn('model = "qwen3.7-plus"', prompt)

    def test_agent_access_page_exposes_one_shot_bootstrap_prompt(self) -> None:
        page = self._page_and_prompt()

        self.assertIn("buildOneShotAgentPrompt", page)
        self.assertIn("BEGIN_SKILL_LIBRARY", page)
        self.assertIn("END_SKILL_LIBRARY", page)
        self.assertIn("SHA256", page)
        self.assertIn("scripts/install.ps1", page)
        self.assertIn("LOOM_ADB", page)
        self.assertIn("BEGIN_MCP_JSON", page)
        self.assertIn("END_MCP_JSON", page)
        self.assertIn("data-agent-one-shot-copy", page)

    def test_unified_skill_contains_phone_matrix_media_and_acquisition_contracts(self) -> None:
        source = self._bundled_library_text()

        for marker in [
            "luming-phone-agent",
            "loom.acquisition.agent_result.v1",
            "acquisition agent-run",
            "integration feishu status",
            "Feishu Bitable",
            "gateMode: weak",
            "matrix",
            "media image",
            "media video",
        ]:
            self.assertIn(marker, source)

    def test_agent_access_prompt_mentions_phone_cli_surface(self) -> None:
        sources = [self._page_and_prompt(), self._bundled_library_text()]

        for source in sources:
            self.assertIn("phone:agent", source)
            self.assertIn("phone:vision", source)
            self.assertIn("phone:video", source)
            self.assertIn("phone:image", source)
            self.assertIn("phone:image:edit", source)
            self.assertIn("phone:fleet", source)
            self.assertIn("phone:game", source)
            self.assertIn("phone:publish", source)
            self.assertIn("loom:phone:video", source)
            self.assertIn("events", source)
            self.assertIn("click_ref", source)
            self.assertTrue(
                "Android screen-capture consent prompt" in source
                or "Android MediaProjection consent prompt" in source
            )

    def test_agent_access_skill_text_has_no_mojibake_or_local_dev_paths(self) -> None:
        sources = [self._page_and_prompt(), self._bundled_library_text()]
        mojibake_markers = [
            "".join(chr(code) for code in codes)
            for codes in (
                (37902, 29808, 58931),
                (38328, 12517, 22717),
                (22994, 28057, 59336),
                (23092, 28355, 25643),
                (28729, 21578, 24387),
                (23138, 36346, 31220),
                (38329, 24658, 20785),
                (38331, 12834, 21904, 37736, 63),
            )
        ]
        forbidden = [
            r"D:\Axiangmu\AUSTART",
            r"C:\Users\Administrator",
            *mojibake_markers,
        ]

        for source in sources:
            for token in forbidden:
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
