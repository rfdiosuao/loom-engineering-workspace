from __future__ import annotations

import os
import sys
import unittest

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from core.feature_access import feature_for_path


class StoryboardFeatureGateTests(unittest.TestCase):
    def test_storyboard_generate_requires_matrix_devices_feature(self) -> None:
        self.assertEqual(feature_for_path("/api/storyboard/generate"), "matrix.devices")

    def test_storyboard_get_param_config_is_unprotected(self) -> None:
        # GET-only read endpoints should not require a paid feature
        self.assertIsNone(feature_for_path("/api/storyboard/param-config"))

    def test_storyboard_import_is_unprotected(self) -> None:
        self.assertIsNone(feature_for_path("/api/storyboard/import-param-config"))


if __name__ == "__main__":
    unittest.main()
