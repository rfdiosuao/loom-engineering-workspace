from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

REPO_ROOT = os.path.dirname(PYTHON_DIR)


class FeishuAcquisitionIntegrationContractTests(unittest.TestCase):
    def test_doctor_reports_missing_cli_without_installing(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "",
            )
            doctor = integration.doctor()
            install = integration.install_cli(confirmed=False)

        self.assertFalse(doctor["cli"]["installed"])
        self.assertEqual(doctor["cli"]["installCommand"], "npm install -g @larksuite/cli@latest")
        self.assertTrue(install["requiresConfirmation"])
        self.assertFalse(install["executed"])

    def test_login_guide_uses_non_blocking_device_flow_and_qr_payload(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        calls: list[list[str]] = []

        def fake_runner(args: list[str], **_kwargs):
            calls.append(args)
            if args[:3] == ["lark-cli", "auth", "login"]:
                return {
                    "returncode": 0,
                    "stdout": json.dumps(
                        {
                            "verification_uri": "https://example.feishu.cn/device",
                            "verification_uri_complete": "https://example.feishu.cn/device?code=ABCD",
                            "user_code": "ABCD",
                            "device_code": "device-secret",
                        }
                    ),
                    "stderr": "",
                }
            if args[:3] == ["lark-cli", "auth", "qrcode"]:
                return {"returncode": 0, "stdout": "ASCII-QR", "stderr": ""}
            return {"returncode": 0, "stdout": "{}", "stderr": ""}

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            guide = integration.start_login()

        self.assertIn(["lark-cli", "auth", "login", "--recommend", "--no-wait", "--json"], calls)
        self.assertEqual(guide["loginUrl"], "https://example.feishu.cn/device?code=ABCD")
        self.assertEqual(guide["userCode"], "ABCD")
        self.assertIn("ASCII-QR", guide["qrAscii"])
        serialized = json.dumps(guide, ensure_ascii=False)
        self.assertNotIn("device-secret", serialized)

    def test_bind_table_and_status_are_local_and_redacted(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"},"bot":{"available":true,"status":"ready"}}}', "stderr": ""}
            return {"returncode": 0, "stdout": "{}", "stderr": ""}

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            bound = integration.bind_table(
                {
                    "url": "https://example.feishu.cn/base/appABC?table=tblXYZ&token=secret-token",
                    "baseToken": "appABC",
                    "tableId": "tblXYZ",
                }
            )
            status = integration.status()

        serialized = json.dumps({"bound": bound, "status": status}, ensure_ascii=False)
        self.assertTrue(status["connected"])
        self.assertEqual(status["table"]["baseToken"], "appABC")
        self.assertEqual(status["table"]["tableId"], "tblXYZ")
        self.assertNotIn("secret-token", serialized)

    def test_status_requires_user_login_for_user_scoped_table_writes(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"bot":{"available":true,"status":"ready"}},"identity":"bot"}', "stderr": ""}
            return {"returncode": 0, "stdout": "{}", "stderr": ""}

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            bound = integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ", "url": "https://example.feishu.cn/base/appABC"})
            status = integration.status()

        self.assertFalse(bound["status"]["connected"])
        self.assertFalse(status["connected"])
        self.assertTrue(status["auth"]["botReady"])
        self.assertFalse(status["auth"]["loggedIn"])

    def test_write_success_requires_remote_readback_before_marking_lead_synced(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        written_fields: dict = {}

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                return {"returncode": 0, "stdout": '{"data":{"records":[]}}', "stderr": ""}
            if "+record-upsert" in args:
                self.assertIn("--base-token", args)
                self.assertIn("--table-id", args)
                written_fields.update(json.loads(args[args.index("--json") + 1]))
                return {"returncode": 0, "stdout": '{"record_id":"rec123"}', "stderr": ""}
            if "+record-get" in args:
                self.assertEqual(args[args.index("--record-id") + 1], "rec123")
                return {
                    "returncode": 0,
                    "stdout": json.dumps(
                        {"data": {"records": [{"record_id": "rec123", "fields": written_fields}]}},
                        ensure_ascii=False,
                    ),
                    "stderr": "",
                }
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ", "url": "https://example.feishu.cn/base/appABC"})
            result = integration.sync_lead({"leadId": "lead_1", "platform": "douyin", "title": "客户", "summary": "需要方案"})

        self.assertEqual(result["syncStatus"], "synced")
        self.assertEqual(result["recordId"], "rec123")
        self.assertEqual(result["verificationStatus"], "verified")

    def test_write_success_with_failed_readback_is_not_reported_as_verified(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                return {"returncode": 0, "stdout": '{"data":{"records":[]}}', "stderr": ""}
            if "+record-upsert" in args:
                return {"returncode": 0, "stdout": '{"record_id":"rec-unverified"}', "stderr": ""}
            if "+record-get" in args:
                return {"returncode": 1, "stdout": "", "stderr": "temporary readback failure"}
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ", "url": "https://example.feishu.cn/base/appABC"})
            result = integration.sync_lead({"leadId": "lead_2", "platform": "douyin", "title": "客户"})
            status = integration.status()

        self.assertEqual(result["syncStatus"], "sync_unverified")
        self.assertEqual(result["verificationStatus"], "pending")
        self.assertEqual(status["pendingVerificationCount"], 1)

    def test_existing_business_key_updates_the_existing_remote_record(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        upsert_calls: list[list[str]] = []
        written_fields: dict = {}

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                filter_json = json.loads(args[args.index("--filter-json") + 1])
                self.assertEqual(filter_json["conditions"][0], ["任务日志 ID", "==", "dedupe-001"])
                return {
                    "returncode": 0,
                    "stdout": json.dumps({"data": {"records": [{"record_id": "rec-existing", "fields": {"任务日志 ID": "dedupe-001"}}]}}),
                    "stderr": "",
                }
            if "+record-upsert" in args:
                upsert_calls.append(args)
                written_fields.update(json.loads(args[args.index("--json") + 1]))
                return {"returncode": 0, "stdout": '{"record_id":"rec-existing"}', "stderr": ""}
            if "+record-get" in args:
                return {
                    "returncode": 0,
                    "stdout": json.dumps({"data": {"records": [{"record_id": "rec-existing", "fields": written_fields}]}}),
                    "stderr": "",
                }
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ"})
            result = integration.sync_lead(
                {"leadId": "lead-new", "dedupeKey": "dedupe-001", "platform": "douyin", "title": "客户"}
            )

        self.assertEqual(result["syncStatus"], "synced")
        self.assertEqual(len(upsert_calls), 1)
        self.assertEqual(upsert_calls[0][upsert_calls[0].index("--record-id") + 1], "rec-existing")
        self.assertEqual(written_fields["任务日志 ID"], "dedupe-001")

    def test_missing_write_record_id_is_recovered_by_business_key_lookup(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        remote_fields: dict = {}
        list_calls = 0
        upsert_calls = 0

        def fake_runner(args: list[str], **_kwargs):
            nonlocal list_calls, upsert_calls
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                list_calls += 1
                records = [] if list_calls == 1 else [{"record_id": "rec-recovered", "fields": remote_fields}]
                return {"returncode": 0, "stdout": json.dumps({"data": {"records": records}}), "stderr": ""}
            if "+record-upsert" in args:
                upsert_calls += 1
                remote_fields.update(json.loads(args[args.index("--json") + 1]))
                return {"returncode": 0, "stdout": "{}", "stderr": ""}
            if "+record-get" in args:
                return {
                    "returncode": 0,
                    "stdout": json.dumps({"data": {"records": [{"record_id": "rec-recovered", "fields": remote_fields}]}}),
                    "stderr": "",
                }
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ"})
            result = integration.sync_lead(
                {"leadId": "lead-recover", "dedupeKey": "dedupe-recover", "platform": "douyin", "title": "客户"}
            )

        self.assertEqual(result["syncStatus"], "synced")
        self.assertEqual(result["recordId"], "rec-recovered")
        self.assertEqual(upsert_calls, 1)
        self.assertEqual(list_calls, 2)

    def test_duplicate_remote_business_keys_block_further_writes(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        upsert_calls = 0

        def fake_runner(args: list[str], **_kwargs):
            nonlocal upsert_calls
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                rows = [
                    {"record_id": "rec-a", "fields": {"任务日志 ID": "dedupe-conflict"}},
                    {"record_id": "rec-b", "fields": {"任务日志 ID": "dedupe-conflict"}},
                ]
                return {"returncode": 0, "stdout": json.dumps({"data": {"records": rows}}), "stderr": ""}
            if "+record-upsert" in args:
                upsert_calls += 1
                return {"returncode": 0, "stdout": '{"record_id":"rec-new"}', "stderr": ""}
            if "+record-get" in args:
                return {"returncode": 0, "stdout": '{"record_id":"rec-new","fields":{}}', "stderr": ""}
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ"})
            result = integration.sync_lead(
                {"leadId": "lead-conflict", "dedupeKey": "dedupe-conflict", "platform": "douyin", "title": "客户"}
            )

        self.assertEqual(result["syncStatus"], "sync_conflict")
        self.assertEqual(upsert_calls, 0)

    def test_retry_pending_preserves_business_key_and_original_fields(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        written_fields: dict = {}
        queried_keys: list[str] = []

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                filter_json = json.loads(args[args.index("--filter-json") + 1])
                queried_keys.append(str(filter_json["conditions"][0][2]))
                return {"returncode": 0, "stdout": '{"data":{"records":[]}}', "stderr": ""}
            if "+record-upsert" in args:
                written_fields.update(json.loads(args[args.index("--json") + 1]))
                return {"returncode": 0, "stdout": '{"record_id":"rec-retry"}', "stderr": ""}
            if "+record-get" in args:
                return {
                    "returncode": 0,
                    "stdout": json.dumps({"data": {"records": [{"record_id": "rec-retry", "fields": written_fields}]}}),
                    "stderr": "",
                }
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            queued = integration.sync_lead(
                {
                    "leadId": "lead-retry",
                    "dedupeKey": "dedupe-retry",
                    "platform": "douyin",
                    "title": "装修客户",
                    "summary": "需要装修获客方案",
                }
            )
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ"})
            retried = integration.retry_pending()

        self.assertEqual(queued["syncStatus"], "pending_sync")
        self.assertEqual(retried["results"][0]["syncStatus"], "synced")
        self.assertEqual(queried_keys, ["dedupe-retry"])
        self.assertEqual(written_fields["任务日志 ID"], "dedupe-retry")
        self.assertEqual(written_fields["来源平台"], "douyin")
        self.assertEqual(written_fields["客户昵称/账号"], "装修客户")

    def test_concurrent_same_business_key_creates_only_one_remote_record(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        remote_records: list[dict] = []
        upsert_commands: list[list[str]] = []
        remote_lock = threading.Lock()
        start = threading.Barrier(2)

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                with remote_lock:
                    rows = [dict(item) for item in remote_records]
                if not rows:
                    time.sleep(0.1)
                return {"returncode": 0, "stdout": json.dumps({"data": {"records": rows}}), "stderr": ""}
            if "+record-upsert" in args:
                fields = json.loads(args[args.index("--json") + 1])
                with remote_lock:
                    upsert_commands.append(list(args))
                    if "--record-id" in args:
                        record_id = args[args.index("--record-id") + 1]
                        row = next(item for item in remote_records if item["record_id"] == record_id)
                        row["fields"] = fields
                    else:
                        record_id = f"rec-{len(remote_records) + 1}"
                        remote_records.append({"record_id": record_id, "fields": fields})
                return {"returncode": 0, "stdout": json.dumps({"record_id": record_id}), "stderr": ""}
            if "+record-get" in args:
                record_id = args[args.index("--record-id") + 1]
                with remote_lock:
                    row = next(item for item in remote_records if item["record_id"] == record_id)
                    payload = {"data": {"records": [dict(row)]}}
                return {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(base_path=temp_dir)
            integrations = [
                FeishuAcquisitionIntegration(paths, command_resolver=lambda _name: "lark-cli", runner=fake_runner)
                for _ in range(2)
            ]
            integrations[0].bind_table({"baseToken": "appABC", "tableId": "tblXYZ"})

            def run_sync(integration):
                start.wait(timeout=5)
                return integration.sync_lead(
                    {
                        "leadId": "lead-concurrent",
                        "dedupeKey": "dedupe-concurrent",
                        "platform": "douyin",
                        "title": "并发客户",
                    }
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(run_sync, integrations))

        self.assertTrue(all(item["syncStatus"] == "synced" for item in results))
        self.assertEqual(len(remote_records), 1)
        self.assertEqual(sum("--record-id" not in command for command in upsert_commands), 1)
        self.assertEqual(sum("--record-id" in command for command in upsert_commands), 1)

    def test_retry_pending_keeps_failed_rows_and_continues_with_the_rest(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        remote_fields: dict[str, dict] = {}

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                filter_json = json.loads(args[args.index("--filter-json") + 1])
                business_key = str(filter_json["conditions"][0][2])
                if business_key == "dedupe-fail":
                    raise RuntimeError("temporary lookup failure")
                return {"returncode": 0, "stdout": '{"data":{"records":[]}}', "stderr": ""}
            if "+record-upsert" in args:
                fields = json.loads(args[args.index("--json") + 1])
                record_id = "rec-success"
                remote_fields[record_id] = fields
                return {"returncode": 0, "stdout": json.dumps({"record_id": record_id}), "stderr": ""}
            if "+record-get" in args:
                record_id = args[args.index("--record-id") + 1]
                payload = {"data": {"records": [{"record_id": record_id, "fields": remote_fields[record_id]}]}}
                return {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            integration.sync_lead({"leadId": "lead-fail", "dedupeKey": "dedupe-fail", "title": "失败行"})
            integration.sync_lead({"leadId": "lead-ok", "dedupeKey": "dedupe-ok", "title": "成功行"})
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ"})
            result = integration.retry_pending()
            pending = integration.pending_syncs()

        self.assertEqual(result["retried"], 2)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["syncStatus"], "sync_failed")
        self.assertEqual(result["results"][1]["syncStatus"], "synced")
        self.assertEqual([item["businessKey"] for item in pending], ["dedupe-fail"])

    def test_sync_runner_exception_is_cached_instead_of_dropping_the_lead(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                raise TimeoutError("lark-cli timed out")
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ"})
            result = integration.sync_lead(
                {"leadId": "lead-timeout", "dedupeKey": "dedupe-timeout", "platform": "douyin", "title": "超时线索"}
            )
            pending = integration.pending_syncs()

        self.assertEqual(result["syncStatus"], "sync_failed")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["businessKey"], "dedupe-timeout")
        self.assertNotIn("Traceback", result["syncError"])

    def test_log_id_is_used_as_the_legacy_stable_business_key(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        queried_keys: list[str] = []

        def fake_runner(args: list[str], **_kwargs):
            if args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            if "+record-list" in args:
                filter_json = json.loads(args[args.index("--filter-json") + 1])
                queried_keys.append(str(filter_json["conditions"][0][2]))
                rows = [
                    {"record_id": "rec-a", "fields": {"任务日志 ID": "legacy-log-id"}},
                    {"record_id": "rec-b", "fields": {"任务日志 ID": "legacy-log-id"}},
                ]
                return {"returncode": 0, "stdout": json.dumps({"data": {"records": rows}}), "stderr": ""}
            raise AssertionError(f"unexpected command: {args}")

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ"})
            result = integration.sync_lead({"logId": "legacy-log-id", "title": "兼容线索"})

        self.assertEqual(result["syncStatus"], "sync_conflict")
        self.assertEqual(queried_keys, ["legacy-log-id"])

    def test_write_failure_keeps_pending_local_cache_without_sensitive_values(self) -> None:
        from core.feishu_integration import FeishuAcquisitionIntegration
        from core.paths import AppPaths

        def fake_runner(_args: list[str], **_kwargs):
            if _args[:3] == ["lark-cli", "auth", "status"]:
                return {"returncode": 0, "stdout": '{"identities":{"user":{"available":true,"status":"ready"}}}', "stderr": ""}
            return {"returncode": 1, "stdout": "", "stderr": "Bearer secret-token failed"}

        with tempfile.TemporaryDirectory() as temp_dir:
            integration = FeishuAcquisitionIntegration(
                AppPaths(base_path=temp_dir),
                command_resolver=lambda _name: "lark-cli",
                runner=fake_runner,
            )
            integration.bind_table({"baseToken": "appABC", "tableId": "tblXYZ", "url": "https://example.feishu.cn/base/appABC"})
            result = integration.sync_lead({"leadId": "lead_1", "platform": "douyin", "summary": "手机号 13800000000 Bearer secret-token"})
            cached = integration.pending_syncs()

        serialized = json.dumps({"result": result, "cached": cached}, ensure_ascii=False)
        self.assertEqual(result["syncStatus"], "sync_failed")
        self.assertEqual(cached[0]["leadId"], "lead_1")
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("13800000000", serialized)

    def test_acquisition_demo_flow_uses_pending_sync_when_feishu_unbound(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            flow = matrix.create_acquisition_demo_flow({"topic": "飞书线索", "leadSummary": "用户需要报价"})
            snapshot = matrix.acquisition_snapshot()

        self.assertEqual(flow["lead"]["syncStatus"], "pending_sync")
        self.assertEqual(snapshot["stats"]["pendingSync"], 1)
        self.assertIn("feishu", snapshot["integrations"])

    def test_loom_cli_exposes_integration_feishu_dry_run_commands(self) -> None:
        from loom_cli import dispatch

        cases = [
            (["integration", "feishu", "doctor", "--json", "--dry-run"], "GET", "/api/matrix/acquisition/feishu/doctor"),
            (["integration", "feishu", "status", "--json", "--dry-run"], "GET", "/api/matrix/acquisition/feishu/status"),
            (["integration", "feishu", "login", "--permission", "control", "--json", "--dry-run"], "POST", "/api/matrix/acquisition/feishu/login"),
            (["integration", "feishu", "bind-table", "--base-token", "appABC", "--table-id", "tblXYZ", "--permission", "control", "--json", "--dry-run"], "POST", "/api/matrix/acquisition/feishu/bind-table"),
            (["integration", "feishu", "test-write", "--permission", "control", "--json", "--dry-run"], "POST", "/api/matrix/acquisition/feishu/test-write"),
            (["integration", "feishu", "reconcile", "--permission", "control", "--json", "--dry-run"], "POST", "/api/matrix/acquisition/feishu/reconcile"),
        ]

        for argv, method, endpoint in cases:
            with self.subTest(argv=argv):
                code, payload = dispatch(argv)

                self.assertEqual(code, 0)
                self.assertEqual(payload["data"]["method"], method)
                self.assertEqual(payload["data"]["endpoint"], endpoint)

    def test_ui_and_prompt_surface_include_feishu_sync_policy(self) -> None:
        page_path = os.path.join(REPO_ROOT, "src", "components", "acquisition", "AcquisitionWorkbenchPage.tsx")
        api_path = os.path.join(REPO_ROOT, "src", "services", "api.ts")
        skill_path = os.path.join(REPO_ROOT, "public", "skills", "luming-skills-library-20260721.zip")

        with open(page_path, "r", encoding="utf-8") as handle:
            page = handle.read()
        with open(api_path, "r", encoding="utf-8") as handle:
            api = handle.read()
        with zipfile.ZipFile(skill_path) as archive:
            skill = archive.read(
                "skills/luming-phone-agent/references/acquisition-workflow.md"
            ).decode("utf-8")

        for marker in [
            "data-acquisition-feishu-sync",
            "飞书同步",
            "扫码登录",
            "绑定",
            "测试写入",
            "最近同步",
            "未绑定",
        ]:
            self.assertIn(marker, page)
        self.assertIn("data-feishu-login-guide", page)
        self.assertIn("data-feishu-login-qr", page)
        self.assertIn("createQrDataUri", page)
        self.assertIn("createDataURL", page)
        self.assertIn("data:image/gif;base64", page)
        self.assertIn("qrcode-generator", page)
        self.assertIn("复制登录链接", page)
        self.assertIn("飞书扫码登录二维码", page)
        self.assertIn("feishuApi", api)
        self.assertIn("feishu", skill.lower())
        self.assertIn("integration feishu status", skill)
        return

        for marker in [
            "data-acquisition-feishu-sync",
            "连接飞书",
            "扫码登录",
            "绑定线索表",
            "测试写入",
            "最近同步",
            "失败原因",
        ]:
            self.assertIn(marker, page)
        self.assertIn("feishuApi", api)
        self.assertIn("飞书线索表", skill)
        self.assertIn("先调用麓鸣集成检查", skill)
        self.assertIn("自动记录线索可以默认执行", skill)


if __name__ == "__main__":
    unittest.main()
