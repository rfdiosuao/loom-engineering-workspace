"""Local skill package management.

The launcher treats skills as files first: scan folders, unpack zip files,
and store enable/disable state. It intentionally does not execute scripts
from uploaded packages.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.acquisition_templates import AcquisitionTemplateLibrary, TemplateError
from core.paths import AppPaths
from core.storage import read_json, write_json


class SkillError(RuntimeError):
    pass


@dataclass(frozen=True)
class SkillSource:
    key: str
    label: str
    path: str
    writable: bool
    default_enabled: bool


class SkillService:
    def __init__(self, paths: AppPaths):
        self.paths = paths

    @property
    def learned_skills_dir(self) -> str:
        return os.path.join(self.paths.state_dir, "learned-skills")

    def list_skills(self) -> dict:
        self._ensure_dirs()
        state = self._read_state()
        skills: dict[str, dict] = {}
        for source in self._sources():
            if not os.path.isdir(source.path):
                continue
            for skill_dir in self._iter_skill_dirs(source.path):
                meta = self._read_skill_metadata(skill_dir)
                if meta is None:
                    continue
                skill_id = meta["id"]
                state_item = state.get("skills", {}).get(skill_id)
                enabled = bool(state_item.get("enabled")) if isinstance(state_item, dict) else source.default_enabled
                installed_at = state_item.get("installedAt") if isinstance(state_item, dict) else None
                usage = state_item if isinstance(state_item, dict) else {}
                skills[skill_id] = {
                    **meta,
                    "source": source.key,
                    "sourceLabel": source.label,
                    "path": skill_dir,
                    "installed": True,
                    "enabled": enabled,
                    "writable": source.writable,
                    "installedAt": installed_at,
                    "hasReadme": self._find_readme(skill_dir) is not None,
                    "invocationCount": self._bounded_int(usage.get("invocationCount"), 0, 0, 2_000_000_000),
                    "successfulInvocations": self._bounded_int(usage.get("successfulInvocations"), 0, 0, 2_000_000_000),
                    "failureCount": self._bounded_int(usage.get("failureCount"), 0, 0, 2_000_000_000),
                    "lastUsedAt": self._safe_text(usage.get("lastUsedAt"), 80) or None,
                    "lastFailureAt": self._safe_text(usage.get("lastFailureAt"), 80) or None,
                    "lastDurationMs": self._bounded_int(usage.get("lastDurationMs"), 0, 0, 86_400_000),
                    "lastAgent": self._safe_text(usage.get("lastAgent"), 120),
                    "linkedTemplateIds": self._safe_list(usage.get("linkedTemplateIds"), limit=50, item_limit=120),
                    "linkedTemplates": self._normalize_template_bindings(usage.get("linkedTemplates")),
                }
        return {
            "skills": sorted(skills.values(), key=lambda item: (item.get("source", ""), item.get("name", ""))),
            "directories": self._directories_payload(),
            "sites": self._skill_sites(),
            "statePath": self.paths.skills_state,
        }

    def install_zip(self, filename: str, data_base64: str) -> dict:
        self._ensure_dirs()
        safe_name = self._safe_filename(filename)
        try:
            payload = data_base64.split(",", 1)[1] if data_base64.startswith("data:") else data_base64
            archive_bytes = base64.b64decode(payload, validate=True)
        except Exception as error:
            raise SkillError("Skill 压缩包不是有效的 Base64 数据") from error
        if not archive_bytes or len(archive_bytes) > 32 * 1024 * 1024:
            raise SkillError("Skill 压缩包为空或超过 32MB")

        staging_parent = tempfile.mkdtemp(prefix="skill-install-", dir=self.paths.launcher_dir)
        target_dir = ""
        backup_dir = ""
        target_activated = False
        meta: dict[str, Any] | None = None
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                self._validate_zip(archive)
                skill_root = self._detect_zip_skill_root(archive)
                target_name = self._safe_slug(skill_root or os.path.splitext(safe_name)[0])
                staging_dir = os.path.join(staging_parent, target_name)
                target_dir = os.path.join(self.paths.skills_dir, target_name)
                os.makedirs(staging_dir, exist_ok=True)
                self._extract_skill_zip(archive, staging_dir, skill_root)
            meta = self._read_skill_metadata(staging_dir)
            if meta is None:
                raise SkillError("未识别到有效 Skill 描述文件，请确认包内包含 skill.json、plugin.json、package.json 或 SKILL.md")
            existing = self._find_skill(meta["id"])
            if existing and os.path.normcase(os.path.realpath(str(existing.get("path") or ""))) != os.path.normcase(os.path.realpath(target_dir)):
                raise SkillError(f"Skill ID 已被其他来源占用: {meta['id']}")

            if os.path.exists(target_dir):
                backup_dir = f"{target_dir}.backup-{uuid.uuid4().hex}"
                os.replace(target_dir, backup_dir)
            os.replace(staging_dir, target_dir)
            target_activated = True

            state = self._read_state()
            state.setdefault("skills", {})
            previous_state = state["skills"].get(meta["id"], {})
            state["skills"][meta["id"]] = {
                **(previous_state if isinstance(previous_state, dict) else {}),
                "enabled": True,
                "version": meta.get("version", "0.0.0"),
                "installedAt": self._timestamp(),
            }
            self._write_state(state)
        except SkillError:
            self._rollback_install(target_dir, backup_dir, target_activated)
            raise
        except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, ValueError) as error:
            self._rollback_install(target_dir, backup_dir, target_activated)
            raise SkillError(f"Skill 安装失败: {self._safe_text(error, 200)}") from error
        finally:
            shutil.rmtree(staging_parent, ignore_errors=True)

        if backup_dir:
            shutil.rmtree(backup_dir, ignore_errors=True)

        assert meta is not None
        return {"skill": {**meta, "path": target_dir, "source": "uploaded", "sourceLabel": "上传安装", "installed": True, "enabled": True}}

    def create_learned_skill(self, payload: dict[str, Any]) -> dict:
        if payload.get("confirmed") is not True:
            raise SkillError("需要用户明确确认后才能沉淀 Skill")
        if payload.get("verifiedSuccess") is not True or payload.get("deterministic") is not True:
            raise SkillError("只有已验证成功且结果确定的任务才能沉淀 Skill")
        if payload.get("sideEffects") is not False:
            raise SkillError("带副作用的流程不能直接进入自动复用")

        skill_id = self._safe_slug(str(payload.get("id") or payload.get("name") or ""))
        name = self._safe_text(payload.get("name"), 120)
        summary = self._safe_text(payload.get("summary"), 240)
        steps = self._safe_list(payload.get("steps"), limit=40, item_limit=300)
        agents = self._safe_list(payload.get("applicableAgents"), limit=20, item_limit=120)
        if not name or not summary or not steps:
            raise SkillError("Skill 名称、摘要和至少一个复用步骤不能为空")
        if not agents:
            agents = ["Codex Desktop", "Codex CLI", "LumiAgent"]

        template_binding: dict[str, Any] | None = None
        template_id = self._safe_text(payload.get("templateId"), 120)
        if template_id:
            template_binding = self._validated_template_binding(
                template_id,
                payload.get("templateVersion"),
            )

        self._ensure_dirs()
        os.makedirs(self.learned_skills_dir, exist_ok=True)
        target_dir = os.path.join(self.learned_skills_dir, skill_id)
        if os.path.exists(target_dir):
            raise SkillError(f"已存在同名沉淀 Skill: {skill_id}")
        staging_dir = tempfile.mkdtemp(prefix=f".{skill_id}-", dir=self.learned_skills_dir)
        now = self._timestamp()
        meta = {
            "id": skill_id,
            "name": name,
            "version": "1.0.0",
            "description": summary,
            "category": "Agent 沉淀",
            "runtime": "instruction",
            "applicableAgents": agents,
            "promotionPolicy": "verified_read_only",
        }
        try:
            with open(os.path.join(staging_dir, "skill.json"), "w", encoding="utf-8") as file:
                json.dump(meta, file, ensure_ascii=False, indent=2)
                file.write("\n")
            with open(os.path.join(staging_dir, "SKILL.md"), "w", encoding="utf-8") as file:
                file.write(f"# {name}\n\n{summary}\n\n## 已验证复用步骤\n\n")
                for index, step in enumerate(steps, 1):
                    file.write(f"{index}. {step}\n")
                file.write("\n仅在输入满足相同前置条件时复用；任何副作用动作必须重新请求确认。\n")
            os.replace(staging_dir, target_dir)
            state = self._read_state()
            state.setdefault("skills", {})
            state["skills"][skill_id] = {
                "enabled": True,
                "version": "1.0.0",
                "installedAt": now,
                "promotionPolicy": "verified_read_only",
                "linkedTemplates": [template_binding] if template_binding else [],
            }
            self._write_state(state)
        except (OSError, ValueError) as error:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise SkillError(f"Skill 沉淀失败: {self._safe_text(error, 200)}") from error
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
        skill = self._find_skill(skill_id)
        if skill is None:
            raise SkillError("Skill 已保存但重新读取失败")
        return {"skill": skill}

    def record_invocation(
        self,
        skill_id: str,
        *,
        success: bool,
        duration_ms: int = 0,
        agent_id: str = "",
        template_id: str = "",
    ) -> dict:
        skill = self._find_skill(skill_id)
        if skill is None:
            raise SkillError(f"未找到 Skill: {skill_id}")
        state = self._read_state()
        state.setdefault("skills", {})
        item = state["skills"].setdefault(skill_id, {})
        if "enabled" not in item:
            item["enabled"] = skill.get("enabled") is not False
        now = self._timestamp()
        item["invocationCount"] = self._bounded_int(item.get("invocationCount"), 0, 0, 2_000_000_000) + 1
        item["lastUsedAt"] = now
        item["lastDurationMs"] = self._bounded_int(duration_ms, 0, 0, 86_400_000)
        item["lastAgent"] = self._safe_text(agent_id, 120)
        if success:
            item["successfulInvocations"] = self._bounded_int(item.get("successfulInvocations"), 0, 0, 2_000_000_000) + 1
        else:
            item["failureCount"] = self._bounded_int(item.get("failureCount"), 0, 0, 2_000_000_000) + 1
            item["lastFailureAt"] = now
        linked = self._safe_list(item.get("linkedTemplateIds"), limit=50, item_limit=120)
        fixed_template_id = self._safe_text(template_id, 120)
        if fixed_template_id and fixed_template_id not in linked:
            linked.append(fixed_template_id)
        item["linkedTemplateIds"] = linked[-50:]
        self._write_state(state)
        refreshed = self._find_skill(skill_id)
        return {"skill": refreshed or skill}

    def set_template_binding(
        self,
        skill_id: str,
        template_id: str,
        template_version: Any,
        *,
        linked: bool,
    ) -> dict:
        skill = self._find_skill(skill_id)
        if skill is None:
            raise SkillError(f"未找到 Skill: {skill_id}")
        fixed_template_id = self._safe_text(template_id, 120)
        if not fixed_template_id:
            raise SkillError("共享模板 ID 不能为空")

        state = self._read_state()
        state.setdefault("skills", {})
        item = state["skills"].setdefault(skill_id, {})
        if "enabled" not in item:
            item["enabled"] = skill.get("enabled") is not False
        bindings = self._normalize_template_bindings(item.get("linkedTemplates"))
        bindings = [binding for binding in bindings if binding.get("templateId") != fixed_template_id]
        if linked:
            binding = self._validated_template_binding(fixed_template_id, template_version)
            bindings.append(binding)
        item["linkedTemplates"] = bindings[-20:]
        self._write_state(state)
        refreshed = self._find_skill(skill_id)
        return {"skill": refreshed or skill}

    def resolve_execution_context(self, skill_id: str) -> dict:
        skill = self._find_skill(skill_id)
        if skill is None:
            raise SkillError(f"未找到 Skill: {skill_id}")
        if skill.get("enabled") is False:
            raise SkillError("这个 Skill 已停用，请先在 Skill 中心启用")
        document = self.read_readme(skill_id)
        resolved_templates: list[dict[str, Any]] = []
        library = AcquisitionTemplateLibrary(self.paths)
        for binding in self._normalize_template_bindings(skill.get("linkedTemplates")):
            try:
                template = library.resolve_template(
                    str(binding["templateId"]),
                    expected_version=int(binding["version"]),
                    require_enabled=True,
                )
            except TemplateError as error:
                raise SkillError(f"Skill 关联的共享模板不可用：{error}") from error
            resolved_templates.append(self._template_execution_payload(template))
        return {
            "skillId": skill_id,
            "instructions": str(document.get("content") or "")[:20_000],
            "sharedTemplates": resolved_templates,
        }

    def _validated_template_binding(self, template_id: str, template_version: Any) -> dict[str, Any]:
        try:
            version = int(template_version)
        except (TypeError, ValueError) as error:
            raise SkillError("绑定共享模板时必须提供明确的模板版本") from error
        if version < 1:
            raise SkillError("共享模板版本必须大于 0")
        try:
            template = AcquisitionTemplateLibrary(self.paths).resolve_template(
                template_id,
                expected_version=version,
                require_enabled=True,
            )
        except TemplateError as error:
            raise SkillError(f"无法绑定共享模板：{error}") from error
        return {
            "templateId": self._safe_text(template.get("templateId"), 120),
            "version": version,
            "name": self._safe_text(template.get("name"), 160),
        }

    def export_zip(self, skill_id: str) -> dict:
        skill = self._find_skill(skill_id)
        if skill is None:
            raise SkillError(f"未找到 Skill: {skill_id}")
        source_dir = os.path.realpath(str(skill.get("path") or ""))
        if not any(self._is_inside(source_dir, source.path) for source in self._sources()):
            raise SkillError("Skill 路径不安全，已拒绝导出")
        output = io.BytesIO()
        total_size = 0
        root_name = self._safe_slug(str(skill.get("id") or skill_id))
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for directory, dir_names, file_names in os.walk(source_dir):
                dir_names[:] = [name for name in dir_names if not os.path.islink(os.path.join(directory, name))]
                for filename in file_names:
                    path = os.path.join(directory, filename)
                    if os.path.islink(path):
                        continue
                    size = os.path.getsize(path)
                    total_size += size
                    if total_size > 80 * 1024 * 1024:
                        raise SkillError("Skill 导出内容超过 80MB")
                    relative = os.path.relpath(path, source_dir).replace("\\", "/")
                    archive.write(path, f"{root_name}/{relative}")
        data = output.getvalue()
        return {
            "id": skill_id,
            "filename": f"{root_name}.zip",
            "mimeType": "application/zip",
            "size": len(data),
            "data": base64.b64encode(data).decode("ascii"),
        }

    def set_enabled(self, skill_id: str, enabled: bool) -> dict:
        self._ensure_dirs()
        skill = self._find_skill(skill_id)
        if skill is None:
            raise SkillError(f"未找到 Skill: {skill_id}")
        state = self._read_state()
        state.setdefault("skills", {})
        state["skills"].setdefault(skill_id, {})
        state["skills"][skill_id]["enabled"] = bool(enabled)
        state["skills"][skill_id]["version"] = skill.get("version", "0.0.0")
        self._write_state(state)
        return {"skill": {**skill, "enabled": bool(enabled)}}

    def uninstall(self, skill_id: str) -> dict:
        self._ensure_dirs()
        skill = self._find_skill(skill_id)
        if skill is None:
            raise SkillError(f"未找到 Skill: {skill_id}")
        if skill.get("source") not in {"uploaded", "learned"} or not skill.get("writable"):
            raise SkillError("只能删除通过麓鸣导入或经用户确认沉淀的 Skill")

        target = os.path.realpath(str(skill.get("path") or ""))
        skills_root = os.path.realpath(
            self.learned_skills_dir if skill.get("source") == "learned" else self.paths.skills_dir
        )
        if not self._is_inside(target, skills_root) or target == skills_root:
            raise SkillError("Skill 路径不安全，已拒绝卸载")

        shutil.rmtree(target, ignore_errors=True)
        state = self._read_state()
        if isinstance(state.get("skills"), dict):
            state["skills"].pop(skill_id, None)
        self._write_state(state)
        return {"status": "removed", "id": skill_id}

    def read_readme(self, skill_id: str) -> dict:
        skill = self._find_skill(skill_id)
        if skill is None:
            raise SkillError(f"未找到 Skill: {skill_id}")
        readme = self._find_readme(str(skill.get("path") or ""))
        if readme is None:
            raise SkillError("这个 Skill 没有说明文件")
        try:
            with open(readme, "r", encoding="utf-8") as file:
                content = file.read(20000)
        except UnicodeDecodeError:
            with open(readme, "r", encoding="gbk", errors="replace") as file:
                content = file.read(20000)
        return {"id": skill_id, "path": readme, "content": content}

    def paths_payload(self) -> dict:
        self._ensure_dirs()
        return {"directories": self._directories_payload(), "sites": self._skill_sites()}

    def _ensure_dirs(self) -> None:
        os.makedirs(self.paths.launcher_dir, exist_ok=True)
        os.makedirs(self.paths.skills_dir, exist_ok=True)
        os.makedirs(self.learned_skills_dir, exist_ok=True)

    def _sources(self) -> list[SkillSource]:
        return [
            SkillSource("uploaded", "上传安装", self.paths.skills_dir, True, True),
            SkillSource("learned", "Agent 沉淀", self.learned_skills_dir, True, True),
            SkillSource("openclaw-extensions", "OpenClaw 扩展目录", self.paths.openclaw_extensions_dir, False, False),
            SkillSource("node-modules", "OpenClaw Node 包", os.path.join(self.paths.base_path, "node_modules"), False, False),
        ]

    def _directories_payload(self) -> list[dict]:
        return [
            {"key": source.key, "label": source.label, "path": source.path, "writable": source.writable}
            for source in self._sources()
        ]

    def _skill_sites(self) -> list[dict]:
        return [
            {"name": "SkillHub 技能中心", "url": "https://www.skillhub.cn/skills"},
            {"name": "OpenClaw 文档", "url": "https://heang.top/docs.html"},
        ]

    def _read_state(self) -> dict:
        data = read_json(self.paths.skills_state, {"skills": {}})
        return data if isinstance(data, dict) else {"skills": {}}

    def _write_state(self, state: dict) -> None:
        write_json(self.paths.skills_state, state)

    def _find_skill(self, skill_id: str) -> dict | None:
        for skill in self.list_skills().get("skills", []):
            if skill.get("id") == skill_id:
                return skill
        return None

    def _iter_skill_dirs(self, root: str) -> list[str]:
        result: list[str] = []
        if self._read_skill_metadata(root):
            return [root]

        try:
            entries = list(os.scandir(root))
        except OSError:
            return result

        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
                if self._read_skill_metadata(entry.path):
                    result.append(entry.path)
                    continue
                # Support one extra layer, useful for OpenClaw/Codex style skill bundles.
                for child in os.scandir(entry.path):
                    if child.is_dir() and self._read_skill_metadata(child.path):
                        result.append(child.path)
            except OSError:
                continue
        return result

    def _read_skill_metadata(self, directory: str) -> dict | None:
        readers = [
            self._read_skill_json,
            self._read_codex_plugin_json,
            self._read_package_json,
            self._read_skill_md,
        ]
        for reader in readers:
            meta = reader(directory)
            if meta:
                return self._normalize_meta(meta, directory)
        return None

    def _read_skill_json(self, directory: str) -> dict | None:
        path = os.path.join(directory, "skill.json")
        if not os.path.exists(path):
            return None
        return read_json(path, {})

    def _read_codex_plugin_json(self, directory: str) -> dict | None:
        path = os.path.join(directory, ".codex-plugin", "plugin.json")
        if not os.path.exists(path):
            return None
        return read_json(path, {})

    def _read_package_json(self, directory: str) -> dict | None:
        path = os.path.join(directory, "package.json")
        if not os.path.exists(path):
            return None
        data = read_json(path, {})
        if not isinstance(data, dict):
            return None
        keywords = data.get("keywords", [])
        name = str(data.get("name", ""))
        if "openclaw" not in name.lower() and "skill" not in name.lower() and "openclaw-skill" not in keywords:
            return None
        return data

    def _read_skill_md(self, directory: str) -> dict | None:
        path = os.path.join(directory, "SKILL.md")
        if not os.path.exists(path):
            return None
        name = os.path.basename(directory)
        description = ""
        try:
            with open(path, "r", encoding="utf-8") as file:
                for line in file:
                    text = line.strip()
                    if text.startswith("#"):
                        name = text.lstrip("#").strip() or name
                        break
                for line in file:
                    text = line.strip()
                    if text:
                        description = text[:180]
                        break
        except OSError:
            pass
        return {"name": name, "description": description, "version": "0.0.0", "runtime": "external"}

    def _find_readme(self, directory: str) -> str | None:
        for filename in ("README.md", "README.txt", "SKILL.md", "readme.md", "readme.txt"):
            path = os.path.join(directory, filename)
            if os.path.exists(path):
                return path
        return None

    def _normalize_meta(self, meta: dict, directory: str) -> dict:
        raw_id = str(meta.get("id") or meta.get("name") or os.path.basename(directory))
        skill_id = self._safe_slug(raw_id)
        return {
            "id": skill_id,
            "name": str(meta.get("displayName") or meta.get("title") or meta.get("name") or skill_id),
            "version": str(meta.get("version") or "0.0.0"),
            "description": str(meta.get("description") or ""),
            "category": str(meta.get("category") or "未分类"),
            "runtime": str(meta.get("runtime") or "external"),
            "icon": str(meta.get("icon") or "SK"),
            "applicableAgents": self._safe_list(
                meta.get("applicableAgents") or meta.get("agents"),
                limit=20,
                item_limit=120,
            ),
            "promotionPolicy": self._safe_text(meta.get("promotionPolicy"), 80),
        }

    def _safe_filename(self, filename: str) -> str:
        name = os.path.basename(filename or "skill.zip")
        if not name.lower().endswith(".zip"):
            raise SkillError("当前仅支持上传 .zip 格式的 Skill 包")
        return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "skill.zip"

    def _safe_slug(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()
        return slug or "skill"

    def _validate_zip(self, archive: zipfile.ZipFile) -> None:
        total_size = 0
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise SkillError("Skill 压缩包包含不安全路径")
            unix_mode = (info.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise SkillError("Skill 压缩包不能包含符号链接")
            total_size += info.file_size
            if total_size > 80 * 1024 * 1024:
                raise SkillError("Skill 压缩包解压后超过 80MB")

    def _detect_zip_skill_root(self, archive: zipfile.ZipFile) -> str:
        roots: set[str] = set()
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = Path(info.filename.replace("\\", "/")).parts
            if parts:
                roots.add(parts[0])
        return next(iter(roots)) if len(roots) == 1 else ""

    def _extract_skill_zip(self, archive: zipfile.ZipFile, target_dir: str, root: str) -> None:
        target_real = os.path.realpath(target_dir)
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if root and name.startswith(f"{root}/"):
                name = name[len(root) + 1:]
            if not name:
                continue
            dest = os.path.realpath(os.path.join(target_dir, name))
            if not self._is_inside(dest, target_real):
                raise SkillError("Skill 压缩包包含不安全路径")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with archive.open(info) as source, open(dest, "wb") as output:
                shutil.copyfileobj(source, output)

    def _is_inside(self, path: str, root: str) -> bool:
        try:
            return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
        except ValueError:
            return False

    def _rollback_install(self, target_dir: str, backup_dir: str, target_activated: bool) -> None:
        if target_activated and target_dir and os.path.exists(target_dir):
            shutil.rmtree(target_dir, ignore_errors=True)
        if backup_dir and os.path.exists(backup_dir):
            if target_dir and os.path.exists(target_dir):
                shutil.rmtree(target_dir, ignore_errors=True)
            os.replace(backup_dir, target_dir)

    def _normalize_template_bindings(self, value: Any) -> list[dict[str, Any]]:
        rows = value if isinstance(value, list) else []
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            template_id = self._safe_text(row.get("templateId"), 120)
            try:
                version = int(row.get("version"))
            except (TypeError, ValueError):
                continue
            if not template_id or version < 1 or template_id in seen:
                continue
            result.append(
                {
                    "templateId": template_id,
                    "version": version,
                    "name": self._safe_text(row.get("name"), 160),
                }
            )
            seen.add(template_id)
            if len(result) >= 20:
                break
        return result

    def _template_execution_payload(self, template: dict[str, Any]) -> dict[str, Any]:
        return {
            "templateId": self._safe_text(template.get("templateId"), 120),
            "version": self._bounded_int(template.get("version"), 1, 1, 2_000_000_000),
            "name": self._safe_text(template.get("name"), 160),
            "industry": self._safe_text(template.get("industry"), 160),
            "platforms": self._safe_list(template.get("platforms"), limit=20, item_limit=120),
            "targetCustomer": self._safe_text(template.get("targetCustomer"), 300),
            "keywords": self._safe_list(template.get("keywords"), limit=80, item_limit=160),
            "leadRules": self._safe_list(template.get("leadRules"), limit=80, item_limit=300),
            "replyStyle": self._safe_text(template.get("replyStyle"), 1000),
            "safetyPolicy": template.get("safetyPolicy") if isinstance(template.get("safetyPolicy"), dict) else {},
            "feishuMapping": template.get("feishuMapping") if isinstance(template.get("feishuMapping"), dict) else {},
        }

    def _safe_list(self, value: Any, *, limit: int, item_limit: int) -> list[str]:
        if isinstance(value, str):
            rows = re.split(r"[,\r\n]+", value)
        elif isinstance(value, (list, tuple, set)):
            rows = list(value)
        else:
            rows = []
        result: list[str] = []
        for row in rows:
            text = self._safe_text(row, item_limit)
            if text and text not in result:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    def _safe_text(self, value: Any, limit: int) -> str:
        text = str(value or "").replace("\x00", "").strip()
        return text[:limit]

    def _bounded_int(self, value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _timestamp(self) -> str:
        import datetime
        return datetime.datetime.now().isoformat(timespec="seconds")
