from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch


PYTHON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PYTHON_DIR not in sys.path:
    sys.path.insert(0, PYTHON_DIR)

from core.acquisition_templates import AcquisitionTemplateLibrary
from core.paths import AppPaths
from services.skills import SkillError, SkillService


def skill_archive(*, name: str = "Fast Text", valid: bool = True) -> str:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        if valid:
            archive.writestr(
                "fast-text/skill.json",
                json.dumps(
                    {
                        "id": "fast-text",
                        "name": name,
                        "version": "1.2.0",
                        "description": "复用已验证的文本流程",
                        "applicableAgents": ["Codex Desktop", "Codex CLI"],
                    },
                    ensure_ascii=False,
                ),
            )
            archive.writestr("fast-text/SKILL.md", f"# {name}\n\n只执行已验证的文本步骤。\n")
        else:
            archive.writestr("fast-text/README.txt", "invalid replacement")
    return base64.b64encode(payload.getvalue()).decode("ascii")


class SkillCenterServiceTests(unittest.TestCase):
    def test_skill_lifecycle_tracks_safe_usage_and_exports_a_portable_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SkillService(AppPaths(base_path=temp_dir))
            installed = service.install_zip("fast-text.zip", skill_archive())
            recorded = service.record_invocation(
                "fast-text",
                success=True,
                duration_ms=245,
                agent_id="codex-desktop",
                template_id="reply-template",
            )
            listed = service.list_skills()["skills"]
            exported = service.export_zip("fast-text")

        self.assertEqual("fast-text", installed["skill"]["id"])
        self.assertEqual(1, recorded["skill"]["invocationCount"])
        self.assertEqual(245, recorded["skill"]["lastDurationMs"])
        self.assertEqual("codex-desktop", recorded["skill"]["lastAgent"])
        self.assertEqual(["reply-template"], recorded["skill"]["linkedTemplateIds"])
        self.assertEqual(["Codex Desktop", "Codex CLI"], listed[0]["applicableAgents"])
        self.assertTrue(listed[0]["lastUsedAt"])
        self.assertEqual("fast-text.zip", exported["filename"])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(exported["data"]))) as archive:
            self.assertIn("fast-text/SKILL.md", archive.namelist())
            self.assertNotIn("skills-state.json", archive.namelist())

    def test_invalid_replacement_rolls_back_without_destroying_the_installed_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SkillService(AppPaths(base_path=temp_dir))
            service.install_zip("fast-text.zip", skill_archive(name="Known Good"))
            with self.assertRaises(SkillError):
                service.install_zip("fast-text.zip", skill_archive(valid=False))
            listed = service.list_skills()["skills"]

        self.assertEqual(1, len(listed))
        self.assertEqual("Known Good", listed[0]["name"])

    def test_learned_skill_requires_user_confirmation_and_a_verified_read_only_run(self) -> None:
        payload = {
            "id": "learned-cleanup",
            "name": "已验证文本整理",
            "summary": "复用第一次成功的文本整理步骤",
            "steps": ["读取工作区文本", "按标题归类", "输出结果"],
            "applicableAgents": ["Codex Desktop", "LumiAgent"],
            "confirmed": True,
            "deterministic": True,
            "verifiedSuccess": True,
            "sideEffects": False,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SkillService(AppPaths(base_path=temp_dir))
            with self.assertRaises(SkillError):
                service.create_learned_skill({**payload, "confirmed": False})
            created = service.create_learned_skill(payload)
            listed = service.list_skills()["skills"]

        self.assertEqual("learned", created["skill"]["source"])
        self.assertEqual("已验证文本整理", listed[0]["name"])
        self.assertTrue(listed[0]["enabled"])
        self.assertEqual("verified_read_only", listed[0]["promotionPolicy"])

    def test_skill_binds_an_exact_shared_template_version_and_validates_it_at_execution(self) -> None:
        payload = {
            "id": "learned-phone-leads",
            "name": "手机线索整理",
            "summary": "复用经过验证的手机矩阵线索整理步骤",
            "steps": ["读取矩阵结果", "套用共享模板", "输出待确认草稿"],
            "confirmed": True,
            "deterministic": True,
            "verifiedSuccess": True,
            "sideEffects": False,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = AppPaths(base_path=temp_dir)
            library = AcquisitionTemplateLibrary(paths)
            with patch.dict(os.environ, {"LOOM_TEMPLATE_DISABLE_DEFAULT_CLOUD": "1"}, clear=False):
                saved = library.save_from_acquisition(
                    {
                        "templateId": "phone-leads",
                        "name": "手机矩阵线索模板",
                        "industry": "本地生活",
                        "platforms": ["douyin"],
                        "targetCustomer": "公开表达到店意向的客户",
                    }
                )["template"]

            service = SkillService(paths)
            created = service.create_learned_skill(
                {
                    **payload,
                    "templateId": saved["templateId"],
                    "templateVersion": saved["version"],
                }
            )
            execution = service.resolve_execution_context("learned-phone-leads")

            self.assertEqual(
                [{"templateId": "phone-leads", "version": 1, "name": "手机矩阵线索模板"}],
                created["skill"]["linkedTemplates"],
            )
            self.assertEqual("phone-leads", execution["sharedTemplates"][0]["templateId"])
            self.assertEqual(1, execution["sharedTemplates"][0]["version"])

            with patch.dict(os.environ, {"LOOM_TEMPLATE_DISABLE_DEFAULT_CLOUD": "1"}, clear=False):
                library.save_from_acquisition(
                    {
                        "templateId": "phone-leads",
                        "expectedVersion": saved["version"],
                        "name": "手机矩阵线索模板 v2",
                        "industry": "本地生活",
                    }
                )
            with self.assertRaisesRegex(SkillError, "模板版本不一致"):
                service.resolve_execution_context("learned-phone-leads")


if __name__ == "__main__":
    unittest.main()
