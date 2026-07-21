from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
import zipfile


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.component_installer import ComponentInstallError, ComponentInstaller
from core.component_state import ComponentStateStore
from core.release_manifest import ReleaseComponent


def make_component(*, sha256: str, version: str = "1.0.0", urls: tuple[str, ...] = ("https://mirror.example/component.zip",)) -> ReleaseComponent:
    return ReleaseComponent(
        component_id="codex-cli",
        name="Codex CLI",
        version=version,
        platform="windows",
        arch="x64",
        archive_type="zip",
        size=100,
        sha256=sha256,
        urls=urls,
        install_path="OpenClawFiles/agents/codex-cli",
        entry="bin/codex.cmd",
    )


def make_zip(entries: dict[str, str]) -> bytes:
    with tempfile.NamedTemporaryFile(delete=False) as temp:
        temp_path = temp.name
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        with open(temp_path, "rb") as handle:
            return handle.read()
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ComponentInstallerTests(unittest.TestCase):
    def test_install_zip_component_extracts_files_and_marks_ready(self) -> None:
        package = make_zip({"bin/codex.cmd": "@echo codex"})

        with tempfile.TemporaryDirectory() as temp_dir:
            store = ComponentStateStore(os.path.join(temp_dir, "state.json"))
            installer = ComponentInstaller(
                base_path=temp_dir,
                state_store=store,
                fetcher=lambda url, timeout: package,
            )

            state = installer.install(make_component(sha256=sha256_bytes(package)))

            self.assertEqual(state.status, "ready")
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "OpenClawFiles", "agents", "codex-cli", "bin", "codex.cmd")))
            self.assertEqual(store.load()["codex-cli"].version, "1.0.0")

    def test_install_records_job_id_and_progress_callbacks(self) -> None:
        package = make_zip({"bin/codex.cmd": "@echo codex"})
        progress: list[tuple[str, str]] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            store = ComponentStateStore(os.path.join(temp_dir, "state.json"))
            installer = ComponentInstaller(
                base_path=temp_dir,
                state_store=store,
                fetcher=lambda url, timeout: package,
            )

            state = installer.install(
                make_component(sha256=sha256_bytes(package)),
                job_id="job_test",
                on_progress=lambda message, tone: progress.append((message, tone)),
            )

            self.assertEqual(state.status, "ready")
            self.assertEqual(state.job_id, "job_test")
            self.assertEqual(store.load()["codex-cli"].job_id, "job_test")
            self.assertTrue(any("Downloading" in message for message, _tone in progress))
            self.assertTrue(any(tone == "ok" for _message, tone in progress))

    def test_hash_mismatch_does_not_replace_existing_install(self) -> None:
        bad_package = make_zip({"bin/codex.cmd": "@echo bad"})

        with tempfile.TemporaryDirectory() as temp_dir:
            existing = os.path.join(temp_dir, "OpenClawFiles", "agents", "codex-cli", "bin")
            os.makedirs(existing, exist_ok=True)
            existing_file = os.path.join(existing, "codex.cmd")
            with open(existing_file, "w", encoding="utf-8") as handle:
                handle.write("@echo existing")

            store = ComponentStateStore(os.path.join(temp_dir, "state.json"))
            installer = ComponentInstaller(base_path=temp_dir, state_store=store, fetcher=lambda url, timeout: bad_package)

            with self.assertRaisesRegex(ComponentInstallError, "sha256"):
                installer.install(make_component(sha256="f" * 64))

            with open(existing_file, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "@echo existing")
            self.assertEqual(store.load()["codex-cli"].status, "verify_failed")

    def test_zip_path_traversal_is_rejected(self) -> None:
        package = make_zip({"../outside.txt": "nope"})

        with tempfile.TemporaryDirectory() as temp_dir:
            store = ComponentStateStore(os.path.join(temp_dir, "state.json"))
            installer = ComponentInstaller(base_path=temp_dir, state_store=store, fetcher=lambda url, timeout: package)

            with self.assertRaisesRegex(ComponentInstallError, "path traversal"):
                installer.install(make_component(sha256=sha256_bytes(package)))

            self.assertFalse(os.path.exists(os.path.join(temp_dir, "outside.txt")))
            self.assertEqual(store.load()["codex-cli"].status, "extract_failed")

    def test_rollback_restores_previous_component_directory(self) -> None:
        v1 = make_zip({"version.txt": "1"})
        v2 = make_zip({"version.txt": "2"})

        with tempfile.TemporaryDirectory() as temp_dir:
            store = ComponentStateStore(os.path.join(temp_dir, "state.json"))
            packages = {"https://mirror.example/v1.zip": v1, "https://mirror.example/v2.zip": v2}
            installer = ComponentInstaller(base_path=temp_dir, state_store=store, fetcher=lambda url, timeout: packages[url])

            installer.install(make_component(sha256=sha256_bytes(v1), version="1.0.0", urls=("https://mirror.example/v1.zip",)))
            installer.install(make_component(sha256=sha256_bytes(v2), version="2.0.0", urls=("https://mirror.example/v2.zip",)))
            state = installer.rollback("codex-cli")

            version_file = os.path.join(temp_dir, "OpenClawFiles", "agents", "codex-cli", "version.txt")
            with open(version_file, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "1")
            self.assertEqual(state.status, "ready")
            self.assertEqual(state.version, "1.0.0")


if __name__ == "__main__":
    unittest.main()
