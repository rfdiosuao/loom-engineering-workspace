from __future__ import annotations

import os
import sys
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


class AgentCapabilityRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.capabilities = [
            {
                "name": "loom.capabilities.list",
                "displayName": "查看能力目录",
                "domain": "agent",
                "available": True,
            },
            {"name": "loom.media.image.generate", "domain": "media", "available": True},
            {"name": "loom.media.video.generate", "domain": "media", "available": True},
            {"name": "loom.media.assets.list", "domain": "media", "available": True},
            {"name": "loom.media.asset.transfer", "domain": "media", "available": True},
            {"name": "loom.mcp.loom.loom_media_config", "domain": "media", "available": True},
            {"name": "loom.mcp.loom.loom_media_save_image_config", "domain": "media", "available": True},
            {"name": "loom.mcp.loom.loom_media_save_video_config", "domain": "media", "available": True},
            {"name": "loom.mcp.loom.loom_media_test_image", "domain": "media", "available": True},
            {"name": "loom.mcp.loom.loom_media_test_video", "domain": "media", "available": True},
            {"name": "loom.phone.publish", "domain": "phone", "available": True},
            {"name": "loom.cli.phone.quick-task", "domain": "phone", "available": True},
            {"name": "loom.mcp.loom.loom_phone_template_task", "domain": "phone", "available": True},
            {"name": "loom.cli.phone.read", "domain": "phone", "available": True},
            {"name": "loom.cli.phone.status", "domain": "phone", "available": True},
            {"name": "loom.mcp.loom.loom_phone_adb_doctor", "domain": "phone", "available": True},
            {"name": "loom.mcp.loom.loom_phone_events_start", "domain": "phone", "available": True},
            {"name": "loom.mcp.loom.loom_phone_events_status", "domain": "phone", "available": True},
            {"name": "loom.mcp.loom.loom_phone_events_stop", "domain": "phone", "available": True},
            {"name": "loom.matrix.dispatch", "domain": "matrix", "available": True},
            {"name": "loom.matrix.cancel", "domain": "matrix", "available": True},
            {"name": "loom.matrix.retry", "domain": "matrix", "available": True},
            {"name": "loom.matrix.screenshot", "domain": "matrix", "available": True},
            {"name": "loom.matrix.status", "domain": "matrix", "available": True},
            {"name": "loom.cli.matrix.watch", "domain": "matrix", "available": True},
            {"name": "loom.cli.template.run", "domain": "matrix", "available": True},
            {"name": "loom.cli.experience.report", "domain": "matrix", "available": True},
            {"name": "loom.acquisition.run", "domain": "acquisition", "available": True},
            {"name": "loom.agent.install", "domain": "agent", "available": True},
            {"name": "loom.mcp.loom.loom_agent_detect", "domain": "agent", "available": True},
            {"name": "loom.mcp.loom.loom_agent_install", "domain": "agent", "available": True},
            {"name": "loom.mcp.loom.loom_agent_list", "domain": "agent", "available": True},
            {"name": "loom.mcp.loom.loom_agent_rollback", "domain": "agent", "available": True},
            {"name": "loom.mcp.loom.loom_agent_start", "domain": "agent", "available": True},
            {"name": "loom.mcp.loom.loom_agent_uninstall", "domain": "agent", "available": True},
            {"name": "loom.schedule.add", "domain": "schedule", "available": True},
            {"name": "loom.mcp.loom.loom_schedule_list", "domain": "schedule", "available": True},
            {"name": "loom.mcp.loom.loom_schedule_add", "domain": "schedule", "available": True},
            {"name": "loom.mcp.loom.loom_schedule_run", "domain": "schedule", "available": True},
            {"name": "loom.mcp.loom.loom_schedule_cancel", "domain": "schedule", "available": True},
            {"name": "loom.settings.theme.set", "domain": "settings", "available": True},
            {"name": "loom.mcp.loom.loom_settings_theme", "domain": "settings", "available": True},
            {"name": "loom.mcp.loom.loom_settings_theme_list", "domain": "settings", "available": True},
            {"name": "loom.mcp.loom.loom_settings_update_check", "domain": "settings", "available": True},
            {"name": "loom.mcp.loom.loom_settings_update_install", "domain": "settings", "available": True},
            {"name": "loom.cli.account.current", "domain": "account", "available": True},
            {"name": "loom.mcp.loom.loom_account_current", "domain": "account", "available": True},
            {"name": "loom.mcp.loom.loom_account_subscription", "domain": "account", "available": True},
            {"name": "loom.mcp.loom.loom_account_send_code", "domain": "account", "available": True},
            {"name": "loom.mcp.loom.loom_account_login_code", "domain": "account", "available": True},
            {"name": "loom.mcp.loom.loom_account_login_password", "domain": "account", "available": True},
            {"name": "loom.mcp.loom.loom_account_logout", "domain": "account", "available": True},
            {"name": "loom.mcp.loom.loom_account_sync", "domain": "account", "available": True},
            {"name": "loom.mcp.loom.loom_account_select_models", "domain": "account", "available": True},
            {"name": "loom.cli.models", "domain": "models", "available": True},
            {"name": "loom.mcp.loom.loom_agent_model_status", "domain": "agent", "available": True},
            {"name": "loom.mcp.loom.loom_agent_model_apply", "domain": "agent", "available": True},
            {"name": "loom.mcp.loom.loom_agent_model_rollback", "domain": "agent", "available": True},
            {"name": "loom.mcp.loom.loom_wire_current", "domain": "models", "available": True},
            {"name": "loom.mcp.loom.loom_wire_custom", "domain": "models", "available": True},
            {"name": "loom.mcp.loom.loom_wire_sync", "domain": "models", "available": True},
            {"name": "loom.mcp.loom.loom_wire_verify", "domain": "models", "available": True},
            {"name": "loom.mcp.loom.loom_wire_rollback", "domain": "models", "available": True},
            {"name": "loom.mcp.loom.loom_acquisition_agent_result", "domain": "acquisition", "available": True},
            {"name": "loom.mcp.loom.loom_lead_list", "domain": "acquisition", "available": True},
            {"name": "loom.mcp.loom.loom_lead_record", "domain": "acquisition", "available": True},
            {"name": "loom.mcp.loom.loom_feishu_status", "domain": "integration", "available": True},
            {"name": "loom.mcp.loom.loom_feishu_doctor", "domain": "integration", "available": True},
            {"name": "loom.mcp.loom.loom_feishu_install", "domain": "integration", "available": True},
            {"name": "loom.mcp.loom.loom_feishu_login", "domain": "integration", "available": True},
            {"name": "loom.mcp.loom.loom_feishu_bind_table", "domain": "integration", "available": True},
            {"name": "loom.mcp.loom.loom_feishu_create_table", "domain": "integration", "available": True},
            {"name": "loom.mcp.loom.loom_feishu_test_write", "domain": "integration", "available": True},
            {"name": "loom.mcp.loom.loom_feishu_retry_sync", "domain": "integration", "available": True},
            {"name": "loom.mcp.loom.loom_feishu_reconcile", "domain": "integration", "available": True},
            {"name": "loom.cli.jobs.list", "domain": "jobs", "available": True},
            {"name": "loom.cli.jobs.get", "domain": "jobs", "available": True},
            {"name": "loom.mcp.loom.loom_status", "domain": "system", "available": True},
            {"name": "loom.cli.logs.tail", "domain": "diagnostics", "available": True},
            {"name": "loom.diagnostics.run", "domain": "diagnostics", "available": True},
            {"name": "loom.mcp.loom.loom_doctor", "domain": "diagnostics", "available": True},
            {"name": "loom.mcp.loom.loom_diagnostics_run", "domain": "diagnostics", "available": True},
            {"name": "loom.mcp.loom.loom_diagnostics_repair", "domain": "diagnostics", "available": True},
            {"name": "loom.mcp.loom.loom_diagnostics_export", "domain": "diagnostics", "available": True},
            {"name": "loom.settings.update.check", "domain": "settings", "available": True},
            {"name": "loom.settings.update.install", "domain": "settings", "available": True},
            {"name": "loom.license.current", "domain": "license", "available": True},
            {"name": "loom.license.activate", "domain": "license", "available": True},
            {"name": "loom.mcp.loom.loom_license_current", "domain": "license", "available": True},
            {"name": "loom.mcp.loom.loom_license_activate", "domain": "license", "available": True},
            {"name": "loom.mcp.loom.loom_license_authorized", "domain": "license", "available": True},
            {"name": "loom.skill.resume-screener", "domain": "custom", "available": True},
        ]

    def test_media_and_phone_cross_domain_request_is_focused(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "生成一张海报，然后发布到 phone-1 的小红书草稿"},
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.media.image.generate", names)
        self.assertIn("loom.phone.publish", names)
        self.assertNotIn("loom.cli.logs.tail", names)
        self.assertNotIn("loom.cli.account.current", names)
        self.assertNotIn("loom.capabilities.list", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertEqual(metadata["domains"], ["media", "phone"])

    def test_matrix_request_does_not_send_media_catalog(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "给招聘一组的多台手机下发矩阵任务"},
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertEqual(metadata["mode"], "focused")

    def test_all_device_wording_keeps_matrix_dispatch_available(self) -> None:
        from core.agent_capability_router import route_capabilities

        for prompt in (
            "给全部设备下发打开抖音的任务",
            "让所有手机同时打开小红书",
            "把任务发给每台手机",
        ):
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn("loom.matrix.dispatch", names)
                self.assertEqual(metadata["mode"], "focused")
                self.assertIn("matrix", metadata["domains"])

    def test_agent_product_install_wording_focuses_agent_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        for prompt in ("安装 Codex", "帮我检测 Claude Code", "启动 OpenClaw"):
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn("loom.agent.install", names)
                self.assertNotIn("loom.media.image.generate", names)
                self.assertEqual(metadata["mode"], "focused")
                self.assertIn("agent", metadata["domains"])

    def test_natural_time_wording_focuses_schedule_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        for prompt in ("明天九点执行一次", "今晚 8 点开始发布", "两小时后运行任务"):
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn("loom.schedule.add", names)
                self.assertNotIn("loom.media.image.generate", names)
                self.assertEqual(metadata["mode"], "focused")
                self.assertIn("schedule", metadata["domains"])

    def test_schedule_actions_are_independently_routed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("查看定时任务", "loom.mcp.loom.loom_schedule_list"),
            ("添加定时任务", "loom.mcp.loom.loom_schedule_add"),
            ("立即执行定时任务", "loom.mcp.loom.loom_schedule_run"),
            ("取消定时任务", "loom.mcp.loom.loom_schedule_cancel"),
        )
        schedule_names = {expected for _prompt, expected in cases}
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn(expected, names)
                self.assertTrue((schedule_names - {expected}).isdisjoint(names), names)
                self.assertEqual(metadata["mode"], "focused")

    def test_diagnostic_actions_and_logs_are_independently_routed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("检查麓鸣运行环境", "loom.mcp.loom.loom_doctor"),
            ("运行系统诊断", "loom.mcp.loom.loom_diagnostics_run"),
            ("执行诊断修复", "loom.mcp.loom.loom_diagnostics_repair"),
            ("导出诊断包", "loom.mcp.loom.loom_diagnostics_export"),
            ("查看运行日志", "loom.cli.logs.tail"),
        )
        diagnostic_names = {expected for _prompt, expected in cases}
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn(expected, names)
                self.assertTrue((diagnostic_names - {expected}).isdisjoint(names), names)
                self.assertEqual(metadata["mode"], "focused")

    def test_license_actions_are_independently_routed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("查看授权状态", "loom.mcp.loom.loom_license_current"),
            ("检查授权有效性", "loom.mcp.loom.loom_license_authorized"),
            ("激活授权码", "loom.mcp.loom.loom_license_activate"),
        )
        license_names = {expected for _prompt, expected in cases}
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn(expected, names)
                self.assertTrue((license_names - {expected}).isdisjoint(names), names)
                self.assertEqual(metadata["mode"], "focused")

    def test_transfer_material_to_phone_hides_generation_and_publish_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "传输素材到手机"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.assets.list", names)
        self.assertIn("loom.media.asset.transfer", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertNotIn("loom.media.video.generate", names)
        self.assertNotIn("loom.phone.publish", names)

    def test_existing_media_album_transfer_hides_generation_publish_and_subject_domain(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "把之前那张招聘海报发到所有在线手机相册"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.assets.list", names)
        self.assertIn("loom.media.asset.transfer", names)
        self.assertNotIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.cli.phone.quick-task", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertNotIn("loom.media.video.generate", names)
        self.assertNotIn("loom.phone.publish", names)
        self.assertNotIn("loom.acquisition.run", names)
        self.assertNotIn("acquisition", metadata["domains"])

    def test_existing_media_publish_keeps_publish_but_hides_generators(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "用刚才的海报发布到小红书，只保存草稿"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.assets.list", names)
        self.assertIn("loom.phone.publish", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertNotIn("loom.media.video.generate", names)

    def test_existing_media_hides_mcp_generation_aliases_when_internal_tools_are_unavailable(self) -> None:
        from core.agent_capability_router import route_capabilities

        capabilities = [
            item
            for item in self.capabilities
            if item["name"] not in {"loom.media.image.generate", "loom.media.video.generate"}
        ] + [
            {"name": "loom.mcp.loom.loom_media_generate_image", "domain": "media", "available": True},
            {"name": "loom.mcp.loom.loom_media_generate_video", "domain": "media", "available": True},
        ]
        selected, _metadata = route_capabilities(
            {"prompt": "把刚才的图片传到手机相册"},
            capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertNotIn("loom.mcp.loom.loom_media_generate_image", names)
        self.assertNotIn("loom.mcp.loom.loom_media_generate_video", names)

    def test_explicit_regeneration_keeps_generation_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "把刚才那张招聘海报重新生成一版"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.image.generate", names)

    def test_phone_settings_action_does_not_expose_loom_settings_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "让 phone-1 打开设置并截图确认"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.cli.phone.quick-task", names)
        self.assertNotIn("loom.settings.theme.set", names)
        self.assertNotIn("loom.phone.publish", names)
        self.assertNotIn("loom.mcp.loom.loom_phone_adb_doctor", names)
        self.assertNotIn("loom.mcp.loom.loom_phone_events_status", names)
        self.assertNotIn("settings", metadata["domains"])

    def test_recruitment_media_subject_does_not_expose_acquisition_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "生成一张招聘海报"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.image.generate", names)
        self.assertNotIn("loom.acquisition.run", names)
        self.assertNotIn("acquisition", metadata["domains"])

    def test_recruitment_workflow_still_exposes_acquisition_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "筛选招聘简历并整理候选人"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.acquisition.run", names)
        self.assertIn("acquisition", metadata["domains"])

    def test_media_creation_hides_configuration_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "生成一张产品海报"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.image.generate", names)
        self.assertNotIn("loom.mcp.loom.loom_media_config", names)
        self.assertNotIn("loom.mcp.loom.loom_media_test_image", names)

    def test_image_creation_hides_video_generation(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "生成一张招聘海报"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.image.generate", names)
        self.assertNotIn("loom.media.video.generate", names)
        self.assertNotIn("loom.media.assets.list", names)
        self.assertNotIn("loom.media.asset.transfer", names)

    def test_video_creation_hides_image_generation(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "生成一段产品视频"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.video.generate", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertNotIn("loom.media.assets.list", names)
        self.assertNotIn("loom.media.asset.transfer", names)

    def test_creation_followed_by_phone_transfer_keeps_transfer_tool(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "生成一张海报再传到两台手机"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.image.generate", names)
        self.assertIn("loom.media.asset.transfer", names)

    def test_editing_an_existing_image_keeps_lookup_and_image_generation_only(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "编辑之前生成的图片，换成蓝色背景"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.assets.list", names)
        self.assertIn("loom.media.image.generate", names)
        self.assertNotIn("loom.media.video.generate", names)
        self.assertNotIn("loom.media.asset.transfer", names)

    def test_existing_image_to_video_keeps_lookup_and_video_generation_only(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "用已有图片生成视频"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.assets.list", names)
        self.assertIn("loom.media.video.generate", names)
        self.assertNotIn("loom.media.image.generate", names)

    def test_existing_video_to_cover_keeps_lookup_and_image_generation_only(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "用之前的视频生成一张封面"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.media.assets.list", names)
        self.assertIn("loom.media.image.generate", names)
        self.assertNotIn("loom.media.video.generate", names)

    def test_media_configuration_hides_execution_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "检查生图 API 配置和模型"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.mcp.loom.loom_media_config", names)
        self.assertIn("loom.mcp.loom.loom_media_test_image", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertNotIn("loom.media.asset.transfer", names)

    def test_phone_repair_intent_keeps_adb_doctor(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "手机连接失败，帮我运行 ADB 修复"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.mcp.loom.loom_phone_adb_doctor", names)
        self.assertNotIn("loom.diagnostics.run", names)

    def test_phone_event_intent_keeps_event_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "查看手机事件同步状态"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.mcp.loom.loom_phone_events_status", names)
        self.assertNotIn("loom.cli.phone.status", names)

    def test_phone_event_start_stop_and_status_are_routed_independently(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("启动手机事件同步", "loom.mcp.loom.loom_phone_events_start"),
            ("停止手机事件同步", "loom.mcp.loom.loom_phone_events_stop"),
            ("查看手机事件同步状态", "loom.mcp.loom.loom_phone_events_status"),
        )
        event_names = {
            "loom.mcp.loom.loom_phone_events_start",
            "loom.mcp.loom.loom_phone_events_stop",
            "loom.mcp.loom.loom_phone_events_status",
        }
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                selected, _metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertEqual(names.intersection(event_names), {expected})
                self.assertNotIn("loom.cli.phone.quick-task", names)
                self.assertNotIn("loom.phone.publish", names)

    def test_video_configuration_test_hides_save_and_image_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "测试视频生成接口"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertNotIn("loom.mcp.loom.loom_media_config", names)
        self.assertIn("loom.mcp.loom.loom_media_test_video", names)
        self.assertNotIn("loom.mcp.loom.loom_media_test_image", names)
        self.assertNotIn("loom.mcp.loom.loom_media_save_image_config", names)
        self.assertNotIn("loom.mcp.loom.loom_media_save_video_config", names)

    def test_media_configuration_save_uses_the_requested_media_type(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("保存图片生成配置", "loom.mcp.loom.loom_media_save_image_config"),
            ("保存视频生成配置", "loom.mcp.loom.loom_media_save_video_config"),
        )
        save_names = {
            "loom.mcp.loom.loom_media_save_image_config",
            "loom.mcp.loom.loom_media_save_video_config",
        }
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                selected, _metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertEqual(names.intersection(save_names), {expected})
                self.assertNotIn("loom.mcp.loom.loom_media_config", names)

    def test_numeric_multi_device_target_enters_matrix_without_exposing_publish(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "让两台手机同时打开抖音"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.matrix.cancel", names)
        self.assertNotIn("loom.matrix.retry", names)
        self.assertNotIn("loom.cli.phone.quick-task", names)
        self.assertNotIn("loom.phone.publish", names)
        self.assertIn("matrix", metadata["domains"])

    def test_single_device_target_does_not_accidentally_enter_matrix(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "让一台手机打开抖音"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertNotIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.phone.publish", names)
        self.assertNotIn("matrix", metadata["domains"])

    def test_phone_quick_task_display_name_reaches_single_device_tool(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("执行手机任务", "loom.cli.phone.quick-task"),
            ("执行手机模板任务", "loom.mcp.loom.loom_phone_template_task"),
        )
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities(
                    {"prompt": prompt},
                    self.capabilities,
                )
                names = {item["name"] for item in selected}

                self.assertIn(expected, names)
                self.assertNotIn("loom.matrix.dispatch", names)
                self.assertIn("phone", metadata["domains"])

    def test_phone_read_display_name_reaches_read_tool(self) -> None:
        from core.agent_capability_router import route_capabilities

        capabilities = [
            *self.capabilities,
            {
                "name": "loom.mcp.loom.loom_phone_read",
                "domain": "phone",
                "available": True,
            },
        ]
        selected, metadata = route_capabilities(
            {"prompt": "读取手机屏幕"},
            capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.mcp.loom.loom_phone_read", names)
        self.assertIn("phone", metadata["domains"])

    def test_theme_query_reaches_theme_list_without_affecting_theme_set(self) -> None:
        from core.agent_capability_router import route_capabilities

        query, _metadata = route_capabilities(
            {"prompt": "查看界面主题"},
            self.capabilities,
        )
        update, _metadata = route_capabilities(
            {"prompt": "设置深色主题"},
            self.capabilities,
        )
        query_names = {item["name"] for item in query}
        update_names = {item["name"] for item in update}

        self.assertIn("loom.mcp.loom.loom_settings_theme_list", query_names)
        self.assertNotIn("loom.mcp.loom.loom_settings_theme_list", update_names)
        self.assertIn("loom.mcp.loom.loom_settings_theme", update_names)

    def test_update_install_display_name_reaches_install_tool(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "安装麓鸣更新"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.mcp.loom.loom_settings_update_install", names)
        self.assertIn("loom.mcp.loom.loom_settings_update_check", names)
        self.assertIn("settings", metadata["domains"])

    def test_negated_media_actions_are_not_exposed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            (
                "只生成一张招聘海报，不要传到手机，也不要发布",
                {"loom.media.image.generate"},
                {"loom.media.asset.transfer", "loom.phone.publish", "loom.acquisition.run"},
            ),
            (
                "不要重新生成，把已有图片传到手机相册",
                {"loom.media.assets.list", "loom.media.asset.transfer"},
                {"loom.media.image.generate", "loom.phone.publish"},
            ),
            (
                "不要生成图片，只生成一段视频",
                {"loom.media.video.generate"},
                {"loom.media.image.generate"},
            ),
        )
        for prompt, required, forbidden in cases:
            with self.subTest(prompt=prompt):
                selected, _metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertTrue(required.issubset(names), names)
                self.assertTrue(forbidden.isdisjoint(names), names)

    def test_negated_matrix_and_settings_actions_are_not_exposed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            (
                "不要下发新任务，只查看矩阵状态",
                {"loom.matrix.status"},
                {"loom.matrix.dispatch"},
            ),
            (
                "不要重试，取消刚才的矩阵任务",
                {"loom.matrix.cancel"},
                {"loom.matrix.retry"},
            ),
            (
                "不要安装更新，只检查有没有新版本",
                {"loom.mcp.loom.loom_settings_update_check"},
                {"loom.mcp.loom.loom_settings_update_install"},
            ),
            (
                "不要检查更新，只把界面设置成深色主题",
                {"loom.mcp.loom.loom_settings_theme"},
                {"loom.mcp.loom.loom_settings_update_check"},
            ),
        )
        for prompt, required, forbidden in cases:
            with self.subTest(prompt=prompt):
                selected, _metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertTrue(required.issubset(names), names)
                self.assertTrue(forbidden.isdisjoint(names), names)

    def test_negated_event_and_media_config_actions_are_not_exposed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            (
                "启动手机事件同步，不要检查状态",
                {"loom.mcp.loom.loom_phone_events_start"},
                {"loom.mcp.loom.loom_phone_events_status"},
            ),
            (
                "停止手机事件同步，不要重新启动",
                {"loom.mcp.loom.loom_phone_events_stop"},
                {"loom.mcp.loom.loom_phone_events_start"},
            ),
            (
                "查看手机事件同步状态，不要启动或停止",
                {"loom.mcp.loom.loom_phone_events_status"},
                {
                    "loom.mcp.loom.loom_phone_events_start",
                    "loom.mcp.loom.loom_phone_events_stop",
                },
            ),
            (
                "保存图片生成配置，不要测试接口",
                {"loom.mcp.loom.loom_media_save_image_config"},
                {"loom.mcp.loom.loom_media_test_image"},
            ),
            (
                "测试视频生成接口，不要保存配置",
                {"loom.mcp.loom.loom_media_test_video"},
                {"loom.mcp.loom.loom_media_save_video_config"},
            ),
        )
        for prompt, required, forbidden in cases:
            with self.subTest(prompt=prompt):
                selected, _metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertTrue(required.issubset(names), names)
                self.assertTrue(forbidden.isdisjoint(names), names)

    def test_negated_cross_domain_subject_does_not_open_the_other_domain(self) -> None:
        from core.agent_capability_router import route_capabilities

        media, media_metadata = route_capabilities(
            {"prompt": "生成招聘海报，不要启动获客任务"},
            self.capabilities,
        )
        acquisition, acquisition_metadata = route_capabilities(
            {"prompt": "启动招聘获客任务，不要生成海报"},
            self.capabilities,
        )
        media_names = {item["name"] for item in media}
        acquisition_names = {item["name"] for item in acquisition}

        self.assertIn("loom.media.image.generate", media_names)
        self.assertNotIn("loom.acquisition.run", media_names)
        self.assertNotIn("acquisition", media_metadata["domains"])
        self.assertIn("loom.acquisition.run", acquisition_names)
        self.assertNotIn("loom.media.image.generate", acquisition_names)
        self.assertNotIn("media", acquisition_metadata["domains"])

    def test_positive_adb_repair_keeps_phone_domain_when_phone_task_is_negated(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "修复 ADB 连接，但不要执行手机任务"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.mcp.loom.loom_phone_adb_doctor", names)
        self.assertNotIn("loom.cli.phone.quick-task", names)
        self.assertIn("phone", metadata["domains"])
        self.assertNotEqual(metadata["mode"], "full")

    def test_ordinary_actions_do_not_expose_background_jobs_or_system_status(self) -> None:
        from core.agent_capability_router import route_capabilities

        for prompt in (
            "生成一张招聘海报",
            "打开QQ",
            "把已有图片传到手机相册",
            "查看矩阵任务状态",
        ):
            with self.subTest(prompt=prompt):
                selected, _metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertNotIn("loom.cli.jobs.list", names)
                self.assertNotIn("loom.cli.jobs.get", names)
                self.assertNotIn("loom.mcp.loom.loom_status", names)

    def test_system_status_is_only_exposed_for_explicit_system_status_intent(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "查看麓鸣工作台整体状态"},
            self.capabilities,
        )
        negated, _negated_metadata = route_capabilities(
            {"prompt": "不要检查麓鸣状态，只生成一张海报"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}
        negated_names = {item["name"] for item in negated}

        self.assertIn("loom.mcp.loom.loom_status", names)
        self.assertIn("system", metadata["domains"])
        self.assertNotIn("loom.cli.jobs.list", names)
        self.assertNotIn("loom.cli.jobs.get", names)
        self.assertNotIn("loom.mcp.loom.loom_status", negated_names)

    def test_job_list_and_detail_are_exposed_separately_for_explicit_intent(self) -> None:
        from core.agent_capability_router import route_capabilities

        listing, listing_metadata = route_capabilities(
            {"prompt": "查看最近的后台任务列表"},
            self.capabilities,
        )
        detail, detail_metadata = route_capabilities(
            {"prompt": "查看 job_abc123 的任务详情"},
            self.capabilities,
        )
        listing_names = {item["name"] for item in listing}
        detail_names = {item["name"] for item in detail}

        self.assertIn("loom.cli.jobs.list", listing_names)
        self.assertNotIn("loom.cli.jobs.get", listing_names)
        self.assertIn("jobs", listing_metadata["domains"])
        self.assertIn("loom.cli.jobs.get", detail_names)
        self.assertNotIn("loom.cli.jobs.list", detail_names)
        self.assertIn("jobs", detail_metadata["domains"])

    def test_active_job_checkpoint_exposes_only_job_detail_followup(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "生成一段视频"},
            self.capabilities,
            {
                "toolResults": [{
                    "toolCallId": "video-1",
                    "capability": "loom.media.video.generate",
                    "status": "completed",
                    "result": {"jobId": "job_video_1", "status": "running"},
                }],
            },
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.cli.jobs.get", names)
        self.assertNotIn("loom.cli.jobs.list", names)
        self.assertIn("jobs", metadata["domains"])

    def test_terminal_job_checkpoint_does_not_keep_job_tools_open(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "生成一张图片"},
            self.capabilities,
            {
                "toolResults": [{
                    "toolCallId": "image-1",
                    "capability": "loom.media.image.generate",
                    "status": "completed",
                    "result": {"jobId": "job_image_1", "status": "succeeded"},
                }],
            },
        )
        names = {item["name"] for item in selected}

        self.assertNotIn("loom.cli.jobs.list", names)
        self.assertNotIn("loom.cli.jobs.get", names)
        self.assertNotIn("jobs", metadata["domains"])

    def test_named_device_group_target_enters_matrix_without_acquisition_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "把本地已有视频传到招聘组"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertNotIn("loom.matrix.dispatch", names)
        self.assertIn("loom.media.asset.transfer", names)
        self.assertNotIn("loom.acquisition.run", names)
        self.assertIn("matrix", metadata["domains"])

    def test_platform_publish_action_still_keeps_publish_tool(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "把海报发到小红书并保存草稿"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.phone.publish", names)

    def test_single_device_open_action_keeps_only_execution_phone_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "让 phone-1 打开抖音"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.cli.phone.quick-task", names)
        self.assertNotIn("loom.mcp.loom.loom_phone_template_task", names)
        self.assertNotIn("loom.cli.phone.read", names)
        self.assertNotIn("loom.cli.phone.status", names)
        self.assertNotIn("loom.phone.publish", names)

    def test_phone_status_query_hides_execution_and_publish_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "查看当前有哪些手机"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.cli.phone.status", names)
        self.assertNotIn("loom.cli.phone.quick-task", names)
        self.assertNotIn("loom.phone.publish", names)

    def test_matrix_cancel_intent_does_not_expose_dispatch_or_retry(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "取消当前矩阵任务"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.matrix.cancel", names)
        self.assertNotIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.matrix.retry", names)

    def test_matrix_actions_status_and_progress_are_independently_routed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("下发矩阵任务", "loom.matrix.dispatch"),
            ("取消矩阵任务", "loom.matrix.cancel"),
            ("重试矩阵任务", "loom.matrix.retry"),
            ("获取矩阵截图", "loom.matrix.screenshot"),
            ("查看矩阵状态", "loom.matrix.status"),
            ("查看矩阵进度", "loom.cli.matrix.watch"),
            ("执行任务模板", "loom.cli.template.run"),
            ("查看运行经验", "loom.cli.experience.report"),
        )
        matrix_names = {expected for _prompt, expected in cases}
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn(expected, names)
                self.assertTrue((matrix_names - {expected}).isdisjoint(names), names)
                self.assertEqual(metadata["mode"], "focused")

    def test_matrix_status_does_not_pull_unrelated_system_diagnostics(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "查看矩阵任务状态"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.matrix.status", names)
        self.assertNotIn("loom.diagnostics.run", names)
        self.assertNotIn("diagnostics", metadata["domains"])

    def test_production_tool_labels_never_fall_back_to_the_full_catalog(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("执行任务模板", "loom.cli.template.run", "matrix"),
            ("查看运行经验", "loom.cli.experience.report", "matrix"),
            ("查看媒体生成配置", "loom.mcp.loom.loom_media_config", "media"),
            ("检查麓鸣运行环境", "loom.mcp.loom.loom_doctor", "diagnostics"),
        )
        for prompt, expected, domain in cases:
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn(expected, names)
                self.assertEqual(metadata["mode"], "focused", metadata)
                self.assertIn(domain, metadata["domains"])
                self.assertLess(len(selected), len(self.capabilities))

    def test_isolated_failure_wording_uses_diagnostics_fallback(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "当前任务执行失败了"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.diagnostics.run", names)
        self.assertIn("diagnostics", metadata["domains"])

    def test_ambiguous_request_uses_full_catalog_but_catalog_request_forces_catalog_tool(self) -> None:
        from core.agent_capability_router import route_capabilities

        ambiguous, ambiguous_meta = route_capabilities({"prompt": "继续"}, self.capabilities)
        catalog, catalog_meta = route_capabilities({"prompt": "列出你的全部能力"}, self.capabilities)

        self.assertEqual(len(ambiguous), len(self.capabilities))
        self.assertEqual(ambiguous_meta["reason"], "ambiguous_intent")
        self.assertEqual([item["name"] for item in catalog], ["loom.capabilities.list"])
        self.assertEqual(catalog_meta["mode"], "forced")
        self.assertEqual(catalog_meta["reason"], "capability_catalog_required")
        self.assertEqual(catalog_meta["forcedCapability"], "loom.capabilities.list")

    def test_greeting_uses_response_only_mode_without_exposing_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        for prompt in (
            "你好",
            "您好！",
            "谢谢",
            "Hello",
            "你是谁",
            "介绍一下你自己",
        ):
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)

                self.assertEqual(selected, [])
                self.assertEqual(metadata["mode"], "response_only")
                self.assertEqual(metadata["reason"], "no_tool_intent")
                self.assertEqual(metadata["toolChoice"], "none")

    def test_catalog_tool_is_not_repeated_after_a_real_result(self) -> None:
        from core.agent_capability_router import route_capabilities

        catalog, metadata = route_capabilities(
            {"prompt": "What capabilities are connected?"},
            self.capabilities,
            {
                "toolResults": [{
                    "toolCallId": "catalog-1",
                    "capability": "loom.capabilities.list",
                    "status": "completed",
                    "result": {"count": 12},
                }],
            },
        )

        self.assertEqual([item["name"] for item in catalog], ["loom.capabilities.list"])
        self.assertEqual(metadata["mode"], "response_only")
        self.assertEqual(metadata["reason"], "capability_catalog_available")
        self.assertEqual(metadata["toolChoice"], "none")
        self.assertNotIn("forcedCapability", metadata)

    def test_selection_repair_restores_full_catalog(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "生成图片"},
            self.capabilities,
            {"toolSelectionRepairAttempts": 1},
        )

        self.assertEqual(len(selected), len(self.capabilities))
        self.assertEqual(metadata["mode"], "full")
        self.assertEqual(metadata["reason"], "selection_repair")

    def test_update_request_includes_settings_update_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "检查麓鸣更新，如果有新版本就安装"},
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.settings.update.check", names)
        self.assertIn("loom.settings.update.install", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertNotIn("loom.diagnostics.run", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertIn("settings", metadata["domains"])

    def test_production_settings_tools_separate_theme_from_update_actions(self) -> None:
        from core.agent_capability_router import route_capabilities

        theme, _theme_metadata = route_capabilities(
            {"prompt": "把麓鸣界面设置为深色主题"},
            self.capabilities,
        )
        check, _check_metadata = route_capabilities(
            {"prompt": "检查麓鸣更新"},
            self.capabilities,
        )
        install, _install_metadata = route_capabilities(
            {"prompt": "立即安装更新"},
            self.capabilities,
        )
        theme_names = {item["name"] for item in theme}
        check_names = {item["name"] for item in check}
        install_names = {item["name"] for item in install}

        self.assertIn("loom.mcp.loom.loom_settings_theme", theme_names)
        self.assertNotIn("loom.mcp.loom.loom_settings_theme_list", theme_names)
        self.assertNotIn("loom.mcp.loom.loom_settings_update_check", theme_names)
        self.assertNotIn("loom.mcp.loom.loom_settings_update_install", theme_names)
        self.assertIn("loom.mcp.loom.loom_settings_update_check", check_names)
        self.assertNotIn("loom.mcp.loom.loom_settings_update_install", check_names)
        self.assertNotIn("loom.mcp.loom.loom_settings_theme", check_names)
        self.assertIn("loom.mcp.loom.loom_settings_update_check", install_names)
        self.assertIn("loom.mcp.loom.loom_settings_update_install", install_names)

    def test_theme_query_does_not_expose_theme_mutation(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "只查看界面主题，不要修改主题"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.mcp.loom.loom_settings_theme_list", names)
        self.assertNotIn("loom.mcp.loom.loom_settings_theme", names)

    def test_model_read_select_and_wire_actions_are_independently_routed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            (
                "列出当前模型，不要修改账号",
                {"loom.cli.models"},
                {
                    "loom.mcp.loom.loom_account_select_models",
                    "loom.mcp.loom.loom_agent_model_apply",
                    "loom.mcp.loom.loom_wire_custom",
                    "loom.mcp.loom.loom_wire_rollback",
                },
            ),
            (
                "把默认模型改成 glm-5.2-coding",
                {"loom.mcp.loom.loom_account_select_models"},
                {"loom.cli.models", "loom.mcp.loom.loom_wire_custom"},
            ),
            (
                "验证模型接口，不要修改或回滚配置",
                {"loom.mcp.loom.loom_wire_verify"},
                {"loom.mcp.loom.loom_wire_custom", "loom.mcp.loom.loom_wire_rollback"},
            ),
            (
                "查看智能体模型状态",
                {"loom.mcp.loom.loom_agent_model_status"},
                {
                    "loom.mcp.loom.loom_agent_model_apply",
                    "loom.mcp.loom.loom_agent_model_rollback",
                },
            ),
        )
        for prompt, required, forbidden in cases:
            with self.subTest(prompt=prompt):
                selected, _metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertTrue(required.issubset(names), names)
                self.assertTrue(forbidden.isdisjoint(names), names)

    def test_account_read_and_auth_actions_are_independently_routed(self) -> None:
        from core.agent_capability_router import route_capabilities

        current, _current_metadata = route_capabilities(
            {"prompt": "查看当前账号和订阅"},
            self.capabilities,
        )
        login, _login_metadata = route_capabilities(
            {"prompt": "使用验证码登录账号"},
            self.capabilities,
        )
        current_names = {item["name"] for item in current}
        login_names = {item["name"] for item in login}

        self.assertIn("loom.mcp.loom.loom_account_current", current_names)
        self.assertIn("loom.mcp.loom.loom_account_subscription", current_names)
        self.assertNotIn("loom.mcp.loom.loom_account_logout", current_names)
        self.assertNotIn("loom.mcp.loom.loom_account_send_code", current_names)
        self.assertNotIn("loom.mcp.loom.loom_account_login_password", current_names)
        self.assertIn("loom.mcp.loom.loom_account_login_code", login_names)
        self.assertNotIn("loom.mcp.loom.loom_account_logout", login_names)
        self.assertNotIn("loom.mcp.loom.loom_account_sync", login_names)

    def test_account_logout_does_not_read_current_account_first(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, _metadata = route_capabilities(
            {"prompt": "退出当前账户"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.mcp.loom.loom_account_logout", names)
        self.assertNotIn("loom.mcp.loom.loom_account_current", names)
        self.assertNotIn("loom.cli.account.current", names)

    def test_acquisition_run_result_and_lead_actions_are_independently_routed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            (
                "启动招聘获客任务，不要生成海报",
                {"loom.acquisition.run"},
                {
                    "loom.mcp.loom.loom_acquisition_agent_result",
                    "loom.mcp.loom.loom_lead_list",
                    "loom.mcp.loom.loom_lead_record",
                    "loom.mcp.loom.loom_feishu_install",
                },
            ),
            (
                "记录获客智能体结果",
                {"loom.mcp.loom.loom_acquisition_agent_result"},
                {"loom.acquisition.run", "loom.mcp.loom.loom_lead_record"},
            ),
            (
                "查看合规线索列表",
                {"loom.mcp.loom.loom_lead_list"},
                {"loom.mcp.loom.loom_lead_record", "loom.acquisition.run"},
            ),
            (
                "记录一条合规线索",
                {"loom.mcp.loom.loom_lead_record"},
                {"loom.mcp.loom.loom_lead_list", "loom.acquisition.run"},
            ),
        )
        for prompt, required, forbidden in cases:
            with self.subTest(prompt=prompt):
                selected, _metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertTrue(required.issubset(names), names)
                self.assertTrue(forbidden.isdisjoint(names), names)

    def test_natural_acquisition_requests_select_only_the_acquisition_runner(self) -> None:
        from core.agent_capability_router import route_capabilities

        for prompt in (
            "抖音自动拓客",
            "帮我做招聘自动化",
            "帮我找客户",
            "BOSS直聘自动筛选简历",
        ):
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertEqual(names, {"loom.acquisition.run"})
                self.assertEqual(metadata["mode"], "focused")
                self.assertIn("acquisition", metadata["domains"])
                self.assertNotIn("loom.phone.publish", names)

    def test_feishu_integration_actions_do_not_open_phone_or_sibling_mutations(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("查看飞书集成状态", "loom.mcp.loom.loom_feishu_status"),
            ("检查飞书集成环境", "loom.mcp.loom.loom_feishu_doctor"),
            ("安装飞书集成", "loom.mcp.loom.loom_feishu_install"),
            ("登录飞书集成", "loom.mcp.loom.loom_feishu_login"),
            ("绑定飞书线索表", "loom.mcp.loom.loom_feishu_bind_table"),
            ("创建飞书线索表", "loom.mcp.loom.loom_feishu_create_table"),
            ("测试写入飞书", "loom.mcp.loom.loom_feishu_test_write"),
            ("重试飞书同步", "loom.mcp.loom.loom_feishu_retry_sync"),
            ("核对飞书同步状态", "loom.mcp.loom.loom_feishu_reconcile"),
        )
        feishu_names = {expected for _prompt, expected in cases}
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn(expected, names)
                self.assertTrue((feishu_names - {expected}).isdisjoint(names), names)
                self.assertNotIn("loom.phone.publish", names)
                self.assertNotIn("phone", metadata["domains"])
                self.assertIn("integration", metadata["domains"])

    def test_nested_single_device_scope_focuses_phone_tools_for_short_followup(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {
                "prompt": "继续",
                "requestScope": {
                    "status": "resolved",
                    "targets": {"deviceIds": ["phone-1"]},
                },
            },
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.phone.publish", names)
        self.assertNotIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertEqual(metadata["domains"], ["phone"])

    def test_nested_all_online_scope_focuses_matrix_tools_for_short_followup(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {
                "prompt": "开始执行",
                "requestScope": {
                    "status": "resolved",
                    "targets": {"allOnline": True},
                },
            },
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.matrix.dispatch", names)
        self.assertNotIn("loom.phone.publish", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertEqual(metadata["domains"], ["matrix"])

    def test_license_request_focuses_license_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "查看商业授权状态，如果未激活就使用授权码激活"},
            self.capabilities,
        )

        names = {item["name"] for item in selected}
        self.assertIn("loom.license.current", names)
        self.assertIn("loom.license.activate", names)
        self.assertNotIn("loom.media.image.generate", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertIn("license", metadata["domains"])

    def test_common_mobile_app_launch_focuses_phone_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        for prompt in ("打开QQ", "打开闲鱼", "启动淘宝"):
            with self.subTest(prompt=prompt):
                selected, metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn("loom.cli.phone.quick-task", names)
                self.assertNotIn("loom.mcp.loom.loom_phone_template_task", names)
                self.assertNotIn("loom.phone.publish", names)
                self.assertNotIn("loom.media.image.generate", names)
                self.assertEqual(metadata["mode"], "focused")
                self.assertIn("phone", metadata["domains"])

    def test_phone_quick_and_template_actions_are_independently_routed(self) -> None:
        from core.agent_capability_router import route_capabilities

        quick, _quick_metadata = route_capabilities(
            {"prompt": "让 phone-1 打开飞书"},
            self.capabilities,
        )
        template, _template_metadata = route_capabilities(
            {"prompt": "让 phone-1 按主页键"},
            self.capabilities,
        )
        quick_names = {item["name"] for item in quick}
        template_names = {item["name"] for item in template}

        self.assertIn("loom.cli.phone.quick-task", quick_names)
        self.assertNotIn("loom.mcp.loom.loom_phone_template_task", quick_names)
        self.assertIn("loom.mcp.loom.loom_phone_template_task", template_names)
        self.assertNotIn("loom.cli.phone.quick-task", template_names)

    def test_agent_management_actions_are_independently_routed(self) -> None:
        from core.agent_capability_router import route_capabilities

        cases = (
            ("检测智能体安装", "loom.mcp.loom.loom_agent_detect"),
            ("安装智能体", "loom.mcp.loom.loom_agent_install"),
            ("查看智能体安装状态", "loom.mcp.loom.loom_agent_list"),
            ("回滚智能体安装", "loom.mcp.loom.loom_agent_rollback"),
            ("启动智能体", "loom.mcp.loom.loom_agent_start"),
            ("卸载智能体", "loom.mcp.loom.loom_agent_uninstall"),
        )
        management_names = {expected for _prompt, expected in cases}
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                selected, _metadata = route_capabilities({"prompt": prompt}, self.capabilities)
                names = {item["name"] for item in selected}

                self.assertIn(expected, names)
                self.assertTrue((management_names - {expected}).isdisjoint(names), names)
                self.assertNotIn("loom.capabilities.list", names)

    def test_business_agent_wording_does_not_open_agent_installation_tools(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {"prompt": "记录获客智能体结果"},
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.mcp.loom.loom_acquisition_agent_result", names)
        self.assertNotIn("loom.mcp.loom.loom_agent_detect", names)
        self.assertNotIn("loom.mcp.loom.loom_agent_install", names)
        self.assertNotIn("loom.mcp.loom.loom_agent_start", names)
        self.assertNotIn("loom.mcp.loom.loom_agent_uninstall", names)
        self.assertNotIn("agent", metadata["domains"])

    def test_explicit_capability_hint_survives_unrelated_domain_routing(self) -> None:
        from core.agent_capability_router import route_capabilities

        selected, metadata = route_capabilities(
            {
                "prompt": "分析这张图片",
                "capabilityHints": ["loom.skill.resume-screener", "loom.skill.not-connected"],
            },
            self.capabilities,
        )
        names = {item["name"] for item in selected}

        self.assertIn("loom.skill.resume-screener", names)
        self.assertNotIn("loom.skill.not-connected", names)
        self.assertEqual(metadata["mode"], "focused")
        self.assertEqual(metadata["hinted"], ["loom.skill.resume-screener"])


if __name__ == "__main__":
    unittest.main()
