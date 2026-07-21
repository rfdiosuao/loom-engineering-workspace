"""Online activation and local license verification."""

from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import json
import os
import uuid
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.constants import LICENSE_SERVER_URL
from core.paths import AppPaths
from core.secret_store import unprotect_secret
from core.storage import read_json, write_json

LICENSE_PUBLIC_KEY_B64 = "njEIf3io24DAXRYVp37p2gIT5u2KZaWoGvBPD0JlTZ4="


class LicenseError(RuntimeError):
    def __init__(self, message: str, code: str = "LICENSE_ACTIVATION_FAILED"):
        super().__init__(message)
        self.code = code


class LicenseManager:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(LICENSE_PUBLIC_KEY_B64))

    @property
    def license_meta_file(self) -> str:
        return os.path.join(self.paths.data_dir, "license-meta.json")

    @staticmethod
    def activation_code_meta(code: str) -> dict[str, str]:
        normalized = "".join(ch for ch in str(code or "").strip().upper() if ch.isalnum())
        last8 = normalized[-8:]
        label = f"{last8[:4]}-{last8[4:]}" if len(last8) == 8 else last8
        return {
            "activationCodeLabel": label,
            "activationCodeLast8": last8,
        }

    def _with_license_meta(self, license_data: dict[str, Any]) -> dict[str, Any]:
        meta = read_json(self.license_meta_file, None)
        if isinstance(meta, dict):
            merged = dict(license_data)
            for key in ("activationCodeLabel", "activationCodeLast8"):
                if not merged.get(key) and meta.get(key):
                    merged[key] = meta[key]
            return merged
        return license_data

    def get_install_id(self) -> str:
        os.makedirs(self.paths.data_dir, exist_ok=True)
        if os.path.exists(self.paths.install_id_file):
            try:
                with open(self.paths.install_id_file, "r", encoding="utf-8") as file:
                    install_id = file.read().strip()
                if install_id:
                    return install_id
            except OSError:
                pass
        install_id = str(uuid.uuid4())
        with open(self.paths.install_id_file, "w", encoding="utf-8") as file:
            file.write(install_id)
        return install_id

    def _volume_serial(self) -> str | None:
        root = os.path.splitdrive(os.path.abspath(self.paths.base_path))[0] + "\\"
        try:
            volume_serial = ctypes.c_ulong()
            ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root),
                None,
                0,
                ctypes.byref(volume_serial),
                None,
                None,
                None,
                0,
            )
            return str(volume_serial.value)
        except Exception:
            return None

    @staticmethod
    def _hash_device_payload(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def device_id(self) -> str:
        serial = self._volume_serial()
        if serial:
            # Bind to the USB volume itself, not to the assigned drive letter.
            # Windows may assign a different drive letter after unplug/replug.
            raw = f"volume:{serial}|openclaw-launcher"
        else:
            # Fallback for non-Windows or environments where volume serial is unavailable.
            # The persisted installId still keeps the license tied to this portable package.
            raw = f"fallback:{uuid.getnode()}|openclaw-launcher"
        return self._hash_device_payload(raw)

    def legacy_device_id(self) -> str:
        """Previous format kept only for already activated packages."""
        root = os.path.splitdrive(os.path.abspath(self.paths.base_path))[0] + "\\"
        serial = self._volume_serial() or str(uuid.getnode())
        return self._hash_device_payload(f"{root}|{serial}|openclaw-launcher")

    def legacy_device_id_candidates(self) -> set[str]:
        """Accept old drive-letter-bound licenses after Windows remaps the USB letter."""
        serial = self._volume_serial() or str(uuid.getnode())
        return {
            self._hash_device_payload(f"{letter}:\\|{serial}|openclaw-launcher")
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        }

    def device_id_candidates(self) -> set[str]:
        return {self.device_id(), self.legacy_device_id(), *self.legacy_device_id_candidates()}

    def current_license(self) -> dict[str, Any] | None:
        license_data = read_json(self.paths.license_file, None)
        if isinstance(license_data, dict) and self.verify(license_data):
            return self._with_license_meta(license_data)
        return None

    def current_gateway_profile(self) -> dict[str, Any] | None:
        def build_profile(source: dict[str, Any], *, fallback_name: str) -> dict[str, Any] | None:
            gateway = source.get("gateway") if isinstance(source.get("gateway"), dict) else {}
            lease = source.get("lease") if isinstance(source.get("lease"), dict) else {}
            member = source.get("member") if isinstance(source.get("member"), dict) else {}
            base_url = self._pick_text(
                source.get("gatewayBaseUrl"),
                source.get("gatewayUrl"),
                source.get("baseUrl"),
                source.get("url"),
                gateway.get("gatewayBaseUrl"),
                gateway.get("baseUrl"),
                gateway.get("url"),
                lease.get("gatewayBaseUrl"),
                lease.get("gatewayUrl"),
                member.get("gatewayBaseUrl"),
                member.get("gatewayUrl"),
            ).rstrip("/")
            image_base_url = self._pick_text(
                source.get("gatewayImageBaseUrl"),
                source.get("imageBaseUrl"),
                source.get("imageUrl"),
                gateway.get("gatewayImageBaseUrl"),
                gateway.get("imageBaseUrl"),
                gateway.get("imageUrl"),
                lease.get("gatewayImageBaseUrl"),
                lease.get("imageBaseUrl"),
                member.get("gatewayImageBaseUrl"),
                member.get("imageBaseUrl"),
                base_url,
            ).rstrip("/")
            video_base_url = self._pick_text(
                source.get("gatewayVideoBaseUrl"),
                source.get("videoBaseUrl"),
                source.get("videoUrl"),
                gateway.get("gatewayVideoBaseUrl"),
                gateway.get("videoBaseUrl"),
                gateway.get("videoUrl"),
                lease.get("gatewayVideoBaseUrl"),
                lease.get("videoBaseUrl"),
                member.get("gatewayVideoBaseUrl"),
                member.get("videoBaseUrl"),
                base_url,
            ).rstrip("/")
            token = self._pick_text(
                source.get("gatewayAccessToken"),
                source.get("gatewayToken"),
                source.get("memberToken"),
                source.get("apiKey"),
                source.get("token"),
                gateway.get("gatewayAccessToken"),
                gateway.get("gatewayToken"),
                gateway.get("memberToken"),
                gateway.get("apiKey"),
                gateway.get("token"),
                gateway.get("accessToken"),
                lease.get("gatewayAccessToken"),
                lease.get("gatewayToken"),
                member.get("gatewayAccessToken"),
                member.get("gatewayToken"),
            )
            if not base_url or not token:
                return None
            image_token = self._pick_text(
                source.get("gatewayImageAccessToken"),
                source.get("gatewayImageToken"),
                source.get("imageApiKey"),
                source.get("imageToken"),
                gateway.get("gatewayImageAccessToken"),
                gateway.get("gatewayImageToken"),
                gateway.get("imageAccessToken"),
                gateway.get("imageToken"),
                gateway.get("imageApiKey"),
                lease.get("gatewayImageAccessToken"),
                lease.get("gatewayImageToken"),
                member.get("gatewayImageAccessToken"),
                member.get("gatewayImageToken"),
                token,
            )
            video_token = self._pick_text(
                source.get("gatewayVideoAccessToken"),
                source.get("gatewayVideoToken"),
                source.get("videoApiKey"),
                source.get("videoToken"),
                gateway.get("gatewayVideoAccessToken"),
                gateway.get("gatewayVideoToken"),
                gateway.get("videoAccessToken"),
                gateway.get("videoToken"),
                gateway.get("videoApiKey"),
                lease.get("gatewayVideoAccessToken"),
                lease.get("gatewayVideoToken"),
                member.get("gatewayVideoAccessToken"),
                member.get("gatewayVideoToken"),
                token,
            )
            models = self._gateway_model_ids(source)
            default_model = self._pick_text(
                source.get("gatewayDefaultModel"),
                source.get("defaultModel"),
                source.get("model"),
                gateway.get("gatewayDefaultModel"),
                gateway.get("defaultModel"),
                gateway.get("model"),
                lease.get("gatewayDefaultModel"),
                lease.get("defaultModel"),
                member.get("gatewayDefaultModel"),
                member.get("defaultModel"),
            )
            if not default_model and models:
                default_model = models[0]
            image_model = self._pick_text(
                source.get("gatewayImageModel"),
                source.get("imageModel"),
                source.get("image_model"),
                gateway.get("gatewayImageModel"),
                gateway.get("imageModel"),
                gateway.get("image_model"),
                lease.get("gatewayImageModel"),
                member.get("gatewayImageModel"),
            )
            video_draft_model = self._pick_text(
                source.get("gatewayVideoDraftModel"),
                source.get("videoDraftModel"),
                gateway.get("gatewayVideoDraftModel"),
                gateway.get("videoDraftModel"),
                lease.get("gatewayVideoDraftModel"),
                lease.get("videoDraftModel"),
                member.get("gatewayVideoDraftModel"),
                member.get("videoDraftModel"),
                source.get("gatewayVideoModel"),
                source.get("videoModel"),
                gateway.get("gatewayVideoModel"),
                gateway.get("videoModel"),
                lease.get("gatewayVideoModel"),
                member.get("gatewayVideoModel"),
            )
            features = source.get("features")
            return {
                "baseUrl": base_url,
                "imageBaseUrl": image_base_url,
                "videoBaseUrl": video_base_url,
                "apiKey": token,
                "imageApiKey": image_token or token,
                "videoApiKey": video_token or token,
                "defaultModel": default_model,
                "imageModel": image_model,
                "videoDraftModel": video_draft_model,
                "models": models,
                "features": features if isinstance(features, list) else (lease.get("features") if isinstance(lease.get("features"), list) else []),
                "plan": str(source.get("plan") or source.get("edition") or fallback_name or "").strip(),
                "memberId": str(source.get("memberId") or source.get("id") or "").strip(),
                "expiresAt": str(source.get("leaseExpiresAt") or source.get("expiresAt") or source.get("expires") or "").strip(),
                "quotas": source.get("quotas") if isinstance(source.get("quotas"), dict) else {},
                "usage": source.get("usage") if isinstance(source.get("usage"), dict) else {},
                "source": str(source.get("source") or fallback_name or "").strip(),
                "managedBy": str(source.get("managedBy") or source.get("source") or "").strip(),
            }

        member_session = read_json(self.paths.member_session_file, None)
        if isinstance(member_session, dict):
            profile = build_profile(member_session, fallback_name="member")
            if profile:
                return profile

        license_data = self.current_license()
        if isinstance(license_data, dict):
            profile = build_profile(license_data, fallback_name="license")
            if profile:
                return profile

        profiles = read_json(self.paths.auth_profiles, {"models": {"providers": {}}})
        models = profiles.get("models") if isinstance(profiles, dict) else {}
        providers = models.get("providers") if isinstance(models, dict) else {}
        if isinstance(providers, dict):
            primary = models.get("primary") if isinstance(models, dict) else None
            candidate = providers.get(primary) if primary else None
            if not isinstance(candidate, dict):
                candidate = next(
                    (
                        item
                        for item in providers.values()
                        if isinstance(item, dict) and str(item.get("authMode") or item.get("mode") or "").strip().lower() == "member"
                    ),
                    None,
                )
            if isinstance(candidate, dict):
                profile = build_profile(candidate, fallback_name="member-profile")
                if profile:
                    return profile
        return None

    def has_gateway_profile(self) -> bool:
        return self.current_gateway_profile() is not None

    def gateway_diagnosis(self) -> dict[str, Any]:
        """Explain why a gateway profile did or didn't resolve.

        ``current_gateway_profile`` silently returns ``None`` when the base URL
        or token can't be picked out of the (many) candidate field names. That
        turns a server-side field rename into an opaque "生成失败". This guard
        names the inspected source and the missing key fields so the failure is
        actionable instead of silent. It does not change resolution behavior.
        """
        profile = self.current_gateway_profile()
        if profile:
            return {"ok": True, "profile": profile}

        # NOTE: read_json(path, None) returns {} (not None) for a missing file,
        # so check for a non-empty dict to tell "no session" apart from "session
        # present but missing fields".
        member_session = read_json(self.paths.member_session_file, None)
        license_data = self.current_license()
        source: dict[str, Any] | None = None
        source_name = ""
        if isinstance(member_session, dict) and member_session:
            source, source_name = member_session, "member"
        elif isinstance(license_data, dict) and license_data:
            source, source_name = license_data, "license"

        if not isinstance(source, dict):
            return {
                "ok": False,
                "code": "no_gateway_source",
                "message": "未找到会员托管或授权网关配置，请先激活会员或导入授权后再使用生图/视频。",
                "source": None,
                "missing": ["baseUrl", "token"],
            }

        def _has(*keys: str) -> bool:
            nests = [source]
            for nested_key in ("gateway", "lease", "member"):
                nested = source.get(nested_key)
                if isinstance(nested, dict):
                    nests.append(nested)
            return any(
                str(nest.get(key) or "").strip()
                for nest in nests
                if isinstance(nest, dict)
                for key in keys
            )

        missing: list[str] = []
        if not _has("gatewayBaseUrl", "gatewayUrl", "baseUrl", "url"):
            missing.append("baseUrl")
        if not _has("gatewayAccessToken", "gatewayToken", "memberToken", "apiKey", "token"):
            missing.append("token")

        return {
            "ok": False,
            "code": "gateway_fields_missing",
            "message": (
                f"会员/授权网关配置不完整（来源：{source_name}），缺少必要字段："
                f"{', '.join(missing) or '未知'}。"
                "可能是授权服务端下发的字段名与客户端不一致，请联系服务方核对网关字段。"
            ),
            "source": source_name,
            "presentKeys": sorted(key for key in source.keys() if isinstance(key, str))[:40],
            "missing": missing,
        }

    def diagnose(self, include_gateway_profile: bool = True) -> dict[str, Any]:
        gateway_profile = self.current_gateway_profile() if include_gateway_profile else None
        if gateway_profile:
            expires = str(gateway_profile.get("expiresAt") or "").strip()
            if expires:
                try:
                    if date.fromisoformat(expires[:10]) < date.today():
                        return {
                            "ok": False,
                            "code": "expired",
                            "message": f"会员托管已过期：{expires}",
                            "detail": str(gateway_profile.get("baseUrl") or self.paths.member_session_file),
                            "license": self.current_license(),
                            "gatewayProfile": gateway_profile,
                        }
                except ValueError:
                    pass
            return {
                "ok": True,
                "code": "member",
                "message": f"会员托管已激活：{gateway_profile.get('memberId') or 'member'}",
                "detail": str(gateway_profile.get("baseUrl") or self.paths.member_session_file),
                "license": self.current_license(),
                "gatewayProfile": gateway_profile,
            }

        if not os.path.exists(self.paths.license_file):
            return {
                "ok": False,
                "code": "missing",
                "message": "未授权，尚未生成 license.json",
                "detail": self.paths.license_file,
                "license": None,
            }
        try:
            with open(self.paths.license_file, "r", encoding="utf-8") as file:
                license_data = json.load(file)
        except json.JSONDecodeError as error:
            return {
                "ok": False,
                "code": "corrupt",
                "message": "授权文件损坏，无法解析 JSON",
                "detail": f"{self.paths.license_file} ({error})",
                "license": None,
            }
        except OSError as error:
            return {
                "ok": False,
                "code": "unreadable",
                "message": "授权文件无法读取",
                "detail": f"{self.paths.license_file} ({error})",
                "license": None,
            }
        if not isinstance(license_data, dict):
            return {
                "ok": False,
                "code": "corrupt",
                "message": "授权文件损坏，根节点不是对象",
                "detail": self.paths.license_file,
                "license": None,
            }

        try:
            signature = base64.b64decode(license_data["signature"], validate=True)
            payload = dict(license_data)
            payload.pop("signature", None)
            self.public_key.verify(signature, self._canonical(payload))
        except KeyError:
            return {
                "ok": False,
                "code": "signature_missing",
                "message": "授权文件缺少签名字段",
                "detail": self.paths.license_file,
                "license": license_data,
            }
        except (binascii.Error, ValueError, InvalidSignature, TypeError) as error:
            return {
                "ok": False,
                "code": "signature_invalid",
                "message": "授权签名无效，文件可能被修改或不属于本产品",
                "detail": f"{self.paths.license_file} ({error.__class__.__name__})",
                "license": license_data,
            }

        install_id = license_data.get("installId")
        current_install_id = self.get_install_id()
        if install_id != current_install_id:
            return {
                "ok": False,
                "code": "install_id_mismatch",
                "message": "installId 不匹配，授权文件不属于当前启动器数据目录",
                "detail": f"license={install_id or '-'} current={current_install_id}",
                "license": license_data,
            }

        licensed_device = license_data.get("deviceId")
        device_candidates = self.device_id_candidates()
        if licensed_device and licensed_device not in device_candidates:
            return {
                "ok": False,
                "code": "device_id_mismatch",
                "message": "deviceId 不匹配，授权文件绑定的设备或 U 盘不是当前运行环境",
                "detail": f"license={licensed_device} current={', '.join(sorted(device_candidates))}",
                "license": license_data,
            }

        expires = license_data.get("expires")
        if expires:
            try:
                expires_date = date.fromisoformat(str(expires))
            except ValueError:
                return {
                    "ok": False,
                    "code": "corrupt",
                    "message": "授权文件损坏，expires 日期格式无效",
                    "detail": f"expires={expires}",
                    "license": license_data,
                }
            if expires_date < date.today():
                return {
                    "ok": False,
                    "code": "expired",
                    "message": f"授权已过期：{expires}",
                    "detail": self.paths.license_file,
                    "license": license_data,
                }

        return {
            "ok": True,
            "code": "ok",
            "message": f"已授权：{license_data.get('licensee', 'OpenClaw Customer')}",
            "detail": self.paths.license_file,
            "license": license_data,
        }

    def is_authorized(self, feature: str | None = None) -> bool:
        license_data = self.current_license()
        if isinstance(license_data, dict):
            if feature and feature not in license_data.get("features", []):
                return False
            return True
        return False

    def verify(self, license_data: dict[str, Any]) -> bool:
        try:
            signature = base64.b64decode(license_data["signature"], validate=True)
            payload = dict(license_data)
            payload.pop("signature", None)
            self.public_key.verify(signature, self._canonical(payload))
            if payload.get("installId") != self.get_install_id():
                return False
            licensed_device = payload.get("deviceId")
            if licensed_device and licensed_device not in self.device_id_candidates():
                return False
            expires = payload.get("expires")
            if expires and date.fromisoformat(expires) < date.today():
                return False
            return True
        except (KeyError, binascii.Error, ValueError, InvalidSignature, TypeError):
            return False

    def activate(self, code: str) -> dict[str, Any]:
        code = code.strip().upper()
        if not code:
            raise LicenseError("请输入授权码")
        payload = {
            "code": code,
            "installId": self.get_install_id(),
            "deviceId": self.device_id(),
            "appVersion": "desktop",
        }
        request_body = json.dumps(payload).encode("utf-8")
        data: dict[str, Any] | None = None
        last_error: Exception | None = None
        for endpoint in ("/api/member/activate", "/activate"):
            request = urllib.request.Request(
                f"{LICENSE_SERVER_URL.rstrip('/')}{endpoint}",
                data=request_body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "LOOM-Desktop/2.0",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code in (404, 405):
                    continue
                message, code = self._read_error(error)
                raise LicenseError(message, code) from error
            except Exception as error:
                last_error = error
                continue
        if not isinstance(data, dict):
            if isinstance(last_error, urllib.error.HTTPError):
                message, code = self._read_error(last_error)
                raise LicenseError(message, code) from last_error
            raise LicenseError(f"无法连接授权服务器：{last_error}") from last_error
        license_data = data.get("license") if isinstance(data.get("license"), dict) else data.get("member")
        if not isinstance(license_data, dict) or not self.verify(license_data):
            raise LicenseError("授权服务器返回的许可证无效")
        write_json(self.paths.license_file, license_data)
        code_meta = self.activation_code_meta(code)
        if code_meta.get("activationCodeLast8"):
            write_json(self.license_meta_file, code_meta)
        theme_data = data.get("theme")
        if isinstance(theme_data, dict) and theme_data.get("colors"):
            write_json(self.paths.theme_json, theme_data)
        return self._with_license_meta(license_data)

    def client_config(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{LICENSE_SERVER_URL.rstrip('/')}/api/client/config",
            headers={"User-Agent": "LOOM-Desktop/2.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def get_brand_config(self) -> dict[str, Any] | None:
        license_data = self.current_license()
        if not isinstance(license_data, dict):
            return None
        brand_config = license_data.get("brandConfig") or license_data.get("theme")
        if isinstance(brand_config, dict):
            return brand_config
        return None

    def _canonical(self, payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _pick_text(*values: Any) -> str:
        for value in values:
            if isinstance(value, str):
                clean = value.strip()
                if clean:
                    return clean
            if isinstance(value, dict):
                try:
                    clean = unprotect_secret(value).strip()
                except Exception:
                    clean = ""
                if clean:
                    return clean
        return ""

    def _gateway_model_ids(self, license_data: dict[str, Any]) -> list[str]:
        candidates: list[Any] = [
            license_data.get("gatewayModels"),
            license_data.get("models"),
            license_data.get("modelIds"),
            license_data.get("model_ids"),
        ]
        for nested_key in ("gateway", "lease", "member"):
            nested = license_data.get(nested_key)
            if isinstance(nested, dict):
                candidates.extend([
                    nested.get("gatewayModels"),
                    nested.get("models"),
                    nested.get("modelIds"),
                    nested.get("model_ids"),
                ])
        raw_models = next((item for item in candidates if isinstance(item, list) and item), [])
        model_ids: list[str] = []
        for item in raw_models:
            model_id = item.get("id") if isinstance(item, dict) else item
            if isinstance(model_id, str):
                clean = model_id.strip()
                if clean and clean not in model_ids:
                    model_ids.append(clean)
        return model_ids
    def _read_error(self, error: urllib.error.HTTPError) -> tuple[str, str]:
        try:
            data = json.loads(error.read().decode("utf-8"))
            return (
                str(data.get("error") or f"授权失败：HTTP {error.code}"),
                str(data.get("code") or "LICENSE_ACTIVATION_FAILED"),
            )
        except Exception:
            return f"授权失败：HTTP {error.code}", "LICENSE_ACTIVATION_FAILED"
