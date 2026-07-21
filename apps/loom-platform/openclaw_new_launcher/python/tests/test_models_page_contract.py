from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS_PAGE = os.path.join(REPO_ROOT, "src", "components", "models", "ModelsPage.tsx")
LOOM_CLIENT = os.path.join(REPO_ROOT, "src", "services", "loomClient.ts")
LOOM_CONTRACTS = os.path.join(REPO_ROOT, "src", "services", "loomContracts.ts")


class ModelsPageContractTests(unittest.TestCase):
    def test_models_page_uses_loom_client_facade_for_backend_calls(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("loomClient", source)
        self.assertIn("loomClient.account.current()", source)
        self.assertIn("loomClient.account.sync()", source)
        self.assertIn("loomClient.account.selectModels", source)
        self.assertIn("loomClient.wire.current()", source)
        self.assertIn("loomClient.wire.custom", source)
        self.assertIn("loomClient.wire.rollback()", source)
        self.assertNotIn("accountApi.", source)
        self.assertNotIn("wireApi.", source)

    def test_loom_client_contract_files_define_account_and_wire_surface(self) -> None:
        with open(LOOM_CLIENT, "r", encoding="utf-8") as handle:
            client_source = handle.read()
        with open(LOOM_CONTRACTS, "r", encoding="utf-8") as handle:
            contract_source = handle.read()

        self.assertIn("export const loomClient", client_source)
        self.assertIn("account:", client_source)
        self.assertIn("wire:", client_source)
        self.assertIn("AccountSnapshot", contract_source)
        self.assertIn("WireSnapshot", contract_source)

    def test_models_page_uses_account_snapshot_cache_without_visible_snapshot_banner(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("loadCachedAccount", source)
        self.assertIn("accountCacheUsable", source)
        self.assertIn("saveCachedAccount", source)
        self.assertIn("cachedAccountRef", source)
        self.assertIn("usingCachedAccount", source)
        self.assertNotIn("已显示上一次账号快照", source)
        self.assertNotIn("离线快照", source)
        self.assertRegex(source, r"loomClient\.account\.current\(\)[\s\S]+?loadCachedAccount\(\)")

    def test_cached_account_snapshot_is_not_treated_as_writable_session(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("managedWritable", source)
        self.assertIn("当前只是离线账号快照，请重新登录后再同步模型。", source)
        self.assertIn("当前只是离线账号快照，请重新登录后再保存模型选择。", source)
        self.assertIn("disabled={busy || loading || !managedWritable}", source)
        self.assertRegex(source, r"if \(usingCachedAccount\)[\s\S]+?setCurrentPage\('license'\)")

    def test_off_model_source_uses_backend_rollback_instead_of_frontend_only_toggle(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("disableModelSource", source)
        self.assertIn("loomClient.wire.rollback", source)
        self.assertIn("没有可回滚的模型配置", source)
        self.assertNotIn("onClick={() => setSourceMode('off')}", source)

    def test_managed_model_source_requires_login_but_custom_provider_does_not(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("sourceMode === 'custom'", source)
        self.assertIn("loomClient.wire.custom", source)
        self.assertIn("sourceMode === 'managed'", source)
        self.assertIn("!loggedIn", source)
        self.assertIn("setCurrentPage('license')", source)

    def test_models_page_restores_current_custom_wire_snapshot(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("loomClient.wire.current", source)
        self.assertIn("applyWireSnapshot", source)
        self.assertIn("wire.managedBy === 'custom_provider'", source)
        self.assertIn("setCustomTextModel(wire.models?.text || '')", source)
        self.assertIn("setCustomBaseUrl(wire.baseUrl || '')", source)
        self.assertIn("data-custom-phone-model-input", source)
        self.assertIn("留空使用手机默认模型", source)


    def test_models_page_does_not_show_non_text_models_as_text_choices(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("looksLikeNonTextModel", source)
        self.assertIn("textModelValues(account?.models?.text)", source)
        self.assertIn("firstTextChoice(managedTextModelValues(next), next?.selectedModels?.text)", source)
        self.assertIn("wire.models?.text && !looksLikeNonTextModel(wire.models.text)", source)
        self.assertIn("managedTextModels", source)

    def test_models_page_does_not_merge_stale_selected_text_into_online_choices(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("missingManagedTextModel", source)
        self.assertIn("managedTextModels.length === 0", source)
        self.assertIn("!missingManagedTextModel", source)
        self.assertNotIn("mergeModelOptions(textModelValues(account?.models?.text), textModel, account?.selectedModels?.text)", source)

    def test_models_page_does_not_offer_qwen_default_when_managed_text_catalog_is_empty(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("managedTextModelValues", source)
        self.assertIn("account.selectedModels?.text", source)
        self.assertIn("managedTextModelValues(account)", source)
        self.assertNotIn("const DEFAULT_TEXT_MODEL = 'qwen3.7-plus'", source)

    def test_models_page_counts_model_classes_separately(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("textCount", source)
        self.assertIn("imageCount", source)
        self.assertIn("videoCount", source)
        self.assertIn("文本", source)
        self.assertIn("图像", source)
        self.assertIn("视频", source)


    def test_models_page_custom_provider_is_compact_provider_form(self) -> None:
        with open(MODELS_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("CUSTOM_PROVIDER_OPTIONS", source)
        self.assertIn("data-model-custom-provider-card", source)
        self.assertIn("data-model-custom-provider-select", source)
        self.assertIn("OpenRouter", source)
        self.assertIn("DeepSeek", source)
        self.assertIn("Moonshot - Kimi", source)
        self.assertIn("仅保存在本机", source)
        self.assertIn("使用陌生的第三方 API Key 需谨慎", source)


if __name__ == "__main__":
    unittest.main()
