from __future__ import annotations

import os
import sys
import tempfile
import unittest


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core import component_state as component_state_module
from core.component_state import ComponentStateStore


class ComponentStateStoreTests(unittest.TestCase):
    def test_detection_evidence_round_trips_without_losing_nested_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ComponentStateStore(os.path.join(temp_dir, "components-state.json"))
            evidence = {
                "identity": "codex-desktop",
                "available": True,
                "healthy": True,
                "reason": "精确 Store 包与入口均通过",
                "nextAction": "可以启动",
                "items": [{"kind": "package", "label": "Store 包", "value": "OpenAI.Codex", "status": "ok"}],
            }

            store.mark("codex-desktop", "ready", version="26.721.4979.0", detection=evidence)

            loaded = store.load()["codex-desktop"]
            self.assertEqual(loaded.detection, evidence)

    def test_write_falls_back_when_windows_replace_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "components-state.json")
            store = ComponentStateStore(path)
            original_replace = component_state_module.os.replace

            def denied_replace(_source: str, _target: str) -> None:
                raise PermissionError(5, "Access is denied")

            component_state_module.os.replace = denied_replace
            try:
                state = store.mark("opencode", "ready", version="1.17.11")
            finally:
                component_state_module.os.replace = original_replace

            self.assertEqual(state.status, "ready")
            self.assertEqual(store.load()["opencode"].version, "1.17.11")


if __name__ == "__main__":
    unittest.main()
