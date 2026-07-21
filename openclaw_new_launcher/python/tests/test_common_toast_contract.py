from __future__ import annotations

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMMON_FILE = os.path.join(REPO_ROOT, "src", "components", "common", "index.tsx")


class CommonToastContractTests(unittest.TestCase):
    def test_toasts_start_below_titlebar_and_stay_below_titlebar_layer(self) -> None:
        with open(COMMON_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-toast-container", source)
        self.assertIn("const TITLEBAR_HEIGHT_PX = 40", source)
        self.assertIn("const TOAST_SAFE_GAP_PX", source)
        self.assertIn("top: TITLEBAR_HEIGHT_PX + TOAST_SAFE_GAP_PX", source)
        self.assertIn("zIndex: TOAST_LAYER_Z_INDEX", source)

        layer_match = re.search(r"const TOAST_LAYER_Z_INDEX = ([\d_]+)", source)
        self.assertIsNotNone(layer_match)
        layer = int(layer_match.group(1).replace("_", ""))
        self.assertGreater(layer, 100)
        self.assertLess(layer, 100_000)


if __name__ == "__main__":
    unittest.main()
