from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY_FILE = os.path.join(REPO_ROOT, "src", "features", "registry.ts")
PAGES_FILE = os.path.join(REPO_ROOT, "src", "features", "pages.tsx")
MATRIX_PAGE = os.path.join(REPO_ROOT, "src", "components", "matrix", "MatrixWorkbenchPage.tsx")
MATRIX_GATE = os.path.join(REPO_ROOT, "src", "components", "license", "PhoneMatrixAccessGate.tsx")
MATRIX_STREAM_HOOK = os.path.join(REPO_ROOT, "src", "components", "matrix", "useMatrixStream.ts")
CAPABILITIES_PAGE = os.path.join(REPO_ROOT, "src", "components", "capabilities", "CapabilityCenterPage.tsx")
SIDEBAR_FILE = os.path.join(REPO_ROOT, "src", "components", "sidebar", "Sidebar.tsx")
TITLEBAR_FILE = os.path.join(REPO_ROOT, "src", "components", "window", "WindowTitlebar.tsx")


class UiNavigationContractTests(unittest.TestCase):
    def test_central_agent_is_a_visible_page_distinct_from_agent_access(self) -> None:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as handle:
            registry = handle.read()
        with open(PAGES_FILE, "r", encoding="utf-8") as handle:
            pages = handle.read()

        agent_definition = next(line for line in registry.splitlines() if "key: 'agent'" in line)
        self.assertIn("label: '智能体'", agent_definition)
        self.assertNotIn("visible: HIDDEN", agent_definition)
        self.assertNotIn("requiresLicense", agent_definition)
        self.assertIn("components/agent/AgentWorkbenchPage", pages)
        self.assertRegex(pages, r"agent:\s*AgentWorkbenchPage")
        self.assertRegex(pages, r"agentAccess:\s*AgentAccessPage")

    def test_only_phone_connection_and_matrix_are_commercially_locked(self) -> None:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        definitions = {
            key: next(line for line in source.splitlines() if f"key: '{key}'" in line)
            for key in ("agent", "creative", "agentAccess", "capabilities", "phone", "workbench")
        }
        for key in ("agent", "creative", "agentAccess", "capabilities"):
            self.assertNotIn("requiresLicense", definitions[key])
        for key in ("phone", "workbench"):
            self.assertIn("requiresLicense: true", definitions[key])
        self.assertIn("visible: HIDDEN", definitions["phone"])
        self.assertNotIn("visible: HIDDEN", definitions["workbench"])

    def test_matrix_workbench_uses_real_backend_data_without_demo_fallback(self) -> None:
        with open(MATRIX_PAGE, "r", encoding="utf-8") as handle:
            page = handle.read()
        with open(MATRIX_STREAM_HOOK, "r", encoding="utf-8") as handle:
            stream_hook = handle.read()
        with open(MATRIX_GATE, "r", encoding="utf-8") as handle:
            gate = handle.read()

        self.assertIn("useMatrixStream(true)", page)
        self.assertIn("matrixApi.status()", stream_hook)
        self.assertIn("matrixApi.watch()", stream_hook)
        self.assertIn("matrixApi.dispatch", page)
        self.assertIn("matrixApi.emergencyStop", page)
        self.assertIn("selectedOnlineIds", page)
        self.assertIn("consumeNavigationContext('workbench')", page)
        self.assertIn("resolveMatrixNavigation", page)
        self.assertIn("licenseApi.authorized('matrix.devices')", gate)
        self.assertNotIn("licenseApi.authorized('matrix.devices')", page)
        combined = page + stream_hook
        self.assertNotIn("DEMO_WORKERS", combined)
        self.assertNotIn("FALLBACK_EVENTS", combined)
        self.assertNotIn("matrixDemoMode", combined)
        self.assertNotIn("success: 128", combined)

    def test_other_page_only_lists_unopened_capabilities(self) -> None:
        with open(CAPABILITIES_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("桌面 RPA", source)
        self.assertIn("平台发布", source)
        self.assertIn("任务库 / 定时任务", source)
        self.assertIn("主题配置", source)
        self.assertNotIn("图片生成", source)
        self.assertNotIn("视频生成", source)
        self.assertNotIn("CLI 自动化", source)
        self.assertNotIn("Agent 接入", source)

    def test_shell_distinguishes_acquisition_and_workbench_icons_and_uses_dark_titlebar(self) -> None:
        with open(SIDEBAR_FILE, "r", encoding="utf-8") as handle:
            sidebar = handle.read()
        with open(TITLEBAR_FILE, "r", encoding="utf-8") as handle:
            titlebar = handle.read()

        self.assertIn("if (key === 'acquisition') return 'target';", sidebar)
        self.assertIn("if (key === 'workbench') return 'matrix';", sidebar)
        self.assertIn("'target'", sidebar)
        self.assertIn("name === 'target'", sidebar)
        self.assertIn("bg-app-sidebar text-white", titlebar)
        self.assertIn("flex min-w-0 flex-1 items-stretch justify-end bg-app-sidebar", titlebar)
        self.assertIn("text-white/58 hover:bg-white/[0.07] hover:text-white", titlebar)
        self.assertIn("text-white/60 hover:bg-[#E81123] hover:text-white", titlebar)
        self.assertNotIn("flex-1 items-stretch justify-end bg-surface", titlebar)
        self.assertNotIn("text-text-muted", titlebar)
        self.assertNotIn("hover:bg-hover", titlebar)


if __name__ == "__main__":
    unittest.main()
