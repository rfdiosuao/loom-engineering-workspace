from __future__ import annotations

import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENT_PAGE = os.path.join(REPO_ROOT, "src", "components", "agents", "AgentInstallerPage.tsx")
AGENT_ACCESS_PAGE = os.path.join(REPO_ROOT, "src", "components", "agentAccess", "AgentAccessPage.tsx")
AGENT_PROMPT_FILE = os.path.join(REPO_ROOT, "src", "components", "agentAccess", "agentPrompt.ts")
FEATURE_REGISTRY = os.path.join(REPO_ROOT, "src", "features", "registry.ts")
API_FILE = os.path.join(REPO_ROOT, "src", "services", "api.ts")
STARTUP_CACHE_FILE = os.path.join(REPO_ROOT, "src", "services", "startupCache.ts")
LOOM_CLIENT = os.path.join(REPO_ROOT, "src", "services", "loomClient.ts")


class AgentInstallerPageContractTests(unittest.TestCase):
    def test_agent_installer_page_uses_loom_client_facade_for_backend_calls(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()
        with open(LOOM_CLIENT, "r", encoding="utf-8") as handle:
            client_source = handle.read()

        self.assertIn("loomClient", source)
        self.assertIn("loomClient.components.status()", source)
        self.assertIn("loomClient.diagnostics.prerequisites()", source)
        self.assertIn("loomClient.jobs.list(20)", source)
        self.assertIn("loomClient.process.status()", source)
        self.assertIn("loomClient.process.waitForReady", source)
        self.assertNotIn("componentApi.", source)
        self.assertNotIn("diagnosticsApi.", source)
        self.assertNotIn("jobApi.", source)
        self.assertNotIn("processApi.", source)
        self.assertIn("jobs:", client_source)
        self.assertIn("process:", client_source)

    def test_install_page_copy_is_readable_chinese_not_mojibake(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        mojibake_markers = tuple(chr(code) for code in (
            0x93C5,
            0x7F02,
            0x935A,
            0x9353,
            0x59AB,
            0x7039,
            0x7ECB,
            0x941C,
            0x95BF,
            0x4FD9,
            0x255C,
        ))
        for marker in mojibake_markers:
            self.assertNotIn(marker, source)

    def test_install_page_exposes_retry_and_log_panel_for_demo_flow(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-agent-log-panel", source)
        self.assertIn("data-agent-retry-button", source)
        self.assertIn("安装日志", source)
        self.assertIn("重试安装", source)

    def test_install_log_whole_panel_is_collapsed_by_default_with_summary_row(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertRegex(source, r"<details\s+data-agent-log-panel(?![^>]*\sopen(?:=|\s|>))")
        self.assertIn("data-agent-log-summary", source)
        self.assertIn("data-agent-log-operation", source)

    def test_backend_progress_is_not_replayed_into_local_history_and_is_normalized_per_operation(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        progress_callback = source[
            source.index("const recordJobProgress"):
            source.index("const refresh =", source.index("const recordJobProgress"))
        ]
        self.assertNotIn("pushLog(", progress_callback)
        self.assertIn("normalizeOperationHistory", source)
        self.assertIn("groupInstallLogEntriesByOperation", source)
        self.assertIn("operationId", source)

    def test_install_log_supports_copy_and_export_without_exposing_full_history_by_default(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("copyInstallLog", source)
        self.assertIn("exportInstallLog", source)
        self.assertIn("formatInstallLogEntries", source)
        self.assertIn("data-agent-copy-log-button", source)
        self.assertIn("data-agent-export-log-button", source)
        self.assertIn("复制日志", source)
        self.assertIn("导出日志", source)

    def test_prepare_flow_installs_when_detection_finds_upgrade_available(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("needsInstallAfterDetect", source)
        self.assertIn("upgrade_available", source)
        self.assertIn("检测到需安装或升级，开始下载安装", source)

    def test_destructive_or_system_modifying_actions_are_confirmed(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("confirmPreflightRepair", source)
        self.assertIn("loomClient.diagnostics.repairPrerequisites()", source)
        self.assertIn("loomClient.components.install(component.id, { confirmed: true", source)

    def test_preflight_detection_uses_corner_busy_state_without_locking_page_scroll(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-installer-nonblocking", source)
        self.assertIn("data-agent-page-locked", source)
        self.assertIn("preflightBusy", source)
        self.assertIn("blockingBusy", source)
        self.assertIn("const pageLocked = loading", source)
        self.assertIn("const controlsLocked = loading", source)
        self.assertIn("const busyOverlayMode = (preflightBusy || componentJobBusy || Boolean(modelConfigBusy)) && !blockingBusy ? 'corner' : 'blocking'", source)
        self.assertIn("aria-busy={busyOverlayActive}", source)
        self.assertIn("overflow-y-auto", source)
        self.assertNotIn("overflow-y-hidden", source)

    def test_agent_access_copy_is_available_on_the_dedicated_page(self) -> None:
        with open(AGENT_ACCESS_PAGE, "r", encoding="utf-8") as handle:
            access_source = handle.read()
        with open(AGENT_PROMPT_FILE, "r", encoding="utf-8") as handle:
            prompt_source = handle.read()
        with open(FEATURE_REGISTRY, "r", encoding="utf-8") as handle:
            registry_source = handle.read()

        self.assertIn("data-agent-one-shot-copy", access_source)
        self.assertIn("buildOneShotAgentPrompt(mcpJson)", access_source)
        self.assertIn("复制接入提示词", access_source)
        self.assertIn("手机矩阵", prompt_source)
        self.assertIn("生图", prompt_source)
        self.assertIn("生视频", prompt_source)
        self.assertIn("key: 'agentAccess'", registry_source)

    def test_codex_and_claude_model_config_controls_are_exposed(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-agent-model-config", source)
        self.assertIn("data-agent-model-source-card", source)
        self.assertIn("data-agent-one-click-config-lock", source)
        self.assertIn("data-agent-custom-provider-card", source)
        self.assertIn("data-agent-custom-provider-select", source)
        self.assertIn("data-codex-model-verification", source)
        self.assertIn("模型连通性已验证", source)
        self.assertIn("尚未完成真实模型验证", source)
        self.assertIn("data-agent-custom-base-url-input", source)
        self.assertIn("data-agent-custom-api-key-input", source)
        self.assertIn("data-agent-custom-model-input", source)
        self.assertIn("customModelPlaceholder", source)
        self.assertIn("loomClient.wire.custom", source)
        self.assertIn("type=\"password\"", source)
        self.assertIn("autoComplete=\"off\"", source)
        self.assertIn("status?.wireManagedBy || managedBy", source)
        self.assertIn("availableManagedBy === 'heang_account'", source)
        self.assertIn("登录后解锁", source)
        self.assertIn("loomClient.components.modelConfigStatus", source)
        self.assertIn("loomClient.components.applyModelConfig", source)

    def test_one_click_model_source_never_writes_until_explicit_apply(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("onClick={() => setSourceMode('oneClick')}", source)
        self.assertIn("data-agent-model-apply", source)
        self.assertNotIn("if (!oneClickLocked) onApply();", source)
        self.assertIn("选择模型不会修改本机", source)
        self.assertIn("只有点击“写入配置”后才会更新 Codex / Claude Code", source)
        self.assertIn("Codex / Claude Code 模型", source)

    def test_codex_model_source_can_restore_official_channel_explicitly(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-agent-model-disable", source)
        self.assertIn("恢复 OpenAI 官方渠道", source)
        self.assertIn("loomClient.components.disableModelConfig", source)
        self.assertIn("status?.channelMode === 'official'", source)
        self.assertNotIn("onClick={() => onDisable()}", source)

    def test_codex_always_prompts_for_scoped_restart_after_model_change(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-agent-model-restart-dialog", source)
        self.assertIn("data-agent-model-restart-wall", source)
        self.assertIn("配置已写入", source)
        self.assertIn("稍后重启", source)
        self.assertIn("重启 Codex", source)
        self.assertIn("loomClient.components.restart", source)
        self.assertIn("if (component.id === 'codex-desktop')", source)
        self.assertNotIn("component.id === 'codex-desktop' && componentStatus === 'started'", source)
        self.assertIn("setModelConfigBusy('')", source)
        self.assertIn("data-agent-model-restart-pending", source)
        self.assertIn("position: 'fixed'", source)
        self.assertIn("bottom: '20px'", source)
        self.assertIn("right: '20px'", source)
        restart_source = source[
            source.index("const restartCodexAfterModelChange"):
            source.index("const applyModelConfig")
        ]
        self.assertLess(
            restart_source.index("beginModelConfigOperation(component.id)"),
            restart_source.index("setBusyAction('restart')"),
        )

    def test_model_config_failure_opens_action_wall_and_preserves_backend_action(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()
        with open(API_FILE, "r", encoding="utf-8") as handle:
            api_source = handle.read()

        self.assertIn("data-agent-model-write-failure-dialog", source)
        self.assertIn("配置未写入", source)
        self.assertIn("重新登录模型账号", source)
        self.assertIn("account_relogin_required", source)
        self.assertIn("setCurrentPage('license')", source)
        self.assertIn("normalizeLoomError", source)
        self.assertIn("throw { ...result, error:", api_source)

    def test_openclaw_exposes_one_click_model_config_and_web_entry(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("new Set(['codex-desktop', 'claude-code', 'opencode', 'openclaw-companion'])", source)
        self.assertIn("data-agent-open-web-button", source)
        self.assertIn("openWeb(selected)", source)
        self.assertIn("isOpenClawComponent(selected)", source)

    def test_npm_installed_agents_require_node_and_npm_before_install(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("'claude-code': new Set(['python_runtime', 'node', 'npm', 'data_dir'])", source)
        self.assertIn("opencode: new Set(['python_runtime', 'node', 'npm', 'data_dir'])", source)
        self.assertIn("'openclaw-companion': new Set(['python_runtime', 'node', 'npm', 'data_dir'])", source)

    def test_openclaw_web_entry_checks_or_starts_local_service_before_opening(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("OPENCLAW_WEB_URL", source)
        self.assertIn("loomClient.process.status", source)
        self.assertIn("loomClient.process.start", source)
        self.assertIn("loomClient.process.waitForReady", source)
        self.assertIn("请先安装 OpenClaw", source)
        self.assertIn("OpenClaw 网页版已打开", source)
        self.assertIn("OpenClaw 网页版启动失败", source)

    def test_agent_detail_groups_uninstall_and_advanced_settings_like_demo_layout(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("data-agent-danger-zone", source)
        self.assertIn("卸载", source)
        self.assertIn("高级详情", source)
        self.assertIn("data-agent-advanced-settings", source)

    def test_agent_page_does_not_expose_nonfunctional_rollback_controls(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertNotIn("回滚配置", source)
        self.assertNotIn("onRollback", source)
        self.assertNotIn("onClick={() => rollback(selected)}", source)
        self.assertNotIn("const rollback = async", source)

    def test_component_warning_is_sanitized_before_ui_display(self) -> None:
        with open(API_FILE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("sanitizeComponentSnapshot", source)
        self.assertIn("manifest_unavailable", source)
        self.assertIn("All manifest sources", source)
        self.assertIn("正式组件清单未就绪。当前仅支持本机检测", source)

    def test_install_actions_lock_when_formal_manifest_is_unavailable(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()
        with open(API_FILE, "r", encoding="utf-8") as handle:
            api_source = handle.read()

        self.assertIn("installLocked?: boolean", api_source)
        self.assertIn("manifestInstallLocked", page_source)
        self.assertIn("installActionsLocked", page_source)
        self.assertIn("安装清单未就绪，安装和启动暂不可用", page_source)
        self.assertIn("if (!snapshot) return true", page_source)
        self.assertIn("disabled={controlsLocked || installActionsLocked || isWorking(selected.status)}", page_source)

    def test_install_actions_lock_while_manifest_is_loading(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()

        self.assertIn("if (!snapshot) return true", page_source)

    def test_first_open_does_not_run_sequential_auto_detect_scan(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()

        self.assertNotIn("AUTO_DETECT_COMPONENT_IDS", page_source)
        self.assertNotIn("autoDetectAttempted", page_source)
        self.assertNotIn("shouldAutoDetectOnFirstOpen", page_source)
        self.assertNotIn("for (const component of targets)", page_source)
        self.assertNotIn("loomClient.components.install(component.id, { confirmed: false", page_source)

    def test_preflight_uses_quick_prerequisite_api_and_scoped_repair(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()

        self.assertIn("loomClient.diagnostics.prerequisites()", page_source)
        self.assertIn("loomClient.diagnostics.repairPrerequisites()", page_source)
        self.assertNotIn("loomClient.diagnostics.run()", page_source)
        self.assertNotIn("loomClient.diagnostics.repair({ confirmed: true })", page_source)

    def test_job_polling_and_component_actions_are_scoped_to_active_component_jobs(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()

        self.assertIn("data-installer-active-job", page_source)
        self.assertIn("activeJobComponentIds", page_source)
        self.assertIn("const componentJobBusy = activeJobComponentIds.size > 0", page_source)
        self.assertIn("const selectedBusy = Boolean(selected && activeJobComponentIds.has(selected.id))", page_source)
        self.assertIn("const selectedActiveJob", page_source)
        self.assertIn("selectedActiveJob?.progress?.message", page_source)
        self.assertIn("data-installer-job-progress", page_source)
        self.assertIn("if (!jobs.some((job) => job.status === 'running' || job.status === 'queued')) return undefined;", page_source)
        self.assertIn("setSelectedId(component.id)", page_source)

    def test_first_open_uses_cached_preflight_until_user_refreshes(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()
        with open(STARTUP_CACHE_FILE, "r", encoding="utf-8") as handle:
            cache_source = handle.read()

        self.assertIn("loadCachedPreflight", page_source)
        self.assertIn("saveCachedPreflight", page_source)
        self.assertIn("preflightCacheUsable", page_source)
        self.assertIn("const reusablePreflight", page_source)
        self.assertIn("const cached = loadCachedPreflight()", page_source)
        self.assertIn("if (reusablePreflight)", page_source)
        self.assertIn("refreshPreflight({ preferCache: true })", page_source)
        self.assertIn("refreshPreflight({ force: true })", page_source)
        self.assertIn("measuredAt", page_source)
        self.assertIn("totalMs", page_source)
        self.assertIn("LOOM_PREFLIGHT_CACHE_KEY", cache_source)
        self.assertIn("STARTUP_CACHE_TTL_MS", cache_source)
        self.assertIn("PREFLIGHT_NON_OK_CACHE_TTL_MS", cache_source)
        self.assertIn("status === 'ok'", cache_source)
        self.assertIn("readCacheWithTtl<DiagnosticReport>(LOOM_PREFLIGHT_CACHE_KEY, PREFLIGHT_NON_OK_CACHE_TTL_MS)", cache_source)
        self.assertIn("Array.isArray(report.checks)", cache_source)

    def test_refresh_preflight_returns_immediately_on_cache_hit_without_prerequisite_recheck(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()

        cached_branch = """if (options.preferCache && cached) {
      cachedPreflight.current = cached;
      setPreflight(cached);
      setPreflightError('');
      setPreflightLoading(false);
      return;
    }"""
        self.assertIn(cached_branch, page_source)
        self.assertIn("const report = await loomClient.diagnostics.prerequisites();", page_source)

    def test_cached_preflight_is_not_rechecked_on_page_return_even_when_not_all_ok(self) -> None:
        with open(STARTUP_CACHE_FILE, "r", encoding="utf-8") as handle:
            cache_source = handle.read()

        self.assertIn("export const PREFLIGHT_NON_OK_CACHE_TTL_MS = STARTUP_CACHE_TTL_MS", cache_source)
        self.assertNotIn("5 * 60 * 1000", cache_source)

    def test_old_auto_detection_deep_scan_effect_is_removed(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()

        self.assertNotIn("pushLog(`自动检测", page_source)
        self.assertNotIn("for (const component of [])", page_source)
        self.assertNotIn("return;\n    void (async () => {", page_source)

    def test_agent_install_repairs_cached_missing_prerequisites_before_component_install(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()

        self.assertIn("prerequisiteNeedsRepair", page_source)
        self.assertIn("blockingPrerequisiteIssues", page_source)
        self.assertIn("repairMissingPrerequisites", page_source)
        self.assertIn("await repairMissingPrerequisites", page_source)
        self.assertIn("const blocking = blockingPrerequisiteIssues(report, componentId)", page_source)

    def test_official_codex_does_not_require_cli_runtime_prerequisites(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()

        self.assertIn("COMPONENT_REQUIRED_PREREQ_IDS", page_source)
        self.assertIn("'codex-desktop': new Set()", page_source)
        self.assertIn("requiredPrerequisiteIdsForComponent", page_source)
        self.assertIn("ensurePreflightReady(component.id)", page_source)
        self.assertIn("repairMissingPrerequisites(report, componentId)", page_source)
        self.assertIn("blockingPrerequisiteIssues(report, componentId)", page_source)

    def test_codex_install_and_start_only_read_model_status(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            page_source = handle.read()

        self.assertIn("readAgentModelConfigStatus", page_source)
        self.assertNotIn("ensureAgentModelConfig", page_source)
        self.assertEqual(page_source.count("loomClient.components.applyModelConfig"), 1)
        self.assertIn("loomClient.components.applyCustomModelConfig", page_source)
        self.assertIn("Codex 未写入 LOOM 模型配置，将沿用 Codex 当前配置或默认登录方式继续启动", page_source)
        self.assertNotIn("throw new Error('Codex 已安装，但模型配置尚未就绪", page_source)

    def test_codex_start_uses_fast_job_polling(self) -> None:
        with open(API_FILE, "r", encoding="utf-8") as handle:
            api_source = handle.read()

        self.assertIn("intervalMs: 250", api_source)

    def test_codex_start_has_a_bounded_wait_instead_of_the_install_timeout(self) -> None:
        with open(API_FILE, "r", encoding="utf-8") as handle:
            api_source = handle.read()

        self.assertIn("const COMPONENT_START_TIMEOUT_MS = 45_000", api_source)
        self.assertIn("timeoutMs: COMPONENT_START_TIMEOUT_MS", api_source)

    def test_codex_card_is_the_official_chatgpt_app_and_does_not_require_python(self) -> None:
        with open(AGENT_PAGE, "r", encoding="utf-8") as handle:
            source = handle.read()

        self.assertIn("ChatGPT Codex 原版", source)
        self.assertIn("Microsoft Store", source)
        self.assertIn("'codex-desktop': new Set()", source)
        self.assertIn("安装原版", source)
        self.assertIn("等待 Microsoft Store 完成安装", source)
        self.assertIn("原版应用请在 Windows 设置中卸载", source)
        self.assertNotIn("'codex-desktop': new Set(['python_runtime'])", source)


if __name__ == "__main__":
    unittest.main()
