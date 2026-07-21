from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LICENSE_PAGE = os.path.join(REPO_ROOT, "src", "components", "license", "LicensePage.tsx")
BRAND_COMPONENT = os.path.join(REPO_ROOT, "src", "components", "brand", "LoomBrand.tsx")
PACKAGED_LOGO = os.path.join(REPO_ROOT, "src", "assets", "luming-logo.svg")
SPLASH_PAGE = os.path.join(REPO_ROOT, "src", "components", "brand", "LoomSplash.tsx")
API_FILE = os.path.join(REPO_ROOT, "src", "services", "api.ts")
STARTUP_CACHE_FILE = os.path.join(REPO_ROOT, "src", "services", "startupCache.ts")
SPLASH_VIDEO = os.path.join(REPO_ROOT, "public", "loom-motion", "luming-splash-v2.mp4")
SPLASH_POSTER = os.path.join(REPO_ROOT, "public", "loom-motion", "luming-splash-v2-poster.jpg")


class AccountUiContractTests(unittest.TestCase):
    def test_license_page_is_password_first_and_sends_registration_to_the_web(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("密码登录", source)
        self.assertNotIn("邮箱注册", source)
        self.assertNotIn("handleRegister", source)
        self.assertNotIn("accountApi.register", source)
        self.assertIn("发送验证码", source)
        self.assertIn("验证并登录", source)
        self.assertIn("accountApi.sendEmailCode", source)
        self.assertIn("purpose: 'login'", source)
        self.assertIn("accountApi.loginWithEmailCode", source)
        self.assertIn("邮箱验证码", source)
        self.assertIn("退出登录", source)
        self.assertIn("useState<AuthMode>('password')", source)
        self.assertIn("accountApi.capabilities", source)
        self.assertIn("inlineEmailCode", source)
        self.assertIn("webRegistrationRequired", source)
        self.assertIn("网页注册", source)
        self.assertIn("grid-cols-2", source)

    def test_account_identity_uses_the_shared_packaged_logo(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()
        with open(BRAND_COMPONENT, "r", encoding="utf-8") as handle:
            brand_source = handle.read()

        self.assertIn("import { LoomLogoMark } from '../brand/LoomBrand'", source)
        self.assertGreaterEqual(source.count("<LoomLogoMark"), 2)
        self.assertNotIn('/logo.png', source)
        self.assertIn("new URL('../../assets/luming-logo.svg', import.meta.url).href", brand_source)
        self.assertIn('src={LOGO_SRC}', brand_source)
        self.assertNotIn("'/loom-motion/logo.svg'", brand_source)
        self.assertTrue(os.path.isfile(PACKAGED_LOGO))

    def test_splash_uses_the_packaged_h264_video_without_the_legacy_iframe(self) -> None:
        with open(SPLASH_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("<video", source)
        self.assertIn("/loom-motion/luming-splash-v2.mp4", source)
        self.assertIn("/loom-motion/luming-splash-v2-poster.jpg", source)
        self.assertIn("muted", source)
        self.assertIn("playsInline", source)
        self.assertIn("onEnded", source)
        self.assertNotIn("<iframe", source)
        self.assertNotIn("logo_motion_vector-v1.html", source)
        self.assertTrue(os.path.isfile(SPLASH_VIDEO))
        self.assertTrue(os.path.isfile(SPLASH_POSTER))

    def test_subscription_entry_is_native_and_keeps_purchase_external(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("订阅", source)
        self.assertIn("余额", source)
        self.assertIn("套餐", source)
        self.assertIn("到期", source)
        self.assertIn("打开订阅页", source)
        self.assertIn("data-native-subscription-dashboard", source)
        self.assertIn("data-subscription-external-fallback", source)
        self.assertIn("账户与余额", source)
        self.assertIn("当前套餐", source)
        self.assertIn("套餐与购买", source)
        self.assertIn("打开账户中心", source)
        self.assertIn("loom-account-metric-grid", source)
        self.assertNotIn("<iframe", source)
        self.assertNotIn("订阅页已在当前页面打开", source)
        self.assertIn("accountApi.subscription", source)
        self.assertIn("purchaseUrl", source)

    def test_subscription_opening_works_for_guests_and_rejects_localhost_urls(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("safeSubscriptionUrl", source)
        self.assertIn("isLocalSubscriptionUrl", source)
        self.assertIn("handleOpenSubscription", source)
        self.assertNotIn("请先登录模型账号，再打开订阅页", source)
        self.assertIn("await openExternalUrl(subscriptionUrl)", source)
        self.assertIn("订阅页已在浏览器打开", source)
        self.assertIn("订阅页打开失败", source)
        self.assertIn("订阅页地址不可用", source)
        self.assertIn("当前网络不可用", source)
        self.assertIn("navigator.onLine === false", source)
        self.assertIn("localhost", source)
        self.assertIn("127.0.0.1", source)
        self.assertIn("DEFAULT_ACCOUNT_CENTER_URL", source)
        self.assertIn("`${DEFAULT_BASE_URL}/wallet`", source)
        self.assertIn("parsed.pathname.replace(/\\/+$/, '') === '/topup'", source)
        self.assertNotIn("`${DEFAULT_BASE_URL}/topup`", source)

    def test_account_login_defaults_to_domestic_accelerated_domain(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("const DEFAULT_BASE_URL = 'https://api.heang.top'", source)
        self.assertNotIn("const DEFAULT_BASE_URL = 'https://api-cn.heang.top'", source)

    def test_account_api_exposes_register_and_subscription(self) -> None:
        with open(API_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("register: (params", source)
        self.assertIn("api('/api/account/register', 'POST'", source)
        self.assertIn("subscription: ()", source)
        self.assertIn("api('/api/account/subscription')", source)
        self.assertIn("capabilities: ()", source)
        self.assertIn("api('/api/account/capabilities')", source)

    def test_account_page_uses_cached_safe_snapshot_before_manual_refresh(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()
        with open(STARTUP_CACHE_FILE, "r", encoding="utf-8") as handle:
            cache_source = handle.read()

        self.assertIn("loadCachedAccount", page_source)
        self.assertIn("saveCachedAccount", page_source)
        self.assertIn("accountCacheUsable", page_source)
        self.assertIn("LOOM_ACCOUNT_CACHE_KEY", cache_source)
        self.assertIn("sanitizeAccountForCache", cache_source)
        self.assertIn("delete safe.tokenMasked", cache_source)
        self.assertIn("delete safe.gatewayBaseUrl", cache_source)
        self.assertNotIn("已显示上一次账号快照", page_source)
        self.assertNotIn("LoggedInPanel", page_source)

    def test_runtime_ui_copy_does_not_use_relay_station_wording(self) -> None:
        forbidden = "\u4e2d\u8f6c\u7ad9"
        roots = (
            os.path.join(REPO_ROOT, "src"),
            os.path.join(REPO_ROOT, "python", "api"),
            os.path.join(REPO_ROOT, "python", "core"),
            os.path.join(REPO_ROOT, "python", "services"),
        )
        violations: list[str] = []
        for root in roots:
            for directory, _subdirs, files in os.walk(root):
                for name in files:
                    if not name.endswith((".py", ".ts", ".tsx")):
                        continue
                    path = os.path.join(directory, name)
                    with open(path, "r", encoding="utf-8") as handle:
                        if forbidden in handle.read():
                            violations.append(os.path.relpath(path, REPO_ROOT))
        self.assertEqual(violations, [])

    def test_legacy_local_authorization_flow_is_not_exposed(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("setLicenseInfo", source)
        self.assertNotIn("setAuthorized", source)
        self.assertNotIn("checkLicense", source)
        self.assertNotIn("licenseApi.activate", source)
        self.assertNotIn("授权码", source)

    def test_login_returns_on_auth_success_and_reports_background_sync(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()
        with open(API_FILE, "r", encoding="utf-8") as handle:
            api_source = handle.read()

        self.assertIn("syncPending", source)
        self.assertIn("本地智能体配置正在后台同步", source)
        self.assertIn("resp.syncPending", source)
        self.assertIn("syncPending?: boolean", api_source)

    def test_login_releases_the_form_before_subscription_refresh_finishes(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        finish_login = source.split("const finishLogin =", 1)[1].split("const handlePasswordLogin =", 1)[0]
        self.assertIn("void loadSubscription(true)", finish_login)
        self.assertNotIn("await loadSubscription(true)", finish_login)

    def test_login_post_is_never_replayed_by_the_local_bridge_client(self) -> None:
        with open(API_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("const canRetry = method === 'GET'", source)
        self.assertIn("if (canRetry && isTransientStatusReadError(error))", source)

    def test_background_subscription_refresh_cannot_restore_data_after_logout(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("subscriptionRequestVersion", source)
        self.assertIn("const requestVersion = ++subscriptionRequestVersion.current", source)
        self.assertIn("if (requestVersion !== subscriptionRequestVersion.current) return", source)
        logout_block = source.split("const logout =", 1)[1].split("const handleOpenSubscription =", 1)[0]
        self.assertIn("subscriptionRequestVersion.current += 1", logout_block)

    def test_password_login_stays_focused_and_keeps_registration_secondary(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("authMode !== 'password' &&", source)
        self.assertIn("autoFocus", source)
        self.assertIn("handleOpenRegistration", source)

    def test_logged_in_account_page_does_not_repeat_balance_plan_or_model_summaries(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        logged_in = source.split("if (loggedIn) {", 1)[1].split("\n  return (", 1)[0]
        self.assertNotIn('<GhostTile label="余额"', logged_in)
        self.assertNotIn('<GhostTile label="套餐"', logged_in)
        self.assertNotIn('<InfoPanel label="默认文本模型"', logged_in)
        self.assertIn('<MetricTile label="可用余额"', logged_in)
        self.assertIn('<MetricTile label="当前套餐"', logged_in)
        self.assertIn('<InfoRow label="默认文本模型"', logged_in)

    def test_account_identity_does_not_repeat_the_plan_summary(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        logged_in = source.split("if (loggedIn) {", 1)[1].split("\n  return (", 1)[0]
        self.assertNotIn("{account?.plan || 'default'}", logged_in)

    def test_expiry_summary_preserves_the_full_timestamp(self) -> None:
        with open(LICENSE_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        info_panel = source.split("const InfoPanel:", 1)[1].split("const SoftPill:", 1)[0]
        self.assertNotIn("truncate", info_panel)
        self.assertIn("break-words", info_panel)


if __name__ == "__main__":
    unittest.main()
