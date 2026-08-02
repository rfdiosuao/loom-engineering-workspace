from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from _support import LICENSE_SERVER_ROOT


DEPLOY_SCRIPT = LICENSE_SERVER_ROOT / "deploy.sh"
PACKAGE_SOURCE = LICENSE_SERVER_ROOT / "luming_license"


def _git_bash_path(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if len(resolved) >= 3 and resolved[1:3] == ":/":
        return f"/{resolved[0].lower()}/{resolved[3:]}"
    return resolved


class LicenseDeployIntegrationTests(unittest.TestCase):
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
        self.temp = tempfile.TemporaryDirectory(prefix="loom-license-deploy-")
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote"
        self.upload = self.root / "upload"
        self.package_upload = self.upload / "luming_license"
        self.fakebin = self.root / "fakebin"
        self.dropin = self.root / "systemd-dropin"
        for path in (self.remote, self.upload, self.fakebin, self.dropin):
            path.mkdir()
        (self.remote / "backups").mkdir()

        self.old_server = b"OLD_LICENSE_SERVER_MARKER = True\n"
        self.new_server = (LICENSE_SERVER_ROOT / "server.py").read_bytes()
        (self.remote / "server.py").write_bytes(self.old_server)
        (self.upload / "server.py").write_bytes(self.new_server)

        self.old_package = self.remote / "luming_license"
        self.old_package.mkdir()
        (self.old_package / "__init__.py").write_text(
            "OLD_LICENSE_PACKAGE_MARKER = True\n", encoding="utf-8"
        )
        shutil.copytree(
            PACKAGE_SOURCE,
            self.package_upload,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
        )

        self.database = self.remote / "license.db"
        with sqlite3.connect(self.database) as connection:
            connection.execute("create table deployment_marker(value text not null)")
            connection.execute("insert into deployment_marker values ('preserve-me')")

        self.environment = self.remote / "openclaw-license.env"
        self._write_environment(include_zpay=True)
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
                export LICENSE_REMOTE_DIR="$root/remote"
                export LICENSE_SERVER_UPLOAD="$root/upload/server.py"
                export LICENSE_PACKAGE_UPLOAD="$root/upload/luming_license"
                export LICENSE_DEPLOY_ENV_HELPER="$root/upload/luming_license/deploy_env.py"
                export LICENSE_ADMIN_HTML_UPLOAD="$root/upload/no-admin.html"
                export LICENSE_RELAY_ENV_FILE="$root/remote/openclaw-license.env"
                export LICENSE_DB="$root/remote/license.db"
                export LICENSE_LOCAL_BASE_URL="http://127.0.0.1:18791"
                export LICENSE_SYSTEMD_DROPIN_DIR="$root/systemd-dropin"
                export LICENSE_REQUIRE_ZPAY_READY=1
                export LICENSE_HEALTH_RETRY_ATTEMPTS=2
                export LICENSE_HEALTH_RETRY_DELAY_SEC=0
                bash "{_git_bash_path(DEPLOY_SCRIPT)}"
                """
            ),
            encoding="utf-8",
            newline="\n",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_environment(self, *, include_zpay: bool) -> None:
        zpay = ""
        if include_zpay:
            zpay = (
                "LICENSE_ZPAY_ENABLED=1\n"
                "LICENSE_ZPAY_BASE_URL=https://zpayz.cn\n"
                "LICENSE_ZPAY_PID=test-merchant-id\n"
                'LICENSE_ZPAY_KEY="test secret placeholder"\n'
                "LICENSE_ZPAY_CREATE_PATH=/mapi.php\n"
                "LICENSE_ZPAY_QUERY_ENABLED=1\n"
                "LICENSE_ZPAY_QUERY_PATH=/api.php\n"
                "LICENSE_ZPAY_NOTIFY_URL=https://license.example.invalid/api/payments/zpay/notify\n"
                "LICENSE_ZPAY_RETURN_URL=https://license.example.invalid/api/payments/zpay/return\n"
            )
        self.environment.write_text(
            "LICENSE_ACCOUNT_REDEEM_SERVICE_TOKEN=" + "t" * 40 + "\n" + zpay,
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
            fail_on_http=0
            output=""
            write_format=""
            url=""
            while [ "$#" -gt 0 ]; do
              case "$1" in
                -f|-fsS|-sfS|-sSf) fail_on_http=1; shift ;;
                -o) output="$2"; shift 2 ;;
                -w) write_format="$2"; shift 2 ;;
                http://*|https://*) url="$1"; shift ;;
                *) shift ;;
              esac
            done
            status=200
            body='{"ok":true}'
            case "$url" in
              */health)
                status="${FAKE_HEALTH_STATUS:-200}"
                body='{"ok":true,"service":"openclaw-license"}'
                ;;
              */api/service/account-entitlements/current)
                status="${FAKE_ENTITLEMENT_ROUTE_STATUS:-401}"
                body='{"ok":false,"code":"SERVICE_AUTH_REQUIRED"}'
                ;;
              */api/service/payments/plans)
                status="${FAKE_PAYMENT_ROUTE_STATUS:-401}"
                body='{"ok":false,"code":"SERVICE_AUTH_REQUIRED"}'
                ;;
              *) status=404; body='{"ok":false}' ;;
            esac
            if [ -n "$output" ]; then
              printf '%s' "$body" > "$output"
            elif [ -z "$write_format" ]; then
              printf '%s' "$body"
            fi
            if [ -n "$write_format" ]; then
              printf '%s' "$status"
            fi
            if [ "$fail_on_http" -eq 1 ] && [ "$status" -ge 400 ]; then
              exit 22
            fi
            """,
        )
        python_path = _git_bash_path(Path(sys.executable))
        self._write_executable(
            "python3",
            f"""\
            #!/bin/bash
            for name in PYTHONPYCACHEPREFIX DEPLOY_ENV_FILE DEPLOY_DB_SOURCE DEPLOY_DB_BACKUP; do
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
        environment.pop("OPENCLAW_PUBLISH_RELAY_TOKEN", None)
        environment.pop("PUBLISH_RELAY_TOKEN", None)
        environment.update(extra_environment)
        return subprocess.run(
            [str(self.bash), _git_bash_path(self.run_script)],
            cwd=LICENSE_SERVER_ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )

    def _database_marker(self) -> str:
        with sqlite3.connect(self.database) as connection:
            row = connection.execute("select value from deployment_marker").fetchone()
        return str(row[0])

    def test_valid_zpay_configuration_switches_complete_package(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("zpay=configured", result.stdout)
        self.assertIn("entitlement_route=ready", result.stdout)
        self.assertIn("payment_route=ready", result.stdout)
        self.assertEqual((self.remote / "server.py").read_bytes(), self.new_server)
        self.assertTrue(
            (self.remote / "luming_license" / "http" / "routes_payments.py").is_file()
        )
        self.assertEqual(self.environment.read_bytes(), self.original_environment)
        self.assertEqual(self._database_marker(), "preserve-me")
        self.assertTrue((self.dropin / "runtime-env.conf").is_file())
        backups = list((self.remote / "backups").glob("deploy-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "server.py").read_bytes(), self.old_server)

    def test_missing_zpay_configuration_fails_before_service_stop(self) -> None:
        self._write_environment(include_zpay=False)
        expected_environment = self.environment.read_bytes()
        result = self._run()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        self.assertIn("LICENSE_ZPAY_ENABLED", combined)
        self.assertNotIn("test-merchant-id", combined)
        self.assertEqual((self.remote / "server.py").read_bytes(), self.old_server)
        self.assertEqual(self.environment.read_bytes(), expected_environment)
        self.assertEqual(self._database_marker(), "preserve-me")
        self.assertFalse(self.systemctl_log.exists())

    def test_missing_payment_module_fails_before_service_stop(self) -> None:
        (self.package_upload / "http" / "routes_payments.py").unlink()
        result = self._run()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.remote / "server.py").read_bytes(), self.old_server)
        self.assertEqual(self.environment.read_bytes(), self.original_environment)
        self.assertFalse(self.systemctl_log.exists())

    def test_payment_route_smoke_failure_restores_old_program_and_package(self) -> None:
        result = self._run(FAKE_PAYMENT_ROUTE_STATUS="503")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.remote / "server.py").read_bytes(), self.old_server)
        self.assertTrue(
            (self.remote / "luming_license" / "__init__.py")
            .read_text(encoding="utf-8")
            .startswith("OLD_LICENSE_PACKAGE_MARKER")
        )
        self.assertEqual(self.environment.read_bytes(), self.original_environment)
        self.assertEqual(self._database_marker(), "preserve-me")
        actions = self.systemctl_log.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(actions.count("stop openclaw-license"), 2)
        self.assertGreaterEqual(actions.count("start openclaw-license"), 2)


if __name__ == "__main__":
    unittest.main()
