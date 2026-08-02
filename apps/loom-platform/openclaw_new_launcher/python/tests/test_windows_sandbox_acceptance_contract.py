from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


PLATFORM_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
SCRIPT_ROOT = os.path.join(PLATFORM_ROOT, "scripts")
PREPARE_SCRIPT = os.path.join(
    SCRIPT_ROOT, "prepare-windows-sandbox-acceptance.ps1"
)
BOOTSTRAP_SCRIPT = os.path.join(
    SCRIPT_ROOT, "windows-sandbox-bootstrap.ps1"
)
CHECKLIST = os.path.join(
    SCRIPT_ROOT, "windows-sandbox-acceptance-checklist.md"
)


class WindowsSandboxAcceptanceContractTests(unittest.TestCase):
    def _read(self, path: str) -> str:
        self.assertTrue(os.path.isfile(path), f"missing Windows Sandbox asset: {path}")
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    def test_preparer_maps_candidate_read_only_and_evidence_read_write(self) -> None:
        source = self._read(PREPARE_SCRIPT)
        for marker in (
            "MappedFolders",
            "C:\\LumingCandidate",
            "C:\\LumingHarness",
            "C:\\LumingEvidence",
            "ReadOnly",
            "Networking",
            "LogonCommand",
            "windows-sandbox-bootstrap.ps1",
            "Get-Sha256Hash",
            "WindowsSandbox.exe",
            "[switch]$Launch",
            "[switch]$Force",
        ):
            self.assertIn(marker, source)
        self.assertIn("Installer must stay inside CandidateDirectory", source)
        self.assertNotIn("Enable-WindowsOptionalFeature", source)
        self.assertNotIn("dism.exe /Online /Enable-Feature", source)

    def test_bootstrap_keeps_installer_interactive_and_records_safe_evidence(self) -> None:
        source = self._read(BOOTSTRAP_SCRIPT)
        for marker in (
            "Start-Transcript",
            "Get-Sha256Hash",
            "Get-AuthenticodeSignature",
            "Win32_OperatingSystem",
            "Start-Process",
            "Uninstall",
            "DisplayIcon",
            "installer-result.json",
            "runtime-environment.json",
        ):
            self.assertIn(marker, source)
        self.assertNotIn('ArgumentList = "/S"', source)
        self.assertNotIn("LICENSE_ZPAY_KEY", source)
        self.assertNotIn("LICENSE_ZPAY_PID", source)

    def test_checklist_covers_the_required_novice_click_paths_and_limits(self) -> None:
        source = self._read(CHECKLIST)
        for marker in (
            "2.4.5",
            "Codex Desktop",
            "Codex CLI",
            "ChatGPT Desktop",
            "在线权威状态",
            "绑定手机",
            "共享模板",
            "Skill 中心",
            "第二次调用",
            "获客",
            "飞书",
            "生成二维码",
            "我已付款",
            "重启恢复",
            "切换账号",
            "Windows Sandbox 不透传 USB",
            "不得进行真实扣款、退款或结算",
        ):
            self.assertIn(marker, source)

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("powershell.exe"),
        "PowerShell is required for Windows Sandbox preparation integration",
    )
    def test_preparer_generates_parseable_least_privilege_mapping(self) -> None:
        with tempfile.TemporaryDirectory(prefix="luming-wsb-") as root:
            candidate = os.path.join(root, "candidate")
            output = os.path.join(root, "evidence")
            os.makedirs(candidate)
            installer = os.path.join(candidate, "麓鸣_2.4.5_x64-setup.exe")
            payload = b"test installer placeholder"
            with open(installer, "wb") as handle:
                handle.write(payload)

            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    PREPARE_SCRIPT,
                    "-CandidateDirectory",
                    candidate,
                    "-Installer",
                    installer,
                    "-OutputDirectory",
                    output,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            tree = ET.parse(os.path.join(output, "Luming-2.4.5-Acceptance.wsb"))
            mappings = {
                item.findtext("SandboxFolder"): item.findtext("ReadOnly")
                for item in tree.findall("./MappedFolders/MappedFolder")
            }
            self.assertEqual(mappings["C:\\LumingCandidate"], "true")
            self.assertEqual(mappings["C:\\LumingHarness"], "true")
            self.assertEqual(mappings["C:\\LumingEvidence"], "false")
            self.assertEqual(tree.findtext("./Networking"), "Enable")

            with open(
                os.path.join(output, "sandbox-preparation.json"),
                "r",
                encoding="utf-8-sig",
            ) as handle:
                metadata = json.load(handle)
            self.assertEqual(
                metadata["installerSha256"], hashlib.sha256(payload).hexdigest().upper()
            )
            self.assertFalse(metadata["usbPassthrough"])

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("powershell.exe"),
        "PowerShell is required for Windows Sandbox preparation integration",
    )
    def test_preparer_rejects_installer_outside_read_only_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="luming-wsb-boundary-") as root:
            candidate = os.path.join(root, "candidate")
            output = os.path.join(root, "evidence")
            os.makedirs(candidate)
            installer = os.path.join(root, "outside.exe")
            with open(installer, "wb") as handle:
                handle.write(b"outside")

            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    PREPARE_SCRIPT,
                    "-CandidateDirectory",
                    candidate,
                    "-Installer",
                    installer,
                    "-OutputDirectory",
                    output,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "Installer must stay inside CandidateDirectory",
                completed.stdout + completed.stderr,
            )


if __name__ == "__main__":
    unittest.main()
