from __future__ import annotations

import os
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(PYTHON_DIR)


class AcquisitionMatrixProductContractTests(unittest.TestCase):
    def test_acquisition_is_guarded_by_the_shared_matrix_entitlement(self) -> None:
        with open(os.path.join(ROOT, "src", "features", "registry.ts"), "r", encoding="utf-8") as handle:
            registry = handle.read()
        with open(os.path.join(ROOT, "src", "features", "pages.tsx"), "r", encoding="utf-8") as handle:
            pages = handle.read()

        acquisition = next(line for line in registry.splitlines() if "key: 'acquisition'" in line)
        self.assertIn("requiresLicense: true", acquisition)
        self.assertIn("GuardedAcquisitionWorkbenchPage", pages)
        self.assertIn("<PhoneMatrixAccessGate>", pages)
        self.assertIn("acquisition: GuardedAcquisitionWorkbenchPage", pages)

    def test_empty_acquisition_state_has_direct_novice_actions(self) -> None:
        page_path = os.path.join(ROOT, "src", "components", "acquisition", "AcquisitionWorkbenchPage.tsx")
        with open(page_path, "r", encoding="utf-8") as handle:
            page = handle.read()

        for marker in (
            "data-acquisition-empty-actions",
            "绑定手机",
            "打开手机矩阵",
            "选择模板",
            "排查连接",
            "openFeature('workbench')",
            "openFeature('skills')",
            "openFeature('agentAccess')",
        ):
            self.assertIn(marker, page)


if __name__ == "__main__":
    unittest.main()
