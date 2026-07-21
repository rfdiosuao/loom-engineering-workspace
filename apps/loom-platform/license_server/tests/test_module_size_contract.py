from __future__ import annotations

import unittest

from _support import LICENSE_SERVER_ROOT


PACKAGE_ROOT = LICENSE_SERVER_ROOT / "luming_license"


class ModuleSizeContractTests(unittest.TestCase):
    def test_every_license_package_module_is_at_most_800_lines(self) -> None:
        oversized = {
            path.relative_to(LICENSE_SERVER_ROOT).as_posix(): len(
                path.read_text(encoding="utf-8").splitlines()
            )
            for path in PACKAGE_ROOT.rglob("*.py")
            if len(path.read_text(encoding="utf-8").splitlines()) > 800
        }

        self.assertEqual({}, oversized)
