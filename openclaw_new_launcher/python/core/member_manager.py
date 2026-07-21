"""Member subscription session management for the launcher."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any

from core.constants import LICENSE_SERVER_URL
from core.license_manager import LicenseManager
from core.paths import AppPaths
from core.storage import read_json, write_json


class MemberError(RuntimeError):
    pass


class MemberManager:
    """Manage the cached member lease and the remote member service."""

    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.license_mgr = LicenseManager(paths)
        self.service_base_url = LICENSE_SERVER_URL.rstrip("/")

    @property
    def session_path(self) -> str:
        return self.paths.member_session_file

    def _endpoint_candidates(self, action: str) -> list[str]:
        action = action.strip("/")
        base = self.service_base_url
        return [
            f"{base}/member/{action}",
            f"{base}/api/member/{action}",
            f"{base}/api/v1/member/{action}",
        ]

    @staticmethod
    def _request_body(payload: dict[str, Any] | None) -> bytes | None:
        if payload is None:
            return None
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _read_http_error(error: urllib.error.HTTPError) -> str:
        try:
            data = json.loads(error.read().decode("utf-8"))
            if isinstance(data, dict):
                if isinstance(data.get("error"), dict):
                    message = data["error"].get("message")
                    if isinstance(message, str) and message:
                        return message
                message = data.get("error") or data.get("message")
                if isinstance(message, str) and message:
                    return message
        except Exception:
            pass
        return f"HTTP {error.code}"

    def _request_json(self, action: str, payload: dict[str, Any] | None = None, *, method: str = "POST", timeout: int = 20) -> dict[str, Any]:
        errors: list[str] = []
        for url in self._endpoint_candidates(action):
            request = urllib.request.Request(
                url,
                data=self._request_body(payload),
                method=method,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "LOOM-Launcher/2.0",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    return data if isinstance(data, dict) else {"data": data}
            except urllib.error.HTTPError as error:
                if error.code in (404, 405):
                    errors.append(f"{url} -> HTTP {error.code}")
                    continue
                raise MemberError(self._read_http_error(error)) from error
            except Exception as error:
                errors.append(f"{url} -> {error}")
                continue
        raise MemberError("无法连接会员服务：" + ("; ".join(errors) if errors else "无可用接口"))

    @staticmethod
    def _feature_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            normalized = value.replace("，", ",").replace(";", ",")
            return [item.strip() for item in normalized.split(",") if item.strip()]
        return []

    @staticmethod
    def _pick_text(*values: Any) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text and text.lower() != "none":
                return text
        return ""

    def _normalize_session(self, data: dict[str, Any]) -> dict[str, Any]:
        member = data.get("member") if isinstance(data.get("member"), dict) else {}
        lease = data.get("lease") if isinstance(data.get("lease"), dict) else {}
        gateway = data.get("gateway") if isinstance(data.get("gateway"), dict) else {}
        license_data = data.get("license") if isinstance(data.get("license"), dict) else {}
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}

        feature_source: Any = data.get("features")
        if not feature_source and isinstance(license_data, dict):
            feature_source = license_data.get("features")
        if not feature_source and isinstance(member, dict):
            feature_source = member.get("features")
        if not feature_source and isinstance(lease, dict):
            feature_source = lease.get("features")

        session: dict[str, Any] = {
            "memberId": self._pick_text(
                data.get("memberId"),
                license_data.get("memberId") if isinstance(license_data, dict) else "",
                member.get("memberId") if isinstance(member, dict) else "",
                lease.get("memberId") if isinstance(lease, dict) else "",
                data.get("id"),
            ),
            "memberName": self._pick_text(
                data.get("memberName"),
                license_data.get("licensee") if isinstance(license_data, dict) else "",
                member.get("memberName") if isinstance(member, dict) else "",
                member.get("name") if isinstance(member, dict) else "",
                data.get("licensee"),
            ),
            "plan": self._pick_text(
                data.get("plan"),
                license_data.get("plan") if isinstance(license_data, dict) else "",
                member.get("plan") if isinstance(member, dict) else "",
                lease.get("plan") if isinstance(lease, dict) else "",
                "monthly",
            ),
            "status": self._pick_text(
                data.get("status"),
                member.get("status") if isinstance(member, dict) else "",
                lease.get("status") if isinstance(lease, dict) else "",
                "active",
            ),
            "expiresAt": self._pick_text(
                data.get("expiresAt"),
                license_data.get("expiresAt") if isinstance(license_data, dict) else "",
                license_data.get("expires") if isinstance(license_data, dict) else "",
                member.get("expiresAt") if isinstance(member, dict) else "",
                lease.get("expiresAt") if isinstance(lease, dict) else "",
            ) or None,
            "leaseExpiresAt": self._pick_text(
                data.get("leaseExpiresAt"),
                license_data.get("leaseExpiresAt") if isinstance(license_data, dict) else "",
                member.get("leaseExpiresAt") if isinstance(member, dict) else "",
                lease.get("leaseExpiresAt") if isinstance(lease, dict) else "",
            ) or None,
            "gatewayBaseUrl": self._pick_text(
                data.get("gatewayBaseUrl"),
                license_data.get("gatewayBaseUrl") if isinstance(license_data, dict) else "",
                license_data.get("gatewayUrl") if isinstance(license_data, dict) else "",
                gateway.get("baseUrl") if isinstance(gateway, dict) else "",
                gateway.get("url") if isinstance(gateway, dict) else "",
                member.get("gatewayBaseUrl") if isinstance(member, dict) else "",
                lease.get("gatewayBaseUrl") if isinstance(lease, dict) else "",
                data.get("baseUrl"),
            ) or None,
            "gatewayImageBaseUrl": self._pick_text(
                data.get("gatewayImageBaseUrl"),
                license_data.get("gatewayImageBaseUrl") if isinstance(license_data, dict) else "",
                member.get("gatewayImageBaseUrl") if isinstance(member, dict) else "",
                lease.get("gatewayImageBaseUrl") if isinstance(lease, dict) else "",
                gateway.get("imageBaseUrl") if isinstance(gateway, dict) else "",
                gateway.get("baseUrl") if isinstance(gateway, dict) else "",
            ) or None,
            "gatewayVideoBaseUrl": self._pick_text(
                data.get("gatewayVideoBaseUrl"),
                license_data.get("gatewayVideoBaseUrl") if isinstance(license_data, dict) else "",
                member.get("gatewayVideoBaseUrl") if isinstance(member, dict) else "",
                lease.get("gatewayVideoBaseUrl") if isinstance(lease, dict) else "",
                gateway.get("videoBaseUrl") if isinstance(gateway, dict) else "",
                gateway.get("baseUrl") if isinstance(gateway, dict) else "",
            ) or None,
            "gatewayDefaultModel": self._pick_text(
                data.get("gatewayDefaultModel"),
                license_data.get("gatewayDefaultModel") if isinstance(license_data, dict) else "",
                member.get("gatewayDefaultModel") if isinstance(member, dict) else "",
                gateway.get("defaultModel") if isinstance(gateway, dict) else "",
            ) or None,
            "gatewayImageModel": self._pick_text(
                data.get("gatewayImageModel"),
                license_data.get("gatewayImageModel") if isinstance(license_data, dict) else "",
                member.get("gatewayImageModel") if isinstance(member, dict) else "",
                gateway.get("imageModel") if isinstance(gateway, dict) else "",
            ) or None,
            "gatewayVideoDraftModel": self._pick_text(
                data.get("gatewayVideoDraftModel"),
                license_data.get("gatewayVideoDraftModel") if isinstance(license_data, dict) else "",
                member.get("gatewayVideoDraftModel") if isinstance(member, dict) else "",
                gateway.get("videoDraftModel") if isinstance(gateway, dict) else "",
                data.get("gatewayVideoModel"),
                license_data.get("gatewayVideoModel") if isinstance(license_data, dict) else "",
                member.get("gatewayVideoModel") if isinstance(member, dict) else "",
                gateway.get("videoModel") if isinstance(gateway, dict) else "",
            ) or None,
            "gatewayImageAccessToken": self._pick_text(
                data.get("gatewayImageAccessToken"),
                data.get("gatewayImageToken"),
                license_data.get("gatewayImageAccessToken") if isinstance(license_data, dict) else "",
                license_data.get("gatewayImageToken") if isinstance(license_data, dict) else "",
                member.get("gatewayImageAccessToken") if isinstance(member, dict) else "",
                member.get("gatewayImageToken") if isinstance(member, dict) else "",
                gateway.get("imageAccessToken") if isinstance(gateway, dict) else "",
                gateway.get("imageToken") if isinstance(gateway, dict) else "",
            ) or None,
            "gatewayVideoAccessToken": self._pick_text(
                data.get("gatewayVideoAccessToken"),
                data.get("gatewayVideoToken"),
                license_data.get("gatewayVideoAccessToken") if isinstance(license_data, dict) else "",
                license_data.get("gatewayVideoToken") if isinstance(license_data, dict) else "",
                member.get("gatewayVideoAccessToken") if isinstance(member, dict) else "",
                member.get("gatewayVideoToken") if isinstance(member, dict) else "",
                gateway.get("videoAccessToken") if isinstance(gateway, dict) else "",
                gateway.get("videoToken") if isinstance(gateway, dict) else "",
            ) or None,
            "gatewayModels": (
                license_data.get("gatewayModels")
                if isinstance(license_data, dict) and isinstance(license_data.get("gatewayModels"), list)
                else (
                    member.get("gatewayModels")
                    if isinstance(member, dict) and isinstance(member.get("gatewayModels"), list)
                    else (
                        gateway.get("models")
                        if isinstance(gateway, dict) and isinstance(gateway.get("models"), list)
                        else []
                    )
                )
            ),
            "memberToken": self._pick_text(
                data.get("memberToken"),
                data.get("token"),
                data.get("accessToken"),
                license_data.get("gatewayAccessToken") if isinstance(license_data, dict) else "",
                license_data.get("gatewayToken") if isinstance(license_data, dict) else "",
                license_data.get("memberToken") if isinstance(license_data, dict) else "",
                member.get("token") if isinstance(member, dict) else "",
                member.get("memberToken") if isinstance(member, dict) else "",
                member.get("gatewayAccessToken") if isinstance(member, dict) else "",
                member.get("gatewayToken") if isinstance(member, dict) else "",
                lease.get("token") if isinstance(lease, dict) else "",
                lease.get("memberToken") if isinstance(lease, dict) else "",
            ) or None,
            "features": self._feature_list(feature_source),
            "usage": usage if isinstance(usage, dict) else {},
            "lease": lease if isinstance(lease, dict) else (member if isinstance(member, dict) else {}),
            "gateway": gateway if isinstance(gateway, dict) else {},
            "updatedAt": datetime.now().isoformat(timespec="seconds"),
            "source": self._pick_text(data.get("source"), member.get("source") if isinstance(member, dict) else "", "server"),
        }

        if not session["memberId"]:
            session["memberId"] = self._pick_text(
                member.get("id") if isinstance(member, dict) else "",
                lease.get("id") if isinstance(lease, dict) else "",
            )
        if not session["memberName"]:
            session["memberName"] = session["memberId"] or "会员"

        session.pop("gatewayVideoModel", None)
        if isinstance(session.get("gateway"), dict):
            session["gateway"].pop("gatewayVideoModel", None)
            session["gateway"].pop("videoModel", None)
            if session.get("gatewayVideoDraftModel"):
                session["gateway"]["videoDraftModel"] = session["gatewayVideoDraftModel"]

        return session

    def _read_session_file(self) -> dict[str, Any] | None:
        session = read_json(self.session_path, None)
        return session if isinstance(session, dict) else None

    def _read_profile_session(self) -> dict[str, Any] | None:
        profiles = read_json(self.paths.auth_profiles, {"models": {"providers": {}}})
        models = profiles.get("models") if isinstance(profiles, dict) else {}
        providers = models.get("providers") if isinstance(models, dict) else {}
        if not isinstance(providers, dict) or not providers:
            return None

        primary = models.get("primary") if isinstance(models, dict) else None
        provider = providers.get(primary) if primary else None
        if not isinstance(provider, dict):
            provider = next(
                (
                    item
                    for item in providers.values()
                    if isinstance(item, dict) and str(item.get("authMode") or item.get("mode") or "").strip().lower() == "member"
                ),
                None,
            )
        if not isinstance(provider, dict):
            return None

        auth_mode = str(provider.get("authMode") or provider.get("mode") or "").strip().lower()
        if auth_mode != "member":
            return None

        gateway_base = self._pick_text(provider.get("gatewayBaseUrl"), provider.get("baseUrl"), provider.get("url"))
        gateway_image_base = self._pick_text(provider.get("gatewayImageBaseUrl"), provider.get("imageBaseUrl"), provider.get("imageUrl"), gateway_base)
        gateway_video_base = self._pick_text(provider.get("gatewayVideoBaseUrl"), provider.get("videoBaseUrl"), provider.get("videoUrl"), gateway_base)
        token = self._pick_text(provider.get("memberToken"), provider.get("apiKey"), provider.get("token"))
        if not gateway_base and not token:
            return None
        gateway_default_model = self._pick_text(provider.get("gatewayDefaultModel"), provider.get("defaultModel"), provider.get("model"))
        gateway_image_model = self._pick_text(provider.get("gatewayImageModel"), provider.get("imageModel"), provider.get("image_model"))
        gateway_video_draft_model = self._pick_text(
            provider.get("gatewayVideoDraftModel"),
            provider.get("videoDraftModel"),
            provider.get("gatewayVideoModel"),
            provider.get("videoModel"),
            provider.get("video_model"),
        )
        gateway_models = provider.get("gatewayModels") if isinstance(provider.get("gatewayModels"), list) else provider.get("models")
        if not isinstance(gateway_models, list):
            gateway_models = []

        return self._normalize_session(
            {
                "memberId": provider.get("memberId") or provider.get("id") or "member",
                "memberName": provider.get("name") or "会员托管",
                "plan": provider.get("plan") or "monthly",
                "status": provider.get("status") or "active",
                "expiresAt": provider.get("expiresAt"),
                "leaseExpiresAt": provider.get("leaseExpiresAt"),
                "gatewayBaseUrl": gateway_base,
                "gatewayImageBaseUrl": gateway_image_base,
                "gatewayVideoBaseUrl": gateway_video_base,
                "memberToken": token,
                "gatewayImageAccessToken": self._pick_text(provider.get("gatewayImageAccessToken"), provider.get("gatewayImageToken")),
                "gatewayVideoAccessToken": self._pick_text(provider.get("gatewayVideoAccessToken"), provider.get("gatewayVideoToken")),
                "gatewayDefaultModel": gateway_default_model,
                "gatewayImageModel": gateway_image_model,
                "gatewayVideoDraftModel": gateway_video_draft_model,
                "gatewayModels": gateway_models,
                "features": provider.get("features") or [],
                "usage": provider.get("usage") or {},
                "lease": provider.get("lease") if isinstance(provider.get("lease"), dict) else {},
                "gateway": {
                    "baseUrl": gateway_base,
                    "imageBaseUrl": gateway_image_base,
                    "videoBaseUrl": gateway_video_base,
                    "accessToken": token,
                    "imageAccessToken": self._pick_text(provider.get("gatewayImageAccessToken"), provider.get("gatewayImageToken"), token),
                    "videoAccessToken": self._pick_text(provider.get("gatewayVideoAccessToken"), provider.get("gatewayVideoToken"), token),
                    "defaultModel": gateway_default_model,
                    "imageModel": gateway_image_model,
                    "videoDraftModel": gateway_video_draft_model,
                    "models": gateway_models,
                },
                "source": "profiles",
            }
        )

    def _read_current_session(self) -> dict[str, Any] | None:
        session = self._read_session_file()
        if session:
            return self._normalize_session(session)
        return self._read_profile_session()

    def _write_session(self, session: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.session_path), exist_ok=True)
        write_json(self.session_path, session)

    def current(self) -> dict[str, Any] | None:
        return self._read_current_session()

    def current_lease(self) -> dict[str, Any] | None:
        session = self.current()
        if not session:
            return None
        lease = session.get("lease")
        return lease if isinstance(lease, dict) and lease else session

    def current_usage(self) -> dict[str, Any] | None:
        session = self.current()
        if not session:
            return None
        usage = session.get("usage")
        return usage if isinstance(usage, dict) and usage else None

    def current_gateway_base_url(self) -> str:
        session = self.current()
        if not session:
            return ""
        return str(session.get("gatewayBaseUrl") or "").strip()

    def current_member_token(self) -> str:
        session = self.current()
        if not session:
            return ""
        return str(session.get("memberToken") or "").strip()

    def _expires_on_or_before_today(self, value: Any) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        try:
            return date.fromisoformat(text[:10]) < date.today()
        except Exception:
            return False

    def is_authorized(self, feature: str | None = None) -> bool:
        session = self.current()
        if not session:
            return False
        if self._expires_on_or_before_today(session.get("leaseExpiresAt") or session.get("expiresAt")):
            return False
        if feature:
            features = session.get("features")
            if isinstance(features, list) and feature in [str(item).strip() for item in features]:
                return True
            lease = session.get("lease") if isinstance(session.get("lease"), dict) else {}
            lease_features = lease.get("features") if isinstance(lease, dict) else []
            if isinstance(lease_features, list) and feature in [str(item).strip() for item in lease_features]:
                return True
            return False
        return True

    def activate(self, code: str) -> dict[str, Any]:
        code = code.strip()
        if not code:
            raise MemberError("请输入会员码")
        payload = {
            "code": code,
            "installId": self.license_mgr.get_install_id(),
            "deviceId": self.license_mgr.device_id(),
            "appVersion": "desktop",
        }
        data = self._request_json("activate", payload)
        session = self._normalize_session(data)
        if isinstance(data.get("theme"), dict) and data["theme"].get("colors"):
            write_json(self.paths.theme_json, data["theme"])
        self._write_session(session)
        return session

    def refresh(self) -> dict[str, Any]:
        session = self.current()
        if not session:
            raise MemberError("当前没有会员会话，请先激活")
        payload = {
            "memberId": session.get("memberId"),
            "memberToken": session.get("memberToken"),
            "leaseToken": session.get("memberToken"),
            "gatewayBaseUrl": session.get("gatewayBaseUrl"),
            "installId": self.license_mgr.get_install_id(),
            "deviceId": self.license_mgr.device_id(),
        }
        data = self._request_json("refresh", payload)
        merged = dict(session)
        merged.update(self._normalize_session(data))
        self._write_session(merged)
        return merged

    def usage(self) -> dict[str, Any]:
        session = self.current()
        if not session:
            raise MemberError("当前没有会员会话，请先激活")
        payload = {
            "memberId": session.get("memberId"),
            "memberToken": session.get("memberToken"),
            "gatewayBaseUrl": session.get("gatewayBaseUrl"),
        }
        try:
            data = self._request_json("usage", payload)
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else data
            if isinstance(usage, dict):
                merged = dict(session)
                merged["usage"] = usage
                merged["updatedAt"] = datetime.now().isoformat(timespec="seconds")
                self._write_session(merged)
                return usage
        except MemberError:
            pass
        usage = session.get("usage")
        return usage if isinstance(usage, dict) else {}

    def diagnose(self) -> dict[str, Any]:
        session = self.current()
        if not session:
            return {
                "ok": False,
                "code": "missing",
                "message": "未配置会员会话",
                "detail": self.session_path,
                "session": None,
                "service": {
                    "baseUrl": self.service_base_url,
                    "reachable": False,
                    "detail": "尚未激活会员",
                },
                "gateway": {
                    "configured": False,
                    "baseUrl": "",
                    "tokenAvailable": False,
                    "detail": "尚未配置会员网关",
                },
            }

        expires = session.get("leaseExpiresAt") or session.get("expiresAt")
        expired = self._expires_on_or_before_today(expires)
        gateway_base = str(session.get("gatewayBaseUrl") or "").strip()
        token = str(session.get("memberToken") or "").strip()
        service_detail = "未检测"
        service_reachable = False
        if token or session.get("memberId"):
            try:
                probe = self._request_json(
                    "current",
                    {
                        "memberId": session.get("memberId"),
                        "memberToken": token,
                        "leaseToken": token,
                    },
                    method="POST",
                    timeout=8,
                )
                service_reachable = True
                service_detail = str(probe.get("message") or probe.get("status") or "可连接")
            except MemberError as error:
                service_detail = str(error)

        gateway_ok = bool(gateway_base and token)
        ok = bool(not expired and gateway_ok and service_reachable)
        code = "ok" if ok else ("expired" if expired else ("gateway_missing" if not gateway_ok else "service_unreachable"))
        message = "会员会话有效" if ok else ("会员已过期" if expired else ("会员网关未配置" if not gateway_ok else "会员服务端不可连接"))
        detail = gateway_base or self.service_base_url
        return {
            "ok": ok,
            "code": code,
            "message": message,
            "detail": detail,
            "session": session,
            "service": {
                "baseUrl": self.service_base_url,
                "reachable": service_reachable,
                "detail": service_detail,
            },
            "gateway": {
                "configured": gateway_ok,
                "baseUrl": gateway_base or None,
                "tokenAvailable": bool(token),
                "detail": gateway_base or "未配置",
            },
        }
