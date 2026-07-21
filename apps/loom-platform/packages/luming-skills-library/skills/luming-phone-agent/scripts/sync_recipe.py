from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as error:
    Draft202012Validator = None
    FormatChecker = None
    JSONSCHEMA_IMPORT_ERROR = str(error)
else:
    JSONSCHEMA_IMPORT_ERROR = None


SYNC_SCHEMA = "loom.phone-agent.recipe-sync.v1"
INDEX_SCHEMA = "loom.phone-agent.recipe-index.v1"
SCHEMAS_ROOT = Path(__file__).resolve().parent.parent / "schemas"
RECIPE_SCHEMA_PATH = SCHEMAS_ROOT / "recipe.schema.json"
INDEX_SCHEMA_PATH = SCHEMAS_ROOT / "recipe-index.schema.json"
SENSITIVE_KEYS = {
    "password",
    "passcode",
    "token",
    "secret",
    "captcha",
    "otp",
    "verificationcode",
    "phonenumber",
    "email",
    "wechat",
    "idcard",
}
REJECTED_PERSONAL_DATA_KEYS = {"rawresume", "unrelatedpersonaldata"}
CHINESE_MOBILE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)
SENSITIVE_STRING_PATTERNS = (
    (
        "auth-token",
        re.compile(r"(?i)\bauth[_ -]?token\s*(?::|=|is\b)\s*\S+"),
    ),
    (
        "password-space",
        re.compile(r"(?i)\b(?:password|passcode|pwd|secret)\s+\S+"),
    ),
    (
        "call-phone",
        re.compile(r"(?i)\b(?:call|phone|mobile|telephone|tel)\s*[:=]?\s*\d{10}\b"),
    ),
    (
        "password",
        re.compile(r"(?i)\b(?:my\s+)?(?:password|passcode|pwd|secret)\s*(?::|=|：|is\b)\s*\S+"),
    ),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    (
        "api-token",
        re.compile(
            r"(?i)(?:\b(?:api[_ -]?key|api[_ -]?token|access[_ -]?token|session[_ -]?token)\s*(?::|=|：|is\b)\s*\S+|\bsk-[A-Za-z0-9_-]{8,})"
        ),
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")),
    (
        "otp",
        re.compile(
            r"(?i)(?:\b(?:otp|one[- ]time(?: password| code)?|verification code)\s*[:=：]?\s*[A-Z0-9-]{4,12}\b|验证码\s*[:=：]?\s*[A-Z0-9-]{4,12})"
        ),
    ),
    ("international-phone", re.compile(r"(?<!\w)\+\d[\d ()-]{7,}\d")),
    (
        "formatted-phone",
        re.compile(r"(?<!\d)(?:\(\d{2,4}\)|\d{2,4})[ -]\d{3,4}[ -]\d{4}(?!\d)"),
    ),
    (
        "wechat",
        re.compile(
            r"(?i)(?:\bwxid_[A-Za-z0-9_-]{4,}|\b(?:wechat|weixin)(?:\s+id)?\s*(?::|=|：|is\b)\s*[A-Za-z][A-Za-z0-9_-]{4,}|微信(?:号|ID)?\s*[:=：]?\s*[A-Za-z][A-Za-z0-9_-]{4,})"
        ),
    ),
    (
        "contact",
        re.compile(
            r"(?i)(?:\bcontact(?:\s+(?:details|info|information|identifier|id))?\s*(?::|=|：|is\b)\s*\S+|联系方式\s*[:=：]\s*\S+)"
        ),
    ),
    ("id-card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
)
BENIGN_SECRET_UI_PATTERN = re.compile(
    r"(?i)(?:password field|password screen|secret settings)[.!?]?"
)
PROHIBITED_NARRATIVE_PATTERNS = (
    (
        "raw resume",
        re.compile(
            r"(?i)\b(?:raw resume|full resume|curriculum vitae)\b|(?:原始|完整)?简历\s*[:：]|(?:\b(?:work experience|employment history)\b[\s\S]{0,1000}\b(?:education|academic background)\b|\b(?:education|academic background)\b[\s\S]{0,1000}\b(?:work experience|employment history)\b)"
        ),
    ),
    (
        "unrelated personal data",
        re.compile(
            r"(?i)\b(?:date of birth|birth date|marital status|family status|gender|home address|religion|nationality|ethnicity|political affiliation|sexual orientation|health status)\b|出生日期|婚姻状况|家庭状况|性别|家庭住址|宗教信仰|民族|政治面貌|健康状况"
        ),
    ),
)
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
FORMAT_CHECKER = FormatChecker() if FormatChecker is not None else None


def _is_rfc3339_date_time(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if not RFC3339_PATTERN.fullmatch(value):
        return False
    datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    return True


if FORMAT_CHECKER is not None:
    FORMAT_CHECKER.checks("date-time", raises=ValueError)(_is_rfc3339_date_time)


class RecipeRejected(ValueError):
    pass


def load_json(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return document


def validate_document(document: dict, schema_path: Path) -> None:
    if JSONSCHEMA_IMPORT_ERROR is not None:
        raise RecipeRejected(f"jsonschema dependency is unavailable: {JSONSCHEMA_IMPORT_ERROR}")
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValueError(f"schema validation failed at {location}: {error.message}")


def sanitize_recipe(recipe: dict) -> tuple[dict, list[str]]:
    redactions: list[str] = []

    def sanitize(value: Any, path: str) -> Any:
        if isinstance(value, dict):
            clean: dict[str, Any] = {}
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if key.casefold() in SENSITIVE_KEYS:
                    redactions.append(f"{child_path}:key")
                    continue
                clean[key] = sanitize(child, child_path)
            return clean
        if isinstance(value, list):
            return [sanitize(child, f"{path}[{index}]") for index, child in enumerate(value)]
        if isinstance(value, str):
            for label, pattern in SENSITIVE_STRING_PATTERNS:
                if label == "password-space" and BENIGN_SECRET_UI_PATTERN.fullmatch(value.strip()):
                    continue
                if pattern.search(value):
                    redactions.append(f"{path}:{label}")
                    return "[REDACTED]"
            clean, mobile_count = CHINESE_MOBILE_PATTERN.subn("[REDACTED]", value)
            if mobile_count:
                redactions.extend(f"{path}:chinese-mobile" for _ in range(mobile_count))
            clean, email_count = EMAIL_PATTERN.subn("[REDACTED]", clean)
            if email_count:
                redactions.extend(f"{path}:email" for _ in range(email_count))
            return clean
        return value

    sanitized = sanitize(copy.deepcopy(recipe), "")
    return sanitized, redactions


def assert_promotable(recipe: dict) -> None:
    def reject_personal_data(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if key.casefold() in REJECTED_PERSONAL_DATA_KEYS:
                    raise RecipeRejected(f"prohibited personal data at {child_path}")
                reject_personal_data(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                reject_personal_data(child, f"{path}[{index}]")
        elif isinstance(value, str):
            for label, pattern in PROHIBITED_NARRATIVE_PATTERNS:
                if pattern.search(value):
                    raise RecipeRejected(f"prohibited {label} at {path}")

    reject_personal_data(recipe)
    if recipe.get("status") != "verified":
        raise RecipeRejected("recipe status must be verified")
    verification = recipe.get("verification")
    if not isinstance(verification, dict) or verification.get("successCount", 0) < 1:
        raise RecipeRejected("verification.successCount must be at least 1")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not steps:
        raise RecipeRejected("recipe must contain route steps")
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("verification") != "verified":
            raise RecipeRejected(f"steps[{index}].verification must be verified")
        evidence = step.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise RecipeRejected(f"steps[{index}].evidence must be non-empty")
        for evidence_index, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise RecipeRejected(f"steps[{index}].evidence[{evidence_index}] must be an object")
            reference = item.get("reference")
            if (
                not isinstance(reference, str)
                or not reference.strip()
                or "[REDACTED]" in reference.upper()
            ):
                raise RecipeRejected(
                    f"steps[{index}].evidence[{evidence_index}].reference must be meaningful"
                )
            assertion = item.get("assertion")
            if not isinstance(assertion, dict) or set(assertion) != {
                "predicate",
                "subject",
                "expected",
            }:
                raise RecipeRejected(
                    f"steps[{index}].evidence[{evidence_index}].assertion must be structured"
                )
            if assertion.get("predicate") not in {
                "visible",
                "present",
                "selected",
                "enabled",
                "checked",
                "matches",
            }:
                raise RecipeRejected(
                    f"steps[{index}].evidence[{evidence_index}].assertion.predicate is invalid"
                )
            subject = assertion.get("subject")
            if (
                not isinstance(subject, str)
                or not subject.strip()
                or "[REDACTED]" in subject.upper()
            ):
                raise RecipeRejected(
                    f"steps[{index}].evidence[{evidence_index}].assertion.subject must be meaningful"
                )
            if not isinstance(assertion.get("expected"), bool):
                raise RecipeRejected(
                    f"steps[{index}].evidence[{evidence_index}].assertion.expected must be boolean"
                )


def acquire_lock(lock_path: Path, timeout_seconds: float = 15.0) -> int:
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            ownership = json.dumps(
                {"pid": os.getpid(), "createdAt": time.time()}, separators=(",", ":")
            ).encode("ascii")
            os.write(lock_fd, ownership)
            os.fsync(lock_fd)
            return lock_fd
        except FileExistsError:
            if _lock_owner_is_stale(lock_path, timeout_seconds):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out acquiring recipe lock: {lock_path}")
            time.sleep(0.05)


def _json_bytes(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def atomic_write_json(path: Path, document: dict) -> None:
    _atomic_write_bytes(Path(path), _json_bytes(document))


def update_index(index: dict, recipe: dict, relative_path: str) -> dict:
    updated = copy.deepcopy(index)
    if updated.get("schema") != INDEX_SCHEMA or not isinstance(updated.get("recipes"), list):
        raise ValueError("recipe index has an invalid root structure")
    _validate_index_semantics(updated)

    entry = {
        "recipeId": recipe["recipeId"],
        "name": recipe["name"],
        "aliases": copy.deepcopy(recipe["aliases"]),
        "status": recipe["status"],
        "app": copy.deepcopy(recipe["app"]),
        "goal": recipe["goal"],
        "mode": recipe["mode"],
        "path": relative_path.replace("\\", "/"),
        "verification": copy.deepcopy(recipe["verification"]),
    }
    entries = [candidate for candidate in updated["recipes"] if candidate.get("recipeId") != recipe["recipeId"]]
    entries.append(entry)
    updated["recipes"] = sorted(entries, key=lambda candidate: candidate["recipeId"])
    _validate_index_semantics(updated)
    return updated


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lock_owner_is_stale(lock_path: Path, timeout_seconds: float) -> bool:
    try:
        text = lock_path.read_text(encoding="ascii").strip()
        try:
            owner = json.loads(text)
            pid = int(owner.get("pid", 0))
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            pid = int(text) if text.isdigit() else 0
        if pid:
            return not _pid_is_alive(pid)
        age = time.time() - lock_path.stat().st_mtime
        return age > max(1.0, timeout_seconds)
    except (FileNotFoundError, PermissionError):
        return False


def _release_lock(lock_fd: int, lock_path: Path) -> None:
    os.close(lock_fd)
    deadline = time.monotonic() + 1.0
    while True:
        try:
            lock_path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                return
            time.sleep(0.01)


def _path_key(path: Path) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=False)))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        Path(path).relative_to(root)
    except ValueError:
        return False
    return True


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return False
    return bool(getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)) or stat.S_ISLNK(metadata.st_mode)


def _ensure_safe_target(root: Path, target: Path) -> None:
    root = Path(root).resolve(strict=False)
    target = Path(target)
    if root.exists() and _is_reparse_point(root):
        raise RecipeRejected(f"target root cannot be a reparse point: {root}")
    if not _is_relative_to(target, root):
        raise RecipeRejected(f"target escapes root: {target}")
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists() and _is_reparse_point(current):
            raise RecipeRejected(f"reparse-point target component is prohibited: {current}")
    resolved_target = target.resolve(strict=False)
    if not _is_relative_to(resolved_target, root):
        raise RecipeRejected(f"resolved target escapes root: {target}")


def _canonical_roots(source_root: Path, installed_root: Path, recipe_id: str) -> tuple[Path, Path]:
    source = Path(source_root).resolve(strict=False)
    installed = Path(installed_root).resolve(strict=False)
    if source == installed or _is_relative_to(source, installed) or _is_relative_to(installed, source):
        raise RecipeRejected("source and installed roots must be distinct and non-overlapping")
    for label, root in (("source", source), ("installed", installed)):
        if root.exists() and not root.is_dir():
            raise RecipeRejected(f"{label} root is not a directory: {root}")
        if root.exists() and _is_reparse_point(root):
            raise RecipeRejected(f"{label} root cannot be a reparse point: {root}")
        _ensure_safe_target(root, root / "recipes" / "index.json")
        _ensure_safe_target(root, root / "recipes" / recipe_id / "recipe.json")
    return source, installed


def _canonical_state_root(state_root: Path, source_root: Path, installed_root: Path) -> Path:
    state = Path(state_root).resolve(strict=False)
    for label, target_root in (("source", source_root), ("installed", installed_root)):
        if state == target_root or _is_relative_to(state, target_root) or _is_relative_to(target_root, state):
            raise RecipeRejected(
                f"state root must be disjoint from {label} root and all transaction targets"
            )
    if state.exists() and _is_reparse_point(state):
        raise RecipeRejected(f"state root cannot be a reparse point: {state}")
    return state


def _coordination_root(source_root: Path, installed_root: Path) -> Path:
    pair = sorted((_path_key(source_root), _path_key(installed_root)))
    identity = hashlib.sha256("\0".join(pair).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / "loom-phone-agent-recipe-sync" / identity


def _validate_index_semantics(index: dict) -> None:
    entries = index.get("recipes")
    if not isinstance(entries, list):
        raise ValueError("recipe index recipes must be an array")
    recipe_ids: set[str] = set()
    paths: set[str] = set()
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"recipe index entry {position} must be an object")
        recipe_id = entry.get("recipeId")
        path = entry.get("path")
        expected_path = f"recipes/{recipe_id}/recipe.json"
        if recipe_id in recipe_ids:
            raise ValueError(f"recipe index contains duplicate recipeId: {recipe_id}")
        if path in paths:
            raise ValueError(f"recipe index contains duplicate path: {path}")
        if path != expected_path:
            raise ValueError(f"recipe index path is not canonical for {recipe_id}: {path}")
        recipe_ids.add(recipe_id)
        paths.add(path)


def _privacy_violations(value: Any, path: str = "") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            normalized_key = key.casefold()
            if normalized_key in SENSITIVE_KEYS or normalized_key in REJECTED_PERSONAL_DATA_KEYS:
                violations.append(f"{child_path}:key")
            violations.extend(_privacy_violations(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_privacy_violations(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if "[REDACTED]" in value.upper():
            violations.append(f"{path}:placeholder")
        for label, pattern in SENSITIVE_STRING_PATTERNS + PROHIBITED_NARRATIVE_PATTERNS:
            if label == "password-space" and BENIGN_SECRET_UI_PATTERN.fullmatch(value.strip()):
                continue
            if pattern.search(value):
                violations.append(f"{path}:{label}")
        if CHINESE_MOBILE_PATTERN.search(value):
            violations.append(f"{path}:chinese-mobile")
        if EMAIL_PATTERN.search(value):
            violations.append(f"{path}:email")
    return violations


def _assert_document_privacy_clean(document: dict, context: str) -> None:
    violations = _privacy_violations(document)
    if violations:
        raise ValueError(f"{context} contains prohibited private data: {', '.join(violations)}")


def _load_index_pair(source_index_path: Path, installed_index_path: Path) -> dict:
    source_exists = source_index_path.is_file()
    installed_exists = installed_index_path.is_file()
    if source_index_path.exists() and not source_exists:
        raise OSError(f"source index is not a file: {source_index_path}")
    if installed_index_path.exists() and not installed_exists:
        raise OSError(f"installed index is not a file: {installed_index_path}")
    if source_exists != installed_exists:
        raise OSError("source and installed indexes require reconciliation")
    if not source_exists:
        return {"schema": INDEX_SCHEMA, "recipes": []}

    source_index = load_json(source_index_path)
    installed_index = load_json(installed_index_path)
    _assert_document_privacy_clean(source_index, "source index")
    _assert_document_privacy_clean(installed_index, "installed index")
    validate_document(source_index, INDEX_SCHEMA_PATH)
    validate_document(installed_index, INDEX_SCHEMA_PATH)
    _validate_index_semantics(source_index)
    _validate_index_semantics(installed_index)
    source_bytes = source_index_path.read_bytes()
    installed_bytes = installed_index_path.read_bytes()
    if hashlib.sha256(source_bytes).digest() != hashlib.sha256(installed_bytes).digest() or source_bytes != installed_bytes:
        raise OSError("source and installed indexes require byte-identical reconciliation")
    return source_index


def _preflight_existing_recipe_targets(
    index: dict, source_root: Path, installed_root: Path
) -> None:
    for entry in index["recipes"]:
        recipe_id = entry["recipeId"]
        relative_path = Path(*entry["path"].split("/"))
        source_path = source_root / relative_path
        installed_path = installed_root / relative_path
        _ensure_safe_target(source_root, source_path)
        _ensure_safe_target(installed_root, installed_path)
        if not source_path.is_file() or not installed_path.is_file():
            raise OSError(f"indexed recipe target pair is incomplete: {recipe_id}")
        source_recipe = load_json(source_path)
        installed_recipe = load_json(installed_path)
        _assert_document_privacy_clean(source_recipe, f"source recipe {recipe_id}")
        _assert_document_privacy_clean(installed_recipe, f"installed recipe {recipe_id}")
        validate_document(source_recipe, RECIPE_SCHEMA_PATH)
        validate_document(installed_recipe, RECIPE_SCHEMA_PATH)
        if source_recipe.get("recipeId") != recipe_id or installed_recipe.get("recipeId") != recipe_id:
            raise ValueError(f"indexed recipeId does not match target document: {recipe_id}")
        source_bytes = source_path.read_bytes()
        installed_bytes = installed_path.read_bytes()
        if source_bytes != installed_bytes:
            raise OSError(f"indexed recipe target pair requires byte-identical reconciliation: {recipe_id}")


def _preflight_candidate_recipe_targets(
    recipe_id: str, source_root: Path, installed_root: Path
) -> None:
    relative_path = Path("recipes") / recipe_id / "recipe.json"
    source_path = source_root / relative_path
    installed_path = installed_root / relative_path
    _ensure_safe_target(source_root, source_path)
    _ensure_safe_target(installed_root, installed_path)
    source_exists = os.path.lexists(source_path)
    installed_exists = os.path.lexists(installed_path)
    if not source_exists and not installed_exists:
        return
    if source_exists != installed_exists:
        raise OSError(f"candidate recipe target pair is incomplete: {recipe_id}")
    if not source_path.is_file() or not installed_path.is_file():
        raise OSError(f"candidate recipe target pair contains a non-file path: {recipe_id}")
    source_recipe = load_json(source_path)
    installed_recipe = load_json(installed_path)
    _assert_document_privacy_clean(source_recipe, f"source candidate target {recipe_id}")
    _assert_document_privacy_clean(installed_recipe, f"installed candidate target {recipe_id}")
    validate_document(source_recipe, RECIPE_SCHEMA_PATH)
    validate_document(installed_recipe, RECIPE_SCHEMA_PATH)
    if source_recipe.get("recipeId") != recipe_id or installed_recipe.get("recipeId") != recipe_id:
        raise ValueError(f"candidate target recipeId does not match requested recipe: {recipe_id}")
    if source_path.read_bytes() != installed_path.read_bytes():
        raise OSError(f"candidate recipe target pair requires byte-identical reconciliation: {recipe_id}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _base_result(recipe_id: Any, status: str, redactions: list[str]) -> dict:
    return {
        "schema": SYNC_SCHEMA,
        "recipeId": recipe_id if isinstance(recipe_id, str) else None,
        "status": status,
        "sourceRecipeSha256": None,
        "installedRecipeSha256": None,
        "sourceIndexSha256": None,
        "installedIndexSha256": None,
        "hashes": {
            "sourceRecipe": None,
            "installedRecipe": None,
            "sourceIndex": None,
            "installedIndex": None,
        },
        "redactions": redactions,
        "transactionPath": None,
    }


def _backup_targets(transaction_path: Path, targets: list[tuple[str, Path, Path]]) -> list[dict]:
    records: list[dict] = []
    backup_root = transaction_path / "backups"
    for label, root, target in targets:
        _ensure_safe_target(root, target)
        existed = target.is_file()
        if target.exists() and not existed:
            raise OSError(f"transaction target is not a file: {target}")
        record = {
            "label": label,
            "root": str(root),
            "target": str(target),
            "existed": existed,
            "backup": None,
            "backupSha256": None,
        }
        if existed:
            relative = target.relative_to(root)
            backup_path = backup_root / label / relative
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_path)
            record["backup"] = str(backup_path)
            record["backupSha256"] = _sha256_file(backup_path)
        records.append(record)
    atomic_write_json(transaction_path / "backup-manifest.json", {"targets": records})
    return records


def _remove_empty_parents(path: Path, root: Path) -> None:
    current = path
    while current != root and root in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _restore_targets(records: list[dict]) -> None:
    errors: list[str] = []
    for record in reversed(records):
        target = Path(record["target"])
        root = Path(record["root"])
        try:
            _ensure_safe_target(root, target)
            if record["existed"]:
                backup_path = Path(record["backup"])
                backup_hash = record.get("backupSha256")
                if not backup_hash or _sha256_file(backup_path) != backup_hash:
                    raise OSError(f"backup hash mismatch: {backup_path}")
                _atomic_write_bytes(target, backup_path.read_bytes())
                if _sha256_file(target) != backup_hash:
                    raise OSError(f"restored target hash mismatch: {target}")
            elif target.exists():
                if target.is_file():
                    target.unlink()
                    _remove_empty_parents(target.parent, root)
                else:
                    raise OSError(f"cannot remove non-file rollback target: {target}")
                if target.exists():
                    raise OSError(f"new rollback target still exists: {target}")
        except Exception as error:
            errors.append(f"{record.get('label', target)}: {type(error).__name__}: {error}")
    if errors:
        raise OSError("rollback failures: " + " | ".join(errors))


def _persist_journal(journal_path: Path, journal: dict) -> None:
    atomic_write_json(journal_path, journal)
    transaction_path = Path(journal["transactionPath"])
    atomic_write_json(transaction_path / "journal.json", journal)


def _remove_canonical_journal(journal_path: Path) -> None:
    try:
        journal_path.unlink()
    except FileNotFoundError:
        pass


def _mirror_terminal_transaction(journal: dict) -> None:
    phase = journal.get("phase")
    transaction_path = Path(journal["transactionPath"])
    result_path = transaction_path / "result.json"
    if phase == "committed":
        result = load_json(result_path)
        if result.get("status") != "synced":
            raise OSError("committed transaction result is not synced")
        result_status = "synced"
    elif phase in {"rolled_back", "recovered"}:
        result = _base_result(
            journal["recipeId"], "sync_pending", list(journal.get("redactions", []))
        )
        result["transactionPath"] = journal["transactionPath"]
        result["error"] = (
            "recovered incomplete transaction"
            if phase == "recovered"
            else "transaction rolled back before finalization"
        )
        atomic_write_json(result_path, result)
        result_status = "sync_pending"
    else:
        raise OSError(f"journal phase is not terminal: {phase}")
    journal["resultStatus"] = result_status
    atomic_write_json(transaction_path / "journal.json", journal)


def _validate_recovery_journal(journal: dict, source_root: Path, installed_root: Path) -> None:
    if journal.get("schema") != "loom.phone-agent.recipe-sync-journal.v1":
        raise OSError("unsupported recipe sync journal schema")
    if _path_key(Path(journal.get("sourceRoot", ""))) != _path_key(source_root):
        raise OSError("journal source root does not match lock target pair")
    if _path_key(Path(journal.get("installedRoot", ""))) != _path_key(installed_root):
        raise OSError("journal installed root does not match lock target pair")
    recipe_id = journal.get("recipeId")
    if not isinstance(recipe_id, str):
        raise OSError("journal recipeId is invalid")
    transaction_path = Path(journal.get("transactionPath", "")).resolve(strict=False)
    records = journal.get("targets")
    if not isinstance(records, list) or len(records) != 4:
        raise OSError("journal must contain four transaction targets")
    expected_targets = {
        "source-recipe": (source_root, source_root / "recipes" / recipe_id / "recipe.json"),
        "installed-recipe": (installed_root, installed_root / "recipes" / recipe_id / "recipe.json"),
        "source-index": (source_root, source_root / "recipes" / "index.json"),
        "installed-index": (installed_root, installed_root / "recipes" / "index.json"),
    }
    seen: set[str] = set()
    for record in records:
        label = record.get("label")
        if label not in expected_targets or label in seen:
            raise OSError(f"journal target label is invalid: {label}")
        expected_root, expected_target = expected_targets[label]
        root = Path(record.get("root", "")).resolve(strict=False)
        target = Path(record.get("target", "")).resolve(strict=False)
        if root != expected_root or target != expected_target.resolve(strict=False):
            raise OSError(f"journal target does not match canonical path: {label}")
        _ensure_safe_target(expected_root, Path(record["target"]))
        if record.get("existed"):
            backup = Path(record.get("backup", "")).resolve(strict=False)
            if not _is_relative_to(backup, transaction_path):
                raise OSError(f"journal backup escapes transaction directory: {label}")
            if not record.get("backupSha256"):
                raise OSError(f"journal backup hash is missing: {label}")
        seen.add(label)


def _recover_incomplete_transactions(
    coordination_root: Path, source_root: Path, installed_root: Path
) -> None:
    journals_root = coordination_root / "journals"
    if not journals_root.exists():
        return
    for journal_path in sorted(journals_root.glob("*.json")):
        journal = load_json(journal_path)
        _validate_recovery_journal(journal, source_root, installed_root)
        phase = journal.get("phase")
        if phase in {"committed", "rolled_back", "recovered"}:
            _mirror_terminal_transaction(journal)
            _remove_canonical_journal(journal_path)
            continue
        owner = journal.get("lockOwnership", {})
        owner_pid = int(owner.get("pid", 0)) if isinstance(owner, dict) else 0
        if owner_pid and owner_pid != os.getpid() and _pid_is_alive(owner_pid):
            raise OSError(f"incomplete transaction owner is still alive: {owner_pid}")
        journal["phase"] = "recovering"
        journal["recoveryOwnerPid"] = os.getpid()
        _persist_journal(journal_path, journal)
        try:
            _restore_targets(journal["targets"])
            pending_result = _base_result(
                journal["recipeId"], "sync_pending", list(journal.get("redactions", []))
            )
            pending_result["transactionPath"] = journal["transactionPath"]
            pending_result["error"] = "recovered incomplete transaction"
            atomic_write_json(Path(journal["transactionPath"]) / "result.json", pending_result)
        except Exception as error:
            journal["phase"] = "recovery_failed"
            journal["recoveryError"] = str(error)
            _persist_journal(journal_path, journal)
            raise OSError(f"incomplete transaction recovery failed: {error}") from error
        journal["phase"] = "recovered"
        journal["resultStatus"] = "sync_pending"
        journal["recoveredAt"] = datetime.now(timezone.utc).isoformat()
        journal.pop("recoveryError", None)
        _persist_journal(journal_path, journal)
        _remove_canonical_journal(journal_path)


def sync_recipe(recipe: dict, source_root: Path, installed_root: Path, state_root: Path) -> dict:
    if JSONSCHEMA_IMPORT_ERROR is not None:
        raise RecipeRejected(f"jsonschema dependency is unavailable: {JSONSCHEMA_IMPORT_ERROR}")
    recipe_id = recipe.get("recipeId") if isinstance(recipe, dict) else None
    redactions: list[str] = []

    try:
        assert_promotable(recipe)
        sanitized, redactions = sanitize_recipe(recipe)
        allowed_field_redactions = [redaction for redaction in redactions if not redaction.endswith(":key")]
        if allowed_field_redactions:
            raise RecipeRejected(
                "schema-allowed fields contain prohibited private data: "
                + ", ".join(allowed_field_redactions)
            )
        _assert_document_privacy_clean(sanitized, "candidate recipe")
        validate_document(sanitized, RECIPE_SCHEMA_PATH)
        assert_promotable(sanitized)
        source_root, installed_root = _canonical_roots(source_root, installed_root, sanitized["recipeId"])
        state_root = _canonical_state_root(state_root, source_root, installed_root)
    except (RecipeRejected, ValueError, TypeError, KeyError) as error:
        result = _base_result(recipe_id, "rejected", redactions)
        result["error"] = str(error)
        return result

    transaction_path = state_root / "transactions" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + f"-{uuid.uuid4().hex}"
    )
    result = _base_result(sanitized["recipeId"], "sync_pending", redactions)
    result["transactionPath"] = str(transaction_path)
    try:
        transaction_path.mkdir(parents=True, exist_ok=False)
        atomic_write_json(transaction_path / "candidate.recipe.json", sanitized)
    except Exception as error:
        result["error"] = f"transaction setup failed: {type(error).__name__}"
        return result

    coordination_root = _coordination_root(source_root, installed_root)
    lock_path = coordination_root / "write.lock"
    lock_fd: int | None = None
    backup_records: list[dict] = []
    journal_path: Path | None = None
    journal: dict | None = None
    try:
        lock_fd = acquire_lock(lock_path)
        _recover_incomplete_transactions(coordination_root, source_root, installed_root)
        source_index_path = source_root / "recipes" / "index.json"
        installed_index_path = installed_root / "recipes" / "index.json"
        index = _load_index_pair(source_index_path, installed_index_path)
        _preflight_existing_recipe_targets(index, source_root, installed_root)
        _preflight_candidate_recipe_targets(sanitized["recipeId"], source_root, installed_root)

        relative_path = f"recipes/{sanitized['recipeId']}/recipe.json"
        updated_index = update_index(index, sanitized, relative_path)
        validate_document(updated_index, INDEX_SCHEMA_PATH)
        atomic_write_json(transaction_path / "candidate.index.json", updated_index)

        source_recipe_path = source_root / Path(relative_path)
        installed_recipe_path = installed_root / Path(relative_path)
        targets = [
            ("source-recipe", source_root, source_recipe_path),
            ("source-index", source_root, source_index_path),
            ("installed-recipe", installed_root, installed_recipe_path),
            ("installed-index", installed_root, installed_index_path),
        ]
        backup_records = _backup_targets(transaction_path, targets)
        journal_path = coordination_root / "journals" / f"{transaction_path.name}.json"
        journal = {
            "schema": "loom.phone-agent.recipe-sync-journal.v1",
            "transactionId": transaction_path.name,
            "transactionPath": str(transaction_path),
            "recipeId": sanitized["recipeId"],
            "sourceRoot": str(source_root),
            "installedRoot": str(installed_root),
            "phase": "prepared",
            "resultStatus": "sync_pending",
            "nextTarget": None,
            "completedWrites": [],
            "targets": backup_records,
            "redactions": redactions,
            "lockOwnership": {
                "pid": os.getpid(),
                "lockPath": str(lock_path),
                "acquiredAt": datetime.now(timezone.utc).isoformat(),
            },
        }
        _persist_journal(journal_path, journal)

        write_plan = [
            ("source-recipe", source_recipe_path, sanitized),
            ("installed-recipe", installed_recipe_path, sanitized),
            ("source-index", source_index_path, updated_index),
            ("installed-index", installed_index_path, updated_index),
        ]
        for label, path, document in write_plan:
            journal["phase"] = f"before:{label}"
            journal["nextTarget"] = str(path)
            _persist_journal(journal_path, journal)
            target_root = source_root if label.startswith("source-") else installed_root
            _ensure_safe_target(target_root, path)
            atomic_write_json(path, document)
            journal["completedWrites"].append(label)
            journal["phase"] = f"after:{label}"
            _persist_journal(journal_path, journal)

        source_recipe_hash = _sha256_file(source_recipe_path)
        installed_recipe_hash = _sha256_file(installed_recipe_path)
        source_index_hash = _sha256_file(source_index_path)
        installed_index_hash = _sha256_file(installed_index_path)
        if source_recipe_hash != installed_recipe_hash:
            raise OSError("source and installed recipe SHA256 differ")
        if source_index_hash != installed_index_hash:
            raise OSError("source and installed index SHA256 differ")

        synced_result = copy.deepcopy(result)
        synced_result.update(
            {
                "status": "synced",
                "sourceRecipeSha256": source_recipe_hash,
                "installedRecipeSha256": installed_recipe_hash,
                "sourceIndexSha256": source_index_hash,
                "installedIndexSha256": installed_index_hash,
                "hashes": {
                    "sourceRecipe": source_recipe_hash,
                    "installedRecipe": installed_recipe_hash,
                    "sourceIndex": source_index_hash,
                    "installedIndex": installed_index_hash,
                },
            }
        )
        journal["phase"] = "finalizing"
        journal["nextTarget"] = str(transaction_path / "result.json")
        _persist_journal(journal_path, journal)
        atomic_write_json(transaction_path / "result.json", synced_result)
        journal["phase"] = "committed"
        journal["resultStatus"] = "synced"
        journal["nextTarget"] = None
        journal["committedAt"] = datetime.now(timezone.utc).isoformat()
        _persist_journal(journal_path, journal)
        _remove_canonical_journal(journal_path)
        return synced_result
    except Exception as error:
        rollback_error: Exception | None = None
        rollback_journal_persisted = False
        if backup_records:
            try:
                _restore_targets(backup_records)
            except Exception as caught:
                rollback_error = caught
        if journal is not None and journal_path is not None:
            journal["phase"] = "rollback_failed" if rollback_error is not None else "rolled_back"
            journal["resultStatus"] = "sync_pending"
            journal["nextTarget"] = None
            journal["rollbackAt"] = datetime.now(timezone.utc).isoformat()
            if rollback_error is not None:
                journal["rollbackError"] = str(rollback_error)
            try:
                _persist_journal(journal_path, journal)
                rollback_journal_persisted = True
            except OSError:
                pass
        result["error"] = str(error)
        if rollback_error is not None:
            result["rollbackError"] = str(rollback_error)
        pending_result_persisted = False
        try:
            atomic_write_json(transaction_path / "result.json", result)
            pending_result_persisted = True
        except OSError:
            pass
        if (
            rollback_error is None
            and rollback_journal_persisted
            and pending_result_persisted
            and journal_path is not None
        ):
            try:
                _remove_canonical_journal(journal_path)
            except OSError:
                pass
        return result
    finally:
        if lock_fd is not None:
            _release_lock(lock_fd, lock_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize a verified LOOM phone recipe")
    parser.add_argument("--check-environment", action="store_true")
    parser.add_argument("--recipe-file", type=Path)
    parser.add_argument("--source-skill-root", type=Path)
    parser.add_argument("--installed-skill-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    args = parser.parse_args(argv)

    if args.check_environment:
        if JSONSCHEMA_IMPORT_ERROR is not None:
            result = {
                "schema": "loom.phone-agent.environment-check.v1",
                "status": "blocked",
                "error": f"jsonschema dependency is unavailable: {JSONSCHEMA_IMPORT_ERROR}",
            }
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 1
        try:
            recipe_schema = load_json(RECIPE_SCHEMA_PATH)
            index_schema = load_json(INDEX_SCHEMA_PATH)
            Draft202012Validator.check_schema(recipe_schema)
            Draft202012Validator.check_schema(index_schema)
            FormatChecker()
            result = {
                "schema": "loom.phone-agent.environment-check.v1",
                "status": "ready",
                "pythonVersion": sys.version.split()[0],
                "jsonschemaVersion": package_version("jsonschema"),
                "recipeSchema": "valid",
                "indexSchema": "valid",
            }
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0
        except Exception as error:
            result = {
                "schema": "loom.phone-agent.environment-check.v1",
                "status": "blocked",
                "error": str(error),
            }
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 1

    required_arguments = {
        "--recipe-file": args.recipe_file,
        "--source-skill-root": args.source_skill_root,
        "--installed-skill-root": args.installed_skill_root,
        "--state-root": args.state_root,
    }
    missing_arguments = [name for name, value in required_arguments.items() if value is None]
    if missing_arguments:
        parser.error(f"the following arguments are required: {', '.join(missing_arguments)}")

    try:
        recipe = load_json(args.recipe_file)
        result = sync_recipe(recipe, args.source_skill_root, args.installed_skill_root, args.state_root)
    except Exception as error:
        result = _base_result(None, "rejected", [])
        result["error"] = str(error)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] == "synced" else 1


if __name__ == "__main__":
    raise SystemExit(main())
