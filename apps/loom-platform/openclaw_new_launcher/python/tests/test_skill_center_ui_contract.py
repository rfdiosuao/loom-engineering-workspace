from __future__ import annotations

import os
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PYTHON_DIR)
PAGE = os.path.join(ROOT, "src", "components", "skills", "SkillCenterPage.tsx")
API = os.path.join(ROOT, "src", "services", "api.ts")
REGISTRY = os.path.join(ROOT, "src", "features", "registry.ts")
PAGES = os.path.join(ROOT, "src", "features", "pages.tsx")


class SkillCenterUiContractTests(unittest.TestCase):
    def test_shared_skill_and_template_center_is_a_matrix_entitled_product_page(self) -> None:
        self.assertTrue(os.path.isfile(PAGE), PAGE)
        with open(PAGE, "r", encoding="utf-8") as handle:
            page = handle.read()
        with open(API, "r", encoding="utf-8") as handle:
            api = handle.read()
        with open(REGISTRY, "r", encoding="utf-8") as handle:
            registry = handle.read()
        with open(PAGES, "r", encoding="utf-8") as handle:
            pages = handle.read()

        for marker in (
            "data-shared-skill-center",
            "Skill 中心",
            "共享模板",
            "调用次数",
            "最近使用",
            "适用 Agent",
            "导入 Skill",
            "导出",
            "从成功任务沉淀",
            "expectedVersion",
            "绑定共享模板",
            "linkedTemplates",
            "templateVersion",
        ):
            self.assertIn(marker, page)
        self.assertIn("skillsApi", api)
        self.assertIn("/api/skills/export", api)
        self.assertIn("/api/skills/learn", api)
        self.assertIn("/api/skills/template", api)
        self.assertIn("setTemplateEnabled", api)
        self.assertIn("deleteTemplate", api)
        self.assertIn("key: 'skills'", registry)
        self.assertIn("requiresLicense: true", registry)
        self.assertIn("PhoneMatrixAccessGate", pages)
        self.assertIn("GuardedSkillCenterPage", pages)


if __name__ == "__main__":
    unittest.main()
