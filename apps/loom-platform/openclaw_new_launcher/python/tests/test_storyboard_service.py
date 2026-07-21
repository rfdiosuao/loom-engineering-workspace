from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from services.storyboard import (
    DEFAULT_OPTION_HINTS,
    build_context,
    resolve_hint,
    extract_asset_prompts,
    GENERIC_HINT_TEMPLATE,
    StoryboardService,
)


def _param_config() -> dict:
    return {
        "模块一": {
            "产品/服务类型": {"实物商品": "你是实物商品定位专家，强调产品实体、品质、供应链。", "虚拟服务": None},
        },
        "模块二": {"内容大类": {"种草测评类": None}},
        "模块三": {},
        "模块四": {"视频类型": {"种草测评": "用种草测评视角组织文案。"}},
        "模块五": {},
    }


def _project(stage: str) -> dict:
    base = {
        "target": {"category": "食品饮料", "object": "3秒冷萃咖啡液"},
        "selections": {
            "模块一": {"产品/服务类型": ["实物商品"]},
            "模块二": {"内容大类": ["种草测评类"]},
            "模块三": {},
            "模块四": {"视频类型": ["种草测评"]},
            "模块五": {},
        },
        "script": {"content": "定稿文案示例"},
        "storyboard": {"shots": [{"num": 1, "scene": "x", "voice": "y", "assetType": "产品图"}]},
    }
    return base


class ResolveHintTests(unittest.TestCase):
    def test_returns_explicit_string_when_present(self) -> None:
        cfg = _param_config()
        self.assertEqual(
            resolve_hint(cfg, "模块一", "产品/服务类型", "实物商品"),
            "你是实物商品定位专家，强调产品实体、品质、供应链。",
        )

    def test_backfills_null_from_default_hints(self) -> None:
        cfg = _param_config()
        # "种草测评类" is null in cfg; default hint must exist
        hint = resolve_hint(cfg, "模块二", "内容大类", "种草测评类")
        self.assertIsInstance(hint, str)
        self.assertTrue(hint.strip())
        self.assertIn(hint, DEFAULT_OPTION_HINTS.values())

    def test_falls_back_to_generic_template_when_unknown(self) -> None:
        cfg = _param_config()
        hint = resolve_hint(cfg, "模块一", "产品/服务类型", "完全不存在的选项")
        self.assertIn("完全不存在的选项", hint)
        self.assertEqual(hint, GENERIC_HINT_TEMPLATE.format(option="完全不存在的选项"))


class BuildContextTests(unittest.TestCase):
    def test_script_stage_includes_target_and_modules_one_two_three(self) -> None:
        system, user = build_context("script", _project("script"), _param_config())
        self.assertIn("3秒冷萃咖啡液", user)
        self.assertIn("食品饮料", user)
        self.assertIn("模块一", user)
        self.assertIn("模块二", user)
        self.assertIn("模块三", user)
        # module 4 selections also included for script stage
        self.assertIn("模块四", user)
        # module 5 not relevant for script
        self.assertIsInstance(system, str)
        self.assertTrue(system.strip())

    def test_storyboard_stage_includes_script_content(self) -> None:
        _, user = build_context("storyboard", _project("storyboard"), _param_config())
        self.assertIn("定稿文案示例", user)

    def test_video_prompt_stage_includes_script_and_shots(self) -> None:
        _, user = build_context("videoPrompt", _project("videoPrompt"), _param_config())
        self.assertIn("定稿文案示例", user)
        self.assertIn('"assetType": "产品图"', user)

    def test_unknown_stage_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_context("nope", _project("script"), _param_config())


class ExtractAssetPromptsTests(unittest.TestCase):
    def test_classifies_shots_by_asset_type_and_appends_style(self) -> None:
        project = {
            "selections": {
                "模块六": {"气质风格": ["亲和邻家"], "画幅": ["9:16"]},
                "模块七": {"视觉风格": ["电商精致"], "画幅比例": ["9:16"]},
                "模块八": {"场景类型": ["厨房"], "画幅": ["9:16"]},
            },
            "storyboard": {
                "shots": [
                    {"num": 1, "scene": "女性手持咖啡杯", "assetType": "人物图"},
                    {"num": 2, "scene": "咖啡液产品特写", "assetType": "产品图"},
                    {"num": 3, "scene": "明亮厨房环境", "assetType": "场景图"},
                    {"num": 4, "scene": "纯口播无素材", "assetType": "无"},
                ]
            },
        }
        result = extract_asset_prompts(project, {})
        self.assertEqual(set(result.keys()), {"人物图", "产品图", "场景图"})
        self.assertEqual(len(result["人物图"]), 1)
        self.assertIn("女性手持咖啡杯", result["人物图"][0])
        self.assertIn("亲和邻家", result["人物图"][0])
        self.assertIn("9:16", result["人物图"][0])
        self.assertIn("电商精致", result["产品图"][0])
        self.assertIn("厨房", result["场景图"][0])
        # "无" assetType shots are dropped
        self.assertEqual(sum(len(v) for v in result.values()), 3)

    def test_handles_missing_asset_type(self) -> None:
        project = {"storyboard": {"shots": [{"num": 1, "scene": "x"}]}}
        result = extract_asset_prompts(project, {})
        self.assertEqual(result, {"人物图": [], "产品图": [], "场景图": []})


def _fake_model_client(text: str) -> SimpleNamespace:
    """A fake LoomModelClient whose complete() returns the given text."""
    def complete(request, emit, cancel, *, timeout_sec=None):
        return {"text": text, "toolCalls": [], "usage": {}, "model": "test"}
    return SimpleNamespace(complete=complete)


class _Paths:
    def __init__(self, base):
        self.nine_step_param_config = os.path.join(base, "param-config.json")
        self.nine_step_dir = base


class StoryboardServiceParamConfigTests(unittest.TestCase):
    def test_get_param_config_backfills_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = StoryboardService(_Paths(tmp))
            imported = svc.import_param_config({
                "模块一": {"产品/服务类型": {"实物商品": None}},
                "模块二": {},
                "模块三": {},
            })
            self.assertTrue(imported["ok"])
            self.assertEqual(imported["optionCount"], 1)
            cfg = svc.get_param_config()
            hint = cfg["模块一"]["产品/服务类型"]["实物商品"]
            self.assertIsInstance(hint, str)
            self.assertTrue(hint.strip())

    def test_import_detects_missing_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = StoryboardService(_Paths(tmp))
            result = svc.import_param_config({"模块一": {}})
            self.assertTrue(result["ok"])
            self.assertIn("模块二", result["warnings"]["missing"])

    def test_generate_script_returns_model_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svc = StoryboardService(_Paths(tmp))
            project = _project("script")
            result = svc.generate("script", project, _fake_model_client("生成的文案"))
            self.assertEqual(result["stage"], "script")
            self.assertEqual(result["result"], "生成的文案")


if __name__ == "__main__":
    unittest.main()
