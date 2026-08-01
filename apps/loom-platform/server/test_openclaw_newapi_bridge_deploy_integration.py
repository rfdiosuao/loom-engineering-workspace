from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parent
DEPLOY_SCRIPT = SERVER_ROOT / "deploy.sh"


def _git_bash_path(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if len(resolved) >= 3 and resolved[1:3] == ":/":
        return f"/{resolved[0].lower()}/{resolved[3:]}"
    return resolved


class BridgeDeployIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configured = os.environ.get("GIT_BASH_PATH", "").strip()
        candidates = (
            Path(configured) if configured else None,
            Path(r"D:\Git\bin\bash.exe"),
            Path(shutil.which("bash") or ""),
        )
        cls.bash = next((item for item in candidates if item and item.is_file()), None)
        if cls.bash is None:
            raise unittest.SkipTest("Git Bash or bash is required for deploy integration tests")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="loom-bridge-deploy-")
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote"
        self.upload = self.root / "upload"
        self.fakebin = self.root / "fakebin"
        self.remote.mkdir()
        self.upload.mkdir()
        self.fakebin.mkdir()
        (self.remote / "backups").mkdir()
        self.old_program = b"OLD_SERVER_MARKER = True\n"
        self.new_program = textwrap.dedent(
            """\
            #!/usr/bin/env python3
            def entitlement_key_payload():
                return {"keyId": "openclaw-ed25519-v1", "publicKey": "test-public-key"}
            NEW_SERVER_MARKER = True
            """
        ).encode("utf-8")
        (self.remote / "openclaw_newapi_bridge.py").write_bytes(self.old_program)
        (self.upload / "openclaw_newapi_bridge.py").write_bytes(self.new_program)
        self.private_key = self.root / "entitlement-private-key.b64"
        self.private_key.write_text("test-private-key-placeholder\n", encoding="utf-8")
        self.environment = self.remote / "bridge.env"
        self._write_environment(include_service_token=True)
        self.original_environment = self.environment.read_bytes()
        self.systemctl_log = self.root / "systemctl.log"
        self._write_fake_commands()
        self.run_script = self.root / "run.sh"
        self.run_script.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/bash
                set -euo pipefail
                root={_git_bash_path(self.root)}
                export PATH="$root/fakebin:$PATH"
                export FAKE_SYSTEMCTL_LOG="$root/systemctl.log"
                export FAKE_BRIDGE_HEALTH_COUNT_FILE="$root/curl-health-count"
                export BRIDGE_REMOTE_DIR="$root/remote"
                export BRIDGE_SERVER_UPLOAD="$root/upload/openclaw_newapi_bridge.py"
                export BRIDGE_ENV_FILE="$root/remote/bridge.env"
                export BRIDGE_LOCAL_BASE_URL="http://127.0.0.1:3016"
                export BRIDGE_READY_RETRY_ATTEMPTS=2
                export BRIDGE_READY_RETRY_DELAY_SEC=0
                bash "{_git_bash_path(DEPLOY_SCRIPT)}"
                """
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_environment(self, *, include_service_token: bool) -> None:
        token_line = (
            "OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_TOKEN=" + "t" * 40 + "\n"
            if include_service_token
            else ""
        )
        bind_db = str(self.root / "bridge-state.db").replace("\\", "/")
        private_key = str(self.private_key).replace("\\", "/")
        self.environment.write_text(
            token_line
            + "OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_BASE=https://license.example.invalid\n"
            + f"OPENCLAW_BIND_DB={bind_db}\n"
            + "OPENCLAW_BIND_TICKET_SECRET="
            + "s" * 40
            + "\n"
            + f"OPENCLAW_ENTITLEMENT_PRIVATE_KEY_FILE={private_key}\n"
            + "OPENCLAW_ENTITLEMENT_KEY_ID=openclaw-ed25519-v1\n",
            encoding="utf-8",
        )

    def _write_executable(self, name: str, source: str) -> None:
        target = self.fakebin / name
        target.write_text(textwrap.dedent(source), encoding="utf-8", newline="\n")
        target.chmod(0o755)

    def _write_fake_commands(self) -> None:
        self._write_executable(
            "systemctl",
            """\
            #!/bin/bash
            printf '%s\n' "$*" >> "$FAKE_SYSTEMCTL_LOG"
            exit 0
            """,
        )
        self._write_executable(
            "install",
            """\
            #!/bin/bash
            directory_mode=0
            while [ "$#" -gt 0 ]; do
              case "$1" in
                -d) directory_mode=1; shift ;;
                -m) shift 2 ;;
                *) break ;;
              esac
            done
            if [ "$directory_mode" -eq 1 ]; then
              mkdir -p "$1"
            else
              cp "$1" "$2"
            fi
            """,
        )
        self._write_executable(
            "curl",
            """\
            #!/bin/bash
            url="${!#}"
            case "$url" in
              */health)
                failures="${FAKE_BRIDGE_HEALTH_FAILS:-0}"
                count=0
                if [ -f "$FAKE_BRIDGE_HEALTH_COUNT_FILE" ]; then
                  count="$(cat "$FAKE_BRIDGE_HEALTH_COUNT_FILE")"
                fi
                if [ "$count" -lt "$failures" ]; then
                  printf '%s' "$((count + 1))" > "$FAKE_BRIDGE_HEALTH_COUNT_FILE"
                  exit 22
                fi
                printf '%s' '{"success":true,"service":"openclaw-newapi-bridge"}'
                ;;
              */api/openclaw/entitlements/public-key)
                if [ "${FAKE_BRIDGE_KEY_FAIL:-0}" = "1" ]; then
                  exit 22
                fi
                printf '%s' '{"success":true,"data":{"keyId":"openclaw-ed25519-v1","publicKey":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}}'
                ;;
              *) exit 22 ;;
            esac
            """,
        )
        python_path = _git_bash_path(Path(sys.executable))
        self._write_executable(
            "python3",
            f"""\
            #!/bin/bash
            for name in PYTHONPYCACHEPREFIX BRIDGE_ENV_FILE BRIDGE_SERVER_UPLOAD DEPLOY_HEALTH_JSON DEPLOY_KEY_JSON; do
              value="${{!name:-}}"
              if [ -n "$value" ] && [[ "$value" = /* ]]; then
                printf -v "$name" '%s' "$(cygpath -w "$value")"
                export "$name"
              fi
            done
            args=()
            for value in "$@"; do
              if [[ "$value" = /* ]] && [ -e "$value" ]; then
                args+=("$(cygpath -w "$value")")
              else
                args+=("$value")
              fi
            done
            exec "{python_path}" "${{args[@]}}"
            """,
        )

    def _run(self, **extra_environment: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment.update(extra_environment)
        return subprocess.run(
            [str(self.bash), _git_bash_path(self.run_script)],
            cwd=SERVER_ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )

    def test_success_switches_program_without_changing_environment(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("entitlement_config=ready", result.stdout)
        self.assertIn("entitlement_public_key=ready", result.stdout)
        self.assertIn("environment_unchanged=verified", result.stdout)
        self.assertEqual(
            (self.remote / "openclaw_newapi_bridge.py").read_bytes(),
            self.new_program,
        )
        self.assertEqual(self.environment.read_bytes(), self.original_environment)
        backups = list((self.remote / "backups").glob("deploy-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(
            (backups[0] / "openclaw_newapi_bridge.py").read_bytes(),
            self.old_program,
        )

    def test_delayed_health_readiness_does_not_roll_back(self) -> None:
        result = self._run(FAKE_BRIDGE_HEALTH_FAILS="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("readiness=ready attempts=2", result.stdout)
        self.assertEqual(
            (self.remote / "openclaw_newapi_bridge.py").read_bytes(),
            self.new_program,
        )

    def test_public_key_smoke_failure_restores_old_program(self) -> None:
        result = self._run(FAKE_BRIDGE_KEY_FAIL="1")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            (self.remote / "openclaw_newapi_bridge.py").read_bytes(),
            self.old_program,
        )
        self.assertEqual(self.environment.read_bytes(), self.original_environment)
        actions = self.systemctl_log.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(actions.count("stop openclaw-newapi-bridge"), 2)
        self.assertGreaterEqual(actions.count("start openclaw-newapi-bridge"), 2)

    def test_missing_configuration_fails_before_service_stop(self) -> None:
        self._write_environment(include_service_token=False)
        expected_environment = self.environment.read_bytes()
        result = self._run()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OPENCLAW_LICENSE_ENTITLEMENT_SERVICE_TOKEN", result.stderr)
        self.assertEqual(
            (self.remote / "openclaw_newapi_bridge.py").read_bytes(),
            self.old_program,
        )
        self.assertEqual(self.environment.read_bytes(), expected_environment)
        self.assertFalse(self.systemctl_log.exists())


if __name__ == "__main__":
    unittest.main()
