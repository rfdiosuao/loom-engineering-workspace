from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class NativeAgentUiContractTests(unittest.TestCase):
    def _source(self, *parts: str) -> str:
        return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")

    def test_composer_has_no_external_runtime_selector(self) -> None:
        source = self._source("src", "components", "agent", "AgentComposer.tsx")

        self.assertNotIn("选择运行时", source)
        self.assertNotIn(">运行时<", source)
        self.assertNotIn("selectedRuntime", source)
        self.assertNotIn("bootstrap?.runtimeProfiles || []", source)
        self.assertNotIn("bootstrap?.capabilities", source)
        self.assertIn("<AgentModelMenu", source)
        self.assertIn("<AgentScopeMenu", source)

    def test_workbench_uses_native_readiness_and_compatibility_profile(self) -> None:
        source = self._source("src", "components", "agent", "AgentWorkbenchPage.tsx")

        self.assertNotIn("请选择已安装且可用的运行时", source)
        self.assertIn("麓鸣原生智能体尚未就绪，请先登录模型账号", source)
        self.assertIn("runtimeProfileId: 'loom-native'", source)
        self.assertIn("智能体状态读取失败", source)

    def test_header_identifies_native_agent_and_profile_error(self) -> None:
        source = self._source("src", "components", "agent", "AgentHeader.tsx")

        self.assertIn("麓鸣原生智能体", source)
        self.assertIn("profile.runtimeProfileId === 'loom-native'", source)
        self.assertIn("userFacingAgentError({ error: nativeProfile.error }).title", source)
        self.assertNotIn("nativeProfile?.error?.message", source)
        self.assertNotIn("未选择运行时", source)

    def test_runtime_profile_supports_safe_error(self) -> None:
        source = self._source("src", "types", "agent.ts")

        self.assertRegex(source, r"export interface AgentRuntimeProfile\s*\{[\s\S]*?error\?: AgentError;")


if __name__ == "__main__":
    unittest.main()
