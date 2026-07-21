from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMMON_FILE = os.path.join(REPO_ROOT, "src", "components", "common", "index.tsx")
TITLEBAR_FILE = os.path.join(REPO_ROOT, "src", "components", "window", "WindowTitlebar.tsx")


class WindowChromeContractTests(unittest.TestCase):
    def test_titlebar_stays_above_overlays_and_preserves_drag_region(self) -> None:
        with open(TITLEBAR_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-window-drag-above-overlays", source)
        self.assertIn("relative z-[100000]", source)
        self.assertIn("data-tauri-drag-region", source)
        self.assertIn("onDoubleClick={toggleMaximize}", source)

    def test_blocking_busy_overlay_leaves_titlebar_drag_strip_uncovered(self) -> None:
        with open(COMMON_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-busy-overlay-mode={mode}", source)
        self.assertIn("fixed bottom-0 left-0 right-0 top-10", source)
        self.assertNotIn("fixed inset-0 z-[99940] flex items-center justify-center bg-[#071916]/64 px-6", source)


if __name__ == "__main__":
    unittest.main()
