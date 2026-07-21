from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

REPO_ROOT = os.path.dirname(PYTHON_DIR)


class CustomerAcquisitionMvpContractTests(unittest.TestCase):
    def test_acquisition_nav_page_and_api_contract_are_registered(self) -> None:
        registry_path = os.path.join(REPO_ROOT, "src", "features", "registry.ts")
        pages_path = os.path.join(REPO_ROOT, "src", "features", "pages.tsx")
        api_path = os.path.join(REPO_ROOT, "src", "services", "api.ts")
        routes_path = os.path.join(PYTHON_DIR, "api", "routes_matrix.py")

        with open(registry_path, "r", encoding="utf-8") as handle:
            registry = handle.read()
        with open(pages_path, "r", encoding="utf-8") as handle:
            pages = handle.read()
        with open(api_path, "r", encoding="utf-8") as handle:
            api = handle.read()
        with open(routes_path, "r", encoding="utf-8") as handle:
            routes = handle.read()

        acquisition_nav = next(line for line in registry.splitlines() if "key: 'acquisition'" in line)
        self.assertIn("label: '获客'", acquisition_nav)
        self.assertIn("action: { type: 'page' }", acquisition_nav)
        self.assertNotIn("requiresLicense", acquisition_nav)
        self.assertIn("AcquisitionWorkbenchPage", pages)
        self.assertIn("acquisitionApi", api)
        self.assertIn("/api/matrix/acquisition", api)
        self.assertIn("/api/matrix/acquisition/import", api)
        self.assertIn("/api/matrix/acquisition/demo", api)
        self.assertIn("/api/matrix/acquisition/draft/confirm", api)
        self.assertIn("/api/matrix/acquisition/draft/manual-send", api)
        self.assertIn("/api/matrix/acquisition/agent/run", api)
        self.assertIn("/api/matrix/acquisition/agent/result", api)
        self.assertIn("/api/matrix/acquisition/agent/result", routes)

    def test_acquisition_page_exposes_overview_feishu_and_ai_prompt_contract(self) -> None:
        page_path = os.path.join(REPO_ROOT, "src", "components", "acquisition", "AcquisitionWorkbenchPage.tsx")
        prompt_path = os.path.join(REPO_ROOT, "src", "components", "agentAccess", "agentPrompt.ts")

        with open(page_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        with open(prompt_path, "r", encoding="utf-8") as handle:
            prompt_source = handle.read()

        for marker in [
            "data-acquisition-workbench",
            "data-ai-executor-console",
            "data-acquisition-overview",
            "data-acquisition-matrix-overview",
            "data-matrix-capability-strip",
            "data-matrix-device-summary",
            "data-feishu-bitable-binding",
            "data-acquisition-agent-prompt",
            "data-feishu-sync-panel",
            "data-followup-log-panel",
            "data-acquisition-lead-pool",
            "data-acquisition-draft-review",
            "data-acquisition-task-log",
            "data-acquisition-stats",
            "获客总览",
            "多台手机矩阵获客总控",
            "线索发现",
            "AI 跟进草稿",
            "飞书沉淀",
            "飞书多维表格",
            "复制 AI 接入提示词",
            "AI 接入提示词",
            "showConfirm",
            "确认新建",
            "最近 Agent",
            "最近日志",
            "线索数",
            "客户数",
            "待确认草稿",
            "飞书待同步",
            "不会自动发送",
            "白名单",
            "频控",
            "matrixApi.status()",
            "Promise.allSettled",
            "setMatrixError",
            "matrixResult.status === 'fulfilled'",
            "snapshot.stats.pendingSync ?? feishu?.pendingCount ?? 0",
        ]:
            self.assertIn(marker, source)

        self.assertIn("buildOneShotAgentPrompt(buildMcpJson())", source)
        self.assertIn("await feishuApi.createTable(false)", source)
        self.assertIn("if (!ok) return", source)
        self.assertIn("await feishuApi.createTable(true)", source)
        self.assertIn("BEGIN_SKILL_LIBRARY", prompt_source)
        self.assertIn("luming-phone-agent", prompt_source)
        self.assertIn(
            "devices.filter((device) => device.online && Boolean(device.busy || device.currentTaskId)).length",
            source,
        )
        self.assertLess(source.index("if (!device.online)"), source.index("if (device.busy || device.currentTaskId)"))

        for removed_marketing_copy in [
            "AI PRIVATE TRAFFIC ACQUISITION",
            "多台手机矩阵，自动帮你发现潜在客户",
            "适合本地商家和销售团队",
            "自动找线索",
            "AI 写话术",
            "沉淀客户池",
        ]:
            self.assertNotIn(removed_marketing_copy, source)

        self.assertNotIn("autoSend", source)
        self.assertNotIn("batchSend", source)
        self.assertNotIn("本地试跑", source)
        self.assertNotIn("runDemo", source)
        self.assertNotIn("agent_task_ui_demo", source)
        self.assertNotIn("StepPanel", source)
        self.assertNotIn("data-acquisition-task-input", source)
        self.assertNotIn("data-agent-dispatch-panel", source)
        self.assertNotIn("data-agent-result-ingest", source)
        self.assertNotIn("生成手机任务", source)
        self.assertNotIn("写入线索池", source)
        self.assertNotIn("example.com/u/", source)
        self.assertNotIn("TikTok 装修意向客户", source)
        self.assertIn("数字来自本机真实状态，没有演示流", source)

    def test_acquisition_demo_flow_is_local_draft_only_and_redacted(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            flow = matrix.create_acquisition_demo_flow(
                {
                    "topic": "企业知识库获客",
                    "platform": "douyin",
                    "leadSummary": "用户想加微信 13800000000，邮箱 test@example.com，Bearer secret-token",
                    "channel": "comment",
                    "knowledge": "先确认场景，再给案例和预约入口。",
                    "token": "secret-token",
                }
            )
            snapshot = matrix.acquisition_snapshot()
            confirmed = matrix.confirm_acquisition_draft(flow["draft"]["draftId"], {"operator": "demo"})

        serialized = json.dumps({"flow": flow, "snapshot": snapshot, "confirmed": confirmed}, ensure_ascii=False)
        self.assertEqual(snapshot["schema"], "loom.customer_acquisition.v1")
        self.assertEqual(flow["draft"]["status"], "pending_manual_review")
        self.assertEqual(confirmed["draft"]["status"], "approved_pending_manual_send")
        self.assertFalse(flow["draft"]["sendEnabled"])
        self.assertTrue(flow["draft"]["requiresHumanReview"])
        self.assertIn("manual_confirm", flow["draft"]["policy"])
        self.assertIn("frequency_cap", flow["draft"]["policy"])
        self.assertGreaterEqual(snapshot["stats"]["leads"], 1)
        self.assertGreaterEqual(snapshot["stats"]["draftsPending"], 1)
        self.assertGreaterEqual(len(snapshot["logs"]), 3)
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("13800000000", serialized)
        self.assertNotIn("test@example.com", serialized)

    def test_import_real_leads_creates_scored_drafts_and_feishu_rows(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        synced: list[dict] = []

        class FakeFeishu:
            def __init__(self, _paths):
                pass

            def status(self):
                return {"connected": True, "pendingCount": 0, "table": {"tableId": "tbl1"}, "auth": {"loggedIn": True}}

            def sync_lead(self, lead):
                synced.append(lead)
                return {"leadId": lead["leadId"], "syncStatus": "synced", "recordId": f"rec_{len(synced)}"}

        csv_text = "\n".join(
            [
                "平台,客户昵称,线索内容,主页链接",
                "douyin,装修张总,想了解装修行业获客报价和案例,https://example.com/u/1",
                "douyin,装修张总,想了解装修行业获客报价和案例,https://example.com/u/1",
                "xiaohongshu,美业老板,有没有美业私域方案，想先看案例,https://example.com/u/2",
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch("core.phone_matrix.FeishuAcquisitionIntegration", FakeFeishu):
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            result = matrix.import_acquisition_leads(
                {
                    "topic": "本地商家获客",
                    "platform": "douyin",
                    "channel": "comment",
                    "sourceText": csv_text,
                    "knowledge": "先问行业、城市和预算，再给试跑方案。",
                    "owner": "销售一组",
                }
            )
            snapshot = matrix.acquisition_snapshot()

        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(len(synced), 2)
        self.assertEqual(snapshot["stats"]["leads"], 2)
        self.assertEqual(snapshot["stats"]["customers"], 2)
        self.assertEqual(snapshot["stats"]["draftsPending"], 2)
        self.assertTrue(all(item["source"] == "manual_import" for item in result["leads"]))
        self.assertTrue(all(item["qualificationSource"] == "rules" for item in result["leads"]))
        self.assertTrue(all(item["intentLevel"] in {"high", "medium"} for item in result["leads"]))
        self.assertTrue(all(not draft["sendEnabled"] for draft in result["drafts"]))
        self.assertIn("manual_confirm", result["drafts"][0]["policy"])
        self.assertIn("飞书已同步 2 条", result["summary"])

    def test_concurrent_identical_imports_create_one_local_and_remote_lead(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        sync_calls: list[str] = []
        calls_lock = threading.Lock()

        class FakeFeishu:
            def __init__(self, _paths):
                pass

            def status(self):
                return {"connected": True, "pendingCount": 0, "pendingVerificationCount": 0, "table": {}, "auth": {}}

            def sync_lead(self, lead):
                with calls_lock:
                    sync_calls.append(str(lead["dedupeKey"]))
                time.sleep(0.15)
                return {"leadId": lead["leadId"], "syncStatus": "synced", "recordId": "rec-once"}

        payload = {
            "topic": "并发线索导入",
            "platform": "douyin",
            "channel": "comment",
            "rows": [
                {
                    "nickname": "装修客户",
                    "summary": "想了解装修获客报价和案例",
                    "profileUrl": "https://example.com/u/concurrent",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch("core.phone_matrix.FeishuAcquisitionIntegration", FakeFeishu):
            paths = AppPaths(base_path=temp_dir)
            matrices = [MatrixControlPlane(paths), MatrixControlPlane(paths)]
            start = threading.Barrier(2)

            def run_import(matrix):
                start.wait(timeout=5)
                return matrix.import_acquisition_leads(payload)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(run_import, matrices))
            snapshot = matrices[0].acquisition_snapshot()

        self.assertEqual(sum(item["imported"] for item in results), 1)
        self.assertEqual(sum(item["duplicates"] for item in results), 1)
        self.assertEqual(len(sync_calls), 1)
        self.assertEqual(snapshot["stats"]["leads"], 1)
        self.assertEqual(snapshot["stats"]["customers"], 1)
        self.assertEqual(snapshot["stats"]["draftsPending"], 1)

    def test_manual_send_record_updates_draft_customer_lead_and_logs(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            flow = matrix.create_acquisition_demo_flow({"topic": "装修获客", "leadSummary": "用户想看报价和案例"})
            confirmed = matrix.confirm_acquisition_draft(flow["draft"]["draftId"], {"operator": "sales"})
            result = matrix.record_acquisition_manual_send(
                confirmed["draft"]["draftId"],
                {
                    "operator": "sales",
                    "outcome": "sent",
                    "reply": "客户回复想明天看方案",
                    "nextFollowUpAt": "2026-07-08 10:00",
                    "note": "已在 TikTok 私信手动发送",
                },
            )
            snapshot = result["snapshot"]

        self.assertEqual(result["draft"]["status"], "manual_sent")
        self.assertEqual(result["draft"]["manualSend"]["outcome"], "sent")
        self.assertFalse(result["draft"]["sendEnabled"])
        self.assertTrue(result["draft"]["requiresHumanReview"])
        self.assertEqual(snapshot["customers"][-1]["stage"], "replied")
        self.assertEqual(snapshot["customers"][-1]["lastReply"], "客户回复想明天看方案")
        self.assertEqual(snapshot["customers"][-1]["nextFollowUpAt"], "2026-07-08 10:00")
        self.assertEqual(snapshot["leads"][-1]["status"], "contacted")
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertIn("draft.manual_sent", serialized)
        self.assertNotIn("autoSend", serialized)

    def test_phone_agent_dry_run_result_enters_lead_pool_drafts_and_feishu(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        synced: list[dict] = []

        class FakeFeishu:
            def __init__(self, _paths):
                pass

            def status(self):
                return {"connected": True, "pendingCount": 0, "table": {"tableId": "tbl1"}, "auth": {"loggedIn": True}}

            def sync_lead(self, lead):
                synced.append(lead)
                return {"leadId": lead["leadId"], "syncStatus": "synced", "recordId": "rec_agent_1"}

        with tempfile.TemporaryDirectory() as temp_dir, patch("core.phone_matrix.FeishuAcquisitionIntegration", FakeFeishu):
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            result = matrix.run_acquisition_agent_task(
                {
                    "dryRun": True,
                    "topic": "TikTok 装修获客",
                    "platform": "tiktok",
                    "action": "discover_leads",
                    "deviceId": "phone-1",
                    "knowledge": "先确认城市和预算，再给案例。",
                    "agentResult": {
                        "schema": "loom.acquisition.agent_result.v1",
                        "taskId": "agent_task_001",
                        "deviceId": "phone-1",
                        "platform": "tiktok",
                        "action": "discover_leads",
                        "status": "pending_human_confirm",
                        "leads": [
                            {
                                "nickname": "海外装修用户",
                                "summary": "用户在 TikTok 评论区询问装修报价和案例",
                                "profileUrl": "https://example.com/tiktok/u/1",
                            }
                        ],
                        "drafts": [
                            {
                                "channel": "dm",
                                "body": "您好，看到您想了解装修报价，我可以先整理一份案例和预算范围供您确认。",
                                "requiresHumanReview": True,
                                "sendEnabled": False,
                            }
                        ],
                    },
                }
            )
            snapshot = result["snapshot"]

        self.assertTrue(result["agentRun"]["dryRun"])
        self.assertEqual(result["agentRun"]["status"], "pending_human_confirm")
        self.assertEqual(result["ingest"]["imported"], 1)
        self.assertEqual(len(synced), 1)
        self.assertEqual(snapshot["leads"][-1]["source"], "phone_agent")
        self.assertEqual(snapshot["leads"][-1]["agentTaskId"], "agent_task_001")
        self.assertEqual(snapshot["leads"][-1]["deviceId"], "phone-1")
        self.assertEqual(snapshot["drafts"][-1]["status"], "pending_manual_review")
        self.assertFalse(snapshot["drafts"][-1]["sendEnabled"])
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertIn("agent.result_ingested", serialized)
        self.assertNotIn("autoSend", serialized)

    def test_agent_result_unsafe_outbound_is_clamped_to_manual_review(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            ingest = matrix.ingest_acquisition_agent_result(
                {
                    "schema": "loom.acquisition.agent_result.v1",
                    "taskId": "agent_task_unsafe_001",
                    "deviceId": "phone-unsafe",
                    "platform": "tiktok",
                    "action": "discover_leads",
                    "status": "ready_to_send",
                    "requestedActions": ["send_dm", "post_comment"],
                    "leads": [{"nickname": "unsafe-lead", "summary": "wants quote"}],
                    "drafts": [
                        {
                            "channel": "dm",
                            "body": "unsafe draft",
                            "requiresHumanReview": False,
                            "sendEnabled": True,
                        }
                    ],
                },
                {"topic": "unsafe agent result", "platform": "tiktok", "deviceId": "phone-unsafe"},
            )
            snapshot = matrix.acquisition_snapshot()

        self.assertEqual(ingest["imported"], 1)
        self.assertEqual(snapshot["drafts"][-1]["status"], "pending_manual_review")
        self.assertFalse(snapshot["drafts"][-1]["sendEnabled"])
        self.assertTrue(snapshot["drafts"][-1]["requiresHumanReview"])
        self.assertIn("manual_confirm", snapshot["drafts"][-1]["policy"])
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertIn("agent.result_policy_clamped", serialized)
        self.assertNotIn('"sendEnabled": true', serialized)

    def test_phone_agent_run_prepares_safe_phone_task_payload(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            result = matrix.run_acquisition_agent_task(
                {
                    "dryRun": True,
                    "topic": "TikTok 装修获客",
                    "platform": "tiktok",
                    "action": "discover_leads",
                    "deviceId": "phone-7",
                    "target": "装修老板",
                    "knowledge": "只生成草稿，必须停在人工确认页。",
                }
            )
            phone_task = result["agentRun"]["phoneTask"]
            serialized = json.dumps(result["snapshot"], ensure_ascii=False)

        self.assertEqual(phone_task["schema"], "loom.acquisition.phone_task.v1")
        self.assertEqual(phone_task["target"]["deviceIds"], ["phone-7"])
        self.assertEqual(phone_task["platform"], "tiktok")
        self.assertEqual(phone_task["mode"], "safe")
        self.assertEqual(phone_task["stopAt"], "human_confirmation")
        self.assertEqual(phone_task["resultSchema"], "loom.acquisition.agent_result.v1")
        self.assertIn("read_public_content", phone_task["allowedActions"])
        self.assertIn("fill_draft", phone_task["allowedActions"])
        self.assertIn("send_dm", phone_task["forbiddenActions"])
        self.assertIn("post_comment", phone_task["forbiddenActions"])
        self.assertIn("add_friend", phone_task["forbiddenActions"])
        self.assertIn("publish_without_confirmation", phone_task["forbiddenActions"])
        self.assertIn("manual_confirm", phone_task["outboundPolicy"])
        self.assertFalse(phone_task["sendEnabled"])
        self.assertTrue(phone_task["requiresHumanReview"])
        self.assertEqual(phone_task["bridgeDispatch"]["method"], "POST")
        self.assertEqual(phone_task["bridgeDispatch"]["endpoint"], "/api/phone/task")
        self.assertEqual(phone_task["bridgeDispatch"]["body"]["mode"], "safe")
        self.assertEqual(phone_task["bridgeDispatch"]["body"]["executionLayer"], "agent")
        self.assertEqual(phone_task["bridgeDispatch"]["body"]["taskId"], phone_task["taskId"])
        self.assertEqual(phone_task["bridgeDispatch"]["body"]["target"]["deviceIds"], ["phone-7"])
        self.assertIn("loom.acquisition.agent_result.v1", phone_task["bridgeDispatch"]["body"]["prompt"])
        self.assertEqual(phone_task["bridgeDispatch"]["body"]["resultCallback"]["method"], "POST")
        self.assertEqual(phone_task["bridgeDispatch"]["body"]["resultCallback"]["endpoint"], "/api/matrix/acquisition/agent/result")
        self.assertEqual(phone_task["bridgeDispatch"]["body"]["resultCallback"]["payloadField"], "agentResult")
        self.assertIn("agent.task_prepared", serialized)

    def test_phone_agent_run_status_is_persisted_in_snapshot(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            result = matrix.run_acquisition_agent_task(
                {
                    "dryRun": True,
                    "topic": "RedNote 美业获客",
                    "platform": "rednote",
                    "action": "discover_leads",
                    "deviceId": "phone-2",
                    "target": "美业老板",
                }
            )
            snapshot = result["snapshot"]

        self.assertEqual(snapshot["agentRuns"][-1]["schema"], "loom.acquisition.agent_run.v1")
        self.assertEqual(snapshot["agentRuns"][-1]["deviceId"], "phone-2")
        self.assertEqual(snapshot["agentRuns"][-1]["platform"], "rednote")
        self.assertEqual(snapshot["agentRuns"][-1]["status"], "pending_human_confirm")
        self.assertEqual(snapshot["agentRuns"][-1]["phoneTask"]["stopAt"], "human_confirmation")
        self.assertFalse(snapshot["agentRuns"][-1]["sendEnabled"])
        self.assertTrue(snapshot["agentRuns"][-1]["requiresHumanReview"])
        self.assertEqual(result["ingest"]["imported"], 0)
        self.assertEqual(snapshot["stats"]["leads"], 0)
        self.assertEqual(snapshot["stats"]["customers"], 0)
        self.assertEqual(snapshot["stats"]["draftsPending"], 0)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("模拟线索", serialized)
        self.assertNotIn("example.com/agent-dry-run", serialized)

    def test_loom_cli_exposes_acquisition_agent_dry_run_command(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "acquisition",
                "agent-run",
                "--platform",
                "tiktok",
                "--topic",
                "TikTok 装修获客",
                "--device-id",
                "phone-1",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["method"], "POST")
        self.assertEqual(payload["data"]["endpoint"], "/api/matrix/acquisition/agent/run")
        self.assertTrue(payload["data"]["body"]["dryRun"])
        self.assertEqual(payload["data"]["body"]["platform"], "tiktok")
        preview = payload["data"]["body"]["phoneTaskPreview"]
        self.assertEqual(preview["schema"], "loom.acquisition.phone_task.v1")
        self.assertIn("taskId", preview)
        self.assertRegex(preview["taskId"], r"^agent_task_[0-9a-f]{10}$")
        self.assertIn("taskId", payload["data"]["body"])
        self.assertEqual(payload["data"]["body"]["taskId"], preview["taskId"])
        self.assertEqual(preview["target"]["deviceIds"], ["phone-1"])
        self.assertEqual(preview["stopAt"], "human_confirmation")
        self.assertFalse(preview["sendEnabled"])
        self.assertIn("fill_draft", preview["allowedActions"])
        self.assertIn("send_dm", preview["forbiddenActions"])
        self.assertIn("post_comment", preview["forbiddenActions"])
        self.assertEqual(preview["bridgeDispatch"]["endpoint"], "/api/phone/task")
        self.assertEqual(preview["bridgeDispatch"]["body"]["executionLayer"], "agent")
        self.assertEqual(preview["bridgeDispatch"]["body"]["taskId"], preview["taskId"])
        self.assertEqual(preview["bridgeDispatch"]["body"]["target"]["deviceIds"], ["phone-1"])
        self.assertEqual(preview["bridgeDispatch"]["body"]["resultCallback"]["endpoint"], "/api/matrix/acquisition/agent/result")
        self.assertEqual(preview["bridgeDispatch"]["body"]["resultCallback"]["payloadField"], "agentResult")

    def test_loom_cli_agent_result_posts_to_independent_ingest_endpoint(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "acquisition",
                "agent-result",
                "--platform",
                "tiktok",
                "--topic",
                "TikTok 瑁呬慨鑾峰",
                "--device-id",
                "phone-1",
                "--agent-result-json",
                json.dumps(
                    {
                        "schema": "loom.acquisition.agent_result.v1",
                        "taskId": "agent_task_cli_001",
                        "deviceId": "phone-1",
                        "platform": "tiktok",
                        "action": "discover_leads",
                        "status": "pending_human_confirm",
                        "leads": [{"nickname": "cli-lead", "summary": "wants quote"}],
                        "drafts": [{"channel": "dm", "body": "draft only", "sendEnabled": False}],
                    }
                ),
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["method"], "POST")
        self.assertEqual(payload["data"]["endpoint"], "/api/matrix/acquisition/agent/result")
        self.assertEqual(payload["data"]["body"]["agentResult"]["taskId"], "agent_task_cli_001")
        self.assertTrue(payload["data"]["body"]["dryRun"])
        self.assertFalse(payload["data"]["body"]["agentResult"]["drafts"][0]["sendEnabled"])

    def test_loom_cli_agent_result_requires_structured_result_json(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "acquisition",
                "agent-result",
                "--platform",
                "tiktok",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "missing_agent_result_json")

    def test_acquisition_agent_real_run_requires_explicit_confirmation(self) -> None:
        from core.paths import AppPaths
        from core.phone_matrix import MatrixControlPlane

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix = MatrixControlPlane(AppPaths(base_path=temp_dir))
            result = matrix.run_acquisition_agent_task(
                {
                    "dryRun": False,
                    "topic": "TikTok 装修获客",
                    "platform": "tiktok",
                    "deviceId": "phone-1",
                }
            )

        self.assertEqual(result["error"], "acquisition_agent_confirmation_required")
        self.assertFalse(result["executed"])
        self.assertIn("confirmed", result["message"])

    def test_loom_cli_real_agent_run_requires_confirmed_flag(self) -> None:
        from loom_cli import dispatch

        code, payload = dispatch(
            [
                "acquisition",
                "agent-run",
                "--platform",
                "tiktok",
                "--topic",
                "TikTok 装修获客",
                "--device-id",
                "phone-1",
                "--real-run",
                "--permission",
                "control",
                "--json",
                "--dry-run",
            ]
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "confirmation_required")


if __name__ == "__main__":
    unittest.main()
