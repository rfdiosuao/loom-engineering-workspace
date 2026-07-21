param(
    [string]$BaseUrl = "",
    [string]$TextModel = "",
    [string]$ImageModel = "",
    [string]$VideoModel = "",
    [switch]$KeepTemp
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $Root "openclaw_new_launcher\python"

$Email = [string]$env:LOOM_NEWAPI_EMAIL
$Password = [string]$env:LOOM_NEWAPI_PASSWORD

if ([string]::IsNullOrWhiteSpace($Email) -or [string]::IsNullOrWhiteSpace($Password)) {
    Write-Host "NewAPI account verification skipped: set LOOM_NEWAPI_EMAIL and LOOM_NEWAPI_PASSWORD in the environment." -ForegroundColor Yellow
    Write-Host "Optional: LOOM_NEWAPI_BASE_URL, LOOM_NEWAPI_TEXT_MODEL, LOOM_NEWAPI_IMAGE_MODEL, LOOM_NEWAPI_VIDEO_MODEL." -ForegroundColor Yellow
    exit 2
}

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    $BaseUrl = [string]$env:LOOM_NEWAPI_BASE_URL
}
if ([string]::IsNullOrWhiteSpace($TextModel)) {
    $TextModel = [string]$env:LOOM_NEWAPI_TEXT_MODEL
}
if ([string]::IsNullOrWhiteSpace($ImageModel)) {
    $ImageModel = [string]$env:LOOM_NEWAPI_IMAGE_MODEL
}
if ([string]::IsNullOrWhiteSpace($VideoModel)) {
    $VideoModel = [string]$env:LOOM_NEWAPI_VIDEO_MODEL
}

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("loom-newapi-verify-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

$pythonScript = @'
from __future__ import annotations

import json
import os
import shutil
import sys
from typing import Any

from core.newapi_account_manager import NewApiAccountManager
from core.paths import AppPaths


def choose_model(candidates: list[str], requested: str, preferred: list[str]) -> str:
    requested = requested.strip()
    if requested:
        return requested
    for model in preferred:
        if model in candidates:
            return model
    return candidates[0] if candidates else ""


def exists(name: str) -> bool:
    return os.path.exists(os.path.join(workdir, name))


def mask_account(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "@" in text:
        name, domain = text.split("@", 1)
        prefix = name[:2] if len(name) > 2 else name[:1]
        return f"{prefix}***@{domain}"
    if len(text) <= 6:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def sanitize_sync_results(items: object) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    sanitized: list[dict[str, Any]] = []
    secret_markers = ("sk-", "sess-", "eyJ")
    for item in items:
        if not isinstance(item, dict):
            continue
        payload: dict[str, Any] = {}
        for key, value in item.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("token", "cookie", "apikey", "api_key", "password", "secret")):
                continue
            if isinstance(value, str):
                text = value
                for marker in secret_markers:
                    index = text.find(marker)
                    if index >= 0:
                        text = text[:index] + "[redacted]"
                payload[key] = text
            else:
                payload[key] = value
        sanitized.append(payload)
    return sanitized


def sanitize_kept_workdir(root: str, summary: dict[str, Any] | None) -> None:
    sensitive_relpaths = [
        "imgapi_config.json",
        "video_config.json",
        "videoapi_config.json",
        os.path.join("data", ".openclaw", "launcher", "member-session.json"),
        os.path.join("data", ".openclaw", "launcher", "desktop-agent.json"),
        os.path.join("data", ".openclaw", "launcher", "phone-agent.json"),
        os.path.join("data", ".openclaw", "agents", "main", "agent", "auth-profiles.json"),
        os.path.join("data", ".openclaw", "agents", "main", "agent", "models.json"),
        os.path.join("data", ".openclaw", "openclaw.json"),
    ]
    for relpath in sensitive_relpaths:
        path = os.path.join(root, relpath)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    if summary is not None:
        safe_summary = dict(summary)
        safe_summary["workdirSanitized"] = True
        with open(os.path.join(root, "verification-summary.json"), "w", encoding="utf-8") as file:
            json.dump(safe_summary, file, ensure_ascii=False, indent=2)
            file.write("\n")


def fail(message: str, detail: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"ok": False, "error": message}
    if detail:
        payload["detail"] = detail
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(1)


workdir = os.environ["LOOM_NEWAPI_VERIFY_WORKDIR"]
keep_temp = os.environ.get("LOOM_NEWAPI_VERIFY_KEEP", "") == "1"
email = os.environ["LOOM_NEWAPI_EMAIL"].strip()
password = os.environ["LOOM_NEWAPI_PASSWORD"].strip()
base_url = os.environ.get("LOOM_NEWAPI_BASE_URL", "").strip()
text_request = os.environ.get("LOOM_NEWAPI_TEXT_MODEL", "").strip()
image_request = os.environ.get("LOOM_NEWAPI_IMAGE_MODEL", "").strip()
video_request = os.environ.get("LOOM_NEWAPI_VIDEO_MODEL", "").strip()
result_payload: dict[str, Any] | None = None

try:
    manager = NewApiAccountManager(AppPaths(workdir))
    session = manager.login(email, password, base_url=base_url)
    public = manager.public_session()
    models = public.get("models") if isinstance(public.get("models"), dict) else {}
    text_models = models.get("text") if isinstance(models.get("text"), list) else []
    image_models = models.get("image") if isinstance(models.get("image"), list) else []
    video_models = models.get("video") if isinstance(models.get("video"), list) else []

    text_model = choose_model(text_models, text_request, ["qwen3.7-plus", "gpt-4o", "gpt-4"])
    image_model = choose_model(image_models, image_request, ["gpt-image-1", "seedream-image-v1"])
    video_model = choose_model(video_models, video_request, [])

    if not text_model:
        fail("当前账号未返回可用文本模型", {"modelCounts": {"text": len(text_models), "image": len(image_models), "video": len(video_models)}})
    if not image_model:
        fail("当前账号未返回可用图片模型", {"modelCounts": {"text": len(text_models), "image": len(image_models), "video": len(video_models)}})

    selected = manager.select_models(text_model=text_model, image_model=image_model, video_model=video_model)
    selected_models = selected.get("selectedModels") if isinstance(selected.get("selectedModels"), dict) else {}

    video_config_exists = exists("video_config.json")
    videoapi_config_exists = exists("videoapi_config.json")
    if video_config_exists or videoapi_config_exists:
        fail("视频模型选择不应写入正式视频 provider 配置", {
            "videoConfig": video_config_exists,
            "videoApiConfig": videoapi_config_exists,
        })

    result_payload = {
        "ok": True,
        "baseUrl": public.get("baseUrl"),
        "accountMasked": mask_account(public.get("account")),
        "tokenPresent": bool(public.get("tokenMasked")),
        "modelCounts": {
            "text": len(text_models),
            "image": len(image_models),
            "video": len(video_models),
        },
        "selectedModels": {
            "text": selected_models.get("text"),
            "image": selected_models.get("image"),
            "videoDraft": selected_models.get("videoDraft"),
        },
        "syncResults": sanitize_sync_results(selected.get("lastSyncResults")),
        "files": {
            "session": exists(os.path.join("data", ".openclaw", "launcher", "member-session.json")),
            "imageConfig": exists("imgapi_config.json"),
            "desktopConfig": exists(os.path.join("data", ".openclaw", "launcher", "desktop-agent.json")),
            "phoneConfig": exists(os.path.join("data", ".openclaw", "launcher", "phone-agent.json")),
            "videoConfig": video_config_exists,
            "videoApiConfig": videoapi_config_exists,
        },
        "workdir": workdir if keep_temp else "<removed>",
    }
    print(json.dumps(result_payload, ensure_ascii=False, indent=2))
finally:
    if keep_temp:
        sanitize_kept_workdir(workdir, result_payload)
    else:
        shutil.rmtree(workdir, ignore_errors=True)
'@

$previousPythonPath = $env:PYTHONPATH
$previousBaseUrl = $env:LOOM_NEWAPI_BASE_URL
$previousTextModel = $env:LOOM_NEWAPI_TEXT_MODEL
$previousImageModel = $env:LOOM_NEWAPI_IMAGE_MODEL
$previousVideoModel = $env:LOOM_NEWAPI_VIDEO_MODEL
$previousWorkDir = $env:LOOM_NEWAPI_VERIFY_WORKDIR
$previousKeep = $env:LOOM_NEWAPI_VERIFY_KEEP

try {
    if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
        $env:PYTHONPATH = $PythonPath
    } else {
        $env:PYTHONPATH = "$PythonPath$([System.IO.Path]::PathSeparator)$previousPythonPath"
    }
    $env:LOOM_NEWAPI_BASE_URL = $BaseUrl
    $env:LOOM_NEWAPI_TEXT_MODEL = $TextModel
    $env:LOOM_NEWAPI_IMAGE_MODEL = $ImageModel
    $env:LOOM_NEWAPI_VIDEO_MODEL = $VideoModel
    $env:LOOM_NEWAPI_VERIFY_WORKDIR = $TempRoot
    $env:LOOM_NEWAPI_VERIFY_KEEP = if ($KeepTemp) { "1" } else { "" }

    $pythonScript | python -
    if ($LASTEXITCODE -ne 0) {
        throw "NewAPI account verification failed with exit code $LASTEXITCODE"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:LOOM_NEWAPI_BASE_URL = $previousBaseUrl
    $env:LOOM_NEWAPI_TEXT_MODEL = $previousTextModel
    $env:LOOM_NEWAPI_IMAGE_MODEL = $previousImageModel
    $env:LOOM_NEWAPI_VIDEO_MODEL = $previousVideoModel
    $env:LOOM_NEWAPI_VERIFY_WORKDIR = $previousWorkDir
    $env:LOOM_NEWAPI_VERIFY_KEEP = $previousKeep
    if (-not $KeepTemp -and (Test-Path -LiteralPath $TempRoot)) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}
