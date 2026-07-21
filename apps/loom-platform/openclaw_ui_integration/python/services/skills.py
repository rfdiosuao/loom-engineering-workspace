"""Local skill package management.

The launcher treats skills as files first: scan folders, unpack zip files,
and store enable/disable state. It intentionally does not execute scripts
from uploaded packages.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

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
        self._cache_lock = threading.Lock()
        self._list_cache: tuple[float, dict] | None = None

    def list_skills(self) -> dict:
        now = time.time()
        with self._cache_lock:
            if self._list_cache and self._list_cache[0] > now:
                return copy.deepcopy(self._list_cache[1])

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
                }
        payload = {
            "skills": sorted(skills.values(), key=lambda item: (item.get("source", ""), item.get("name", ""))),
            "directories": self._directories_payload(),
            "sites": self._skill_sites(),
            "statePath": self.paths.skills_state,
        }
        with self._cache_lock:
            self._list_cache = (time.time() + 5, copy.deepcopy(payload))
        return payload

    def install_zip(self, filename: str, data_base64: str) -> dict:
        self._ensure_dirs()
        safe_name = self._safe_filename(filename)
        upload_dir = os.path.join(self.paths.launcher_dir, "skill-uploads")
        os.makedirs(upload_dir, exist_ok=True)
        zip_path = os.path.join(upload_dir, safe_name)

        import base64

        try:
            payload = data_base64.split(",", 1)[1] if data_base64.startswith("data:") else data_base64
            with open(zip_path, "wb") as file:
                file.write(base64.b64decode(payload))
        except Exception as error:
            raise SkillError(f"Skill 压缩包写入失败: {error}") from error

        with zipfile.ZipFile(zip_path) as archive:
            self._validate_zip(archive)
            skill_root = self._detect_zip_skill_root(archive)
            target_name = self._safe_slug(skill_root or os.path.splitext(safe_name)[0])
            target_dir = os.path.join(self.paths.skills_dir, target_name)
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)
            os.makedirs(target_dir, exist_ok=True)
            self._extract_skill_zip(archive, target_dir, skill_root)

        meta = self._read_skill_metadata(target_dir)
        if meta is None:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise SkillError("未识别到有效 Skill 描述文件，请确认包内包含 skill.json、plugin.json、package.json 或 SKILL.md")

        state = self._read_state()
        state.setdefault("skills", {})
        state["skills"][meta["id"]] = {
            "enabled": True,
            "version": meta.get("version", "0.0.0"),
            "installedAt": self._timestamp(),
        }
        self._write_state(state)
        self._invalidate_cache()
        return {"skill": {**meta, "path": target_dir, "source": "uploaded", "sourceLabel": "上传安装", "installed": True, "enabled": True}}

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
        self._invalidate_cache()
        return {"skill": {**skill, "enabled": bool(enabled)}}

    def uninstall(self, skill_id: str) -> dict:
        self._ensure_dirs()
        skill = self._find_skill(skill_id)
        if skill is None:
            raise SkillError(f"未找到 Skill: {skill_id}")
        if skill.get("source") != "uploaded" or not skill.get("writable"):
            raise SkillError("只能卸载通过启动器上传安装的 Skill")

        target = os.path.realpath(str(skill.get("path") or ""))
        skills_root = os.path.realpath(self.paths.skills_dir)
        if not self._is_inside(target, skills_root) or target == skills_root:
            raise SkillError("Skill 路径不安全，已拒绝卸载")

        shutil.rmtree(target, ignore_errors=True)
        state = self._read_state()
        if isinstance(state.get("skills"), dict):
            state["skills"].pop(skill_id, None)
        self._write_state(state)
        self._invalidate_cache()
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
        self._migrate_legacy_skills()

    def _migrate_legacy_skills(self) -> None:
        legacy_dir = getattr(self.paths, "legacy_skills_dir", "")
        target_root = self.paths.skills_dir
        if not legacy_dir or os.path.realpath(legacy_dir) == os.path.realpath(target_root):
            return
        if not os.path.isdir(legacy_dir):
            return
        try:
            entries = list(os.scandir(legacy_dir))
        except OSError:
            return
        for entry in entries:
            try:
                if not entry.is_dir() or not self._read_skill_metadata(entry.path):
                    continue
                target = os.path.join(target_root, os.path.basename(entry.path))
                if os.path.exists(target):
                    continue
                shutil.copytree(entry.path, target)
            except OSError:
                continue

    def _sources(self) -> list[SkillSource]:
        return [
            SkillSource("uploaded", "上传安装", self.paths.skills_dir, True, True),
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

    def _invalidate_cache(self) -> None:
        with self._cache_lock:
            self._list_cache = None

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

    def _timestamp(self) -> str:
        import datetime
        return datetime.datetime.now().isoformat(timespec="seconds")
