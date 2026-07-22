"""Image and video generation FastAPI routes."""

from __future__ import annotations

import base64
import concurrent.futures
import datetime
import json
import os
import re
import subprocess
import sys
import uuid

from fastapi import Request
from fastapi.responses import FileResponse, Response

from api.safe_payload import redact_secret_text
from core.constants import IMAGE_MODEL
from core.secret_store import protect_secret, unprotect_secret
from core.storage import read_json, write_json
from services.image_api import ImageApiError
from services.media_library import MediaLibrary, MediaLibraryError
from services.pippit_video_api import PippitManualRequired, PippitResumeRequired
from services.video_api import VideoApiError


IMAGE_RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "3:4": "1152x1536",
    "4:3": "1536x1152",
    "9:16": "1152x2048",
    "16:9": "2048x1152",
    "5:2": "2560x1024",
}
IMAGE_SIZE_TO_RATIO = {size: ratio for ratio, size in IMAGE_RATIO_TO_SIZE.items()}


def _text(value: object) -> str:
    return str(value or "").strip()


def _image_size_for_ratio(ratio: object) -> str:
    return IMAGE_RATIO_TO_SIZE.get(_text(ratio), "")


def _image_ratio_for_size(size: object, fallback: object = "") -> str:
    return _text(fallback) or IMAGE_SIZE_TO_RATIO.get(_text(size), "")


def _media_library(ctx) -> MediaLibrary:
    return MediaLibrary(ctx.paths.data_dir)


def _record_media(ctx, path: str, metadata: dict) -> None:
    try:
        _media_library(ctx).record(path, metadata)
    except (MediaLibraryError, OSError):
        # The generated file is the primary result. Metadata failure must not discard it.
        return


def _write_unique_media_file(directory: str, prefix: str, extension: str, payload: bytes, *, index: int | None = None) -> tuple[str, str]:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    index_suffix = f"-{index}" if index is not None else ""
    for attempt in range(1000):
        collision_suffix = "" if attempt == 0 else f"-{attempt + 1}"
        filename = f"{prefix}-{stamp}{index_suffix}{collision_suffix}{extension}"
        save_path = os.path.join(directory, filename)
        try:
            with open(save_path, "xb") as file:
                file.write(payload)
            return filename, save_path
        except FileExistsError:
            continue
    raise OSError("无法为生成素材分配唯一文件名")


def _image_storage_format(payload: bytes) -> tuple[str, str]:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return ".png", "image/png"


def _video_storage_format(payload: bytes) -> tuple[str, str]:
    if payload.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm", "video/webm"
    return ".mp4", "video/mp4"


def _compact_media_job_result(result: dict) -> dict:
    return {key: value for key, value in result.items() if key not in {"images", "video"}}


def _phone_transfer_summary(
    status: str,
    reason: str,
    message: str,
    *,
    attempted: bool,
    device: dict | None = None,
    uploaded_count: int = 0,
    total_count: int = 0,
    uploaded_files: list[str] | None = None,
) -> dict:
    selected = device if isinstance(device, dict) else {}
    summary = {
        "status": status,
        "reason": reason,
        "message": message,
        "attempted": attempted,
        "uploadedCount": max(0, int(uploaded_count or 0)),
        "totalCount": max(0, int(total_count or 0)),
    }
    device_id = _text(selected.get("id") or selected.get("deviceId"))[:80]
    if device_id:
        summary["deviceId"] = device_id
    device_name = _text(selected.get("name"))[:80]
    if device_name:
        summary["deviceName"] = device_name
    album = _text(selected.get("album"))[:80]
    if album:
        summary["album"] = album
    safe_files = []
    for filename in uploaded_files or []:
        safe_name = os.path.basename(_text(filename))[:160]
        if safe_name and safe_name not in safe_files:
            safe_files.append(safe_name)
        if len(safe_files) >= 50:
            break
    if safe_files:
        summary["uploadedFiles"] = safe_files
    return summary


def _explicit_selected_phone(ctx) -> tuple[dict, str]:
    try:
        from api.routes_phone import _load_store

        store = _load_store(ctx)
    except Exception:
        return {}, "no_selected_phone"
    if not isinstance(store, dict):
        return {}, "no_selected_phone"

    selected_id = _text(store.get("selectedDeviceId"))
    if not selected_id:
        return {}, "no_selected_phone"
    devices = store.get("devices") if isinstance(store.get("devices"), list) else []
    selected = next(
        (
            item
            for item in devices
            if isinstance(item, dict) and _text(item.get("id") or item.get("deviceId")) == selected_id
        ),
        None,
    )
    if not isinstance(selected, dict):
        return {}, "no_selected_phone"

    # Connectivity can change while an asynchronous generation job is running.
    # Preserve only the selected device here; the upload helper performs the
    # authoritative connection check when the generated file is ready.
    return dict(selected), ""


def _selected_phone_snapshot(ctx) -> dict:
    selected, unavailable_reason = _explicit_selected_phone(ctx)
    public_device = {}
    if isinstance(selected, dict):
        device_id = _text(selected.get("id") or selected.get("deviceId"))[:80]
        if device_id:
            public_device["id"] = device_id
        device_name = _text(selected.get("name"))[:80]
        if device_name:
            public_device["name"] = device_name
        album = _text(selected.get("album"))[:80]
        if album:
            public_device["album"] = album
    return {"device": public_device, "reason": unavailable_reason}


def _configured_phone_snapshot(ctx, device_ids: list[str] | None = None) -> dict:
    try:
        from api.routes_phone import _load_store

        store = _load_store(ctx)
    except Exception:
        store = {}
    devices = store.get("devices") if isinstance(store, dict) and isinstance(store.get("devices"), list) else []
    public_devices: list[dict] = []
    by_id: dict[str, dict] = {}
    for item in devices:
        if not isinstance(item, dict):
            continue
        device_id = _text(item.get("id") or item.get("deviceId"))[:80]
        if not device_id or device_id in by_id:
            continue
        public_device = {"id": device_id}
        device_name = _text(item.get("name"))[:80]
        if device_name:
            public_device["name"] = device_name
        album = _text(item.get("album"))[:80]
        if album:
            public_device["album"] = album
        by_id[device_id] = public_device
        public_devices.append(public_device)

    missing_ids: list[str] = []
    if device_ids is not None:
        requested: list[str] = []
        for value in device_ids:
            device_id = _text(value)[:80]
            if device_id and device_id not in requested:
                requested.append(device_id)
        missing_ids = [device_id for device_id in requested if device_id not in by_id]
        public_devices = [by_id[device_id] for device_id in requested if device_id in by_id]
    return {
        "devices": public_devices,
        "reason": "" if public_devices else "no_configured_phones",
        "missingDeviceIds": missing_ids,
    }


def _uploaded_filenames(payload: object) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("uploaded"), list):
        return []
    filenames = []
    for item in payload["uploaded"]:
        if not isinstance(item, dict):
            continue
        filename = os.path.basename(_text(item.get("filename")))[:160]
        if filename and filename not in filenames:
            filenames.append(filename)
        if len(filenames) >= 50:
            break
    return filenames


def _safe_upload_count(payload: object, total_count: int) -> int:
    if not isinstance(payload, dict):
        return 0
    value = payload.get("uploadedCount")
    if isinstance(value, bool):
        return 0
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return min(max(0, count), max(0, total_count))


def _transfer_generated_media_to_phone(
    ctx,
    kind: str,
    files: list[dict],
    *,
    phone_snapshot: dict | None = None,
) -> dict:
    snapshot = phone_snapshot if isinstance(phone_snapshot, dict) else _selected_phone_snapshot(ctx)
    selected = snapshot.get("device") if isinstance(snapshot.get("device"), dict) else {}
    unavailable_reason = _text(snapshot.get("reason"))
    if unavailable_reason == "no_selected_phone":
        return _phone_transfer_summary(
            "skipped",
            unavailable_reason,
            "未选择手机，素材仅保存在本地",
            attempted=False,
        )
    if unavailable_reason == "selected_phone_offline":
        return _phone_transfer_summary(
            "skipped",
            unavailable_reason,
            "所选手机离线，素材仅保存在本地",
            attempted=False,
            device=selected,
        )

    media_kind = "video" if kind == "video" else "image"
    paths = [
        _text(item.get("path"))
        for item in files
        if isinstance(item, dict) and _text(item.get("path"))
    ]
    if not paths:
        return _phone_transfer_summary(
            "failed",
            "generated_files_missing",
            "本地生成成功，但没有可传送的文件",
            attempted=False,
            device=selected,
        )

    try:
        from api.routes_phone import _script_path, node_executable, phone_process_env

        script_path = _script_path(ctx, "openclaw-media-phone.mjs")
        if not os.path.isfile(script_path):
            return _phone_transfer_summary(
                "failed",
                "upload_helper_unavailable",
                "本地生成成功，手机传送组件不可用",
                attempted=False,
                device=selected,
                total_count=len(paths),
            )
        node_path = node_executable(
            getattr(ctx.paths, "base_path", None),
            explicit=getattr(ctx.paths, "node_exe", None),
        )
        command = [
            node_path,
            script_path,
            "--device-id",
            _text(selected.get("id") or selected.get("deviceId")),
        ]
        flag = "--video" if media_kind == "video" else "--image"
        for file_path in paths:
            command.extend([flag, file_path])
        command.append("--json")
        completed = subprocess.run(
            command,
            cwd=getattr(ctx.paths, "base_path", None) or None,
            env=phone_process_env(ctx),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(180, len(paths) * 130),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw_output = _text(completed.stdout)
        try:
            payload = json.loads(raw_output) if raw_output else None
        except json.JSONDecodeError:
            payload = None
        if not isinstance(payload, dict):
            return _phone_transfer_summary(
                "failed",
                "phone_upload_invalid_response",
                "本地生成成功，但手机传送组件返回无效结果",
                attempted=True,
                device=selected,
                total_count=len(paths),
            )
        uploaded_count = _safe_upload_count(payload, len(paths))
        uploaded_files = _uploaded_filenames(payload)
        if completed.returncode != 0 or payload.get("ok") is not True:
            reason = _text(payload.get("errorCode")) or "phone_upload_failed"
            return _phone_transfer_summary(
                "failed",
                reason[:80],
                "本地生成成功，传到手机失败",
                attempted=True,
                device=selected,
                uploaded_count=uploaded_count,
                total_count=len(paths),
                uploaded_files=uploaded_files,
            )
        if uploaded_count != len(paths):
            return _phone_transfer_summary(
                "failed",
                "phone_upload_incomplete",
                "本地生成成功，但仅部分素材传到手机",
                attempted=True,
                device=selected,
                uploaded_count=uploaded_count,
                total_count=len(paths),
                uploaded_files=uploaded_files,
            )
        return _phone_transfer_summary(
            "succeeded",
            "uploaded",
            "已传到所选手机相册",
            attempted=True,
            device=selected,
            uploaded_count=uploaded_count,
            total_count=len(paths),
            uploaded_files=uploaded_files,
        )
    except subprocess.TimeoutExpired:
        reason = "phone_upload_timeout"
    except Exception:
        reason = "phone_upload_failed"
    return _phone_transfer_summary(
        "failed",
        reason,
        "本地生成成功，传到手机失败",
        attempted=True,
        device=selected,
        total_count=len(paths),
    )


def _transfer_generated_media_to_phones(
    ctx,
    kind: str,
    files: list[dict],
    *,
    phone_snapshot: dict | None = None,
) -> dict:
    snapshot = phone_snapshot if isinstance(phone_snapshot, dict) else _configured_phone_snapshot(ctx)
    devices = snapshot.get("devices") if isinstance(snapshot.get("devices"), list) else []
    devices = [device for device in devices if isinstance(device, dict) and _text(device.get("id") or device.get("deviceId"))]
    if not devices:
        return {
            "status": "skipped",
            "reason": _text(snapshot.get("reason")) or "no_configured_phones",
            "message": "未配置手机，素材仅保存在本地",
            "attempted": False,
            "deviceCount": 0,
            "succeededDeviceCount": 0,
            "failedDeviceCount": 0,
            "uploadedCount": 0,
            "totalCount": 0,
            "deviceResults": [],
        }

    def transfer(device: dict) -> dict:
        return _transfer_generated_media_to_phone(
            ctx,
            kind,
            files,
            phone_snapshot={"device": device, "reason": ""},
        )

    max_workers = min(4, len(devices))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="loom-media-phone") as executor:
        device_results = list(executor.map(transfer, devices))

    succeeded_count = sum(1 for result in device_results if result.get("status") == "succeeded")
    failed_count = len(device_results) - succeeded_count
    uploaded_count = sum(max(0, int(result.get("uploadedCount") or 0)) for result in device_results)
    total_count = sum(max(0, int(result.get("totalCount") or 0)) for result in device_results)
    if failed_count == 0:
        status = "succeeded"
        reason = "uploaded_all"
        message = f"已传到 {succeeded_count} 台手机相册"
    else:
        status = "failed"
        failure_reasons = {
            _text(result.get("reason"))
            for result in device_results
            if result.get("status") != "succeeded" and _text(result.get("reason"))
        }
        reason = (
            "phone_upload_partial_failure"
            if succeeded_count
            else next(iter(failure_reasons))
            if len(failure_reasons) == 1
            else "phone_upload_failed"
        )
        message = f"已传到 {succeeded_count}/{len(device_results)} 台手机，{failed_count} 台失败"
    summary = {
        "status": status,
        "reason": reason,
        "message": message,
        "attempted": True,
        "deviceCount": len(device_results),
        "succeededDeviceCount": succeeded_count,
        "failedDeviceCount": failed_count,
        "uploadedCount": uploaded_count,
        "totalCount": total_count,
        "deviceResults": device_results,
    }
    if len(device_results) == 1:
        for key in ("deviceId", "deviceName", "album"):
            if device_results[0].get(key):
                summary[key] = device_results[0][key]
    return summary


def _async_media_job_result(
    ctx,
    kind: str,
    generated: dict,
    *,
    phone_snapshot: dict | None = None,
    compact: bool = True,
) -> dict:
    result = _compact_media_job_result(generated) if compact else dict(generated)
    if kind == "video":
        files = [{
            "path": generated.get("path"),
            "filename": generated.get("filename"),
            "mime": generated.get("mime"),
        }]
    else:
        files = generated.get("files") if isinstance(generated.get("files"), list) else []
    try:
        result["phoneTransfer"] = _transfer_generated_media_to_phones(
            ctx,
            kind,
            files,
            phone_snapshot=phone_snapshot,
        )
    except Exception:
        result["phoneTransfer"] = _phone_transfer_summary(
            "failed",
            "phone_upload_failed",
            "本地生成成功，传到手机失败",
            attempted=True,
            total_count=len(files),
        )
    return result


def _reveal_in_file_manager(path: str) -> None:
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def _media_file_response(asset, range_header: str) -> Response:
    file_size = asset.size
    headers = {"Accept-Ranges": "bytes", "Content-Disposition": f'inline; filename="{asset.filename}"'}
    if not range_header:
        return FileResponse(asset.path, media_type=asset.mime, filename=asset.filename, headers=headers)

    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip(), flags=re.IGNORECASE)
    if not match or (not match.group(1) and not match.group(2)):
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{file_size}"})

    try:
        if match.group(1):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else file_size - 1
        else:
            suffix = int(match.group(2))
            start = max(0, file_size - suffix)
            end = file_size - 1
    except ValueError:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{file_size}"})

    if start < 0 or start >= file_size or end < start:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{file_size}"})
    end = min(end, file_size - 1)
    length = end - start + 1
    with open(asset.path, "rb") as handle:
        handle.seek(start)
        content = handle.read(length)
    return Response(
        content=content,
        status_code=206,
        media_type=asset.mime,
        headers={
            **headers,
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
        },
    )


def _read_config(path: str) -> dict:
    payload = read_json(path, {})
    if not isinstance(payload, dict):
        return {}
    config = dict(payload)
    for key in ("apiKey", "dashKey"):
        if key in config:
            config[key] = unprotect_secret(config.get(key))
    provider_keys = config.get("providerApiKeys")
    if isinstance(provider_keys, dict):
        config["providerApiKeys"] = {
            _text(provider).lower(): unprotect_secret(value)
            for provider, value in provider_keys.items()
            if _text(provider)
        }
    return config


def _write_merged_config(
    path: str,
    incoming: dict,
    *,
    clear_keys: set[str] | None = None,
) -> dict:
    current = _read_config(path)
    merged = dict(current)
    for key, value in incoming.items():
        if key == "providerApiKeys" and isinstance(value, dict):
            provider_keys = (
                dict(merged.get("providerApiKeys"))
                if isinstance(merged.get("providerApiKeys"), dict)
                else {}
            )
            for provider, secret in value.items():
                if _text(provider) and _text(secret):
                    provider_keys[_text(provider).lower()] = _text(secret)
            merged[key] = provider_keys
            continue
        if key in {"apiKey", "dashKey"} and not _text(value):
            continue
        if value is None:
            continue
        merged[key] = value
    for key in clear_keys or set():
        merged.pop(key, None)
    stored = dict(merged)
    for key in ("apiKey", "dashKey"):
        if _text(stored.get(key)):
            stored[key] = protect_secret(stored[key])
    provider_keys = stored.get("providerApiKeys")
    if isinstance(provider_keys, dict):
        stored["providerApiKeys"] = {
            provider: protect_secret(secret)
            for provider, secret in provider_keys.items()
            if _text(secret)
        }
    write_json(path, stored)
    return merged


def _canonical_video_provider(value: object) -> str:
    provider = _text(value).lower() or "dashscope"
    if provider in {"pippit", "xyq", "xiaoyunque", "小云雀"}:
        return "pippit"
    return provider


def _video_provider_api_key(config: dict, provider_id: str) -> str:
    provider = _canonical_video_provider(provider_id)
    provider_keys = config.get("providerApiKeys")
    if isinstance(provider_keys, dict):
        secret = _text(provider_keys.get(provider))
        if secret:
            return secret
    saved_provider = _canonical_video_provider(config.get("providerId"))
    if saved_provider == provider:
        return _text(config.get("apiKey")) or _text(config.get("dashKey"))
    return ""


def _public_image_config(config: dict) -> dict:
    return {
        "baseUrl": _text(config.get("baseUrl")),
        "model": _text(config.get("model")) or IMAGE_MODEL,
        "size": _text(config.get("size")) or "1024x1024",
        "count": int(config.get("count") or 1),
        "hasApiKey": bool(_text(config.get("apiKey"))),
        "updatedAt": _text(config.get("updatedAt")),
    }


def _public_video_config(config: dict) -> dict:
    provider_id = _canonical_video_provider(config.get("providerId"))
    is_pippit = provider_id == "pippit"
    provider_keys = config.get("providerApiKeys")
    configured_providers = {
        _canonical_video_provider(provider)
        for provider, secret in provider_keys.items()
        if isinstance(provider_keys, dict) and _text(secret)
    } if isinstance(provider_keys, dict) else set()
    if _video_provider_api_key(config, provider_id):
        configured_providers.add(provider_id)
    return {
        "providerId": "pippit" if is_pippit else provider_id,
        "apiBase": _text(config.get("apiBase")) or ("https://xyq.jianying.com" if is_pippit else ""),
        "model": _text(config.get("model")) or ("pippit-video" if is_pippit else ""),
        "mode": _text(config.get("mode")) or "t2v",
        "resolution": _text(config.get("resolution")) or "720P",
        "duration": int(config.get("duration") or 5),
        "ratio": _text(config.get("ratio")) or "16:9",
        "hasApiKey": bool(_video_provider_api_key(config, provider_id)),
        "configuredProviders": sorted(configured_providers),
        "updatedAt": _text(config.get("updatedAt")),
    }


def _image_config_fallback(ctx) -> dict:
    return _read_config(ctx.paths.image_config)


def _video_config_fallback(ctx) -> dict:
    config = _read_config(ctx.paths.video_config)
    provider_id = _canonical_video_provider(config.get("providerId"))
    config["providerId"] = provider_id
    active_key = _video_provider_api_key(config, provider_id)
    config["apiKey"] = active_key
    config["dashKey"] = active_key
    if provider_id == "pippit":
        config["providerId"] = "pippit"
        config["apiBase"] = _text(config.get("apiBase")) or "https://xyq.jianying.com"
        config["model"] = _text(config.get("model")) or "pippit-video"
    return config


def _media_config_snapshot(ctx) -> dict:
    return {
        "image": _public_image_config(_image_config_fallback(ctx)),
        "video": _public_video_config(_video_config_fallback(ctx)),
    }


def _save_media_config(ctx, body: dict) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    image = body.get("image") if isinstance(body.get("image"), dict) else {}
    video = body.get("video") if isinstance(body.get("video"), dict) else {}

    if image:
        try:
            count = max(1, min(int(image.get("count", 1) or 1), 9))
        except (TypeError, ValueError):
            raise ValueError("图片数量必须是数字")
        _write_merged_config(ctx.paths.image_config, {
            "baseUrl": _text(image.get("baseUrl")),
            "apiKey": _text(image.get("apiKey")),
            "model": _text(image.get("model")) or IMAGE_MODEL,
            "size": _text(image.get("size")) or "1024x1024",
            "count": count,
            "updatedAt": now,
        })

    if video:
        try:
            duration = max(1, min(int(video.get("duration", 5) or 5), 30))
        except (TypeError, ValueError):
            raise ValueError("视频时长必须是数字")
        api_key = _text(video.get("apiKey")) or _text(video.get("dashKey"))
        provider_id = _canonical_video_provider(video.get("providerId"))
        is_pippit = provider_id == "pippit"
        current = _video_config_fallback(ctx)
        provider_keys = (
            dict(current.get("providerApiKeys"))
            if isinstance(current.get("providerApiKeys"), dict)
            else {}
        )
        current_provider = _canonical_video_provider(current.get("providerId"))
        current_key = _text(current.get("apiKey")) or _text(current.get("dashKey"))
        if current_key and not _text(provider_keys.get(current_provider)):
            provider_keys[current_provider] = current_key
        if api_key:
            provider_keys[provider_id] = api_key
        _write_merged_config(ctx.paths.video_config, {
            "providerId": provider_id,
            "apiBase": _text(video.get("apiBase")) or ("https://xyq.jianying.com" if is_pippit else ""),
            "providerApiKeys": provider_keys,
            "model": _text(video.get("model")) or ("pippit-video" if is_pippit else ""),
            "mode": _text(video.get("mode")) or "t2v",
            "resolution": _text(video.get("resolution")) or "720P",
            "duration": duration,
            "ratio": _text(video.get("ratio")) or "16:9",
            "updatedAt": now,
        }, clear_keys={"apiKey", "dashKey"})

    return _media_config_snapshot(ctx)


def _test_media_config(ctx, body: dict) -> dict:
    kind = _text(body.get("kind")) or "image"
    snapshot = _save_media_config(ctx, body) if ("image" in body or "video" in body) else _media_config_snapshot(ctx)
    target = snapshot["video"] if kind == "video" else snapshot["image"]
    missing = []
    if kind == "video":
        if not target.get("hasApiKey"):
            missing.append("API Key")
        if target.get("providerId") != "pippit" and not target.get("model"):
            missing.append("模型")
    else:
        if not target.get("baseUrl"):
            missing.append("Base URL")
        if not target.get("hasApiKey"):
            missing.append("API Key")
        if not target.get("model"):
            missing.append("模型")
    if missing:
        return {"ok": False, "message": f"请补全：{'、'.join(missing)}", "config": snapshot}
    return {"ok": True, "message": "配置已就绪，可提交生成任务验证", "config": snapshot}


def _image_generate_payload(ctx, body: dict) -> dict:
    client = ctx.get_image_client()
    gateway_profile = ctx.get_license_mgr().current_gateway_profile()
    saved_config = _image_config_fallback(ctx)
    base_url = (
        str(body.get("baseUrl", "") or "").strip()
        or str(saved_config.get("baseUrl") or "").strip()
        or str((gateway_profile or {}).get("imageBaseUrl") or "").strip()
        or str((gateway_profile or {}).get("baseUrl") or "").strip()
    )
    api_key = (
        str(body.get("apiKey", "") or "").strip()
        or str(saved_config.get("apiKey") or "").strip()
        or str((gateway_profile or {}).get("imageApiKey") or "").strip()
        or str((gateway_profile or {}).get("apiKey") or "").strip()
    )
    prompt = body.get("prompt", "")
    requested_ratio = _text(body.get("ratio"))
    size = _image_size_for_ratio(requested_ratio) or _text(body.get("size")) or _text(saved_config.get("size")) or "1024x1024"
    ratio = _image_ratio_for_size(size, requested_ratio)
    model = (
        str(body.get("model", "") or "").strip()
        or str(saved_config.get("model") or "").strip()
        or str((gateway_profile or {}).get("imageModel") or "").strip()
        or IMAGE_MODEL
    )
    edit_path = body.get("editImagePath")
    try:
        count = max(1, min(int(body.get("count", 1) or 1), 9))
    except (TypeError, ValueError):
        raise ImageApiError("图片数量必须是数字")

    if not base_url:
        diag = ctx.get_license_mgr().gateway_diagnosis()
        if not diag.get("ok") and diag.get("code") == "gateway_fields_missing":
            raise ImageApiError(str(diag["message"]))
        raise ImageApiError("模型服务地址不能为空")
    if not prompt:
        raise ImageApiError("提示词不能为空")

    temp_file: str | None = None
    if edit_path and edit_path.startswith("data:"):
        edit_path, temp_file = ctx.data_url_to_temp_file(edit_path)

    try:
        results = client.generate_many(base_url, api_key, prompt, size, count=count, edit_image_path=edit_path, model=model)
        images_b64 = [base64.b64encode(result).decode() for result in results]
        image_dir = os.path.join(ctx.paths.data_dir, "generated-images")
        os.makedirs(image_dir, exist_ok=True)
        files = []
        for index, image_bytes in enumerate(results):
            extension, mime = _image_storage_format(image_bytes)
            filename, save_path = _write_unique_media_file(
                image_dir,
                "loom-image",
                extension,
                image_bytes,
                index=index + 1 if len(results) > 1 else None,
            )
            files.append({
                "path": save_path,
                "directory": image_dir,
                "filename": filename,
                "size": len(image_bytes),
                "mime": mime,
            })
            _record_media(ctx, save_path, {
                "prompt": prompt,
                "mode": "i2i" if edit_path else "t2i",
                "ratio": ratio,
                "generationSize": _text(size),
                "model": _text(model),
                "source": _text(body.get("source")) or "ui",
                "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
        return {"images": images_b64, "files": files, "count": len(images_b64), "ratio": ratio, "size": _text(size)}
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except OSError:
                pass


def _video_generate_payload(ctx, body: dict, on_status=None, *, request_key: str = "") -> dict:
    client = ctx.get_video_client()
    saved_config = _video_config_fallback(ctx)
    provider_id = _canonical_video_provider(body.get("providerId") or saved_config.get("providerId"))
    saved_provider_id = _canonical_video_provider(saved_config.get("providerId"))
    same_saved_provider = provider_id == saved_provider_id
    gateway_profile = ctx.get_license_mgr().current_gateway_profile()
    api_base = str(body.get("apiBase", "") or "").strip()
    model = str(body.get("model", "") or "").strip()
    if provider_id == "pippit":
        api_base = api_base or "https://xyq.jianying.com"
        model = "pippit-video"
    else:
        api_base = (
            api_base
            or (str(saved_config.get("apiBase") or "").strip() if same_saved_provider else "")
            or str((gateway_profile or {}).get("videoBaseUrl") or "").strip()
            or str((gateway_profile or {}).get("baseUrl") or "").strip()
        )
        model = (
            model
            or (str(saved_config.get("model") or "").strip() if same_saved_provider else "")
            or str((gateway_profile or {}).get("videoDraftModel") or "").strip()
            or str((gateway_profile or {}).get("defaultModel") or "").strip()
        )
    if "agnes-video" in model.lower():
        provider_id = "agnes"
    explicit_key = (
        str(body.get("dashKey", "") or "").strip()
        or str(body.get("apiKey", "") or "").strip()
    )
    dash_key = explicit_key or _video_provider_api_key(saved_config, provider_id)
    if not dash_key and provider_id != "pippit":
        dash_key = (
            str((gateway_profile or {}).get("videoApiKey") or "").strip()
            or str((gateway_profile or {}).get("apiKey") or "").strip()
        )
    prompt = body.get("prompt", "")
    mode = body.get("mode") or saved_config.get("mode") or "t2v"
    resolution = body.get("resolution") or saved_config.get("resolution") or "720P"
    duration = body.get("duration") or saved_config.get("duration") or 5
    ratio = body.get("ratio") or saved_config.get("ratio") or "16:9"
    image_path = body.get("imagePath")
    continuation_message = _text(body.get("continuationMessage") or body.get("reply"))
    resume_existing = body.get("resumeExisting") is True
    request_key = _text(body.get("requestKey")) or _text(request_key)

    if not dash_key:
        diag = ctx.get_license_mgr().gateway_diagnosis()
        if not diag.get("ok") and diag.get("code") == "gateway_fields_missing":
            raise VideoApiError(str(diag["message"]))
        raise VideoApiError("视频服务密钥不能为空")
    if not prompt and not continuation_message and not resume_existing:
        raise VideoApiError("提示词不能为空")

    temp_file: str | None = None
    if image_path and not resume_existing and image_path.startswith("data:"):
        image_path, temp_file = ctx.data_url_to_temp_file(image_path)

    try:
        video_bytes = client.generate(
            dash_key,
            prompt,
            mode,
            resolution,
            duration,
            ratio,
            image_path,
            provider_id=provider_id,
            api_base=api_base,
            model=model,
            on_status=on_status,
            request_key=request_key,
            state_path=os.path.join(ctx.paths.data_dir, "pippit-video-runs.json"),
            continuation_message=continuation_message,
            resume_existing=resume_existing,
            poll_interval_ms=body.get("pollIntervalMs"),
            timeout_ms=body.get("timeoutMs"),
        )
        video_dir = os.path.join(ctx.paths.data_dir, "videos")
        os.makedirs(video_dir, exist_ok=True)
        extension, mime = _video_storage_format(video_bytes)
        filename, save_path = _write_unique_media_file(video_dir, "loom-video", extension, video_bytes)
        _record_media(ctx, save_path, {
            "prompt": prompt,
            "mode": _text(mode) or "t2v",
            "ratio": _text(ratio),
            "model": _text(model),
            "source": _text(body.get("source")) or "ui",
            "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "duration": duration,
            "resolution": _text(resolution),
            "providerId": _text(provider_id),
        })
        return {
            "video": base64.b64encode(video_bytes).decode(),
            "mime": mime,
            "size": len(video_bytes),
            "path": save_path,
            "directory": video_dir,
            "filename": filename,
        }
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except OSError:
                pass


def _image_generation_failure(error: Exception) -> dict:
    detail = str(error or "").strip()
    lowered = detail.lower()
    if "invalid url" in lowered or "http 404" in lowered or "not found" in lowered:
        code = "image_provider_endpoint_mismatch"
        message = "图片 Provider、Base URL 与模型接口不匹配，请检查后重试。"
        retryable = False
    elif "http 401" in lowered or "http 403" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        code = "image_provider_auth_failed"
        message = "图片服务鉴权失败，请检查 API Key 和账号状态。"
        retryable = False
    elif "http 429" in lowered or "rate limit" in lowered:
        code = "image_provider_rate_limited"
        message = "图片服务当前请求过多，请稍后再试。"
        retryable = True
    elif any(marker in lowered for marker in ("http 502", "http 504", "http 524", "gateway timeout")):
        code = "image_provider_gateway_timeout"
        message = "图片服务网关等待超时，结果可能稍后到达。请先查看素材库，未出现结果时再重试。"
        retryable = True
    elif "http 503" in lowered or "service busy" in lowered or "unavailable" in lowered:
        code = "image_provider_unavailable"
        message = "图片服务暂时不可用，请稍后重试。"
        retryable = True
    elif "可识别的图片" in detail or "incorrect padding" in lowered or "invalid base64" in lowered:
        code = "image_provider_invalid_result"
        message = "图片服务返回了无效文件，请检查模型接口配置后重试。"
        retryable = False
    elif "timeout" in lowered or "超时" in detail:
        code = "image_generation_timeout"
        message = "图片生成等待超时，请稍后重试。"
        retryable = True
    else:
        code = "image_generation_failed"
        message = "图片生成失败，请检查模型配置、参考图和提示词后重试。"
        retryable = True
    return {
        "success": False,
        "errorCode": code,
        "error": message,
        "retryable": retryable,
    }


def _log_image_generation_failure(ctx, job_id: str, error: Exception) -> None:
    safe_detail = redact_secret_text(str(error or "").strip())[:1200]
    append_log = getattr(ctx, "append_log", None)
    if callable(append_log):
        append_log(f"[Image] {job_id or 'sync'} failed: {safe_detail}\n")


def _video_generation_failure(error: Exception) -> dict:
    if isinstance(error, PippitResumeRequired):
        return {
            "success": False,
            "resumeRequired": True,
            "errorCode": "pippit_resume_required",
            "message": "小云雀原任务仍在服务端，请继续查询原任务",
            "error": str(error),
            "requestKey": error.request_key,
            "threadId": error.thread_id,
            "runId": error.run_id,
            "webThreadLink": error.web_thread_link,
            "retryable": True,
        }
    if isinstance(error, PippitManualRequired):
        return {
            "success": False,
            "manualRequired": True,
            "errorCode": "pippit_manual_required",
            "message": "小云雀需要补充信息后继续",
            "error": "小云雀正在等待您的确认或补充信息",
            "question": error.question,
            "requestKey": error.request_key,
            "threadId": error.thread_id,
            "runId": error.run_id,
            "webThreadLink": error.web_thread_link,
            "retryable": True,
        }
    detail = str(error or "").strip()
    lowered = detail.lower()
    if "重复计费" in detail or ("提交结果" in detail and "不确定" in detail):
        code = "pippit_submission_uncertain"
        message = "小云雀上次提交结果不确定，已停止自动重提。请打开小云雀任务页确认。"
        retryable = False
    elif "invalid url" in lowered or "http 404" in lowered or "not found" in lowered:
        code = "video_provider_endpoint_mismatch"
        message = "视频 Provider、Base URL 与模型接口不匹配，请检查后重试。"
        retryable = False
    elif "http 401" in lowered or "http 403" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        code = "video_provider_auth_failed"
        message = "视频服务鉴权失败，请检查 API Key 和账号状态。"
        retryable = False
    elif "http 429" in lowered or "rate limit" in lowered:
        code = "video_provider_rate_limited"
        message = "视频服务当前请求过多，请稍后再试。"
        retryable = True
    elif any(marker in lowered for marker in ("http 502", "http 503", "http 504", "http 524", "service busy", "unavailable")):
        code = "video_provider_unavailable"
        message = "视频服务暂时不可用，请稍后重试。"
        retryable = True
    elif "timeout" in lowered or "超时" in detail:
        code = "video_generation_timeout"
        message = "视频生成等待超时，任务可能仍在服务端处理中，请稍后重试。"
        retryable = True
    else:
        code = "video_generation_failed"
        message = "视频生成失败，请检查模型配置、参考图和提示词后重试。"
        retryable = True
    return {
        "success": False,
        "errorCode": code,
        "error": message,
        "retryable": retryable,
    }


def _log_video_generation_failure(ctx, job_id: str, error: Exception) -> None:
    safe_detail = redact_secret_text(str(error or "").strip())[:1200]
    append_log = getattr(ctx, "append_log", None)
    if callable(append_log):
        append_log(f"[Video] {job_id or 'sync'} failed: {safe_detail}\n")


def register_media_routes(app, ctx) -> None:
    @app.get("/api/media/assets")
    async def media_assets(request: Request, kind: str | None = None, cursor: str = "", limit: int = 20):
        if error := ctx.auth_error(request):
            return error
        try:
            return ctx.fastapi_json(_media_library(ctx).list_assets(kind, cursor, limit))
        except (MediaLibraryError, ValueError) as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.get("/api/media/assets/{asset_id}/content")
    async def media_asset_content(request: Request, asset_id: str):
        if error := ctx.auth_error(request):
            return error
        try:
            asset = _media_library(ctx).resolve(asset_id)
            return _media_file_response(asset, request.headers.get("range", ""))
        except MediaLibraryError:
            return ctx.fastapi_json({"error": "素材不存在或已被删除"}, 404)

    @app.post("/api/media/assets/{asset_id}/reveal")
    async def media_asset_reveal(request: Request, asset_id: str):
        if error := ctx.auth_error(request):
            return error
        try:
            asset = _media_library(ctx).resolve(asset_id)
            _reveal_in_file_manager(asset.path)
            return ctx.fastapi_json({"opened": True, "id": asset.asset_id})
        except MediaLibraryError:
            return ctx.fastapi_json({"error": "素材不存在或已被删除"}, 404)
        except OSError as exc:
            return ctx.fastapi_json({"error": f"无法打开素材位置：{exc}"}, 500)

    @app.post("/api/media/assets/{asset_id}/transfer")
    async def media_asset_transfer(request: Request, asset_id: str):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        requested_ids = body.get("deviceIds") if isinstance(body, dict) else None
        if not isinstance(requested_ids, list) or not requested_ids:
            return ctx.fastapi_json({"error": "请至少选择一台手机"}, 400)
        try:
            asset = _media_library(ctx).resolve(asset_id)
        except MediaLibraryError:
            return ctx.fastapi_json({"error": "素材不存在或已被删除"}, 404)
        phone_snapshot = _configured_phone_snapshot(ctx, requested_ids)
        missing_ids = phone_snapshot.get("missingDeviceIds") if isinstance(phone_snapshot.get("missingDeviceIds"), list) else []
        if missing_ids:
            return ctx.fastapi_json({"error": f"手机配置不存在：{', '.join(missing_ids)}"}, 400)
        if not phone_snapshot.get("devices"):
            return ctx.fastapi_json({"error": "未找到可用的手机配置"}, 400)

        files = [{"path": asset.path, "filename": asset.filename, "mime": asset.mime}]

        def target(job_id: str) -> dict:
            device_count = len(phone_snapshot["devices"])
            ctx.get_job_mgr().progress(job_id, f"正在传送到 {device_count} 台手机相册", "neutral", phase="phone-transfer")
            return _transfer_generated_media_to_phones(
                ctx,
                asset.kind,
                files,
                phone_snapshot=phone_snapshot,
            )

        job = ctx.get_job_mgr().submit_progress("media.transfer", "传输素材到手机", target)
        return ctx.fastapi_json({"jobId": job["id"], "job": job})

    @app.delete("/api/media/assets/{asset_id}")
    async def media_asset_delete(request: Request, asset_id: str):
        if error := ctx.auth_error(request):
            return error
        try:
            return ctx.fastapi_json(_media_library(ctx).delete(asset_id))
        except MediaLibraryError:
            return ctx.fastapi_json({"error": "素材不存在或已被删除"}, 404)
        except OSError as exc:
            return ctx.fastapi_json({"error": f"删除素材失败：{exc}"}, 500)

    @app.get("/api/media/config")
    async def media_config(request: Request):
        if error := ctx.auth_error(request):
            return error
        return ctx.fastapi_json({"config": _media_config_snapshot(ctx)})

    @app.post("/api/media/config")
    async def media_config_save(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        try:
            return ctx.fastapi_json({"config": _save_media_config(ctx, body)})
        except ValueError as exc:
            return ctx.fastapi_json({"error": str(exc)}, 400)

    @app.post("/api/media/test")
    async def media_config_test(request: Request):
        if error := ctx.auth_error(request):
            return error
        body = await ctx.body(request)
        try:
            return ctx.fastapi_json(_test_media_config(ctx, body))
        except ValueError as exc:
            return ctx.fastapi_json({"ok": False, "error": str(exc)}, 400)

    @app.post("/api/image/generate")
    async def image_generate(request: Request):
        if error := ctx.auth_error(request):
            return error
        if error := ctx.protected_error("/api/image/generate"):
            return error

        body = await ctx.body(request)
        phone_snapshot = _configured_phone_snapshot(ctx)
        try:
            generated = _image_generate_payload(ctx, body)
            return ctx.fastapi_json(
                _async_media_job_result(
                    ctx,
                    "image",
                    generated,
                    phone_snapshot=phone_snapshot,
                    compact=False,
                )
            )
        except (ImageApiError, ValueError) as exc:
            _log_image_generation_failure(ctx, "sync", exc)
            return ctx.fastapi_json(_image_generation_failure(exc), 500)

    @app.post("/api/image/generate/submit")
    async def image_generate_submit(request: Request):
        if error := ctx.auth_error(request):
            return error
        if error := ctx.protected_error("/api/image/generate"):
            return error

        body = await ctx.body(request)
        phone_snapshot = _configured_phone_snapshot(ctx)

        def target(job_id: str) -> dict:
            ctx.get_job_mgr().progress(job_id, "正在生成图片", "neutral")
            try:
                generated = _image_generate_payload(ctx, body)
            except (ImageApiError, ValueError) as exc:
                _log_image_generation_failure(ctx, job_id, exc)
                return _image_generation_failure(exc)
            ctx.get_job_mgr().progress(job_id, "正在传送到全部已配置手机相册", "neutral", phase="phone-transfer")
            return _async_media_job_result(
                ctx,
                "image",
                generated,
                phone_snapshot=phone_snapshot,
            )

        job = ctx.get_job_mgr().submit_progress("image", "图片生成", target)
        return ctx.fastapi_json({"jobId": job["id"], "job": job})

    @app.post("/api/video/generate")
    async def video_generate(request: Request):
        if error := ctx.auth_error(request):
            return error
        if error := ctx.protected_error("/api/video/generate"):
            return error

        body = await ctx.body(request)
        phone_snapshot = _configured_phone_snapshot(ctx)
        try:
            generated = _video_generate_payload(
                ctx,
                body,
                request_key=_text(body.get("requestKey")) or f"sync_{uuid.uuid4().hex}",
            )
            return ctx.fastapi_json(
                _async_media_job_result(
                    ctx,
                    "video",
                    generated,
                    phone_snapshot=phone_snapshot,
                    compact=False,
                )
            )
        except (VideoApiError, PippitManualRequired, PippitResumeRequired, ValueError) as exc:
            _log_video_generation_failure(ctx, "sync", exc)
            failure = _video_generation_failure(exc)
            return ctx.fastapi_json(
                failure,
                409 if failure.get("manualRequired") or failure.get("resumeRequired") else 500,
            )

    @app.post("/api/video/generate/submit")
    async def video_generate_submit(request: Request):
        if error := ctx.auth_error(request):
            return error
        if error := ctx.protected_error("/api/video/generate"):
            return error

        body = await ctx.body(request)
        phone_snapshot = _configured_phone_snapshot(ctx)

        def target(job_id: str) -> dict:
            ctx.get_job_mgr().progress(job_id, "正在提交视频任务", "neutral", phase="submitting")
            try:
                generated = _video_generate_payload(
                    ctx,
                    body,
                    on_status=lambda message, tone="neutral": ctx.get_job_mgr().progress(
                        job_id,
                        message,
                        tone,
                        phase="generating",
                    ),
                    request_key=_text(body.get("requestKey")) or job_id,
                )
            except (VideoApiError, PippitManualRequired, PippitResumeRequired, ValueError) as exc:
                _log_video_generation_failure(ctx, job_id, exc)
                return _video_generation_failure(exc)
            ctx.get_job_mgr().progress(job_id, "正在传送到全部已配置手机相册", "neutral", phase="phone-transfer")
            return _async_media_job_result(
                ctx,
                "video",
                generated,
                phone_snapshot=phone_snapshot,
            )

        job = ctx.get_job_mgr().submit_progress("video", "视频生成", target)
        return ctx.fastapi_json({"jobId": job["id"], "job": job})
