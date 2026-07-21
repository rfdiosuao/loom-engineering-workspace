from __future__ import annotations

import os
import re
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read(rel_path: str) -> str:
    with open(os.path.join(ROOT, rel_path), "r", encoding="utf-8") as handle:
        return handle.read()


class PhoneSignatureContractTests(unittest.TestCase):
    def test_secure_client_keeps_lumi_pairing_fields_and_endpoint(self) -> None:
        source = read("scripts/openclaw-phone-secure.mjs")

        self.assertIn("/api/lumi/security/pair", source)
        self.assertIn("lumiLauncherId", source)
        self.assertIn("lumiLauncherSecret", source)
        self.assertRegex(source, r"lumiLauncherId:\s*typeof item\.launcherId")
        self.assertRegex(source, r"lumiLauncherSecret:\s*typeof item\.launcherSecret")

    def test_secure_client_signs_requests_with_lumi_headers(self) -> None:
        source = read("scripts/openclaw-phone-secure.mjs")

        for header in (
            "X-LUMI-LAUNCHER-ID",
            "X-LUMI-TIMESTAMP",
            "X-LUMI-NONCE",
            "X-LUMI-BODY-SHA256",
            "X-LUMI-SIGNATURE",
        ):
            self.assertIn(header, source)
        self.assertRegex(source, r"createHmac\('sha256',\s*pairing\.launcherSecret\)")
        self.assertRegex(source, r"method\.toUpperCase\(\),\s*endpoint,\s*timestamp,\s*nonce,\s*bodyHash")

    def test_secure_client_repairs_pairing_once_after_signature_failure(self) -> None:
        source = read("scripts/openclaw-phone-secure.mjs")

        self.assertIn("response.status === 403 && retryPairing", source)
        self.assertIn("clearLumiPairingCache(config)", source)
        self.assertIn("config.lumiLauncherSecret = ''", source)
        self.assertIn("config.lumiLauncherId = ''", source)
        self.assertRegex(source, r"return signedJsonRequest\(config, method, endpoint, body, timeoutMs, false\)")

    def test_secure_client_persists_pairing_credentials_to_launcher_store(self) -> None:
        source = read("scripts/openclaw-phone-secure.mjs")

        self.assertIn("persistLumiPairing", source)
        self.assertIn("launcherId: data.launcherId", source)
        self.assertIn("launcherSecret: data.launcherSecret", source)
        self.assertRegex(source, r"await persistLumiPairing\(config,\s*data\)")

    def test_phone_agent_submission_uses_signed_lumi_task_routes(self) -> None:
        agent_source = read("scripts/openclaw-phone-agent.mjs")
        fleet_source = read("scripts/openclaw-phone-fleet.mjs")

        self.assertIn("signedJsonRequest(config, 'POST', '/api/lumi/agent/tasks'", agent_source)
        self.assertRegex(agent_source, r"/api/lumi/agent/tasks/\$\{encodeURIComponent\(taskId\)\}")
        self.assertIn("signedJsonRequest(device, 'POST', '/api/lumi/agent/tasks'", fleet_source)

    def test_phone_agent_event_stream_uses_signed_lumi_channel(self) -> None:
        agent_source = read("scripts/openclaw-phone-agent.mjs")
        core_source = read("scripts/lib/phone-command-core.mjs")

        self.assertIn("events-sync", agent_source)
        self.assertIn("syncPhoneEvents", agent_source)
        self.assertIn("printPhoneEventSyncSummary", agent_source)
        self.assertIn("if (config.command === 'events-sync')", agent_source)

        self.assertIn("syncPhoneEvents(config, onEvent)", core_source)
        self.assertIn("signedFetch", core_source)
        self.assertIn("'/api/lumi/events'", core_source)

    def test_phone_agent_event_stream_has_deadline_after_headers(self) -> None:
        core_source = read("scripts/lib/phone-command-core.mjs")

        self.assertIn("readSseChunksWithDeadline", core_source)
        self.assertIn("response.body.getReader()", core_source)
        self.assertIn("reader.cancel()", core_source)

    def test_signed_phone_scripts_forward_persisted_lumi_pairing_fields(self) -> None:
        for rel_path in (
            "scripts/openclaw-phone-agent.mjs",
            "scripts/openclaw-phone-vision.mjs",
            "scripts/openclaw-phone-game.mjs",
            "scripts/openclaw-phone-video.mjs",
        ):
            with self.subTest(script=rel_path):
                source = read(rel_path)
                self.assertRegex(source, r"lumiLauncherId:\s*firstNonEmpty")
                self.assertRegex(source, r"launcherPhone\.lumiLauncherId")
                self.assertRegex(source, r"lumiLauncherSecret:\s*firstNonEmpty")
                self.assertRegex(source, r"launcherPhone\.lumiLauncherSecret")
                self.assertRegex(source, r"source:\s*launcherPhone\.source")

    def test_phone_agent_supports_template_layer_without_forcing_model_agent(self) -> None:
        agent_source = read("scripts/openclaw-phone-agent.mjs")

        self.assertIn("templateName", agent_source)
        self.assertIn("executionLayer", agent_source)
        self.assertIn("stepTimeoutSec", agent_source)
        self.assertRegex(agent_source, r"use_template:\s*config\.executionLayer === 'template'")
        self.assertRegex(agent_source, r"force_agent:\s*config\.executionLayer === 'agent'")

    def test_phone_agent_can_import_launcher_phone_model_into_apkclaw(self) -> None:
        secure_source = read("scripts/openclaw-phone-secure.mjs")
        agent_source = read("scripts/openclaw-phone-agent.mjs")

        self.assertIn("readLauncherPhoneLlmConfig", secure_source)
        self.assertIn("readLauncherPhoneLlmConfig", agent_source)
        self.assertIn("/api/lumi/config/llm/import", agent_source)
        self.assertIn("config.command === 'config-sync'", agent_source)
        self.assertIn("stop?.code === 'model_not_configured'", agent_source)
        self.assertIn("importPhoneLlmConfig(config)", agent_source)
        self.assertIn("/api/lumi/config/llm/export", agent_source)
        self.assertIn("phoneHasUsableLlmConfig", agent_source)
        self.assertIn("apiKeyConfigured", agent_source)
        self.assertIn("local: publicPhoneLlmConfig(config)", agent_source)

    def test_phone_agent_distinguishes_uninitialized_agent_from_missing_model(self) -> None:
        agent_source = read("scripts/openclaw-phone-agent.mjs")

        self.assertIn("agent_not_initialized", agent_source)
        self.assertIn("phoneAgentRuntimeLooksReady", agent_source)
        self.assertRegex(agent_source, r"status\?\.agentInitialized === false[\s\S]+?!phoneAgentRuntimeLooksReady\(status\)[\s\S]+?agent_not_initialized")
        self.assertIn("stale_enabled_not_bound", agent_source)
        self.assertRegex(agent_source, r"status\?\.modelConfigured === false[\s\S]+?model_not_configured")
        self.assertRegex(agent_source, r"status\?\.llmConfigured === false[\s\S]+?model_not_configured")
        self.assertRegex(agent_source, r"status\?\.modelReady === false[\s\S]+?model_not_ready")

    def test_phone_bridge_errors_include_lan_config_preflight_guidance(self) -> None:
        secure_source = read("scripts/openclaw-phone-secure.mjs")
        agent_source = read("scripts/openclaw-phone-agent.mjs")
        daemon_source = read("scripts/openclaw-phone-daemon.mjs")

        self.assertIn("PhoneBridgeError", secure_source)
        self.assertIn("phoneBridgeErrorPayload", secure_source)
        self.assertIn("phone_config_server_unreachable", secure_source)
        self.assertIn("APKClaw -> Settings -> LAN Config", secure_source)
        self.assertIn("phoneBridgeErrorPayload(error", agent_source)
        self.assertIn("phoneBridgeErrorPayload(error", daemon_source)

    def test_phone_agent_serializes_mutating_actions_and_marks_stale_reads(self) -> None:
        core_source = read("scripts/lib/phone-command-core.mjs")

        self.assertIn("withDeviceMutationLock", core_source)
        self.assertIn("phone-action-locks", core_source)
        self.assertRegex(core_source, r"commandQueueKind\(config\) === QUEUE_KIND\.ACTION")
        self.assertIn("stalePossible", core_source)
        self.assertIn("读屏/截图允许并发", core_source)

    def test_phone_vision_supports_powershell_action_body_file_and_stdin(self) -> None:
        vision_source = read("scripts/openclaw-phone-vision.mjs")

        self.assertIn("--action-body-file", vision_source)
        self.assertIn("--action-body-stdin", vision_source)
        self.assertIn("readActionBodyText", vision_source)
        self.assertIn("invalid_action_body_json", vision_source)
        self.assertIn("PowerShell", vision_source)


if __name__ == "__main__":
    unittest.main()
