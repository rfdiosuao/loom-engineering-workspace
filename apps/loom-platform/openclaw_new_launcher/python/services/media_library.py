"""Persistent local media index backed by generated files on disk."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from core.storage import read_json, write_json


class MediaLibraryError(ValueError):
    """Raised when an asset reference is invalid or unsafe."""


@dataclass(frozen=True)
class MediaAsset:
    asset_id: str
    kind: str
    path: str
    filename: str
    mime: str
    size: int
    created_at: str
    metadata: dict[str, Any]


class MediaLibrary:
    _EXTENSIONS = {
        "image": {".png", ".jpg", ".jpeg", ".webp"},
        "video": {".mp4", ".webm", ".mov"},
    }
    _PUBLIC_METADATA = {
        "schema",
        "prompt",
        "mode",
        "ratio",
        "generationSize",
        "model",
        "source",
        "createdAt",
        "duration",
        "resolution",
        "providerId",
    }

    def __init__(self, data_dir: str):
        self.data_dir = os.path.realpath(data_dir)
        self.roots = {
            "image": os.path.realpath(os.path.join(self.data_dir, "generated-images")),
            "video": os.path.realpath(os.path.join(self.data_dir, "videos")),
        }

    def list_assets(self, kind: str | None = None, cursor: str = "", limit: int = 20) -> dict[str, Any]:
        kinds = self._normalize_kinds(kind)
        assets = sorted(
            self._scan(kinds),
            key=lambda item: (item.created_at, item.asset_id),
            reverse=True,
        )
        start = self._decode_cursor(cursor)
        page_size = max(1, min(int(limit or 20), 50))
        if start > len(assets):
            raise MediaLibraryError("素材分页游标已失效")
        page = assets[start : start + page_size]
        next_index = start + len(page)
        has_more = next_index < len(assets)
        return {
            "items": [self._public(item) for item in page],
            "nextCursor": self._encode_cursor(next_index) if has_more else "",
            "hasMore": has_more,
        }

    def resolve(self, asset_id: str) -> MediaAsset:
        requested = str(asset_id or "").strip()
        if not requested:
            raise MediaLibraryError("素材 ID 不能为空")
        for asset in self._scan(tuple(self.roots)):
            if asset.asset_id == requested:
                return asset
        raise MediaLibraryError("素材不存在或已被删除")

    def record(self, path: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        kind, safe_path = self._assert_allowed_file(path)
        normalized_metadata = dict(metadata or {})
        if "generationSize" not in normalized_metadata and normalized_metadata.get("size") is not None:
            normalized_metadata["generationSize"] = str(normalized_metadata["size"])
        payload = {
            "schema": "loom.media.asset.v1",
            **{
                key: value
                for key, value in normalized_metadata.items()
                if key in self._PUBLIC_METADATA and value is not None
            },
        }
        write_json(f"{safe_path}.json", payload)
        return self._public(self._asset_from_path(kind, safe_path))

    def delete(self, asset_id: str) -> dict[str, Any]:
        asset = self.resolve(asset_id)
        _, safe_path = self._assert_allowed_file(asset.path)
        os.unlink(safe_path)
        sidecar = f"{safe_path}.json"
        if os.path.isfile(sidecar) and not os.path.islink(sidecar):
            os.unlink(sidecar)
        return {"deleted": True, "id": asset.asset_id}

    def reveal(self, asset_id: str) -> dict[str, str]:
        asset = self.resolve(asset_id)
        return {"id": asset.asset_id, "path": asset.path, "directory": os.path.dirname(asset.path)}

    def _normalize_kinds(self, kind: str | None) -> tuple[str, ...]:
        if kind is None or not str(kind).strip():
            return tuple(self.roots)
        normalized = str(kind).strip().lower()
        if normalized not in self.roots:
            raise MediaLibraryError("素材类型仅支持 image 或 video")
        return (normalized,)

    def _scan(self, kinds: Iterable[str]) -> list[MediaAsset]:
        assets: list[MediaAsset] = []
        for kind in kinds:
            root = self.roots[kind]
            if not os.path.isdir(root):
                continue
            try:
                entries = list(os.scandir(root))
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
                if Path(entry.name).suffix.lower() not in self._EXTENSIONS[kind]:
                    continue
                try:
                    assets.append(self._asset_from_path(kind, entry.path))
                except (MediaLibraryError, OSError):
                    continue
        return assets

    def _assert_allowed_file(self, path: str) -> tuple[str, str]:
        candidate = os.path.abspath(os.path.normpath(str(path or "")))
        if not candidate or os.path.islink(candidate) or not os.path.isfile(candidate):
            raise MediaLibraryError("素材文件不存在或不是普通文件")
        real_candidate = os.path.realpath(candidate)
        for kind, root in self.roots.items():
            if os.path.commonpath((real_candidate, root)) != root:
                continue
            if os.path.dirname(real_candidate) != root:
                raise MediaLibraryError("素材文件必须位于素材库根目录")
            if Path(real_candidate).suffix.lower() not in self._EXTENSIONS[kind]:
                raise MediaLibraryError("不支持的素材文件格式")
            return kind, real_candidate
        raise MediaLibraryError("素材文件不在允许的本地素材库中")

    def _asset_from_path(self, kind: str, path: str) -> MediaAsset:
        verified_kind, safe_path = self._assert_allowed_file(path)
        if verified_kind != kind:
            raise MediaLibraryError("素材类型与目录不匹配")
        stat = os.stat(safe_path, follow_symlinks=False)
        relative = os.path.relpath(safe_path, self.roots[kind]).replace("\\", "/")
        asset_id = hashlib.sha256(f"{kind}:{relative.casefold()}".encode("utf-8")).hexdigest()[:24]
        mime = mimetypes.guess_type(safe_path)[0] or ("image/png" if kind == "image" else "video/mp4")
        metadata = read_json(f"{safe_path}.json", {})
        if not isinstance(metadata, dict):
            metadata = {}
        public_metadata = {
            key: value for key, value in metadata.items() if key in self._PUBLIC_METADATA
        }
        legacy_generation_size = metadata.get("size")
        if "generationSize" not in public_metadata and legacy_generation_size is not None:
            public_metadata["generationSize"] = str(legacy_generation_size)
        created = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc).isoformat()
        return MediaAsset(
            asset_id=asset_id,
            kind=kind,
            path=safe_path,
            filename=os.path.basename(safe_path),
            mime=mime,
            size=stat.st_size,
            created_at=str(metadata.get("createdAt") or created),
            metadata=public_metadata,
        )

    @staticmethod
    def _public(asset: MediaAsset) -> dict[str, Any]:
        return {
            "id": asset.asset_id,
            "kind": asset.kind,
            "path": asset.path,
            "filename": asset.filename,
            "mime": asset.mime,
            "size": asset.size,
            "createdAt": asset.created_at,
            **asset.metadata,
        }

    @staticmethod
    def _encode_cursor(index: int) -> str:
        payload = json.dumps({"offset": index}, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> int:
        if not cursor:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
            offset = int(payload["offset"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise MediaLibraryError("素材分页游标无效") from exc
        if offset < 0:
            raise MediaLibraryError("素材分页游标无效")
        return offset
