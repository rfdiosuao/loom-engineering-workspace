from __future__ import annotations

import os
import sys
import unittest


PYTHON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)


from core.agent_scope import resolve_request_scope


MATRIX_STATUS = {
    "devices": [
        {"deviceId": "P01", "online": True, "group": "招聘一组", "groups": ["招聘一组"]},
        {"deviceId": "P02", "online": True, "group": "招聘一组", "groups": ["招聘一组", "演示组"]},
        {"deviceId": "P03", "online": False, "group": "招聘二组", "groups": ["招聘二组"]},
    ],
}


class AgentScopeTests(unittest.TestCase):
    def test_resolves_real_device_group_against_matrix_facts(self) -> None:
        result = resolve_request_scope("让招聘一组筛选简历", {"mode": "auto"}, MATRIX_STATUS)

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.groups, ["招聘一组"])
        self.assertEqual(result.device_ids, [])

    def test_resolves_multiple_explicit_device_ids_without_truncating(self) -> None:
        result = resolve_request_scope("让 P01 和 P02 读取屏幕", {"mode": "auto"}, MATRIX_STATUS)

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.device_ids, ["P01", "P02"])

    def test_all_online_requires_an_explicit_all_online_phrase(self) -> None:
        resolved = resolve_request_scope("让全部在线设备继续任务", {"mode": "auto"}, MATRIX_STATUS)
        common_phrase = resolve_request_scope("让全部手机打开抖音", {"mode": "auto"}, MATRIX_STATUS)
        ambiguous = resolve_request_scope("让那几台手机继续", {"mode": "auto"}, MATRIX_STATUS)

        self.assertTrue(resolved.all_online)
        self.assertEqual(resolved.status, "resolved")
        self.assertTrue(common_phrase.all_online)
        self.assertEqual(common_phrase.status, "resolved")
        self.assertFalse(ambiguous.all_online)
        self.assertEqual(ambiguous.status, "ambiguous")

    def test_ordinary_question_does_not_require_phone_scope(self) -> None:
        result = resolve_request_scope("帮我总结招聘流程的优缺点", {"mode": "auto"}, MATRIX_STATUS)

        self.assertEqual(result.status, "not_required")
        self.assertEqual(result.targets(), {})

    def test_auto_scope_selects_the_only_available_phone_for_mobile_publish(self) -> None:
        matrix_status = {
            "devices": [
                {"deviceId": "phone-1", "online": True, "group": "default"},
            ],
        }

        result = resolve_request_scope(
            "\u751f\u6210\u4e00\u5f20\u609f\u7a7a\u6d77\u62a5\u7136\u540e\u53d1\u5e03\u5230\u5c0f\u7ea2\u4e66",
            {"mode": "auto"},
            matrix_status,
        )

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.device_ids, ["phone-1"])
        self.assertEqual(result.targets(), {"deviceIds": ["phone-1"]})

    def test_common_mobile_app_launch_selects_one_phone_and_clarifies_multiple(self) -> None:
        one_phone = {"devices": [{"deviceId": "phone-1", "online": True}]}

        for prompt in ("打开QQ", "打开闲鱼", "启动淘宝"):
            with self.subTest(prompt=prompt):
                resolved = resolve_request_scope(prompt, {"mode": "auto"}, one_phone)
                ambiguous = resolve_request_scope(prompt, {"mode": "auto"}, MATRIX_STATUS)

                self.assertEqual(resolved.status, "resolved")
                self.assertEqual(resolved.device_ids, ["phone-1"])
                self.assertEqual(ambiguous.status, "ambiguous")

    def test_phone_inspection_language_requires_a_bound_target_when_needed(self) -> None:
        one_phone = {"devices": [{"deviceId": "phone-1", "online": True}]}

        for prompt in ("查看手机屏幕", "检查手机页面", "检测手机当前界面"):
            with self.subTest(prompt=prompt):
                result = resolve_request_scope(prompt, {"mode": "auto"}, one_phone)
                self.assertEqual(result.status, "resolved")
                self.assertEqual(result.device_ids, ["phone-1"])

    def test_resolves_unique_device_display_name_to_its_stable_id(self) -> None:
        matrix_status = {
            "devices": [
                {"deviceId": "phone-1", "name": "Android Phone", "online": True},
                {"deviceId": "phone-2", "name": "Android Phone 2", "online": True},
            ],
        }

        result = resolve_request_scope("让 Android Phone 2 打开QQ", {"mode": "auto"}, matrix_status)

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.device_ids, ["phone-2"])

    def test_resolves_two_explicit_prefix_device_names_without_dropping_one(self) -> None:
        matrix_status = {
            "devices": [
                {"deviceId": "phone-1", "name": "Android Phone", "online": True},
                {"deviceId": "phone-2", "name": "Android Phone 2", "online": True},
            ],
        }

        result = resolve_request_scope(
            "让 Android Phone 和 Android Phone 2 打开QQ",
            {"mode": "auto"},
            matrix_status,
        )

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.device_ids, ["phone-1", "phone-2"])

    def test_duplicate_device_display_name_is_ambiguous(self) -> None:
        matrix_status = {
            "devices": [
                {"deviceId": "phone-1", "name": "发布手机", "online": True},
                {"deviceId": "phone-2", "name": "发布手机", "online": True},
            ],
        }

        result = resolve_request_scope("让发布手机打开小红书", {"mode": "auto"}, matrix_status)

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.targets(), {})

    def test_unknown_or_mixed_phone_targets_are_ambiguous(self) -> None:
        unknown = resolve_request_scope("给 P99 截图", {"mode": "auto"}, MATRIX_STATUS)
        mixed = resolve_request_scope("让 P01 和招聘一组继续", {"mode": "auto"}, MATRIX_STATUS)

        self.assertEqual(unknown.status, "ambiguous")
        self.assertEqual(mixed.status, "ambiguous")
        self.assertEqual(unknown.device_ids, [])
        self.assertEqual(mixed.targets(), {})

    def test_manual_scope_is_validated_against_current_matrix_facts(self) -> None:
        valid = resolve_request_scope(
            "执行任务",
            {"mode": "manual", "deviceIds": ["P02", "P01", "P02"]},
            MATRIX_STATUS,
        )
        invalid = resolve_request_scope(
            "执行任务",
            {"mode": "manual", "groups": ["不存在的组"]},
            MATRIX_STATUS,
        )

        self.assertEqual(valid.status, "resolved")
        self.assertEqual(valid.device_ids, ["P02", "P01"])
        self.assertEqual(invalid.status, "ambiguous")


if __name__ == "__main__":
    unittest.main()
