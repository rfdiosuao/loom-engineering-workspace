from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import tomllib
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.paths import AppPaths
from core.storage import read_json
from core.wire_config import WireConfigError, WireService, build_wire_from_session
import core.wire_config as wire_config_module
from core.openclaw_model_sync import _text_model_ids, sync_openclaw_models_from_gateway_profile


def session_snapshot() -> dict:
    return {
        "source": "newapi_account",
        "memberId": "newapi:test-user",
        "memberName": "test@example.invalid",
        "gatewayBaseUrl": "https://api.heang.top/v1",
        "gatewayImageBaseUrl": "https://api.heang.top/v1",
        "gatewayDefaultModel": "qwen3.7-plus",
        "gatewayImageModel": "gpt-image-1",
        "gatewayVideoDraftModel": "agnes-video-v1",
        "gatewayModels": ["qwen3.7-plus", "gpt-4o", "gpt-image-1", "agnes-video-v1"],
        "memberToken": "sk-test-token-not-real",
        "gatewayImageAccessToken": "sk-test-token-not-real",
        "phoneAgent": {
            "baseUrl": "https://api.heang.top/v1",
            "apiKey": "sk-test-token-not-real",
            "model": "agnes-2.0-flash",
        },
        "gateway": {
            "classifiedModels": {
                "text": ["qwen3.7-plus", "gpt-4o"],
                "image": ["gpt-image-1"],
                "video": ["agnes-video-v1"],
            },
        },
    }


class WireServiceTests(unittest.TestCase):
    def test_user_environment_secret_uses_reg_sz_and_creates_environment_key(self) -> None:
        key = mock.MagicMock()
        key.__enter__.return_value = key
        fake_winreg = mock.MagicMock()
        fake_winreg.HKEY_CURRENT_USER = object()
        fake_winreg.KEY_SET_VALUE = 2
        fake_winreg.KEY_QUERY_VALUE = 1
        fake_winreg.REG_SZ = 1
        fake_winreg.REG_EXPAND_SZ = 2
        fake_winreg.CreateKeyEx.return_value = key
        fake_winreg.QueryValueEx.side_effect = FileNotFoundError

        with (
            mock.patch.object(wire_config_module.os, "name", "nt"),
            mock.patch.dict(sys.modules, {"winreg": fake_winreg}),
            mock.patch("core.wire_config._broadcast_user_env_change"),
        ):
            changed = wire_config_module._write_user_env_var("LOOM_CODEX_API_KEY", "not-a-real-key")

        self.assertTrue(changed)
        fake_winreg.CreateKeyEx.assert_called_once_with(
            fake_winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            fake_winreg.KEY_SET_VALUE | fake_winreg.KEY_QUERY_VALUE,
        )
        fake_winreg.SetValueEx.assert_called_once_with(key, "LOOM_CODEX_API_KEY", 0, fake_winreg.REG_SZ, "not-a-real-key")

    def test_default_text_model_prefers_glm52_coding_for_managed_accounts(self) -> None:
        session = {
            **session_snapshot(),
            "gatewayDefaultModel": "",
            "gateway": {
                "classifiedModels": {
                    "text": ["agnes-2.0-flash", "qwen3.7-plus", "glm-5.2-coding"],
                    "image": [],
                    "video": [],
                },
            },
        }

        wire = build_wire_from_session(session)

        self.assertEqual(wire["models"]["text"], "glm-5.2-coding")

    def test_openclaw_model_order_prefers_glm52_coding_when_no_explicit_default(self) -> None:
        models = _text_model_ids(["qwen3.7-plus", "glm-5.2-coding", "gpt-4o"])

        self.assertEqual(models[0], "glm-5.2-coding")

    def test_default_text_model_is_empty_when_managed_catalog_has_no_text_models(self) -> None:
        session = {
            **session_snapshot(),
            "gatewayDefaultModel": "",
            "gatewayModels": ["agnes-image-2.1-flash", "agnes-video-v2.0", "agnes-2.0-flash"],
            "gateway": {
                "classifiedModels": {
                    "text": [],
                    "image": ["agnes-image-2.1-flash"],
                    "video": ["agnes-video-v2.0"],
                },
            },
        }

        wire = build_wire_from_session(session)

        self.assertEqual(wire["models"]["text"], "")
        self.assertEqual(wire["modelLists"]["text"], [])

    def test_agent_sync_reports_clear_error_when_managed_catalog_has_no_text_models(self) -> None:
        session = {
            **session_snapshot(),
            "gatewayDefaultModel": "",
            "gatewayModels": ["agnes-image-2.1-flash", "agnes-video-v2.0", "agnes-2.0-flash"],
            "gateway": {
                "classifiedModels": {
                    "text": [],
                    "image": ["agnes-image-2.1-flash"],
                    "video": ["agnes-video-v2.0"],
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)

            result = service.sync_from_session(session, targets=("openclaw", "opencode", "codex", "claude"))
            errors = {item["target"]: item.get("error", "") for item in result["syncResults"]}

            self.assertEqual(result["wire"]["models"]["text"], "")
            self.assertIn("没有可用文本模型", errors["openclaw"])
            self.assertIn("没有可用文本模型", errors["opencode"])
            self.assertIn("没有可用文本模型", errors["codex"])
            self.assertIn("没有可用文本模型", errors["claude"])
            self.assertFalse(os.path.exists(os.path.join(paths.data_dir, ".codex", "config.toml")))
            self.assertFalse(os.path.exists(os.path.join(paths.data_dir, ".opencode", "opencode.json")))

    def test_sync_from_session_persists_public_wire_without_exposing_raw_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)

            result = service.sync_from_session(session_snapshot())
            public_wire = result["wire"]

            self.assertTrue(public_wire["ok"])
            self.assertEqual(public_wire["managedBy"], "heang_account")
            self.assertEqual(public_wire["provider"], "heang")
            self.assertEqual(public_wire["models"]["text"], "qwen3.7-plus")
            self.assertEqual(public_wire["models"]["phone"], "agnes-2.0-flash")
            self.assertNotIn("apiKey", json.dumps(public_wire))
            self.assertIn("tokenMasked", public_wire)

            with open(paths.wire_current, "r", encoding="utf-8") as handle:
                raw_text = handle.read()
            if os.name == "nt":
                self.assertNotIn("sk-test-token-not-real", raw_text)

    def test_sync_from_session_writes_managed_runtime_configs_and_keeps_video_locked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)

            result = service.sync_from_session(session_snapshot())
            targets = {item["target"]: item["ok"] for item in result["syncResults"]}

            self.assertTrue(targets["openclaw"])
            self.assertTrue(targets["opencode"])
            self.assertTrue(targets["phone"])
            self.assertTrue(targets["desktop"])
            self.assertTrue(targets["image"])

            auth_profiles = read_json(paths.auth_profiles, {})
            provider = auth_profiles["models"]["providers"]["member_gateway"]
            self.assertEqual(provider["managedBy"], "heang_account")
            self.assertEqual(provider["apiKey"], "sk-test-token-not-real")

            phone_config = read_json(os.path.join(paths.launcher_dir, "phone-agent.json"), {})
            self.assertEqual(phone_config["llm"]["managedBy"], "heang_account")
            self.assertEqual(phone_config["llm"]["model"], "agnes-2.0-flash")

            desktop_config = read_json(os.path.join(paths.launcher_dir, "desktop-agent.json"), {})
            self.assertEqual(desktop_config["provider"]["managedBy"], "heang_account")
            self.assertEqual(desktop_config["provider"]["model"], "qwen3.7-plus")

            image_config = read_json(paths.image_config, {})
            self.assertEqual(image_config["managedBy"], "heang_account")
            self.assertEqual(image_config["model"], "gpt-image-1")

            opencode_config = read_json(os.path.join(paths.data_dir, ".opencode", "opencode.json"), {})
            self.assertEqual(opencode_config["model"], "loom/qwen3.7-plus")
            opencode_provider = opencode_config["provider"]["loom"]
            self.assertEqual(opencode_provider["options"]["apiKey"], "{env:LOOM_OPENCODE_API_KEY}")
            self.assertNotIn("sk-test-token-not-real", json.dumps(opencode_config))

            self.assertFalse(os.path.exists(paths.video_config))
            self.assertFalse(os.path.exists(paths.videoapi_config))

    def test_sync_from_session_writes_codex_and_claude_launcher_configs_without_exposing_raw_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            secret = session_snapshot()["memberToken"]

            result = service.sync_from_session(session_snapshot())
            targets = {item["target"]: item["ok"] for item in result["syncResults"]}

            self.assertTrue(targets["codex"])
            self.assertTrue(targets["claude"])

            codex_config = os.path.join(paths.data_dir, ".codex", "config.toml")
            claude_settings = os.path.join(paths.data_dir, ".claude", "settings.json")
            self.assertTrue(os.path.isfile(codex_config))
            self.assertTrue(os.path.isfile(claude_settings))

            with open(codex_config, "r", encoding="utf-8") as handle:
                codex_text = handle.read()
            with open(claude_settings, "r", encoding="utf-8") as handle:
                claude_text = handle.read()

            self.assertIn('model = "qwen3.7-plus"', codex_text)
            self.assertIn('model_provider = "heang"', codex_text)
            self.assertIn("[model_providers.heang]", codex_text)
            self.assertIn('env_key = "LOOM_CODEX_API_KEY"', codex_text)
            self.assertIn('wire_api = "responses"', codex_text)
            self.assertNotIn('wire_api = "chat"', codex_text)
            self.assertNotIn(secret, codex_text)

            user_codex_config = os.path.join(paths.data_dir, ".codex-user", "config.toml")
            self.assertTrue(os.path.isfile(user_codex_config))
            with open(user_codex_config, "r", encoding="utf-8") as handle:
                user_codex_text = handle.read()
            self.assertEqual(user_codex_text, codex_text)

            claude_config = json.loads(claude_text)
            self.assertEqual(claude_config["env"]["ANTHROPIC_MODEL"], "qwen3.7-plus")
            self.assertEqual(claude_config["env"]["ANTHROPIC_BASE_URL"], "https://api.heang.top")
            self.assertEqual(claude_config["env"]["ANTHROPIC_AUTH_TOKEN"], "{env:LOOM_CLAUDE_API_KEY}")
            self.assertEqual(claude_config["env"]["ANTHROPIC_API_KEY"], "{env:LOOM_CLAUDE_API_KEY}")
            self.assertNotIn(secret, claude_text)

    def test_codex_user_config_merge_preserves_existing_desktop_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            user_codex_config = os.path.join(paths.data_dir, ".codex-user", "config.toml")
            os.makedirs(os.path.dirname(user_codex_config), exist_ok=True)
            with open(user_codex_config, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    "\n".join([
                        'model = "gpt-5.5"',
                        'model_reasoning_effort = "xinflo"',
                        'service_tier = "priority"',
                        'approval_policy = "never"',
                        'model_provider = "xinflo"',
                        "",
                        '[plugins."computer-use@openai-bundled"]',
                        "enabled = true",
                        "",
                        "[mcp_servers.node_repl]",
                        'command = "node_repl.exe"',
                        "",
                        "[model_providers.xinflo]",
                        'name = "xinflo"',
                        'base_url = "https://xinflo.com/v1"',
                        'env_key = "XINFLO_API_KEY"',
                        'wire_api = "responses"',
                        "",
                    ])
                )

            service = WireService(paths)
            service.sync_custom_provider(
                provider="xinflo",
                base_url="https://api.heang.top/v1",
                api_key="sk-test-token-not-real",
                text_model="qwen3.7-plus",
                targets=("codex",),
            )

            with open(user_codex_config, "r", encoding="utf-8") as handle:
                merged = handle.read()

            self.assertIn('model = "qwen3.7-plus"', merged)
            self.assertIn('model_provider = "xinflo"', merged)
            self.assertIn('model_reasoning_effort = "xinflo"', merged)
            self.assertIn('service_tier = "priority"', merged)
            self.assertIn('approval_policy = "never"', merged)
            self.assertIn('[plugins."computer-use@openai-bundled"]', merged)
            self.assertIn("[mcp_servers.node_repl]", merged)
            self.assertIn("[model_providers.xinflo]", merged)
            self.assertIn('base_url = "https://api.heang.top/v1"', merged)
            self.assertIn('env_key = "LOOM_CODEX_API_KEY"', merged)
            self.assertIn('wire_api = "responses"', merged)
            self.assertNotIn("sk-test-token-not-real", merged)

    def test_agent_env_keys_are_persisted_for_codex_claude_and_opencode_launches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            secret = session_snapshot()["memberToken"]

            with (
                mock.patch("core.wire_config._should_persist_user_env", return_value=True),
                mock.patch("core.wire_config._write_user_env_var") as write_env,
            ):
                service.sync_from_session(session_snapshot(), targets=("opencode", "codex", "claude"))

            calls = {(call.args[0], call.args[1]) for call in write_env.call_args_list}
            self.assertIn(("LOOM_OPENCODE_API_KEY", secret), calls)
            self.assertIn(("LOOM_CODEX_API_KEY", secret), calls)
            self.assertIn(("LOOM_CLAUDE_API_KEY", secret), calls)

    def test_clear_agent_user_env_keys_removes_codex_dotenv_secret_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            dotenv_path = os.path.join(
                os.path.dirname(wire_config_module._user_codex_config_path(paths)),
                ".env",
            )
            os.makedirs(os.path.dirname(dotenv_path), exist_ok=True)
            with open(dotenv_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("USER_SETTING=keep\nLOOM_CODEX_API_KEY=managed-key-not-real\n")

            wire_config_module.clear_agent_user_env_keys(paths)

            with open(dotenv_path, "r", encoding="utf-8") as handle:
                dotenv_text = handle.read()
            self.assertIn("USER_SETTING=keep", dotenv_text)
            self.assertIsNone(
                wire_config_module._read_dotenv_value(dotenv_path, "LOOM_CODEX_API_KEY")
            )

    def test_agent_model_sync_clears_stale_model_env_without_deleting_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            stale_env = {
                "OPENAI_MODEL": "agnes-2.0-flash",
                "ANTHROPIC_MODEL": "agnes-2.0-flash",
                "OPENAI_API_KEY": "sk-user-key-should-stay",
            }

            with (
                mock.patch.dict(os.environ, stale_env, clear=False),
                mock.patch("core.wire_config._should_persist_user_env", return_value=True),
                mock.patch("core.wire_config._delete_user_env_var") as delete_env,
                mock.patch("core.wire_config._write_user_env_var"),
            ):
                service.sync_from_session(session_snapshot(), targets=("codex", "claude", "opencode"))

                self.assertNotIn("OPENAI_MODEL", os.environ)
                self.assertNotIn("ANTHROPIC_MODEL", os.environ)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "sk-user-key-should-stay")

            deleted_names = {call.args[0] for call in delete_env.call_args_list}
            self.assertIn("OPENAI_MODEL", deleted_names)
            self.assertIn("ANTHROPIC_MODEL", deleted_names)
            self.assertNotIn("OPENAI_API_KEY", deleted_names)

    def test_codex_model_apply_batches_environment_changes_into_one_broadcast(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())

            with (
                mock.patch("core.wire_config._should_persist_user_env", return_value=True),
                mock.patch("core.wire_config._delete_user_env_var", return_value=True) as delete_env,
                mock.patch("core.wire_config._write_user_env_var", return_value=True) as write_env,
                mock.patch("core.wire_config._read_user_env_var", return_value=session_snapshot()["memberToken"]),
                mock.patch("core.wire_config._read_user_env_kind", return_value=None),
                mock.patch("core.wire_config._broadcast_user_env_change") as broadcast,
            ):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o")

            self.assertTrue(delete_env.call_count)
            self.assertEqual(write_env.call_count, 1)
            self.assertTrue(all(call.kwargs.get("broadcast") is False for call in delete_env.call_args_list))
            self.assertIs(write_env.call_args.kwargs.get("broadcast"), False)
            broadcast.assert_called_once_with()

    def test_identical_model_config_write_skips_backup_and_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "config.toml")
            text = 'model = "gpt-4o"\n'
            with open(config_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)

            with (
                mock.patch("core.wire_config._backup_text_file") as backup,
                mock.patch("core.wire_config._atomic_write_text") as atomic_write,
            ):
                result = wire_config_module._write_text_with_backup(config_path, text)

            self.assertEqual(result, "")
            backup.assert_not_called()
            atomic_write.assert_not_called()

    def test_openclaw_agent_model_config_writes_managed_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot())

            status = service.sync_agent_model_config("openclaw-companion", model="gpt-4o")

            self.assertTrue(status["configured"])
            self.assertEqual(status["model"], "gpt-4o")
            self.assertEqual(status["configPath"], paths.openclaw_config)

            openclaw_config = read_json(paths.openclaw_config, {})
            primary = openclaw_config["agents"]["defaults"]["model"]["primary"]
            self.assertTrue(primary.endswith("/gpt-4o"))
            providers = openclaw_config["models"]["providers"]
            self.assertTrue(any(provider.get("baseUrl") == "https://api.heang.top/v1" for provider in providers.values()))

    def test_agent_model_config_write_failure_restores_previous_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot())
            codex_config = os.path.join(paths.data_dir, ".codex", "config.toml")

            with open(codex_config, "r", encoding="utf-8") as handle:
                before = handle.read()

            with mock.patch("core.wire_config._atomic_write_text", side_effect=OSError("disk full")):
                with self.assertRaises(WireConfigError):
                    service.sync_agent_model_config("codex-desktop", model="gpt-4o")

            with open(codex_config, "r", encoding="utf-8") as handle:
                after = handle.read()
            self.assertEqual(after, before)

    def test_codex_remote_validation_failure_leaves_all_local_state_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            managed_path = service._agent_config_path("codex-desktop")
            user_path = wire_config_module._user_codex_config_path(paths)
            auth_path = os.path.join(os.path.dirname(user_path), "auth.json")
            metadata_path = service._agent_config_metadata_path("codex-desktop")
            os.makedirs(os.path.dirname(user_path), exist_ok=True)
            with open(user_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write('model = "official-model"\n')
            with open(auth_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write('{"tokens":{"access_token":"official-token-not-real"}}\n')
            with open(auth_path, "rb") as handle:
                before_auth = handle.read()

            with (
                mock.patch.dict(os.environ, {"LOOM_CODEX_API_KEY": "previous-key-not-real"}, clear=False),
                mock.patch(
                    "core.wire_config._probe_codex_provider",
                    side_effect=WireConfigError("remote_responses_probe_failed"),
                ),
            ):
                with self.assertRaisesRegex(WireConfigError, "remote_responses_probe_failed"):
                    service.sync_agent_model_config(
                        "codex-desktop",
                        model="gpt-4o",
                        validate_remote=True,
                    )
                self.assertEqual(os.environ["LOOM_CODEX_API_KEY"], "previous-key-not-real")

            self.assertFalse(os.path.exists(managed_path))
            self.assertFalse(os.path.exists(metadata_path))
            with open(user_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), 'model = "official-model"\n')
            with open(auth_path, "rb") as handle:
                self.assertEqual(handle.read(), before_auth)

    def test_codex_transaction_rolls_back_files_environment_and_metadata_on_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            managed_path = service._agent_config_path("codex-desktop")
            user_path = wire_config_module._user_codex_config_path(paths)
            metadata_path = service._agent_config_metadata_path("codex-desktop")
            for path, text in (
                (managed_path, 'model = "managed-before"\n'),
                (user_path, 'model = "user-before"\n'),
                (metadata_path, '{"configured":false,"marker":"before"}\n'),
            ):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)

            with (
                mock.patch.dict(os.environ, {"LOOM_CODEX_API_KEY": "previous-key-not-real"}, clear=False),
                mock.patch("core.wire_config._probe_codex_provider", return_value={
                    "baseUrl": "https://api.heang.top/v1",
                    "endpoint": "https://api.heang.top/v1/responses",
                    "httpStatus": 200,
                    "model": "gpt-4o",
                }),
                mock.patch("core.wire_config._should_persist_user_env", return_value=True),
                mock.patch("core.wire_config._read_user_env_var", return_value="previous-key-not-real"),
                mock.patch("core.wire_config._read_user_env_kind", return_value=None),
                mock.patch(
                    "core.wire_config._write_user_env_var",
                    side_effect=PermissionError("registry write blocked"),
                ),
                mock.patch("core.wire_config._restore_user_env_var") as restore_registry,
            ):
                with self.assertRaisesRegex(WireConfigError, "registry write blocked"):
                    service.sync_agent_model_config(
                        "codex-desktop",
                        model="gpt-4o",
                        validate_remote=True,
                    )
                self.assertEqual(os.environ["LOOM_CODEX_API_KEY"], "previous-key-not-real")
                restore_registry.assert_any_call(
                    "LOOM_CODEX_API_KEY",
                    "previous-key-not-real",
                    registry_kind=None,
                )

            expected = {
                managed_path: 'model = "managed-before"\n',
                user_path: 'model = "user-before"\n',
                metadata_path: '{"configured":false,"marker":"before"}\n',
            }
            for path, text in expected.items():
                with open(path, "r", encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), text)

    def test_codex_transaction_commits_only_after_remote_and_readback_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())

            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                status = service.sync_agent_model_config(
                    "codex-desktop",
                    model="gpt-4o",
                    validate_remote=True,
                )

            self.assertTrue(status["configured"])
            self.assertTrue(status["remoteVerified"])
            self.assertEqual(status["transactionState"], "committed")
            self.assertTrue(status["transactionId"])
            self.assertTrue(status["officialAuthUnchanged"])
            with open(status["userConfigPath"], "rb") as handle:
                parsed = tomllib.loads(handle.read().decode("utf-8"))
            self.assertEqual(parsed["model"], "gpt-4o")
            self.assertEqual(parsed["model_providers"]["heang"]["env_key"], "LOOM_CODEX_API_KEY")

    def test_codex_transaction_reports_and_preserves_existing_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_config_path = wire_config_module._user_codex_config_path(paths)
            codex_home = os.path.dirname(user_config_path)
            active_dir = os.path.join(codex_home, "sessions", "2026", "07")
            archived_dir = os.path.join(codex_home, "archived_sessions")
            os.makedirs(active_dir, exist_ok=True)
            os.makedirs(archived_dir, exist_ok=True)
            session_paths = (
                os.path.join(active_dir, "active.jsonl"),
                os.path.join(archived_dir, "archived.jsonl"),
            )
            for path in session_paths:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write('{"type":"session_meta"}\n')

            status = service.sync_agent_model_config("codex-desktop", model="gpt-4o")

            self.assertEqual(status["sessionPreservation"]["status"], "protected")
            self.assertEqual(status["sessionPreservation"]["totalThreads"], 2)
            self.assertEqual(status["sessionPreservation"]["baselineThreads"], 2)
            self.assertEqual(status["sessionPreservation"]["homePath"], codex_home)
            for path in session_paths:
                self.assertTrue(os.path.isfile(path))

    def test_codex_switching_relay_preserves_all_existing_session_files_and_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            codex_home = os.path.join(temp_dir, "customer-codex-home")
            active_path = os.path.join(
                codex_home,
                "sessions",
                "2026",
                "07",
                "old-relay-active.jsonl",
            )
            archived_path = os.path.join(
                codex_home,
                "archived_sessions",
                "old-relay-archived.jsonl",
            )
            index_path = os.path.join(codex_home, "session_index.jsonl")
            state_path = os.path.join(codex_home, "state_5.sqlite")
            expected_files = {
                active_path: b'{"type":"session_meta","provider":"old-relay"}\n',
                archived_path: b'{"type":"session_meta","provider":"older-relay"}\n',
                index_path: b'{"thread_id":"old-relay-thread"}\n',
                state_path: b"sqlite-session-index-sentinel",
            }
            for path, content in expected_files.items():
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(content)

            with mock.patch.dict(os.environ, {"CODEX_HOME": codex_home}, clear=False):
                service.sync_custom_provider(
                    provider="old-relay",
                    base_url="https://old-relay.example.invalid/v1",
                    api_key="sk-old-relay-not-real",
                    text_model="old-relay-model",
                    targets=(),
                )
                service.sync_agent_model_config(
                    "codex-desktop",
                    model="old-relay-model",
                )

                service.sync_custom_provider(
                    provider="new-relay",
                    base_url="https://new-relay.example.invalid/v1",
                    api_key="sk-new-relay-not-real",
                    text_model="new-relay-model",
                    targets=(),
                )
                status = service.sync_agent_model_config(
                    "codex-desktop",
                    model="new-relay-model",
                )

            self.assertEqual(status["baseUrl"], "https://new-relay.example.invalid/v1")
            self.assertEqual(status["sessionPreservation"]["status"], "protected")
            self.assertEqual(status["sessionPreservation"]["totalThreads"], 2)
            self.assertEqual(status["sessionPreservation"]["homePath"], codex_home)
            for path, expected in expected_files.items():
                with open(path, "rb") as handle:
                    self.assertEqual(handle.read(), expected)

    def test_codex_transaction_rolls_back_when_session_inventory_drops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_config_path = wire_config_module._user_codex_config_path(paths)
            os.makedirs(os.path.dirname(user_config_path), exist_ok=True)
            original_config = 'model = "customer-model"\n'
            with open(user_config_path, "w", encoding="utf-8") as handle:
                handle.write(original_config)
            baseline = {
                "componentId": "codex-desktop",
                "homePath": os.path.dirname(user_config_path),
                "totalThreads": 3,
                "indexes": {"stateDatabase": True},
            }
            reduced = {
                **baseline,
                "totalThreads": 2,
            }

            with mock.patch(
                "core.wire_config.capture_agent_session_inventory",
                side_effect=(baseline, reduced),
            ):
                with self.assertRaisesRegex(WireConfigError, "agent_session_count_decreased"):
                    service.sync_agent_model_config("codex-desktop", model="gpt-4o")

            with open(user_config_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original_config)

    def test_claude_transaction_rolls_back_config_and_environment_when_sessions_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            config_path = service._agent_config_path("claude-code")
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            original_config = '{"customerSetting":true}\n'
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(original_config)
            baseline = {
                "componentId": "claude-code",
                "homePath": os.path.join(temp_dir, "customer-claude"),
                "totalThreads": 4,
                "indexes": {},
            }
            reduced = {
                **baseline,
                "totalThreads": 3,
            }

            with (
                mock.patch.dict(os.environ, {"LOOM_CLAUDE_API_KEY": "customer-key"}, clear=False),
                mock.patch(
                    "core.wire_config.capture_agent_session_inventory",
                    side_effect=(baseline, reduced),
                ),
            ):
                with self.assertRaisesRegex(WireConfigError, "agent_session_count_decreased"):
                    service.sync_agent_model_config("claude-code", model="gpt-4o")
                self.assertEqual(os.environ.get("LOOM_CLAUDE_API_KEY"), "customer-key")

            with open(config_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original_config)

    def test_codex_transaction_writes_desktop_dotenv_and_preserves_existing_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_path = wire_config_module._user_codex_config_path(paths)
            dotenv_path = os.path.join(os.path.dirname(user_path), ".env")
            os.makedirs(os.path.dirname(dotenv_path), exist_ok=True)
            with open(dotenv_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("USER_SETTING=keep\nLOOM_CODEX_API_KEY=old-key-not-real\n")

            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                service.sync_agent_model_config(
                    "codex-desktop",
                    model="gpt-4o",
                    validate_remote=True,
                )

            with open(dotenv_path, "r", encoding="utf-8") as handle:
                dotenv_text = handle.read()
            self.assertIn("USER_SETTING=keep", dotenv_text)
            self.assertNotIn("old-key-not-real", dotenv_text)
            self.assertEqual(
                wire_config_module._read_dotenv_value(dotenv_path, "LOOM_CODEX_API_KEY"),
                session_snapshot()["memberToken"],
            )

    def test_disable_codex_model_config_restores_dotenv_key_without_losing_user_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_path = wire_config_module._user_codex_config_path(paths)
            dotenv_path = os.path.join(os.path.dirname(user_path), ".env")
            os.makedirs(os.path.dirname(dotenv_path), exist_ok=True)
            with open(dotenv_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("USER_SETTING=before\nLOOM_CODEX_API_KEY=previous-key-not-real\n")

            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                service.sync_agent_model_config(
                    "codex-desktop",
                    model="gpt-4o",
                    validate_remote=True,
                )
                with open(dotenv_path, "a", encoding="utf-8", newline="\n") as handle:
                    handle.write("USER_ADDED_AFTER_APPLY=keep\n")
                service.disable_agent_model_config("codex-desktop")

            with open(dotenv_path, "r", encoding="utf-8") as handle:
                dotenv_text = handle.read()
            self.assertIn("USER_SETTING=before", dotenv_text)
            self.assertIn("USER_ADDED_AFTER_APPLY=keep", dotenv_text)
            self.assertEqual(
                wire_config_module._read_dotenv_value(dotenv_path, "LOOM_CODEX_API_KEY"),
                "previous-key-not-real",
            )

    def test_codex_transaction_aborts_when_wire_is_cleared_during_remote_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            managed_path = service._agent_config_path("codex-desktop")
            user_path = wire_config_module._user_codex_config_path(paths)

            def clear_wire_during_probe(*_args, **_kwargs):
                os.remove(paths.wire_current)
                return {
                    "baseUrl": "https://api.heang.top/v1",
                    "endpoint": "https://api.heang.top/v1/responses",
                    "httpStatus": 200,
                    "model": "gpt-4o",
                }

            with (
                mock.patch.dict(os.environ, {"LOOM_CODEX_API_KEY": "before-logout"}, clear=False),
                mock.patch("core.wire_config._probe_codex_provider", side_effect=clear_wire_during_probe),
            ):
                with self.assertRaisesRegex(WireConfigError, "codex_wire_changed_during_validation"):
                    service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)
                self.assertEqual(os.environ.get("LOOM_CODEX_API_KEY"), "before-logout")

            self.assertFalse(os.path.exists(managed_path))
            self.assertFalse(os.path.exists(user_path))

    def test_codex_transaction_rejects_a_second_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())

            with (
                wire_config_module._exclusive_codex_config_lock(paths, timeout_seconds=0.2),
                mock.patch("core.wire_config.CODEX_TRANSACTION_LOCK_TIMEOUT_SECONDS", 0.02),
            ):
                with self.assertRaisesRegex(WireConfigError, "codex_config_busy"):
                    service.sync_agent_model_config("codex-desktop", model="gpt-4o")

    def test_new_service_recovers_an_interrupted_codex_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            managed_path = service._agent_config_path("codex-desktop")
            user_path = wire_config_module._user_codex_config_path(paths)
            metadata_path = service._agent_config_metadata_path("codex-desktop")
            for path, text in (
                (managed_path, 'model = "managed-before"\n'),
                (user_path, 'model = "user-before"\n'),
                (metadata_path, '{"marker":"before"}\n'),
            ):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
            journal = {
                "schemaVersion": 1,
                "transactionId": "interrupted-test",
                "componentId": "codex-desktop",
                "state": "verifying",
                "snapshots": {
                    "managedConfig": wire_config_module._snapshot_text_file(managed_path),
                    "userConfig": wire_config_module._snapshot_text_file(user_path),
                    "metadata": wire_config_module._snapshot_text_file(metadata_path),
                },
                "environment": {},
                "officialAuthPath": os.path.join(os.path.dirname(user_path), "auth.json"),
                "officialAuthSha256": "",
            }
            service._write_codex_transaction_journal(journal)
            for path in (managed_path, user_path, metadata_path):
                with open(path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write("partial transaction data\n")

            recovered = WireService(paths)

            self.assertIsInstance(recovered, WireService)
            expected = {
                managed_path: 'model = "managed-before"\n',
                user_path: 'model = "user-before"\n',
                metadata_path: '{"marker":"before"}\n',
            }
            for path, text in expected.items():
                with open(path, "r", encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), text)
            recovered_journal = read_json(service._codex_transaction_journal_path(), {})
            self.assertEqual(recovered_journal["state"], "rolled_back")
            self.assertTrue(recovered_journal["recoveredAfterRestart"])

    def test_recovery_required_blocks_new_transaction_and_preserves_original_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            journal = {
                "schemaVersion": 1,
                "transactionId": "must-not-be-overwritten",
                "componentId": "codex-desktop",
                "state": "recovery_required",
                "snapshots": {"managedConfig": {"path": "", "existed": False}},
                "environment": {},
            }
            service._write_codex_transaction_journal(journal)

            with self.assertRaisesRegex(WireConfigError, "codex_config_recovery_required"):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o")

            current = read_json(service._codex_transaction_journal_path(), {})
            self.assertEqual(current["transactionId"], "must-not-be-overwritten")
            self.assertEqual(current["state"], "recovery_required")

    def test_manual_rollback_is_write_ahead_and_records_recovery_required_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)

            def fail_restore(_journal):
                active = read_json(service._codex_transaction_journal_path(), {})
                self.assertEqual(active["state"], "rolling_back")
                raise OSError("simulated rollback interruption")

            with mock.patch("core.wire_config._restore_codex_transaction_snapshot", side_effect=fail_restore):
                with self.assertRaisesRegex(WireConfigError, "codex_config_recovery_required"):
                    service.rollback_agent_model_config("codex-desktop")

            failed = read_json(service._codex_transaction_journal_path(), {})
            self.assertEqual(failed["state"], "recovery_required")

    def test_manual_rollback_status_does_not_claim_another_rollback_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = WireService(AppPaths(temp_dir))
            service.sync_from_session(session_snapshot(), targets=())
            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)

            status = service.rollback_agent_model_config("codex-desktop")

            self.assertFalse(status["rollbackAvailable"])
            self.assertEqual(status["transactionState"], "manually_rolled_back")

    def test_recovery_required_status_is_never_reported_as_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = WireService(AppPaths(temp_dir))
            service.sync_from_session(session_snapshot(), targets=())
            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)
            journal = read_json(service._codex_transaction_journal_path(), {})
            journal["state"] = "recovery_required"
            service._write_codex_transaction_journal(journal)

            status = service.agent_model_config_status("codex-desktop")

            self.assertFalse(status["configured"])
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["transactionState"], "recovery_required")

    def test_manual_rollback_does_not_reject_a_later_official_codex_login(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_path = wire_config_module._user_codex_config_path(paths)
            auth_path = os.path.join(os.path.dirname(user_path), "auth.json")
            os.makedirs(os.path.dirname(auth_path), exist_ok=True)
            with open(auth_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write('{"account":"before"}\n')
            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)

            with open(auth_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write('{"account":"after"}\n')

            status = service.rollback_agent_model_config("codex-desktop")

            self.assertEqual(status["transactionState"], "manually_rolled_back")
            with open(auth_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"account":"after"}\n')

    def test_disable_codex_model_config_restores_official_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_path = wire_config_module._user_codex_config_path(paths)
            auth_path = os.path.join(os.path.dirname(user_path), "auth.json")
            managed_path = service._agent_config_path("codex-desktop")
            os.makedirs(os.path.dirname(user_path), exist_ok=True)
            official_config = 'model = "gpt-5.2-codex"\n[features]\nweb_search = true\n'
            with open(user_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(official_config)
            with open(auth_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write('{"tokens":{"access_token":"official-token-not-real"}}\n')
            with open(auth_path, "rb") as handle:
                official_auth = handle.read()

            with (
                mock.patch.dict(os.environ, {"LOOM_CODEX_API_KEY": "previous-value-not-real"}, clear=False),
                mock.patch("core.wire_config._probe_codex_provider", return_value={
                    "baseUrl": "https://api.heang.top/v1",
                    "endpoint": "https://api.heang.top/v1/responses",
                    "httpStatus": 200,
                    "model": "gpt-4o",
                }),
            ):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)
                status = service.disable_agent_model_config("codex-desktop")
                self.assertEqual(os.environ["LOOM_CODEX_API_KEY"], "previous-value-not-real")

            self.assertFalse(status["configured"])
            self.assertEqual(status["channelMode"], "official")
            self.assertEqual(status["managedBy"], "")
            self.assertEqual(status["wireManagedBy"], "heang_account")
            self.assertEqual(status["transactionState"], "official")
            self.assertFalse(os.path.exists(managed_path))
            with open(user_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), official_config)
            with open(auth_path, "rb") as handle:
                self.assertEqual(handle.read(), official_auth)

    def test_disable_after_repeated_codex_writes_restores_first_official_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_path = wire_config_module._user_codex_config_path(paths)
            os.makedirs(os.path.dirname(user_path), exist_ok=True)
            official_config = 'model = "gpt-5.2-codex"\n[features]\nweb_search = true\n'
            with open(user_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(official_config)

            def probe(base_url, _api_key, model):
                return {
                    "baseUrl": base_url,
                    "endpoint": f"{base_url}/responses",
                    "httpStatus": 200,
                    "model": model,
                }

            with mock.patch("core.wire_config._probe_codex_provider", side_effect=probe):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)
                service.sync_agent_model_config("codex-desktop", model="qwen3.7-plus", validate_remote=True)
                service.disable_agent_model_config("codex-desktop")

            with open(user_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), official_config)

    def test_disable_preserves_user_changes_made_after_loom_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_path = wire_config_module._user_codex_config_path(paths)
            os.makedirs(os.path.dirname(user_path), exist_ok=True)
            with open(user_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write('model = "gpt-5.2-codex"\n')

            with (
                mock.patch.dict(os.environ, {"LOOM_CODEX_API_KEY": "before-apply"}, clear=False),
                mock.patch("core.wire_config._probe_codex_provider", return_value={
                    "baseUrl": "https://api.heang.top/v1",
                    "endpoint": "https://api.heang.top/v1/responses",
                    "httpStatus": 200,
                    "model": "gpt-4o",
                }),
            ):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)
                with open(user_path, "a", encoding="utf-8", newline="\n") as handle:
                    handle.write('\n[mcp_servers.added_after_apply]\ncommand = "new-mcp"\n')
                os.environ["LOOM_CODEX_API_KEY"] = "user-changed-after-apply"
                service.disable_agent_model_config("codex-desktop")
                self.assertEqual(os.environ["LOOM_CODEX_API_KEY"], "user-changed-after-apply")

            with open(user_path, "r", encoding="utf-8") as handle:
                restored = handle.read()
            self.assertIn('model = "gpt-5.2-codex"', restored)
            self.assertIn("[mcp_servers.added_after_apply]", restored)
            self.assertIn('command = "new-mcp"', restored)

    def test_codex_lock_is_shared_for_same_user_config_across_launcher_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            shared_config = os.path.join(temp_dir, "shared-codex", "config.toml")
            paths_a = AppPaths(os.path.join(temp_dir, "launcher-a"))
            paths_b = AppPaths(os.path.join(temp_dir, "launcher-b"))
            with mock.patch.dict(os.environ, {"LOOM_CODEX_CONFIG_PATH": shared_config}, clear=False):
                with wire_config_module._exclusive_codex_config_lock(paths_a, timeout_seconds=0.2):
                    with self.assertRaisesRegex(WireConfigError, "codex_config_busy"):
                        with wire_config_module._exclusive_codex_config_lock(paths_b, timeout_seconds=0.02):
                            pass

    def test_disable_allows_official_auth_to_change_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_path = wire_config_module._user_codex_config_path(paths)
            auth_path = os.path.join(os.path.dirname(user_path), "auth.json")
            os.makedirs(os.path.dirname(user_path), exist_ok=True)
            with open(user_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write('model = "gpt-5.2-codex"\n')
            with open(auth_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write('{"account":"before"}\n')
            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)

            original_atomic_write = wire_config_module._atomic_write_text
            changed = False

            def change_auth_during_disable(path, text):
                nonlocal changed
                if not changed and path == service._codex_transaction_journal_path():
                    changed = True
                    with open(auth_path, "w", encoding="utf-8", newline="\n") as handle:
                        handle.write('{"account":"after"}\n')
                return original_atomic_write(path, text)

            with mock.patch("core.wire_config._atomic_write_text", side_effect=change_auth_during_disable):
                status = service.disable_agent_model_config("codex-desktop")

            self.assertEqual(status["channelMode"], "official")
            with open(auth_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"account":"after"}\n')

    def test_disable_rejects_unknown_custom_user_provider_without_managed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            user_path = wire_config_module._user_codex_config_path(paths)
            os.makedirs(os.path.dirname(user_path), exist_ok=True)
            with open(user_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join([
                    'model = "local-model"',
                    'model_provider = "local"',
                    '[model_providers.local]',
                    'name = "Local"',
                    'base_url = "http://127.0.0.1:11434/v1"',
                    'env_key = "LOCAL_API_KEY"',
                    '',
                ]))

            with self.assertRaisesRegex(WireConfigError, "codex_official_restore_unmanaged_config"):
                service.disable_agent_model_config("codex-desktop")

    def test_codex_status_detects_provider_and_environment_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_path = wire_config_module._user_codex_config_path(paths)
            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)
            with open(user_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join([
                    'model = "gpt-4o"',
                    'model_provider = "local"',
                    '[model_providers.local]',
                    'name = "Local"',
                    'base_url = "http://127.0.0.1:11434/v1"',
                    'env_key = "LOCAL_API_KEY"',
                    '',
                ]))
            os.environ.pop("LOOM_CODEX_API_KEY", None)

            status = service.agent_model_config_status("codex-desktop")

            self.assertFalse(status["configured"])
            self.assertEqual(status["channelMode"], "custom")
            self.assertFalse(status["userConfigSynchronized"])
            self.assertFalse(status["environmentSynchronized"])

    def test_custom_codex_apply_restores_previous_wire_when_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            previous_wire = service.current_public()

            with mock.patch(
                "core.wire_config._probe_codex_provider",
                side_effect=WireConfigError("remote_responses_probe_failed: http_401"),
            ):
                with self.assertRaisesRegex(WireConfigError, "remote_responses_probe_failed"):
                    service.sync_custom_agent_model_config(
                        "codex-desktop",
                        provider="Custom",
                        base_url="https://custom.example.invalid/v1",
                        api_key="sk-custom-not-real",
                        model="custom-text-model",
                    )

            self.assertEqual(service.current_public(), previous_wire)

    def test_disable_codex_model_config_without_snapshot_preserves_unrelated_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            user_path = wire_config_module._user_codex_config_path(paths)
            managed_path = service._agent_config_path("codex-desktop")
            auth_path = os.path.join(os.path.dirname(user_path), "auth.json")
            loom_config = "\n".join([
                'model = "gpt-4o"',
                'model_provider = "heang"',
                '',
                '[model_providers.heang]',
                'name = "LOOM"',
                'base_url = "https://api.heang.top/v1"',
                'env_key = "LOOM_CODEX_API_KEY"',
                'wire_api = "responses"',
                '',
                '[model_providers.local]',
                'name = "Local"',
                'base_url = "http://127.0.0.1:11434/v1"',
                'env_key = "LOCAL_API_KEY"',
                '',
                '[projects."D:/work"]',
                'trust_level = "trusted"',
                '',
            ])
            os.makedirs(os.path.dirname(user_path), exist_ok=True)
            os.makedirs(os.path.dirname(managed_path), exist_ok=True)
            with open(user_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(loom_config)
            with open(managed_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join([
                    'model = "gpt-4o"',
                    'model_provider = "heang"',
                    '',
                    '[model_providers.heang]',
                    'name = "LOOM"',
                    'base_url = "https://api.heang.top/v1"',
                    'env_key = "LOOM_CODEX_API_KEY"',
                    'wire_api = "responses"',
                    '',
                ]))
            with open(auth_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write('{"auth_mode":"chatgpt"}\n')
            with open(auth_path, "rb") as handle:
                official_auth = handle.read()

            with mock.patch.dict(os.environ, {"LOOM_CODEX_API_KEY": "managed-key-not-real"}, clear=False):
                status = service.disable_agent_model_config("codex-desktop")
                self.assertNotIn("LOOM_CODEX_API_KEY", os.environ)

            self.assertEqual(status["channelMode"], "official")
            self.assertEqual(status["transactionState"], "official")
            self.assertFalse(os.path.exists(managed_path))
            with open(user_path, "r", encoding="utf-8") as handle:
                restored = handle.read()
            self.assertNotIn('model_provider = "heang"', restored)
            self.assertNotIn("[model_providers.heang]", restored)
            self.assertIn("[model_providers.local]", restored)
            self.assertIn('[projects."D:/work"]', restored)
            with open(auth_path, "rb") as handle:
                self.assertEqual(handle.read(), official_auth)

    def test_codex_remote_probe_discovers_v1_and_verifies_selected_model(self) -> None:
        requests: list[tuple[str, str]] = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _send_json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization", "")))
                if self.path == "/v1/models":
                    self._send_json(200, {"data": [{"id": "glm-5.2-coding"}]})
                else:
                    self._send_json(404, {"error": "not found"})

            def do_POST(self):
                requests.append((self.path, self.headers.get("Authorization", "")))
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if (
                    self.path == "/v1/responses"
                    and payload.get("model") == "glm-5.2-coding"
                    and payload.get("tools", [{}])[0].get("name") == "loom_capability_probe"
                    and payload.get("tool_choice", {}).get("name") == "loom_capability_probe"
                ):
                    self._send_json(200, {
                        "id": "resp-test",
                        "status": "completed",
                        "output": [{
                            "type": "function_call",
                            "call_id": "call-probe",
                            "name": "loom_capability_probe",
                            "arguments": '{"probe":"codex-tools"}',
                        }],
                    })
                else:
                    self._send_json(404, {"error": "not found"})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = wire_config_module._probe_codex_provider(
                f"http://127.0.0.1:{server.server_port}",
                "test-key-not-real",
                "glm-5.2-coding",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertTrue(result["responsesVerified"])
        self.assertTrue(result["toolCallsVerified"])
        self.assertTrue(result["modelsVerified"])
        self.assertTrue(result["baseUrl"].endswith("/v1"))
        self.assertIn(("/v1/responses", "Bearer test-key-not-real"), requests)

    def test_codex_remote_probe_rejects_insecure_non_loopback_provider(self) -> None:
        with self.assertRaisesRegex(WireConfigError, "insecure_provider_url"):
            wire_config_module._probe_codex_provider(
                "http://example.invalid/v1",
                "test-key-not-real",
                "glm-5.2-coding",
            )

    def test_codex_remote_probe_uses_responses_as_authority_when_models_list_hides_alias(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _send_json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send_json(200, {"data": [{"id": "public-model-only"}]})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if payload.get("model") == "hidden-alias":
                    self._send_json(200, {
                        "id": "resp-hidden",
                        "status": "completed",
                        "output": [{
                            "type": "function_call",
                            "call_id": "call-hidden",
                            "name": "loom_capability_probe",
                            "arguments": {"probe": "codex-tools"},
                        }],
                    })
                else:
                    self._send_json(400, {"error": "bad model"})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = wire_config_module._probe_codex_provider(
                f"http://127.0.0.1:{server.server_port}/v1",
                "test-key-not-real",
                "hidden-alias",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertTrue(result["responsesVerified"])
        self.assertTrue(result["toolCallsVerified"])
        self.assertFalse(result["modelsVerified"])

    def test_codex_remote_probe_rejects_text_only_tool_call_output(self) -> None:
        with mock.patch(
            "core.wire_config._provider_json_request",
            side_effect=[
                {"data": [{"id": "qwen3.7-plus"}]},
                {
                    "id": "resp-text-only",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '<tool_call>{"name":"loom_capability_probe"}</tool_call>',
                                }
                            ],
                        }
                    ],
                },
            ],
        ):
            with self.assertRaisesRegex(WireConfigError, "responses_tool_call_missing"):
                wire_config_module._probe_codex_provider(
                    "https://api-cn.heang.top/v1",
                    "test-key-not-real",
                    "qwen3.7-plus",
                )

    def test_codex_remote_probe_rejects_http_200_error_payload(self) -> None:
        with mock.patch(
            "core.wire_config._provider_json_request",
            side_effect=[
                {"data": [{"id": "gpt-4o"}]},
                {"error": {"message": "model unavailable"}},
            ],
        ):
            with self.assertRaisesRegex(WireConfigError, "remote_responses_probe_failed"):
                wire_config_module._probe_codex_provider(
                    "https://api.heang.top/v1",
                    "test-key",
                    "gpt-4o",
                )

    def test_codex_remote_probe_rejects_failed_or_incomplete_success_payload(self) -> None:
        for responses_payload in ({"status": "failed"}, {"id": "resp-without-output"}):
            with self.subTest(responses_payload=responses_payload):
                with mock.patch(
                    "core.wire_config._provider_json_request",
                    side_effect=[
                        {"data": [{"id": "gpt-4o"}]},
                        responses_payload,
                    ],
                ):
                    with self.assertRaisesRegex(WireConfigError, "remote_responses_probe_failed"):
                        wire_config_module._probe_codex_provider(
                            "https://api.heang.top/v1",
                            "test-key",
                            "gpt-4o",
                        )

    def test_codex_user_config_merge_accepts_quoted_provider_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot(), targets=())
            user_path = wire_config_module._user_codex_config_path(paths)
            os.makedirs(os.path.dirname(user_path), exist_ok=True)
            with open(user_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    'model = "old"\nmodel_provider = "heang"\n\n'
                    '[model_providers."heang"]\n'
                    'name = "old"\nbase_url = "https://old.invalid/v1"\n'
                    'env_key = "OLD_KEY"\nwire_api = "responses"\n'
                )
            with mock.patch("core.wire_config._probe_codex_provider", return_value={
                "baseUrl": "https://api.heang.top/v1",
                "endpoint": "https://api.heang.top/v1/responses",
                "httpStatus": 200,
                "model": "gpt-4o",
            }):
                status = service.sync_agent_model_config("codex-desktop", model="gpt-4o", validate_remote=True)

            self.assertTrue(status["configured"])
            with open(user_path, "r", encoding="utf-8") as handle:
                parsed = tomllib.loads(handle.read())
            self.assertEqual(parsed["model_providers"]["heang"]["base_url"], "https://api.heang.top/v1")

    def test_user_codex_config_path_does_not_treat_temp_prefix_sibling_as_temp_child(self) -> None:
        paths = AppPaths(r"C:\Temp项目\LOOM")
        with (
            mock.patch("core.wire_config.tempfile.gettempdir", return_value=r"C:\Temp"),
            mock.patch("core.wire_config.os.path.expanduser", return_value=r"C:\Users\Tester"),
        ):
            path = wire_config_module._user_codex_config_path(paths)

        self.assertEqual(path, r"C:\Users\Tester\.codex\config.toml")

    def test_verify_and_rollback_use_current_and_last_good_wire(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = WireService(AppPaths(temp_dir))
            before = session_snapshot()
            after = {**session_snapshot(), "gatewayDefaultModel": "gpt-4o"}

            service.sync_from_session(before)
            service.sync_from_session(after)

            verified = service.verify()
            self.assertFalse(verified["ok"])
            self.assertFalse(verified["targets"]["codex"]["ok"])

            rolled_back = service.rollback()
            self.assertEqual(rolled_back["wire"]["models"]["text"], "qwen3.7-plus")

    def test_first_custom_provider_does_not_create_fake_last_good_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)

            service.sync_custom_provider(
                provider="custom",
                base_url="https://third.example/v1",
                api_key="sk-test-token-not-real",
                text_model="gpt-4o",
                targets=("codex",),
            )

            self.assertFalse(os.path.exists(paths.wire_last_good))

    def test_verify_candidate_checks_remote_models_without_persisting_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            secret = "sk-candidate-secret-not-real"

            with mock.patch.object(
                wire_config_module,
                "_provider_json_request",
                return_value={"data": [{"id": "gpt-test"}, {"id": "gpt-other"}]},
            ) as request:
                result = service.verify_candidate(
                    provider="Example",
                    base_url="https://api.example.invalid/v1",
                    api_key=secret,
                    text_model="gpt-test",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["model"], "gpt-test")
            self.assertEqual(result["availableModelCount"], 2)
            self.assertNotIn(secret, repr(result))
            self.assertFalse(os.path.exists(paths.wire_current))
            request.assert_called_once_with(
                "https://api.example.invalid/v1/models",
                secret,
                method="GET",
            )

    def test_verify_candidate_rejects_model_missing_from_remote_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = WireService(AppPaths(temp_dir))
            with mock.patch.object(
                wire_config_module,
                "_provider_json_request",
                return_value={"data": [{"id": "gpt-other"}]},
            ):
                with self.assertRaises(WireConfigError) as caught:
                    service.verify_candidate(
                        provider="Example",
                        base_url="https://api.example.invalid/v1",
                        api_key="sk-candidate-secret-not-real",
                        text_model="gpt-missing",
                    )

            self.assertIn("selected_model_not_listed", str(caught.exception))
            with self.assertRaises(WireConfigError):
                service.rollback()

    def test_sync_target_errors_are_redacted_before_returning_to_account_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            service = WireService(AppPaths(temp_dir), append_log=logs.append)
            secret = "s" + "k-" + "demo-secret"

            def fail_sync(_wire):
                raise RuntimeError(f"apiKey={secret}")

            service._sync_image = fail_sync
            results = service.apply_wire(build_wire_from_session(session_snapshot()), targets=("image",))
            dumped = repr(results) + repr(logs)

            self.assertNotIn(secret, dumped)
            self.assertIn("apiKey=[redacted]", dumped)

    def test_sync_custom_provider_writes_runtime_configs_without_exposing_raw_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            secret = "s" + "k-test-token-not-real"

            result = service.sync_custom_provider(
                provider="OpenAI 兼容",
                base_url="https://third.example/v1",
                api_key=secret,
                text_model="gpt-4o",
                image_model="gpt-image-1",
                phone_model="gpt-4o-mini",
                video_model="sora-draft",
            )
            public_wire = result["wire"]

            self.assertTrue(public_wire["ok"])
            self.assertEqual(public_wire["managedBy"], "custom_provider")
            self.assertEqual(public_wire["provider"], "OpenAI 兼容")
            self.assertEqual(public_wire["models"]["text"], "gpt-4o")
            self.assertEqual(public_wire["models"]["phone"], "gpt-4o-mini")
            self.assertEqual(public_wire["models"]["video"], "sora-draft")
            self.assertNotIn(secret, repr(public_wire))
            self.assertNotIn("apiKey", repr(public_wire))

            with open(paths.wire_current, "r", encoding="utf-8") as handle:
                raw_text = handle.read()
            if os.name == "nt":
                self.assertNotIn(secret, raw_text)

            auth_profiles = read_json(paths.auth_profiles, {})
            provider = auth_profiles["models"]["providers"]["custom_provider"]
            self.assertEqual(auth_profiles["models"]["primary"], "custom_provider")
            self.assertEqual(provider["managedBy"], "custom_provider")
            self.assertEqual(provider["defaultModel"], "gpt-4o")
            self.assertEqual(provider["apiKey"], secret)

            phone_config = read_json(os.path.join(paths.launcher_dir, "phone-agent.json"), {})
            self.assertEqual(phone_config["llm"]["managedBy"], "custom_provider")
            self.assertEqual(phone_config["llm"]["model"], "gpt-4o-mini")

            desktop_config = read_json(os.path.join(paths.launcher_dir, "desktop-agent.json"), {})
            self.assertEqual(desktop_config["provider"]["managedBy"], "custom_provider")
            self.assertEqual(desktop_config["provider"]["model"], "gpt-4o")

            self.assertFalse(os.path.exists(paths.video_config))
            self.assertFalse(os.path.exists(paths.videoapi_config))

    def test_custom_provider_blank_phone_model_keeps_desktop_and_phone_models_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)

            result = service.sync_custom_provider(
                provider="custom",
                base_url="https://third.example/v1",
                api_key="sk-test-token-not-real",
                text_model="claude-3-5-sonnet",
                targets=("codex", "claude", "desktop", "phone"),
            )

            public_wire = result["wire"]
            self.assertEqual(public_wire["models"]["text"], "claude-3-5-sonnet")
            self.assertEqual(public_wire["models"]["phone"], "qwen3.7-plus")

            with open(os.path.join(paths.data_dir, ".codex", "config.toml"), "r", encoding="utf-8") as handle:
                codex_text = handle.read()
            with open(os.path.join(paths.data_dir, ".claude", "settings.json"), "r", encoding="utf-8") as handle:
                claude_text = handle.read()
            phone_config = read_json(os.path.join(paths.launcher_dir, "phone-agent.json"), {})

            self.assertIn('model = "claude-3-5-sonnet"', codex_text)
            self.assertNotIn('model = "agnes-2.0-flash"', codex_text)
            claude_env = json.loads(claude_text)["env"]
            self.assertEqual(claude_env["ANTHROPIC_MODEL"], "claude-3-5-sonnet")
            self.assertEqual(claude_env["ANTHROPIC_BASE_URL"], "https://third.example")
            self.assertEqual(phone_config["llm"]["model"], "qwen3.7-plus")

    def test_codex_model_config_rejects_phone_agent_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot())

            with self.assertRaises(WireConfigError):
                service.sync_agent_model_config("codex-desktop", model="agnes-2.0-flash")

    def test_custom_provider_rejects_non_text_models_as_desktop_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = WireService(AppPaths(temp_dir))

            for invalid_model in ("agnes-2.0-flash", "agnes-image-2.1-flash", "agnes-video-v2.0"):
                with self.subTest(model=invalid_model):
                    with self.assertRaises(WireConfigError):
                        service.sync_custom_provider(
                            provider="custom",
                            base_url="https://third.example/v1",
                            api_key="sk-test-token-not-real",
                            text_model=invalid_model,
                            targets=("codex",),
                        )

    def test_codex_status_detects_user_config_model_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot())
            user_codex_config = os.path.join(paths.data_dir, ".codex-user", "config.toml")
            with open(user_codex_config, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    "\n".join([
                        "# Managed by LOOM.",
                        'model = "gpt-5.5"',
                        'model_provider = "loom"',
                        "",
                    ])
                )

            status = service.agent_model_config_status("codex-desktop")

            self.assertFalse(status["configured"])
            self.assertEqual(status["status"], "unconfigured")
            self.assertEqual(status["expectedModel"], "qwen3.7-plus")
            self.assertEqual(status["actualModel"], "qwen3.7-plus")
            self.assertEqual(status["userActualModel"], "gpt-5.5")
            self.assertFalse(status["userConfigSynchronized"])

    def test_codex_status_flags_phone_model_in_user_config_as_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            service.sync_from_session(session_snapshot())
            user_codex_config = os.path.join(paths.data_dir, ".codex-user", "config.toml")
            with open(user_codex_config, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    "\n".join([
                        "# stale bad model written by older LOOM builds",
                        'model = "agnes-2.0-flash"',
                        'model_provider = "heang"',
                        "",
                    ])
                )

            status = service.agent_model_config_status("codex-desktop")

            self.assertFalse(status["configured"])
            self.assertEqual(status["status"], "unconfigured")
            self.assertEqual(status["expectedModel"], "qwen3.7-plus")
            self.assertEqual(status["actualModel"], "qwen3.7-plus")
            self.assertEqual(status["userActualModel"], "agnes-2.0-flash")
            self.assertEqual(status["userInvalidModel"], "agnes-2.0-flash")
            self.assertFalse(status["userConfigSynchronized"])
            self.assertIn("用户 Codex", status["message"])

    def test_codex_transaction_rejects_partial_user_config_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)
            managed_path = os.path.join(paths.data_dir, ".codex", "config.toml")
            user_path = os.path.join(paths.data_dir, ".codex-user", "config.toml")
            from core import wire_config as wire_module

            original_write = wire_module._atomic_write_text
            failed = False

            def fail_user_write(path: str, text: str) -> None:
                nonlocal failed
                if os.path.abspath(path) == os.path.abspath(user_path) and not failed:
                    failed = True
                    raise PermissionError("simulated locked user profile")
                return original_write(path, text)

            with mock.patch("core.wire_config._atomic_write_text", side_effect=fail_user_write):
                result = service.sync_custom_provider(
                    provider="OpenAI compatible",
                    base_url="https://third.example/v1",
                    api_key="sk-test-token-not-real",
                    text_model="gpt-4o",
                    targets=("codex",),
                )

            target = result["syncResults"][0]
            self.assertFalse(target["ok"])
            self.assertFalse(os.path.isfile(managed_path))
            self.assertFalse(os.path.isfile(user_path))
            status = service.agent_model_config_status("codex-desktop")
            self.assertFalse(status["configured"])

    def test_codex_transaction_rejects_partial_environment_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            service = WireService(paths)

            with (
                mock.patch("core.wire_config._should_persist_user_env", return_value=True),
                mock.patch("core.wire_config._read_user_env_var", return_value=None),
                mock.patch("core.wire_config._read_user_env_kind", return_value=None),
                mock.patch("core.wire_config._write_user_env_var", side_effect=PermissionError("simulated registry policy block")),
            ):
                result = service.sync_custom_provider(
                    provider="OpenAI compatible",
                    base_url="https://third.example/v1",
                    api_key="sk-test-token-not-real",
                    text_model="gpt-4o",
                    targets=("codex",),
                )

            target = result["syncResults"][0]
            self.assertFalse(target["ok"])
            status = service.agent_model_config_status("codex-desktop")
            self.assertFalse(status["configured"])

    def test_openclaw_model_sync_rejects_phone_only_model_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            ok = sync_openclaw_models_from_gateway_profile(
                paths,
                {
                    "baseUrl": "https://third.example/v1",
                    "apiKey": "sk-test-token-not-real",
                    "models": ["agnes-2.0-flash"],
                },
            )

            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
