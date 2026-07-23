from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.error


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.newapi_account_manager import (
    ACCOUNT_SOURCE,
    DEFAULT_API_BASE,
    DEFAULT_BASE_URL,
    NewApiAccountError,
    NewApiAccountManager,
    _trusted_managed_api_base,
    _classified_models_from_catalog,
    _choose_model,
    _extract_models,
    _flatten_model_catalog,
)
import core.newapi_account_manager as account_module
from core.license_manager import LicenseManager
from core.paths import AppPaths
from core.storage import read_json


class NewApiAccountManagerTests(unittest.TestCase):
    def test_launcher_permission_contract_accepts_only_the_account_routing_group(self) -> None:
        base = {
            "tokenKind": "launcher",
            "permissionMode": "default",
            "modelLimitsEnabled": False,
            "unlimitedQuota": True,
            "group": "SVIP",
        }

        self.assertTrue(account_module._launcher_permission_contract_satisfied({**base, "tokenGroup": "SVIP"}))
        self.assertTrue(account_module._launcher_permission_contract_satisfied({**base, "tokenGroup": ""}))
        self.assertFalse(account_module._launcher_permission_contract_satisfied({**base, "tokenGroup": "default"}))

    def test_accelerated_request_falls_back_to_legacy_domain_on_network_failure(self) -> None:
        class Response:
            def read(self):
                return b'{"success":true,"data":{"ok":true}}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        class Opener:
            def __init__(self):
                self.urls: list[str] = []

            def open(self, request, timeout=20):
                del timeout
                self.urls.append(request.full_url)
                if request.full_url.startswith("https://api-cn.heang.top"):
                    raise urllib.error.URLError("accelerated route unavailable")
                return Response()

        manager = NewApiAccountManager(AppPaths("."))
        opener = Opener()

        payload = manager._request_json(opener, "https://api-cn.heang.top/api/status")

        self.assertTrue(payload["success"])
        self.assertEqual(
            opener.urls,
            [
                "https://api-cn.heang.top/api/status",
                "https://api.heang.top/api/status",
            ],
        )

    def test_side_effecting_requests_are_never_replayed_to_legacy_domain(self) -> None:
        class Opener:
            def __init__(self):
                self.urls: list[str] = []

            def open(self, request, timeout=20):
                del timeout
                self.urls.append(request.full_url)
                raise urllib.error.URLError("accelerated route unavailable")

        manager = NewApiAccountManager(AppPaths("."))
        opener = Opener()

        with self.assertRaises(NewApiAccountError):
            manager._request_json(
                opener,
                "https://api-cn.heang.top/api/openclaw/auth/email-code/send",
                method="POST",
                body={"email": "user@example.invalid"},
            )

        self.assertEqual(opener.urls, ["https://api-cn.heang.top/api/openclaw/auth/email-code/send"])

    def test_managed_defaults_use_canonical_cloudflare_domain(self) -> None:
        self.assertEqual(DEFAULT_BASE_URL, "https://api.heang.top")
        self.assertEqual(DEFAULT_API_BASE, "https://api.heang.top/v1")
        self.assertEqual(NewApiAccountManager.normalize_base_url(""), DEFAULT_BASE_URL)

    def test_trusted_gateway_aligns_known_legacy_alias_to_login_origin(self) -> None:
        self.assertEqual(
            _trusted_managed_api_base(
                "https://api.heang.top/v1",
                "https://api-cn.heang.top",
            ),
            "https://api-cn.heang.top/v1",
        )
        self.assertEqual(
            _trusted_managed_api_base(
                "https://api-cn.heang.top/v1",
                "https://api.heang.top",
            ),
            "https://api.heang.top/v1",
        )

    def test_current_migrates_legacy_managed_session_and_resyncs_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NewApiAccountManager(AppPaths(temp_dir))
            manager._write_session({
                "source": ACCOUNT_SOURCE,
                "memberToken": "sk-migration-test-not-real",
                "gatewayBaseUrl": "https://api.heang.top/v1",
                "gatewayImageBaseUrl": "https://api.heang.top/v1",
                "gatewayVideoBaseUrl": "https://api.heang.top/v1",
                "gateway": {
                    "baseUrl": "https://api.heang.top/v1",
                    "imageBaseUrl": "https://api.heang.top/v1",
                    "videoBaseUrl": "https://api.heang.top/v1",
                },
                "newApi": {"baseUrl": "https://api.heang.top"},
                "phoneAgent": {"baseUrl": "https://api.heang.top/v1"},
            })
            sync_calls: list[tuple[str, ...]] = []

            def record_sync(session, *, targets=account_module.DEFAULT_RUNTIME_SYNC_TARGETS):
                sync_calls.append(targets)
                return []

            manager.sync_targets = record_sync

            session = manager.current()

            self.assertEqual(session["newApi"]["baseUrl"], DEFAULT_BASE_URL)
            self.assertEqual(session["gatewayBaseUrl"], DEFAULT_API_BASE)
            self.assertEqual(session["gateway"]["baseUrl"], DEFAULT_API_BASE)
            self.assertEqual(session["phoneAgent"]["baseUrl"], DEFAULT_API_BASE)
            self.assertEqual(sync_calls, [account_module.DEFAULT_RUNTIME_SYNC_TARGETS])
            self.assertEqual(session["managedGatewayMigrationVersion"], 1)

    def test_failed_gateway_migration_sync_is_retried_on_next_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NewApiAccountManager(AppPaths(temp_dir))
            manager._write_session({
                "source": ACCOUNT_SOURCE,
                "memberToken": "sk-" + "migration-retry-not-real",
                "gatewayBaseUrl": "https://api.heang.top/v1",
                "newApi": {"baseUrl": "https://api.heang.top"},
            })
            sync_calls = 0

            def fail_sync(_session, *, targets=account_module.DEFAULT_RUNTIME_SYNC_TARGETS):
                nonlocal sync_calls
                del targets
                sync_calls += 1
                raise OSError("temporary local write failure")

            manager.sync_targets = fail_sync

            first = manager.current()
            second = manager.current()

            self.assertEqual(sync_calls, 2)
            self.assertEqual(first["gatewayBaseUrl"], DEFAULT_API_BASE)
            self.assertEqual(second["gatewayBaseUrl"], DEFAULT_API_BASE)
            self.assertNotIn("managedGatewayMigrationVersion", second)

    def test_nested_model_catalog_maps_are_flattened_and_classified(self) -> None:
        catalog = {
            "data": {
                "models": {
                    "qwen3.7-plus": {"owned_by": "heang"},
                    "gpt-4o": {"owned_by": "heang"},
                    "agnes-image-2.1-flash": {"type": "image"},
                    "agnes-video-v2.0": {"type": "video"},
                },
                "phone": {
                    "agnes-2.0-flash": {"type": "phone"},
                },
            }
        }

        models = _extract_models(catalog)
        classes = _classified_models_from_catalog(catalog)
        flat = _flatten_model_catalog(catalog)

        self.assertIn("qwen3.7-plus", models)
        self.assertIn("gpt-4o", models)
        self.assertIn("agnes-image-2.1-flash", classes["image"])
        self.assertIn("agnes-video-v2.0", classes["video"])
        self.assertIn("agnes-2.0-flash", flat)

    def test_newapi_user_models_map_response_keeps_multiple_text_models_without_phone_default(self) -> None:
        payload = {
            "success": True,
            "data": {
                "models": {
                    "qwen3.7-plus": {},
                    "qwen3.6-plus": {},
                    "deepseek-v3.2": {},
                    "agnes-2.0-flash": {},
                }
            },
        }

        classes = _classified_models_from_catalog(payload)

        self.assertEqual(
            classes["text"],
            ["qwen3.7-plus", "qwen3.6-plus", "deepseek-v3.2"],
        )
        self.assertNotIn("agnes-2.0-flash", classes["text"])

    def test_text_model_choice_never_uses_image_video_or_phone_fallback(self) -> None:
        chosen = _choose_model(
            [],
            "qwen3.7-plus",
            ["agnes-video-v2.0", "agnes-image-2.1-flash", "agnes-2.0-flash"],
        )

        self.assertEqual(chosen, "")

    def test_default_text_model_choice_prefers_glm52_coding(self) -> None:
        chosen = _choose_model(
            ["qwen3.7-plus", "glm-5.2-coding", "gpt-4o"],
            account_module.DEFAULT_TEXT_MODEL,
        )

        self.assertEqual(chosen, "glm-5.2-coding")

    def test_public_session_and_select_models_do_not_invent_qwen_when_catalog_has_no_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            manager = NewApiAccountManager(paths)
            manager._write_session({
                "source": ACCOUNT_SOURCE,
                "memberId": "newapi:test-user",
                "memberName": "user@example.invalid",
                "memberToken": "sk-test-token-not-real",
                "gatewayBaseUrl": "https://api.heang.top/v1",
                "gatewayImageBaseUrl": "https://api.heang.top/v1",
                "gatewayDefaultModel": "",
                "gatewayImageModel": "agnes-image-2.1-flash",
                "gatewayVideoDraftModel": "agnes-video-v2.0",
                "gatewayModels": ["agnes-image-2.1-flash", "agnes-video-v2.0", "agnes-2.0-flash"],
                "gateway": {
                    "classifiedModels": {
                        "text": [],
                        "image": ["agnes-image-2.1-flash"],
                        "video": ["agnes-video-v2.0"],
                    },
                },
                "newApi": {
                    "baseUrl": "https://api.heang.top",
                    "account": "user@example.invalid",
                },
                "phoneAgent": {
                    "baseUrl": "https://api.heang.top/v1",
                    "apiKey": "sk-test-token-not-real",
                    "model": "agnes-2.0-flash",
                },
            })

            public_session = manager.public_session()
            self.assertEqual(public_session["models"]["text"], [])
            self.assertEqual(public_session["selectedModels"]["text"], "")

            with self.assertRaisesRegex(NewApiAccountError, "文本模型不在当前账号可用列表中"):
                manager.select_models(text_model="qwen3.7-plus")

    def test_login_creates_launcher_token_before_using_generic_agnes_only_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[
                    {
                        "name": "Default",
                        "key": "fake-generic-token-not-real",
                        "status": 1,
                        "remain_quota": 1000,
                    }
                ],
                create_token="fake-loom-token-not-real",
                model_by_token={
                    "fake-generic-token-not-real": ["agnes-2.0-flash"],
                    "fake-loom-token-not-real": ["qwen3.7-plus", "gpt-4o", "agnes-2.0-flash"],
                },
            )

            session = manager.login("user@example.invalid", "password-not-real", base_url="https://custom-newapi.example.invalid")

            self.assertEqual(session["memberToken"], "fake-loom-token-not-real")
            self.assertEqual(session["gatewayDefaultModel"], "qwen3.7-plus")
            self.assertIn("gpt-4o", session["gateway"]["classifiedModels"]["text"])
            self.assertEqual(session["lease"]["tokenSource"], "created_launcher")

            create_request = next(
                request
                for request in manager.requests
                if request["url"].endswith("/api/token/") and request["method"] == "POST"
            )
            self.assertEqual(
                create_request["body"],
                {
                    "name": create_request["body"]["name"],
                    "remain_quota": 0,
                    "expired_time": -1,
                    "unlimited_quota": True,
                    "model_limits_enabled": False,
                    "model_limits": "",
                    "allow_ips": "",
                    "group": "",
                    "cross_group_retry": False,
                },
            )

    def test_password_login_uses_one_bridge_round_trip_when_payload_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                bridge_token="fake-bridge-token-not-real",
                bridge_models=["qwen3.7-plus", "gpt-4o", "agnes-2.0-flash"],
            )

            session = manager.login("user@example.invalid", "password-not-real", base_url="https://api.heang.top")

            self.assertEqual(
                [request["url"] for request in manager.requests],
                ["https://api.heang.top/api/openclaw/launcher-token"],
            )
            self.assertEqual(session["memberToken"], "fake-bridge-token-not-real")
            self.assertEqual(session["memberName"], "user@example.invalid")
            self.assertEqual(session["newApi"]["userId"], "u_123")
            self.assertEqual(session["newApi"]["sessionCookie"], "session=fake-session-not-real")
            self.assertEqual(session["newApi"]["authMethod"], "password_bridge")
            self.assertEqual(session["gatewayDefaultModel"], "qwen3.7-plus")
            self.assertEqual(session["lease"]["permissionMode"], "default")
            self.assertFalse(session["lease"]["modelLimitsEnabled"])
            self.assertTrue(session["lease"]["unlimitedQuota"])
            self.assertEqual(manager.synced_targets, account_module.DEFAULT_RUNTIME_SYNC_TARGETS)
            self.assertLessEqual(manager.requests[0]["timeout"], 5)

    def test_password_login_preserves_significant_surrounding_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                bridge_token="fake-bridge-token-not-real",
                bridge_models=["glm-5.2-coding"],
            )
            password = " password with spaces "

            manager.login("user@example.invalid", password, base_url="https://api.heang.top")

            self.assertEqual(manager.requests[0]["body"]["password"], password)

    def test_password_login_can_return_before_runtime_config_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                bridge_token="fake-bridge-token-not-real",
                bridge_models=["glm-5.2-coding"],
            )

            session = manager.login(
                "user@example.invalid",
                "password-not-real",
                base_url="https://api-cn.heang.top",
                sync_runtime=False,
            )

            self.assertIsNone(manager.synced_targets)
            self.assertEqual(session["managedGatewayMigrationVersion"], account_module.MANAGED_GATEWAY_MIGRATION_VERSION)
            self.assertTrue(os.path.isfile(manager.session_path))

    def test_managed_password_login_fails_fast_when_bridge_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                create_token="fake-created-token-not-real",
                model_by_token={"fake-created-token-not-real": ["qwen3.7-plus"]},
            )

            with self.assertRaisesRegex(NewApiAccountError, "http_404"):
                manager.login("user@example.invalid", "password-not-real", base_url="https://api.heang.top")

            self.assertEqual(
                [request["url"] for request in manager.requests],
                ["https://api.heang.top/api/openclaw/launcher-token"],
            )

    def test_password_login_does_not_retry_rejected_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                bridge_error=NewApiAccountError("invalid credentials", status_code=401),
            )

            with self.assertRaisesRegex(NewApiAccountError, "invalid credentials"):
                manager.login("user@example.invalid", "wrong-password", base_url="https://api.heang.top")

            self.assertEqual(
                [request["url"] for request in manager.requests],
                ["https://api.heang.top/api/openclaw/launcher-token"],
            )

    def test_login_regenerates_launcher_token_when_existing_launcher_key_has_only_phone_models(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[
                    {
                        "name": "LOOM Launcher 1700000000",
                        "key": "fake-loom-old-token-not-real",
                        "status": 1,
                        "remain_quota": 1000,
                    }
                ],
                create_token="fake-loom-new-token-not-real",
                model_by_token={
                    "fake-loom-old-token-not-real": ["agnes-2.0-flash"],
                    "fake-loom-new-token-not-real": ["qwen3.7-plus", "MiniMax-M2.5", "agnes-2.0-flash"],
                },
            )

            session = manager.login("user@example.invalid", "password-not-real", base_url="https://custom-newapi.example.invalid")

            self.assertEqual(session["memberToken"], "fake-loom-new-token-not-real")
            self.assertEqual(session["gatewayDefaultModel"], "qwen3.7-plus")
            self.assertIn("MiniMax-M2.5", session["gateway"]["classifiedModels"]["text"])
            self.assertEqual(session["lease"]["tokenSource"], "created_launcher_after_model_check")

    def test_login_skips_disabled_launcher_token_and_creates_fresh_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[
                    {
                        "name": "LOOM Launcher disabled",
                        "key": "fake-disabled-token-not-real",
                        "status": 2,
                        "remain_quota": 0,
                    }
                ],
                create_token="fake-loom-fresh-token-not-real",
                model_by_token={
                    "fake-disabled-token-not-real": ["agnes-2.0-flash"],
                    "fake-loom-fresh-token-not-real": ["qwen3.7-plus", "gpt-4o"],
                },
            )

            session = manager.login("user@example.invalid", "password-not-real", base_url="https://custom-newapi.example.invalid")

            self.assertEqual(session["memberToken"], "fake-loom-fresh-token-not-real")
            self.assertEqual(session["gatewayDefaultModel"], "qwen3.7-plus")
            self.assertEqual(session["lease"]["tokenSource"], "created_launcher")

    def test_login_does_not_resubmit_password_when_bridge_has_no_text_models(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                bridge_token="fake-bridge-token-not-real",
                bridge_models=["agnes-2.0-flash"],
                create_token="fake-loom-fresh-token-not-real",
                model_by_token={
                    "fake-bridge-token-not-real": ["agnes-2.0-flash"],
                    "fake-loom-fresh-token-not-real": ["qwen3.7-plus", "gpt-4o"],
                },
            )

            with self.assertRaisesRegex(NewApiAccountError, "文本模型"):
                manager.login("user@example.invalid", "password-not-real", base_url="https://api.heang.top")

            self.assertEqual(
                [request["url"] for request in manager.requests],
                ["https://api.heang.top/api/openclaw/launcher-token"],
            )

    def test_managed_login_does_not_enter_slow_legacy_path_after_bridge_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                bridge_error=NewApiAccountError("launcher bridge requires additional configuration", status_code=500),
                create_token="fake-created-token-not-real",
                model_by_token={"fake-created-token-not-real": ["glm-5.2-coding"]},
            )

            with self.assertRaisesRegex(NewApiAccountError, "additional configuration"):
                manager.login("user@example.invalid", "password-not-real", base_url="https://api-cn.heang.top")

            self.assertEqual(
                [request["url"] for request in manager.requests],
                ["https://api-cn.heang.top/api/openclaw/launcher-token"],
            )

    def test_custom_newapi_origin_keeps_legacy_login_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                bridge_error=NewApiAccountError("http_404", status_code=404),
                create_token="fake-created-token-not-real",
                model_by_token={"fake-created-token-not-real": ["glm-5.2-coding"]},
            )

            session = manager.login(
                "user@example.invalid",
                "password-not-real",
                base_url="https://custom-newapi.example.invalid",
            )

            self.assertEqual(session["memberToken"], "fake-created-token-not-real")
            self.assertIn(
                "https://custom-newapi.example.invalid/api/user/login",
                [request["url"] for request in manager.requests],
            )

    def test_managed_email_capabilities_prefer_launcher_bridge_capability(self) -> None:
        class CapabilitiesManager(NewApiAccountManager):
            def _request_json(self, _opener, url, **_kwargs):
                self.requested_url = url
                return {
                    "success": True,
                    "data": {
                        "passwordLogin": True,
                        "inlineEmailCode": False,
                        "inlineRegistration": False,
                        "webRegistrationRequired": False,
                        "emailConfigured": False,
                        "emailReason": "服务器 SMTP 邮箱尚未配置，请使用密码登录。",
                    },
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CapabilitiesManager(AppPaths(temp_dir))

            capabilities = manager.auth_capabilities(base_url="https://api.heang.top")

        self.assertTrue(capabilities["passwordLogin"])
        self.assertFalse(capabilities["inlineEmailCode"])
        self.assertFalse(capabilities["inlineRegistration"])
        self.assertFalse(capabilities["webRegistrationRequired"])
        self.assertFalse(capabilities["emailConfigured"])
        self.assertIn("SMTP", capabilities["emailReason"])
        self.assertEqual(manager.requested_url, "https://api.heang.top/api/openclaw/auth/capabilities")

    def test_password_login_rejects_cross_origin_bridge_api_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                bridge_token="fake-bridge-token-not-real",
                bridge_models=["qwen3.7-plus"],
                bridge_api_base_url="https://api.heang.top/v1",
            )

            with self.assertRaisesRegex(NewApiAccountError, "域名"):
                manager.login(
                    "user@example.invalid",
                    "password-not-real",
                    base_url="https://relay.example.invalid",
                )

            self.assertEqual(len(manager.requests), 1)

    def test_login_fails_closed_when_launcher_token_creation_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[
                    {
                        "name": "Default",
                        "key": "fake-generic-token-not-real",
                        "status": 1,
                        "remain_quota": 1000,
                    }
                ],
                create_fails=True,
                model_by_token={"fake-generic-token-not-real": ["agnes-2.0-flash"]},
            )

            with self.assertRaisesRegex(NewApiAccountError, "token_create_unavailable"):
                manager.login("user@example.invalid", "password-not-real", base_url="https://custom-newapi.example.invalid")

    def test_ensure_launcher_token_upgrades_old_session_and_syncs_runtime(self) -> None:
        class EnsureLauncherManager(LauncherTokenFakeManager):
            def _request_json(self, opener, url, *, method="GET", body=None, headers=None, timeout=20):
                if url.endswith("/api/openclaw/launcher-token/ensure"):
                    self.requests.append({
                        "url": url,
                        "method": method,
                        "body": body or {},
                        "headers": headers or {},
                        "timeout": timeout,
                    })
                    return {
                        "success": True,
                        "data": {
                            "userId": "u_123",
                            "account": "user@example.invalid",
                            "group": "standard",
                            "source": "created",
                            "tokenKind": "launcher",
                            "permissionMode": "default",
                            "modelLimitsEnabled": False,
                            "unlimitedQuota": True,
                            "tokenGroup": "",
                            "tokenName": "LOOM Launcher upgraded",
                            "tokenId": 99,
                            "apiKey": "fake-dedicated-token-not-real",
                            "models": ["glm-5.2-coding", "agnes-image-2.1-flash"],
                            "api": {"baseUrl": "https://api.heang.top/v1"},
                        },
                    }
                return super()._request_json(
                    opener,
                    url,
                    method=method,
                    body=body,
                    headers=headers,
                    timeout=timeout,
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EnsureLauncherManager(AppPaths(temp_dir), tokens=[])
            manager._write_session({
                "source": ACCOUNT_SOURCE,
                "memberToken": "fake-arbitrary-token-not-real",
                "gatewayImageAccessToken": "fake-arbitrary-token-not-real",
                "gatewayModels": ["glm-5.2-coding"],
                "gatewayDefaultModel": "glm-5.2-coding",
                "gateway": {
                    "accessToken": "fake-arbitrary-token-not-real",
                    "imageAccessToken": "fake-arbitrary-token-not-real",
                },
                "newApi": {
                    "baseUrl": "https://api.heang.top",
                    "userId": "u_123",
                    "account": "user@example.invalid",
                },
                "lease": {"tokenSource": "existing"},
                "phoneAgent": {"apiKey": "fake-arbitrary-token-not-real"},
            })

            session = manager.ensure_launcher_token()

            self.assertEqual(session["memberToken"], "fake-dedicated-token-not-real")
            self.assertEqual(session["gateway"]["accessToken"], "fake-dedicated-token-not-real")
            self.assertEqual(session["phoneAgent"]["apiKey"], "fake-dedicated-token-not-real")
            self.assertEqual(session["lease"]["tokenKind"], "launcher")
            self.assertEqual(session["lease"]["permissionMode"], "default")
            self.assertFalse(session["lease"]["modelLimitsEnabled"])
            self.assertTrue(session["lease"]["unlimitedQuota"])
            self.assertEqual(session["lease"]["tokenName"], "LOOM Launcher upgraded")
            self.assertEqual(manager.synced_targets, account_module.DEFAULT_RUNTIME_SYNC_TARGETS)
            request = next(item for item in manager.requests if item["url"].endswith("/launcher-token/ensure"))
            self.assertEqual(
                request["headers"]["Authorization"],
                "Bearer fake-arbitrary-token-not-real",
            )

    def test_ensure_launcher_token_reissues_launcher_key_when_permission_contract_is_missing(self) -> None:
        class EnsureLauncherManager(LauncherTokenFakeManager):
            def _request_json(self, opener, url, *, method="GET", body=None, headers=None, timeout=20):
                if url.endswith("/api/openclaw/launcher-token/ensure"):
                    self.requests.append({"url": url, "headers": headers or {}})
                    return {
                        "success": True,
                        "data": {
                            "source": "created",
                            "tokenKind": "launcher",
                            "permissionMode": "default",
                            "modelLimitsEnabled": False,
                            "unlimitedQuota": True,
                            "tokenGroup": "",
                            "apiKey": "fake-reissued-token-not-real",
                            "models": ["glm-5.2-coding"],
                            "api": {"baseUrl": "https://api.heang.top/v1"},
                        },
                    }
                return super()._request_json(opener, url, method=method, body=body, headers=headers, timeout=timeout)

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EnsureLauncherManager(AppPaths(temp_dir), tokens=[])
            manager._write_session({
                "source": ACCOUNT_SOURCE,
                "memberToken": "fake-old-launcher-token-not-real",
                "gatewayModels": ["glm-5.2-coding"],
                "gatewayDefaultModel": "glm-5.2-coding",
                "gateway": {},
                "newApi": {"baseUrl": "https://api.heang.top"},
                "lease": {"tokenKind": "launcher"},
                "phoneAgent": {},
            })

            session = manager.ensure_launcher_token(sync_runtime=False)

            self.assertEqual(session["memberToken"], "fake-reissued-token-not-real")
            self.assertEqual(session["lease"]["permissionMode"], "default")
            self.assertEqual(len(manager.requests), 1)

    def test_ensure_launcher_token_force_refresh_bypasses_valid_cached_contract(self) -> None:
        class ForceRefreshManager(LauncherTokenFakeManager):
            def _request_json(self, opener, url, *, method="GET", body=None, headers=None, timeout=20):
                if url.endswith("/api/openclaw/launcher-token/ensure"):
                    self.requests.append({"url": url, "headers": headers or {}})
                    return {
                        "success": True,
                        "data": {
                            "source": "refreshed",
                            "tokenKind": "launcher",
                            "permissionMode": "default",
                            "modelLimitsEnabled": False,
                            "unlimitedQuota": True,
                            "tokenGroup": "",
                            "apiKey": "fake-force-refreshed-token-not-real",
                            "models": ["glm-5.2-coding"],
                            "api": {"baseUrl": "https://api.heang.top/v1"},
                        },
                    }
                return super()._request_json(opener, url, method=method, body=body, headers=headers, timeout=timeout)

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ForceRefreshManager(AppPaths(temp_dir), tokens=[])
            manager._write_session({
                "source": ACCOUNT_SOURCE,
                "memberToken": "fake-valid-but-revoked-token-not-real",
                "gatewayModels": ["glm-5.2-coding"],
                "gatewayDefaultModel": "glm-5.2-coding",
                "gateway": {},
                "newApi": {"baseUrl": "https://api.heang.top"},
                "lease": {
                    "tokenKind": "launcher",
                    "permissionMode": "default",
                    "modelLimitsEnabled": False,
                    "unlimitedQuota": True,
                    "tokenGroup": "",
                    "accountGroup": "standard",
                },
                "phoneAgent": {},
            })

            session = manager.ensure_launcher_token(sync_runtime=False, force_refresh=True)

            self.assertEqual(session["memberToken"], "fake-force-refreshed-token-not-real")
            self.assertEqual(len(manager.requests), 1)
            self.assertEqual(
                manager.requests[0]["headers"]["Authorization"],
                "Bearer fake-valid-but-revoked-token-not-real",
            )

    def test_ensure_launcher_token_rejects_server_key_without_default_permission_contract(self) -> None:
        class InvalidEnsureManager(LauncherTokenFakeManager):
            def _request_json(self, opener, url, *, method="GET", body=None, headers=None, timeout=20):
                if url.endswith("/api/openclaw/launcher-token/ensure"):
                    return {
                        "success": True,
                        "data": {
                            "tokenKind": "launcher",
                            "permissionMode": "limited",
                            "modelLimitsEnabled": True,
                            "unlimitedQuota": False,
                            "tokenGroup": "restricted",
                            "apiKey": "fake-limited-token-not-real",
                            "models": ["glm-5.2-coding"],
                        },
                    }
                return super()._request_json(opener, url, method=method, body=body, headers=headers, timeout=timeout)

        with tempfile.TemporaryDirectory() as temp_dir:
            manager = InvalidEnsureManager(AppPaths(temp_dir), tokens=[])
            manager._write_session({
                "source": ACCOUNT_SOURCE,
                "memberToken": "fake-old-token-not-real",
                "gatewayModels": ["glm-5.2-coding"],
                "gateway": {},
                "newApi": {"baseUrl": "https://api.heang.top"},
                "lease": {},
                "phoneAgent": {},
            })

            with self.assertRaisesRegex(NewApiAccountError, "launcher_token_permission_contract_invalid"):
                manager.ensure_launcher_token(sync_runtime=False)

            self.assertEqual(manager.current()["memberToken"], "fake-old-token-not-real")

    def test_email_code_send_uses_newapi_verification_endpoint_without_returning_code_or_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(AppPaths(temp_dir))

            result = manager.send_email_code("user@example.invalid", base_url="https://api.heang.top")

            self.assertTrue(result["sent"])
            self.assertEqual(result["email"], "user@example.invalid")
            self.assertEqual(manager.requests[0]["url"], "https://api.heang.top/api/verification?email=user%40example.invalid")
            self.assertNotIn("123456", repr(result))
            self.assertNotIn("sk-test-token-not-real", repr(result))

    def test_email_code_login_send_uses_login_endpoint_not_register_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(AppPaths(temp_dir))

            result = manager.send_email_code(
                "user@example.invalid",
                base_url="https://api.heang.top",
                purpose="login",
            )

            self.assertTrue(result["sent"])
            self.assertEqual(manager.requests[0]["url"], "https://api.heang.top/api/openclaw/auth/email-code/send")
            self.assertEqual(manager.requests[0]["body"]["purpose"], "login")
            self.assertEqual(manager.requests[0]["body"]["scene"], "login")
            self.assertEqual(manager.requests[0]["body"]["type"], "login")
            self.assertEqual(manager.requests[0]["body"]["mode"], "login")
            self.assertEqual(manager.requests[0]["body"]["action"], "login")
            self.assertEqual(manager.requests[0]["body"]["authType"], "email_code_login")
            self.assertNotIn("/api/verification", manager.requests[0]["url"])

    def test_email_code_register_fallback_uses_register_scene_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(AppPaths(temp_dir))

            original_request_json = manager._request_json

            def request_json(opener, url, **kwargs):
                if "/api/verification?" in url:
                    raise NewApiAccountError("http_404")
                return original_request_json(opener, url, **kwargs)

            manager._request_json = request_json  # type: ignore[method-assign]
            result = manager.send_email_code(
                "user@example.invalid",
                base_url="https://api.heang.top",
                purpose="register",
            )

            self.assertTrue(result["sent"])
            body = manager.requests[-1]["body"]
            self.assertEqual(body["purpose"], "register")
            self.assertEqual(body["scene"], "register")
            self.assertEqual(body["type"], "register")
            self.assertEqual(body["mode"], "register")
            self.assertEqual(body["action"], "register")

    def test_email_code_login_builds_protected_managed_session_and_syncs_wire(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(AppPaths(temp_dir))

            session = manager.login_with_email_code(
                "user@example.invalid",
                "654321",
                base_url="https://api.heang.top",
            )
            public_session = manager.public_session()

            self.assertEqual(session["memberName"], "user@example.invalid")
            self.assertEqual(session["memberToken"], "sk-test-token-not-real")
            self.assertEqual(session["gatewayDefaultModel"], "qwen3.7-plus")
            self.assertEqual(session["gatewayImageModel"], "gpt-image-1")
            self.assertEqual(session["gatewayVideoDraftModel"], "agnes-video-v1")
            self.assertEqual(session["phoneAgent"]["model"], "agnes-2.0-flash")
            self.assertEqual(session["newApi"]["launcherToken"], "sess-test-launcher-not-real")
            self.assertEqual(public_session["account"], "user@example.invalid")
            self.assertNotIn("sk-test-token-not-real", repr(public_session))
            self.assertNotIn("sess-test-launcher-not-real", repr(public_session))
            self.assertEqual(manager.synced_targets, ("openclaw", "opencode", "claude", "image", "desktop", "phone"))
            self.assertNotIn("codex", manager.synced_targets)

            with open(manager.session_path, "r", encoding="utf-8") as file:
                raw_text = file.read()
            if os.name == "nt":
                self.assertNotIn("sk-test-token-not-real", raw_text)
                self.assertNotIn("sess-test-launcher-not-real", raw_text)

    def test_email_code_send_does_not_hide_newapi_business_errors_behind_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeBusinessErrorManager(AppPaths(temp_dir))

            with self.assertRaisesRegex(NewApiAccountError, "email domain"):
                manager.send_email_code("user@example.invalid", base_url="https://api.heang.top")

            self.assertEqual(len(manager.requests), 1)
            self.assertEqual(manager.requests[0]["url"], "https://api.heang.top/api/verification?email=user%40example.invalid")

    def test_refresh_regenerates_launcher_token_when_current_token_has_no_text_models(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = LauncherTokenFakeManager(
                AppPaths(temp_dir),
                tokens=[],
                create_token="fake-loom-refresh-token-not-real",
                model_by_token={
                    "fake-old-token-not-real": ["agnes-image-2.1-flash", "agnes-video-v2.0", "agnes-2.0-flash"],
                    "fake-loom-refresh-token-not-real": ["qwen3.7-plus", "gpt-4o", "gpt-image-1", "agnes-2.0-flash"],
                },
            )
            manager._write_session({
                "source": ACCOUNT_SOURCE,
                "memberToken": "fake-old-token-not-real",
                "gatewayImageAccessToken": "fake-old-token-not-real",
                "gatewayDefaultModel": "agnes-video-v2.0",
                "gatewayModels": ["agnes-image-2.1-flash", "agnes-video-v2.0", "agnes-2.0-flash"],
                "gateway": {
                    "accessToken": "fake-old-token-not-real",
                    "imageAccessToken": "fake-old-token-not-real",
                    "defaultModel": "agnes-video-v2.0",
                    "models": ["agnes-image-2.1-flash", "agnes-video-v2.0", "agnes-2.0-flash"],
                },
                "newApi": {
                    "baseUrl": "https://api.heang.top",
                    "userId": "u_123",
                    "account": "user@example.invalid",
                },
                "lease": {"tokenSource": "existing_launcher"},
                "phoneAgent": {
                    "apiKey": "fake-old-token-not-real",
                    "model": "agnes-2.0-flash",
                },
            })

            refreshed = manager.refresh_current()
            public_session = manager.public_session()

            self.assertEqual(refreshed["memberToken"], "fake-loom-refresh-token-not-real")
            self.assertEqual(refreshed["gatewayDefaultModel"], "qwen3.7-plus")
            self.assertIn("gpt-4o", public_session["models"]["text"])
            self.assertNotIn("agnes-video-v2.0", public_session["models"]["text"])
            self.assertEqual(refreshed["lease"]["tokenSource"], "created_launcher_after_refresh_model_check")

    def test_register_with_email_code_builds_session_without_persisting_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(AppPaths(temp_dir))

            session = manager.register_with_email_code(
                "new@example.invalid",
                "secret123",
                "246810",
                base_url="https://api.heang.top",
            )
            public_session = manager.public_session()

            self.assertEqual(manager.requests[0]["url"], "https://api.heang.top/api/openclaw/auth/email-code/register")
            self.assertEqual(manager.requests[0]["body"]["password"], "secret123")
            self.assertEqual(manager.requests[0]["body"]["verification_code"], "246810")
            self.assertEqual(len(manager.requests), 1)
            self.assertEqual(session["memberName"], "new@example.invalid")
            self.assertEqual(session["gatewayDefaultModel"], "qwen3.7-plus")
            self.assertEqual(session["newApi"]["sessionCookie"], "session=fake-register-session-not-real")
            self.assertNotIn("secret123", repr(session))
            self.assertNotIn("secret123", repr(public_session))

    def test_register_business_error_does_not_probe_additional_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(
                AppPaths(temp_dir),
                register_error=NewApiAccountError("invalid verification code", status_code=400),
            )

            with self.assertRaisesRegex(NewApiAccountError, "invalid verification code"):
                manager.register_with_email_code(
                    "new@example.invalid",
                    "secret123",
                    "wrong-code",
                    base_url="https://api.heang.top",
                )

            self.assertEqual(
                [request["url"] for request in manager.requests],
                ["https://api.heang.top/api/openclaw/auth/email-code/register"],
            )

    def test_register_not_found_business_error_does_not_probe_compatibility_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(
                AppPaths(temp_dir),
                register_error=NewApiAccountError("verification code not found", status_code=400),
            )

            with self.assertRaisesRegex(NewApiAccountError, "verification code not found"):
                manager.register_with_email_code(
                    "new@example.invalid",
                    "secret123",
                    "wrong-code",
                    base_url="https://api.heang.top",
                )

            self.assertEqual(len(manager.requests), 1)

    def test_register_falls_back_to_legacy_managed_endpoint_before_native_register(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(AppPaths(temp_dir), missing_primary_register=True)

            session = manager.register_with_email_code(
                "new@example.invalid",
                "secret123",
                "246810",
                base_url="https://api.heang.top",
            )

            self.assertEqual(
                [request["url"] for request in manager.requests[:2]],
                [
                    "https://api.heang.top/api/openclaw/auth/email-code/register",
                    "https://api.heang.top/api/openclaw/email-code/register",
                ],
            )
            self.assertEqual(session["memberName"], "new@example.invalid")

    def test_register_rejects_cross_origin_managed_api_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(
                AppPaths(temp_dir),
                managed_api_base_url="https://api.heang.top/v1",
            )

            with self.assertRaisesRegex(NewApiAccountError, "域名"):
                manager.register_with_email_code(
                    "new@example.invalid",
                    "secret123",
                    "246810",
                    base_url="https://relay.example.invalid",
                )

            self.assertEqual(len(manager.requests), 1)

    def test_register_accepts_same_origin_custom_managed_api_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(
                AppPaths(temp_dir),
                managed_api_base_url="https://relay.example.invalid/openai/v1",
            )

            session = manager.register_with_email_code(
                "new@example.invalid",
                "secret123",
                "246810",
                base_url="https://relay.example.invalid",
            )

            self.assertEqual(session["gatewayBaseUrl"], "https://relay.example.invalid/openai/v1")

    def test_subscription_snapshot_reads_native_account_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = EmailCodeFakeManager(AppPaths(temp_dir))
            manager.login_with_email_code(
                "user@example.invalid",
                "654321",
                base_url="https://api.heang.top",
            )
            manager.requests.clear()

            snapshot = manager.subscription_snapshot()

            self.assertEqual(manager.requests[0]["url"], "https://api.heang.top/api/user/subscription")
            self.assertEqual(snapshot["mode"], "native")
            self.assertEqual(snapshot["plan"], "pro")
            self.assertEqual(snapshot["balance"], "1200")
            self.assertEqual(snapshot["usage"]["usedQuota"], "12")
            self.assertEqual(snapshot["purchaseUrl"], "https://api.heang.top/wallet")

    def test_session_file_protects_secret_fields_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NewApiAccountManager(AppPaths(temp_dir))
            session = {
                "source": ACCOUNT_SOURCE,
                "memberToken": "test-token-not-real",
                "gatewayImageAccessToken": "test-token-not-real",
                "gateway": {
                    "accessToken": "test-token-not-real",
                    "imageAccessToken": "test-token-not-real",
                },
                "newApi": {
                    "sessionCookie": "sid=secret-cookie",
                },
                "phoneAgent": {
                    "apiKey": "test-token-not-real",
                },
            }

            manager._write_session(session)
            with open(manager.session_path, "r", encoding="utf-8") as file:
                raw_text = file.read()
            loaded_raw = json.loads(raw_text)
            loaded_session = manager.current()

            if os.name == "nt":
                self.assertNotIn("test-token-not-real", raw_text)
                self.assertNotIn("sid=secret-cookie", raw_text)
                self.assertEqual(loaded_raw["memberToken"]["__loomSecret"], "dpapi")
            self.assertEqual(loaded_session["memberToken"], "test-token-not-real")
            self.assertEqual(loaded_session["newApi"]["sessionCookie"], "sid=secret-cookie")

    def test_default_sync_does_not_write_video_provider_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NewApiAccountManager(AppPaths(temp_dir))
            session = {
                "source": ACCOUNT_SOURCE,
                "gatewayBaseUrl": "https://api.heang.top/v1",
                "gatewayImageBaseUrl": "https://api.heang.top/v1",
                "gatewayDefaultModel": "qwen3.7-plus",
                "gatewayImageModel": "gpt-image-1",
                "gatewayVideoModel": "agnes-video-v1",
                "memberToken": "test-token-not-real",
                "gatewayImageAccessToken": "test-token-not-real",
                "phoneAgent": {
                    "baseUrl": "https://api.heang.top/v1",
                    "apiKey": "test-token-not-real",
                    "model": "agnes-2.0-flash",
                },
            }

            results = manager.sync_targets(session)

            self.assertIn("openclaw", [item["target"] for item in results])
            self.assertTrue(os.path.exists(AppPaths(temp_dir).wire_current))
            self.assertNotIn("video", [item["target"] for item in results])
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "video_config.json")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "videoapi_config.json")))

    def test_logout_clears_managed_launcher_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            manager = NewApiAccountManager(paths)
            session = {
                "source": ACCOUNT_SOURCE,
                "memberId": "newapi:test-user",
                "memberName": "test@example.invalid",
                "gatewayBaseUrl": "https://api.heang.top/v1",
                "gatewayImageBaseUrl": "https://api.heang.top/v1",
                "gatewayDefaultModel": "qwen3.7-plus",
                "gatewayImageModel": "gpt-image-1",
                "gatewayModels": ["qwen3.7-plus", "gpt-image-1", "agnes-2.0-flash"],
                "memberToken": "test-token-not-real",
                "gatewayImageAccessToken": "test-token-not-real",
                "phoneAgent": {
                    "baseUrl": "https://api.heang.top/v1",
                    "apiKey": "test-token-not-real",
                    "model": "agnes-2.0-flash",
                },
            }
            manager._write_session(session)
            manager.sync_targets(session)

            self.assertTrue(manager.logout())

            self.assertFalse(os.path.exists(manager.session_path))
            self.assertEqual(read_json(paths.wire_current, {}), {})
            self.assertEqual(read_json(os.path.join(paths.launcher_dir, "phone-agent.json"), {}), {"llm": {}})
            desktop_config = read_json(os.path.join(paths.launcher_dir, "desktop-agent.json"), {})
            self.assertEqual(desktop_config.get("provider"), {})
            self.assertEqual(desktop_config.get("llm"), {})
            self.assertEqual(desktop_config.get("chatProvider", {}).get("config"), {})
            dumped = repr(read_json(paths.wire_current, {}))
            dumped += repr(read_json(os.path.join(paths.launcher_dir, "phone-agent.json"), {}))
            dumped += repr(desktop_config)
            self.assertNotIn("test-token-not-real", dumped)

    def test_select_models_writes_text_phone_and_image_but_not_video_provider_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = NewApiAccountManager(AppPaths(temp_dir))
            session = {
                "source": ACCOUNT_SOURCE,
                "gatewayBaseUrl": "https://api.heang.top/v1",
                "gatewayImageBaseUrl": "https://api.heang.top/v1",
                "gatewayDefaultModel": "qwen3.7-plus",
                "gatewayImageModel": "gpt-image-1",
                "gatewayVideoModel": "agnes-video-v1",
                "gatewayModels": [
                    "qwen3.7-plus",
                    "gpt-4o",
                    "agnes-2.0-flash",
                    "gpt-image-1",
                    "seedream-image-v1",
                    "agnes-video-v1",
                ],
                "memberToken": "test-token-not-real",
                "gatewayImageAccessToken": "test-token-not-real",
                "gateway": {
                    "classifiedModels": {
                        "text": ["qwen3.7-plus", "gpt-4o"],
                        "phone": ["qwen3.7-plus", "agnes-2.0-flash"],
                        "image": ["gpt-image-1", "seedream-image-v1"],
                        "video": ["agnes-video-v1"],
                    }
                },
                "newApi": {
                    "modelClasses": {
                        "text": ["qwen3.7-plus", "gpt-4o"],
                        "phone": ["qwen3.7-plus", "agnes-2.0-flash"],
                        "image": ["gpt-image-1", "seedream-image-v1"],
                        "video": ["agnes-video-v1"],
                    }
                },
                "phoneAgent": {
                    "baseUrl": "https://api.heang.top/v1",
                    "apiKey": "test-token-not-real",
                    "model": "agnes-2.0-flash",
                },
            }
            manager._write_session(session)

            next_public = manager.select_models(
                text_model="gpt-4o",
                phone_model="qwen3.7-plus",
                image_model="seedream-image-v1",
                video_model="agnes-video-v1",
            )

            self.assertEqual(next_public["selectedModels"]["text"], "gpt-4o")
            self.assertEqual(next_public["selectedModels"]["phone"], "qwen3.7-plus")
            self.assertEqual(next_public["selectedModels"]["image"], "seedream-image-v1")
            self.assertEqual(next_public["selectedModels"]["videoDraft"], "agnes-video-v1")
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "video_config.json")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "videoapi_config.json")))

            auth_profiles = read_json(AppPaths(temp_dir).auth_profiles, {})
            provider = auth_profiles["models"]["providers"]["member_gateway"]
            self.assertEqual(provider["apiKey"], "test-token-not-real")
            self.assertEqual(provider["managedBy"], "heang_account")
            self.assertNotIn("gatewayVideoModel", provider)
            self.assertNotIn("videoModel", provider)
            self.assertTrue(os.path.exists(AppPaths(temp_dir).wire_current))
            phone_config = read_json(os.path.join(AppPaths(temp_dir).launcher_dir, "phone-agent.json"), {})
            self.assertEqual(phone_config["llm"]["model"], "qwen3.7-plus")

            models_json = read_json(os.path.join(temp_dir, "data", ".openclaw", "agents", "main", "agent", "models.json"), {})
            model_providers = models_json["providers"]
            self.assertEqual(len(model_providers), 1)
            model_provider = next(iter(model_providers.values()))
            self.assertEqual(model_provider["apiKey"], "test-token-not-real")
            self.assertNotIn("gatewayVideoModel", model_provider)
            self.assertNotIn("videoModel", model_provider)

            openclaw_config = read_json(AppPaths(temp_dir).openclaw_config, {})
            openclaw_providers = openclaw_config["models"]["providers"]
            self.assertEqual(len(openclaw_providers), 1)
            openclaw_provider = next(iter(openclaw_providers.values()))
            self.assertEqual(openclaw_provider["apiKey"], "test-token-not-real")
            self.assertNotIn("gatewayVideoModel", openclaw_provider)
            self.assertNotIn("videoModel", openclaw_provider)

    def test_license_manager_reads_protected_member_session_for_gateway_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(temp_dir)
            manager = NewApiAccountManager(paths)
            session = {
                "source": ACCOUNT_SOURCE,
                "memberId": "newapi:test-user",
                "memberName": "test@example.invalid",
                "gatewayBaseUrl": "https://api.heang.top/v1",
                "gatewayImageBaseUrl": "https://api.heang.top/v1",
                "gatewayDefaultModel": "qwen3.7-plus",
                "gatewayImageModel": "gpt-image-1",
                "gatewayVideoDraftModel": "agnes-video-v1",
                "gatewayModels": ["qwen3.7-plus", "gpt-image-1", "agnes-video-v1"],
                "memberToken": "test-token-not-real",
                "gatewayImageAccessToken": "test-token-not-real",
                "gateway": {
                    "accessToken": "test-token-not-real",
                    "imageAccessToken": "test-token-not-real",
                    "defaultModel": "qwen3.7-plus",
                    "imageModel": "gpt-image-1",
                    "videoDraftModel": "agnes-video-v1",
                    "models": ["qwen3.7-plus", "gpt-image-1", "agnes-video-v1"],
                },
            }

            manager._write_session(session)
            profile = LicenseManager(paths).current_gateway_profile()

            self.assertIsNotNone(profile)
            self.assertEqual(profile["apiKey"], "test-token-not-real")
            self.assertEqual(profile["imageApiKey"], "test-token-not-real")
            self.assertEqual(profile["defaultModel"], "qwen3.7-plus")
            self.assertEqual(profile["imageModel"], "gpt-image-1")
            self.assertEqual(profile["videoDraftModel"], "agnes-video-v1")
            self.assertNotIn("videoModel", profile)

    def test_sync_target_errors_are_redacted_before_storage_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs: list[str] = []
            manager = NewApiAccountManager(AppPaths(temp_dir), append_log=logs.append)
            secret = "s" + "k-" + "demo-secret"

            original_wire_service = account_module.WireService

            class FakeWireService:
                def __init__(self, *_args, **_kwargs):
                    pass

                def sync_from_session(self, _session, *, targets):
                    return {"syncResults": [{"target": targets[0], "ok": False, "error": "apiKey=[redacted]"}]}

            try:
                account_module.WireService = FakeWireService
                results = manager.sync_targets({"source": ACCOUNT_SOURCE}, targets=("image",))
            finally:
                account_module.WireService = original_wire_service
            dumped = repr(results) + repr(logs)

            self.assertNotIn(secret, dumped)
            self.assertIn("apiKey=[redacted]", dumped)


class LauncherTokenFakeManager(NewApiAccountManager):
    def __init__(
        self,
        paths: AppPaths,
        *,
        tokens: list[dict],
        create_token: str = "sk-created-token-not-real",
        create_fails: bool = False,
        bridge_token: str = "",
        bridge_models: list[str] | None = None,
        bridge_error: NewApiAccountError | None = None,
        bridge_api_base_url: str = "",
        model_by_token: dict[str, list[str]] | None = None,
    ):
        super().__init__(paths)
        self.tokens = list(tokens)
        self.create_token = create_token
        self.create_fails = create_fails
        self.bridge_token = bridge_token
        self.bridge_models = bridge_models or []
        self.bridge_error = bridge_error
        self.bridge_api_base_url = bridge_api_base_url
        self.model_by_token = model_by_token or {}
        self.requests: list[dict] = []
        self.synced_targets: tuple[str, ...] | None = None

    def _request_json(self, opener, url, *, method="GET", body=None, headers=None, timeout=20):
        self.requests.append({
            "url": url,
            "method": method,
            "body": body or {},
            "headers": headers or {},
            "timeout": timeout,
        })
        if url.endswith("/api/user/login"):
            return {
                "success": True,
                "data": {
                    "id": "u_123",
                    "username": (body or {}).get("username") or "user@example.invalid",
                    "email": "user@example.invalid",
                    "group": "standard",
                    "token": "user-session-token-not-real",
                },
            }
        if url.endswith("/api/openclaw/launcher-token"):
            if self.bridge_error:
                raise self.bridge_error
            if self.bridge_token:
                return {
                    "success": True,
                    "data": {
                        "userId": "u_123",
                        "account": "user@example.invalid",
                        "group": "standard",
                        "sessionCookie": "session=fake-session-not-real",
                        "remainQuota": 1000000,
                        "api": {"baseUrl": self.bridge_api_base_url} if self.bridge_api_base_url else {},
                        "source": "bridge",
                        "tokenKind": "launcher",
                        "permissionMode": "default",
                        "modelLimitsEnabled": False,
                        "unlimitedQuota": True,
                        "tokenGroup": "",
                        "tokenName": "LOOM Launcher test",
                        "apiKey": self.bridge_token,
                        "models": self.bridge_models,
                    },
                }
            raise NewApiAccountError("http_404")
        if url.endswith("/api/user/self"):
            return {
                "success": True,
                "data": {
                    "id": "u_123",
                    "username": "user@example.invalid",
                    "email": "user@example.invalid",
                    "group": "standard",
                    "quota": 1000000,
                    "used_quota": 12,
                    "request_count": 34,
                },
            }
        if url.endswith("/api/token/?p=0&page_size=100"):
            return {"success": True, "data": self.tokens}
        if url.endswith("/api/token/") and method == "POST":
            if self.create_fails:
                raise NewApiAccountError("token_create_unavailable")
            token_name = (body or {}).get("name") or "LOOM Launcher test"
            created = {
                "name": token_name,
                "key": self.create_token,
                "status": 1,
                "unlimited_quota": True,
            }
            self.tokens.append(created)
            return {"success": True, "data": created}
        if url.endswith("/api/user/models"):
            return {"success": True, "data": {"models": {"agnes-2.0-flash": {}}}}
        if url.endswith("/v1/models"):
            auth = (headers or {}).get("Authorization", "")
            token = auth.replace("Bearer", "", 1).strip()
            models = self.model_by_token.get(token, ["agnes-2.0-flash"])
            return {"object": "list", "data": [{"id": model} for model in models]}
        raise AssertionError(f"unexpected request: {url}")

    def sync_targets(self, session, *, targets=("openclaw", "image", "desktop", "phone")):
        self.synced_targets = targets
        session["lastSyncResults"] = [{"target": "openclaw", "ok": True}]
        return session["lastSyncResults"]


class EmailCodeFakeManager(NewApiAccountManager):
    def __init__(
        self,
        paths: AppPaths,
        *,
        register_error: NewApiAccountError | None = None,
        missing_primary_register: bool = False,
        managed_api_base_url: str = "https://api.heang.top/v1",
    ):
        super().__init__(paths)
        self.requests: list[dict] = []
        self.synced_targets: tuple[str, ...] | None = None
        self.register_error = register_error
        self.missing_primary_register = missing_primary_register
        self.managed_api_base_url = managed_api_base_url

    def _request_json(self, opener, url, *, method="GET", body=None, headers=None, timeout=20):
        self.requests.append({
            "url": url,
            "method": method,
            "body": body or {},
            "headers": headers or {},
            "timeout": timeout,
        })
        if "/api/verification?" in url:
            return {
                "success": True,
                "data": {
                    "sent": True,
                    "email": "user@example.invalid",
                    "retryAfter": 60,
                    "code": "123456",
                    "token": "sk-test-token-not-real",
                },
            }
        if url.endswith("/api/user/register"):
            return {
                "success": True,
                "message": "registered",
            }
        if url.endswith("/api/user/login"):
            username = (body or {}).get("username") or (body or {}).get("email") or "user@example.invalid"
            return {
                "success": True,
                "data": {
                    "id": "u_123",
                    "username": username,
                    "email": username,
                    "group": "standard",
                    "token": "user-session-token-not-real",
                },
            }
        if url.endswith("/api/user/self"):
            return {
                "success": True,
                "data": {
                    "id": "u_123",
                    "username": "new@example.invalid",
                    "email": "new@example.invalid",
                    "group": "standard",
                    "quota": 1000000,
                    "used_quota": 12,
                    "request_count": 34,
                },
            }
        if url.endswith("/api/openclaw/launcher-token"):
            return {
                "success": True,
                "data": {
                    "source": "bridge",
                    "apiKey": "sk-test-token-not-real",
                    "models": ["qwen3.7-plus", "gpt-4o", "gpt-image-1", "agnes-video-v1"],
                },
            }
        if url.endswith("/api/openclaw/auth/email-code/send"):
            return {
                "success": True,
                "data": {
                    "sent": True,
                    "email": body.get("email"),
                    "retryAfter": 60,
                },
            }
        if url.endswith("/api/openclaw/auth/email-code/register"):
            if self.missing_primary_register:
                raise NewApiAccountError("http_404", status_code=404)
            if self.register_error:
                raise self.register_error
        if (
            url.endswith("/api/openclaw/auth/email-code/login")
            or url.endswith("/api/openclaw/auth/email-code/register")
            or url.endswith("/api/openclaw/email-code/register")
        ):
            return {
                "success": True,
                "data": {
                    "launcherToken": "sess-test-launcher-not-real",
                    "account": {
                        "id": "u_123",
                        "email": body.get("email"),
                        "name": "LOOM Tester",
                        "plan": "standard",
                    },
                    "quota": {
                        "remaining": 1000000,
                        "unit": "tokens",
                    },
                    "api": {
                        "baseUrl": self.managed_api_base_url,
                        "token": "sk-test-token-not-real",
                        "tokenMasked": "sk-****real",
                    },
                    "sessionCookie": "session=fake-register-session-not-real",
                    "models": {
                        "text": ["qwen3.7-plus", "gpt-4o"],
                        "phone": ["agnes-2.0-flash"],
                        "image": ["gpt-image-1"],
                        "video": ["agnes-video-v1"],
                    },
                    "defaults": {
                        "textModel": "qwen3.7-plus",
                        "phoneModel": "agnes-2.0-flash",
                    },
                },
            }
        if url.endswith("/api/user/subscription"):
            return {
                "success": True,
                "data": {
                    "subscription": {
                        "plan": "pro",
                        "balance": 1200,
                        "expiresAt": "2026-12-31T00:00:00Z",
                        "purchaseUrl": "https://api.heang.top/wallet",
                    },
                    "usage": {
                        "usedQuota": 12,
                        "requestCount": 34,
                    },
                },
            }
        raise AssertionError(f"unexpected request: {url}")

    def sync_targets(self, session, *, targets=("openclaw", "image", "desktop", "phone")):
        self.synced_targets = targets
        session["lastSyncResults"] = [{"target": "openclaw", "ok": True}]
        return session["lastSyncResults"]


class EmailCodeBusinessErrorManager(NewApiAccountManager):
    def __init__(self, paths: AppPaths):
        super().__init__(paths)
        self.requests: list[dict] = []

    def _request_json(self, opener, url, *, method="GET", body=None, headers=None, timeout=20):
        self.requests.append({
            "url": url,
            "method": method,
            "body": body or {},
            "headers": headers or {},
            "timeout": timeout,
        })
        if "/api/verification?" in url:
            raise NewApiAccountError("The administrator has enabled the email domain name whitelist")
        if "/api/openclaw/" in url:
            raise AssertionError("business errors from /api/verification must not fall back")
        raise AssertionError(f"unexpected request: {url}")


if __name__ == "__main__":
    unittest.main()
