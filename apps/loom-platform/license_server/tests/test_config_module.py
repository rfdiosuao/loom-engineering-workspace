from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from _support import LICENSE_SERVER_ROOT
from luming_license.config import Settings, bounded_int_env


class ConfigModuleTests(unittest.TestCase):
    def test_bounded_integer_falls_back_and_clamps(self) -> None:
        with patch.dict(os.environ, {"LIMIT": "invalid"}, clear=False):
            self.assertEqual(10, bounded_int_env("LIMIT", 10, 1, 20))
        with patch.dict(os.environ, {"LIMIT": "99"}, clear=False):
            self.assertEqual(20, bounded_int_env("LIMIT", 10, 1, 20))

    def test_settings_normalize_origins_and_paths(self) -> None:
        with patch.dict(os.environ, {
            "LICENSE_DB": "C:/tmp/license.db",
            "LICENSE_ADMIN_CORS_ORIGINS": "https://license.heang.top/, https://admin.example.com",
            "LICENSE_PORT": "19001",
        }, clear=False):
            settings = Settings.from_env()
        self.assertEqual(19001, settings.port)
        self.assertEqual("C:/tmp/license.db", settings.db_path)
        self.assertEqual(
            {"https://license.heang.top", "https://admin.example.com"},
            settings.admin_cors_allowed_origins,
        )
