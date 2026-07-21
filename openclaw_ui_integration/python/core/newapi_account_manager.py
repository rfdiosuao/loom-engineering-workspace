"""New API account login and launcher model sync support."""

from __future__ import annotations

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from core.license_manager import LicenseManager
from core.paths import AppPaths
from core.storage import read_json, write_json


class NewApiAccountError(RuntimeError):
    pass


DEFAULT_BASE_URL = "https://api.heang.top"
DEFAULT_API_BASE = "https://api.heang.top/v1"
ACCOUNT_SOURCE = "newapi_account"
LEGACY_ACCOUNT_SOURCE = "heang_account"
SESSION_GRACE_DAYS = 14
DEFAULT_TEXT_MODEL = "qwen3.7-plus"
DEFAULT_PHONE_MODEL = "agnes-2.0-flash"
MANAGED_ACCOUNT_SOURCES = {ACCOUNT_SOURCE, LEGACY_ACCOUNT_SOURCE}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pick_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "none":
            return text
    return ""


def _mask_secret(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}****{text[-4:]}"


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("data"), (dict, list)):
        return payload["data"]
    return payload


def _candidate_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "tokens", "rows", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _candidate_items(value)
            if nested:
                return nested
    return []


def _extract_user_id(*payloads: Any) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        candidates = [payload]
        for key in ("user", "account", "data"):
            if isinstance(payload.get(key), dict):
                candidates.append(payload[key])
        for item in candidates:
            user_id = _pick_text(item.get("id"), item.get("user_id"), item.get("userId"))
            if user_id:
                return user_id
    return ""


def _extract_account_name(*payloads: Any) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        candidates = [payload]
        for key in ("user", "account", "data"):
            if isinstance(payload.get(key), dict):
                candidates.append(payload[key])
        for item in candidates:
            text = _pick_text(item.get("email"), item.get("username"), item.get("display_name"), item.get("name"))
            if text:
                return text
    return ""


def _extract_api_key(payload: Any) -> str:
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("sk-"):
            return text
        return ""
    if isinstance(payload, list):
        for item in payload:
            token = _extract_api_key(item)
            if token:
                return token
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("key", "value", "api_key", "apiKey"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if len(text) >= 8 and "*" not in text:
                return text
    for key in ("token", "access_token"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("sk-") or (len(text) >= 8 and "*" not in text and isinstance(payload.get("name"), str)):
                return text
    for key in ("data", "token", "result", "items", "tokens", "rows", "list"):
        token = _extract_api_key(payload.get(key))
        if token:
            return token
    return ""


def _token_quota_value(item: dict[str, Any]) -> int:
    try:
        return int(item.get("remain_quota") or item.get("remainQuota") or item.get("quota") or 0)
    except (TypeError, ValueError):
        return 0


def _token_is_usable(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    token = _extract_api_key(item)
    if not token:
        return False
    status = str(item.get("status") or "1")
    if status not in ("1", "true", "active"):
        return False
    return item.get("unlimited_quota") is True or item.get("unlimitedQuota") is True or _token_quota_value(item) > 0


def _extract_best_api_key(payload: Any, preferred_name: str = "") -> str:
    items = _candidate_items(payload)
    if not items:
        return _extract_api_key(payload)

    preferred = []
    usable = []
    fallback = []
    for item in items:
        token = _extract_api_key(item)
        if not token:
            continue
        if preferred_name and isinstance(item, dict) and str(item.get("name") or "") == preferred_name:
            preferred.append(item)
        if _token_is_usable(item):
            usable.append(item)
        fallback.append(item)

    for group in (preferred, usable, fallback):
        for item in group:
            token = _extract_api_key(item)
            if token:
                return token
    return ""


def _extract_models(payload: Any) -> list[str]:
    models: list[str] = []
    raw = _candidate_items(payload)
    if not raw and isinstance(payload, dict):
        raw = payload.get("models") if isinstance(payload.get("models"), list) else []
    for item in raw:
        model_id = _pick_text(item.get("id"), item.get("model"), item.get("name")) if isinstance(item, dict) else _pick_text(item)
        if model_id and model_id not in models:
            models.append(model_id)
    return models


def _looks_like_image_model(model_id: str) -> bool:
    text = model_id.lower()
    markers = ("image", "dall-e", "gpt-image", "flux", "midjourney", "mj-", "stable-diffusion", "sd-", "imagen", "seedream")
    return any(marker in text for marker in markers)


def _looks_like_video_model(model_id: str) -> bool:
    text = model_id.lower()
    markers = ("video", "veo", "sora", "seedance", "kling", "wan", "hailuo", "runway", "pika", "luma", "happyhorse")
    return any(marker in text for marker in markers)


def _classify_models(models: list[str]) -> dict[str, list[str]]:
    classified = {"text": [], "image": [], "video": []}
    for model in models:
        if _looks_like_video_model(model):
            classified["video"].append(model)
        elif _looks_like_image_model(model):
            classified["image"].append(model)
        else:
            classified["text"].append(model)
    return classified


def _choose_model(candidates: list[str], preferred: str, fallback: list[str] | None = None) -> str:
    if preferred in candidates:
        return preferred
    if candidates:
        return candidates[0]
    fallback = fallback or []
    if preferred in fallback:
        return preferred
    return fallback[0] if fallback else preferred


class NewApiAccountManager:
    def __init__(self, paths: AppPaths, append_log=None):
        self.paths = paths
        self.license_mgr = LicenseManager(paths)
        self.append_log = append_log or (lambda _text: None)

    @property
    def session_path(self) -> str:
        return self.paths.member_session_file

    @staticmethod
    def normalize_base_url(value: Any) -> str:
        text = str(value or "").strip().rstrip("/")
        if not text:
            return DEFAULT_BASE_URL
        if not text.startswith(("http://", "https://")):
            text = f"https://{text}"
        return text.rstrip("/")

    def _request_json(
        self,
        opener: urllib.request.OpenerDirector,
        url: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 20,
    ) -> dict[str, Any]:
        data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "OpenClaw-Launcher/2.1",
                **(headers or {}),
            },
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                payload = json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as error:
            try:
                raw = error.read().decode("utf-8", errors="replace")
                payload = json.loads(raw) if raw.strip() else {}
                message = _pick_text(
                    payload.get("message") if isinstance(payload, dict) else "",
                    payload.get("error") if isinstance(payload, dict) else "",
                )
            except Exception:
                message = ""
            raise NewApiAccountError(message or f"http_{error.code}") from error
        except Exception as error:
            raise NewApiAccountError(f"newapi_network_error:{error}") from error

        if isinstance(payload, dict) and payload.get("success") is False:
            raise NewApiAccountError(_pick_text(payload.get("message"), payload.get("error"), "newapi_request_failed"))
        return payload if isinstance(payload, dict) else {"data": payload}

    def _auth_headers(self, access_token: str = "", user_id: str = "") -> dict[str, str]:
        headers: dict[str, str] = {}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if user_id:
            headers["New-Api-User"] = user_id
        return headers

    def _request_launcher_token_bridge(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        username: str,
        password: str,
    ) -> tuple[str, dict[str, Any]]:
        payload = self._request_json(
            opener,
            f"{base_url}/api/openclaw/launcher-token",
            method="POST",
            body={"username": username, "password": password},
            timeout=35,
        )
        data = _unwrap(payload)
        token = _extract_best_api_key(payload)
        if not token:
            raise NewApiAccountError("launcher_token_bridge_no_key")
        models = []
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            models = [str(item).strip() for item in data.get("models") or [] if str(item).strip()]
        return token, {
            "source": _pick_text(data.get("source") if isinstance(data, dict) else "", "bridge"),
            "tokenId": data.get("tokenId") if isinstance(data, dict) else None,
            "tokenName": data.get("tokenName") if isinstance(data, dict) else "",
            "models": models,
        }

    def _claim_bind_ticket(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        ticket: str,
    ) -> dict[str, Any]:
        payload = self._request_json(
            opener,
            f"{base_url}/api/openclaw/bind/claim",
            method="POST",
            body={"ticket": ticket},
            timeout=35,
        )
        data = _unwrap(payload)
        token = _extract_best_api_key(payload)
        if not token:
            raise NewApiAccountError("bind_ticket_no_key")
        models = []
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            models = [str(item).strip() for item in data.get("models") or [] if str(item).strip()]
        return {
            "raw": payload,
            "data": data if isinstance(data, dict) else {},
            "token": token,
            "models": models,
        }

    def _create_launcher_token(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        headers: dict[str, str],
    ) -> str:
        token_name = f"OpenClaw Launcher {int(time.time())}"
        attempts = [
            {"name": token_name, "remain_quota": 0, "expired_time": -1, "unlimited_quota": True},
            {"name": token_name, "remain_quota": 500000, "expired_time": -1, "unlimited_quota": False},
            {"name": token_name, "expired_time": -1},
            {"name": token_name},
        ]
        errors: list[str] = []
        for body in attempts:
            try:
                payload = self._request_json(opener, f"{base_url}/api/token/", method="POST", body=body, headers=headers)
                token = _extract_best_api_key(payload, token_name)
                if token:
                    return token
                created = _unwrap(payload)
                if isinstance(created, dict) and created.get("success") is False:
                    errors.append(_pick_text(created.get("message"), "token_create_failed"))
                    continue
                list_payload = self._request_json(opener, f"{base_url}/api/token/?p=0&page_size=100", headers=headers)
                token = _extract_best_api_key(list_payload, token_name)
                if token:
                    return token
                self._delete_created_tokens_by_name(opener, base_url, headers, token_name, list_payload)
                raise NewApiAccountError("中转站已创建 Token，但接口只返回脱敏 key；请手动填入 API Token，或在服务端开放创建后返回完整 key")
            except NewApiAccountError as error:
                message = str(error)
                errors.append(message)
                if "脱敏 key" in message:
                    break
        raise NewApiAccountError("无法自动创建 API Token：" + "; ".join(errors[-3:]))

    def _delete_created_tokens_by_name(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        headers: dict[str, str],
        token_name: str,
        payload: dict[str, Any],
    ) -> None:
        for item in _candidate_items(payload):
            if not isinstance(item, dict) or str(item.get("name") or "") != token_name:
                continue
            token_id = _pick_text(item.get("id"))
            if not token_id:
                continue
            try:
                self._request_json(opener, f"{base_url}/api/token/{token_id}", method="DELETE", headers=headers, timeout=10)
            except NewApiAccountError:
                pass

    def _read_or_create_api_token(
        self,
        opener: urllib.request.OpenerDirector,
        base_url: str,
        headers: dict[str, str],
        username: str,
        password: str,
        supplied_api_token: str,
    ) -> tuple[str, dict[str, Any]]:
        supplied_api_token = supplied_api_token.strip()
        if supplied_api_token:
            return supplied_api_token, {"source": "supplied"}

        try:
            return self._request_launcher_token_bridge(opener, base_url, username, password)
        except NewApiAccountError as error:
            self.append_log(f"[Account] launcher token bridge unavailable: {error}\n")

        try:
            payload = self._request_json(opener, f"{base_url}/api/token/?p=0&page_size=100", headers=headers)
            token = _extract_best_api_key(payload)
            if token:
                return token, {"source": "existing", "raw": _candidate_items(payload)}
        except NewApiAccountError:
            pass

        token = self._create_launcher_token(opener, base_url, headers)
        return token, {"source": "created"}

    def _fetch_models(self, opener: urllib.request.OpenerDirector, base_url: str, api_token: str, headers: dict[str, str]) -> list[str]:
        model_ids: list[str] = []
        for url, request_headers in (
            (f"{base_url}/api/user/models", headers),
            (f"{base_url}/v1/models", {"Authorization": f"Bearer {api_token}"}),
        ):
            try:
                payload = self._request_json(opener, url, headers=request_headers, timeout=25)
                for model in _extract_models(payload):
                    if model not in model_ids:
                        model_ids.append(model)
            except NewApiAccountError:
                continue
        return model_ids

    def _session_headers(self, session: dict[str, Any]) -> dict[str, str]:
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        headers = self._auth_headers("", _pick_text(newapi.get("userId")))
        cookie = _pick_text(newapi.get("sessionCookie"))
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _build_session(
        self,
        base_url: str,
        username: str,
        api_token: str,
        login_payload: dict[str, Any],
        self_payload: dict[str, Any],
        token_meta: dict[str, Any],
        models: list[str],
        cookie_jar: http.cookiejar.CookieJar,
    ) -> dict[str, Any]:
        login_data = _unwrap(login_payload)
        self_data = _unwrap(self_payload)
        account_name = _extract_account_name(self_data, login_data) or username
        user_id = _extract_user_id(self_data, login_data) or account_name
        classified = _classify_models(models)
        text_model = _choose_model(classified["text"], DEFAULT_TEXT_MODEL, models)
        image_model = classified["image"][0] if classified["image"] else ""
        video_model = classified["video"][0] if classified["video"] else ""
        now = _utc_now()
        cookies = "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookie_jar)
        usage = {}
        if isinstance(self_data, dict):
            usage = {
                "quota": self_data.get("quota"),
                "usedQuota": self_data.get("used_quota") or self_data.get("usedQuota"),
                "requestCount": self_data.get("request_count") or self_data.get("requestCount"),
            }
        return {
            "source": ACCOUNT_SOURCE,
            "memberId": f"newapi:{user_id}",
            "memberName": account_name,
            "plan": _pick_text((self_data or {}).get("group") if isinstance(self_data, dict) else "", "default"),
            "status": "active",
            "expiresAt": None,
            "leaseExpiresAt": _iso(now + timedelta(days=SESSION_GRACE_DAYS)),
            "gatewayBaseUrl": f"{base_url}/v1",
            "gatewayImageBaseUrl": f"{base_url}/v1",
            "gatewayVideoBaseUrl": "",
            "gatewayDefaultModel": text_model,
            "gatewayImageModel": image_model,
            "gatewayVideoModel": video_model,
            "gatewayModels": models,
            "lastGoodModels": {
                "models": models,
                "classified": classified,
                "updatedAt": _iso(now),
            },
            "memberToken": api_token,
            "gatewayImageAccessToken": api_token,
            "gatewayVideoAccessToken": "",
            "features": ["llm", "image"] + (["video"] if video_model else []),
            "usage": usage,
            "lease": {
                "source": ACCOUNT_SOURCE,
                "quota": usage,
                "tokenSource": token_meta.get("source"),
            },
            "gateway": {
                "baseUrl": f"{base_url}/v1",
                "imageBaseUrl": f"{base_url}/v1",
                "videoBaseUrl": "",
                "accessToken": api_token,
                "imageAccessToken": api_token,
                "videoAccessToken": "",
                "defaultModel": text_model,
                "imageModel": image_model,
                "videoModel": video_model,
                "models": models,
                "classifiedModels": classified,
            },
            "newApi": {
                "baseUrl": base_url,
                "userId": user_id,
                "account": account_name,
                "sessionCookie": cookies,
                "lastOnlineAt": _iso(now),
                "graceExpiresAt": _iso(now + timedelta(days=SESSION_GRACE_DAYS)),
                "modelClasses": classified,
            },
            "phoneAgent": {
                "managedBy": ACCOUNT_SOURCE,
                "baseUrl": f"{base_url}/v1",
                "apiKey": api_token,
                "model": DEFAULT_PHONE_MODEL,
            },
            "updatedAt": _iso(now),
            "managedBy": ACCOUNT_SOURCE,
        }

    def login(self, username: str, password: str, *, base_url: str = "", api_token: str = "") -> dict[str, Any]:
        username = username.strip()
        password = password.strip()
        if not username or not password:
            raise NewApiAccountError("请输入中转站账号和密码")

        base_url = self.normalize_base_url(base_url)
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        login_payload = self._request_json(
            opener,
            f"{base_url}/api/user/login",
            method="POST",
            body={"username": username, "password": password},
        )
        login_data = _unwrap(login_payload)
        access_token = _pick_text(
            login_payload.get("access_token"),
            login_payload.get("accessToken"),
            login_payload.get("token"),
            login_data.get("access_token") if isinstance(login_data, dict) else "",
            login_data.get("accessToken") if isinstance(login_data, dict) else "",
            login_data.get("token") if isinstance(login_data, dict) else "",
        )
        user_id = _extract_user_id(login_payload, login_data)
        headers = self._auth_headers(access_token, user_id)

        try:
            self_payload = self._request_json(opener, f"{base_url}/api/user/self", headers=headers)
        except NewApiAccountError:
            self_payload = login_payload
        if not user_id:
            user_id = _extract_user_id(self_payload, login_payload)
            headers = self._auth_headers(access_token, user_id)

        api_token_value, token_meta = self._read_or_create_api_token(opener, base_url, headers, username, password, api_token)
        models = token_meta.get("models") if isinstance(token_meta.get("models"), list) else []
        if not models:
            models = self._fetch_models(opener, base_url, api_token_value, headers)
        session = self._build_session(base_url, username, api_token_value, login_payload, self_payload, token_meta, models, cookie_jar)
        self._write_session(session)
        self.sync_targets(session)
        return session

    def bind_ticket(self, ticket: str, *, base_url: str = "") -> dict[str, Any]:
        ticket = ticket.strip()
        if not ticket:
            raise NewApiAccountError("bind ticket is required")

        base_url = self.normalize_base_url(base_url)
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        claimed = self._claim_bind_ticket(opener, base_url, ticket)
        data = claimed["data"] if isinstance(claimed.get("data"), dict) else {}
        api_token_value = _pick_text(claimed.get("token"))
        username = _pick_text(data.get("account"), data.get("username"), "NewAPI Account")
        user_id = _pick_text(data.get("userId"), data.get("user_id"), data.get("id"), username)
        login_payload = {
            "success": True,
            "data": {
                "id": user_id,
                "username": username,
                "email": username,
                "group": _pick_text(data.get("group"), data.get("plan"), "default"),
            },
        }
        self_payload = login_payload
        headers = self._auth_headers("", user_id)
        models = claimed["models"] if isinstance(claimed.get("models"), list) else []
        if not models:
            models = self._fetch_models(opener, base_url, api_token_value, headers)
        token_meta = {
            "source": _pick_text(data.get("source"), "website_bind"),
            "tokenId": data.get("tokenId"),
            "tokenName": data.get("tokenName") or "",
            "models": models,
        }
        session = self._build_session(base_url, username, api_token_value, login_payload, self_payload, token_meta, models, cookie_jar)
        self._write_session(session)
        self.sync_targets(session)
        return session

    def refresh_current(self) -> dict[str, Any]:
        session = self.current()
        if not session:
            raise NewApiAccountError("尚未登录中转站账号")
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        base_url = self.normalize_base_url(newapi.get("baseUrl") or DEFAULT_BASE_URL)
        api_token = _pick_text(session.get("memberToken"))
        if not api_token:
            raise NewApiAccountError("本机会话缺少 API Token，请重新登录")

        opener = urllib.request.build_opener()
        headers = self._session_headers(session)
        try:
            self_payload = self._request_json(opener, f"{base_url}/api/user/self", headers=headers)
        except NewApiAccountError:
            self_payload = {}
        online = False
        try:
            models = self._fetch_models(opener, base_url, api_token, headers)
            online = bool(models)
        except NewApiAccountError:
            models = []
        if not models and isinstance(session.get("gatewayModels"), list):
            models = list(session.get("gatewayModels") or [])
        if not models:
            last_good = session.get("lastGoodModels") if isinstance(session.get("lastGoodModels"), dict) else {}
            if isinstance(last_good.get("models"), list):
                models = list(last_good.get("models") or [])
        classified = _classify_models(models)
        now = _utc_now()
        session["gatewayModels"] = models
        session["gatewayDefaultModel"] = _choose_model(classified["text"], DEFAULT_TEXT_MODEL, models or [_pick_text(session.get("gatewayDefaultModel"))])
        session["gatewayImageModel"] = classified["image"][0] if classified["image"] else _pick_text(session.get("gatewayImageModel"))
        session["gatewayVideoModel"] = classified["video"][0] if classified["video"] else _pick_text(session.get("gatewayVideoModel"))
        gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
        gateway.update({
            "models": models,
            "classifiedModels": classified,
            "defaultModel": session["gatewayDefaultModel"],
            "imageModel": session["gatewayImageModel"],
            "videoModel": session["gatewayVideoModel"],
        })
        session["gateway"] = gateway
        if isinstance(self_payload, dict) and self_payload:
            self_data = _unwrap(self_payload)
            if isinstance(self_data, dict):
                session["usage"] = {
                    "quota": self_data.get("quota"),
                    "usedQuota": self_data.get("used_quota") or self_data.get("usedQuota"),
                    "requestCount": self_data.get("request_count") or self_data.get("requestCount"),
                }
                online = True
        if online:
            newapi.update({
                "lastOnlineAt": _iso(now),
                "graceExpiresAt": _iso(now + timedelta(days=SESSION_GRACE_DAYS)),
            })
            session["lastGoodModels"] = {
                "models": models,
                "classified": classified,
                "updatedAt": _iso(now),
            }
        else:
            newapi.update({
                "offline": True,
                "stale": True,
            })
        newapi.update({
            "baseUrl": base_url,
            "modelClasses": classified,
        })
        session["newApi"] = newapi
        session["updatedAt"] = _iso(now)
        self._write_session(session)
        self.sync_targets(session)
        return session

    def _write_session(self, session: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.session_path), exist_ok=True)
        write_json(self.session_path, session)

    def current(self) -> dict[str, Any] | None:
        session = read_json(self.session_path, None)
        if isinstance(session, dict) and session.get("source") == ACCOUNT_SOURCE:
            return session
        return None

    def public_session(self) -> dict[str, Any]:
        session = self.current()
        if not session:
            return {"loggedIn": False, "source": "", "account": "", "tokenMasked": "", "models": {"text": [], "image": [], "video": []}, "usage": {}, "lastSyncResults": []}
        newapi = session.get("newApi") if isinstance(session.get("newApi"), dict) else {}
        gateway = session.get("gateway") if isinstance(session.get("gateway"), dict) else {}
        classes = gateway.get("classifiedModels") if isinstance(gateway.get("classifiedModels"), dict) else newapi.get("modelClasses")
        if not isinstance(classes, dict):
            classes = _classify_models(session.get("gatewayModels") if isinstance(session.get("gatewayModels"), list) else [])
        return {
            "loggedIn": True,
            "source": ACCOUNT_SOURCE,
            "account": _pick_text(newapi.get("account"), session.get("memberName")),
            "memberId": _pick_text(session.get("memberId")),
            "plan": _pick_text(session.get("plan"), "default"),
            "status": _pick_text(session.get("status"), "active"),
            "baseUrl": _pick_text(newapi.get("baseUrl"), DEFAULT_BASE_URL),
            "gatewayBaseUrl": _pick_text(session.get("gatewayBaseUrl")),
            "tokenMasked": _mask_secret(session.get("memberToken")),
            "models": {
                "text": classes.get("text") if isinstance(classes.get("text"), list) else [],
                "image": classes.get("image") if isinstance(classes.get("image"), list) else [],
                "video": classes.get("video") if isinstance(classes.get("video"), list) else [],
            },
            "usage": session.get("usage") if isinstance(session.get("usage"), dict) else {},
            "lastOnlineAt": _pick_text(newapi.get("lastOnlineAt")),
            "graceExpiresAt": _pick_text(newapi.get("graceExpiresAt"), session.get("leaseExpiresAt")),
            "offline": bool(newapi.get("offline")),
            "stale": bool(newapi.get("stale")),
            "lastSyncResults": session.get("lastSyncResults") if isinstance(session.get("lastSyncResults"), list) else [],
        }

    def _sync_image_config(self, session: dict[str, Any]) -> None:
        image_model = _pick_text(session.get("gatewayImageModel"))
        if not image_model:
            return
        current = read_json(self.paths.image_config, {})
        if not isinstance(current, dict):
            current = {}
        if current.get("lockedByUser") is True:
            return
        current.update({
            "gatewayMode": "member",
            "managedBy": ACCOUNT_SOURCE,
            "baseUrl": session.get("gatewayImageBaseUrl") or session.get("gatewayBaseUrl"),
            "apiKey": session.get("gatewayImageAccessToken") or session.get("memberToken"),
            "model": image_model,
        })
        write_json(self.paths.image_config, current)

    def _sync_video_config(self, session: dict[str, Any]) -> None:
        video_model = _pick_text(session.get("gatewayVideoModel"))
        if not video_model:
            return
        payload = {
            "gatewayMode": "member",
            "managedBy": ACCOUNT_SOURCE,
            "baseUrl": session.get("gatewayVideoBaseUrl") or session.get("gatewayBaseUrl"),
            "apiBase": session.get("gatewayVideoBaseUrl") or session.get("gatewayBaseUrl"),
            "apiKey": session.get("gatewayVideoAccessToken") or session.get("memberToken"),
            "model": video_model,
            "providerId": "agnes" if video_model.startswith("agnes-video") else "",
        }
        for path in (self.paths.video_config, self.paths.videoapi_config):
            current = read_json(path, {})
            if not isinstance(current, dict):
                current = {}
            if current.get("lockedByUser") is True:
                continue
            current.update(payload)
            write_json(path, current)

    def _sync_desktop_agent_config(self, session: dict[str, Any]) -> None:
        model = _pick_text(session.get("gatewayDefaultModel"), DEFAULT_TEXT_MODEL)
        base_url = _pick_text(session.get("gatewayBaseUrl"), DEFAULT_API_BASE)
        api_key = _pick_text(session.get("memberToken"))
        path = os.path.join(self.paths.launcher_dir, "desktop-agent.json")
        current = read_json(path, {})
        if not isinstance(current, dict):
            current = {}
        provider = {
            "managedBy": ACCOUNT_SOURCE,
            "apiKey": api_key,
            "baseUrl": base_url,
            "baseURL": base_url,
            "model": model,
        }
        current.setdefault("provider", {})
        current.setdefault("llm", {})
        current.setdefault("chatProvider", {})
        current["chatProvider"].setdefault("config", {})
        current["provider"].update(provider)
        current["llm"].update(provider)
        current["chatProvider"]["config"].update(provider)
        write_json(path, current)

    def _sync_phone_agent_config(self, session: dict[str, Any]) -> None:
        phone_agent = session.get("phoneAgent") if isinstance(session.get("phoneAgent"), dict) else {}
        base_url = _pick_text(phone_agent.get("baseUrl"), session.get("gatewayBaseUrl"), DEFAULT_API_BASE)
        api_key = _pick_text(phone_agent.get("apiKey"), session.get("memberToken"))
        model = _pick_text(phone_agent.get("model"), DEFAULT_PHONE_MODEL)
        path = os.path.join(self.paths.launcher_dir, "phone-agent.json")
        current = read_json(path, {})
        if not isinstance(current, dict):
            current = {}
        current.setdefault("llm", {})
        current["llm"].update({
            "managedBy": ACCOUNT_SOURCE,
            "baseUrl": base_url,
            "apiKey": api_key,
            "model": model,
        })
        write_json(path, current)

    def sync_targets(self, session: dict[str, Any] | None = None, *, targets: tuple[str, ...] = ("image", "video", "desktop", "phone")) -> list[dict[str, Any]]:
        session = session or self.current()
        if not session:
            raise NewApiAccountError("not_logged_in")
        actions = {
            "image": self._sync_image_config,
            "video": self._sync_video_config,
            "desktop": self._sync_desktop_agent_config,
            "phone": self._sync_phone_agent_config,
        }
        results: list[dict[str, Any]] = []
        for target in targets:
            action = actions.get(target)
            if action is None:
                results.append({"target": target, "ok": False, "error": "unknown_target"})
                continue
            try:
                action(session)
                results.append({"target": target, "ok": True})
            except Exception as exc:
                self.append_log(f"[Account] sync target {target} failed: {exc}\n")
                results.append({"target": target, "ok": False, "error": str(exc)})
        session["lastSyncResults"] = results
        if isinstance(session, dict) and session.get("source") == ACCOUNT_SOURCE:
            self._write_session(session)
        return results

    def logout(self) -> bool:
        session = self.current()
        if not session:
            return False
        try:
            os.remove(self.session_path)
        except FileNotFoundError:
            pass
        self._clear_synced_configs()
        return True

    def _clear_synced_configs(self) -> None:
        profiles = read_json(self.paths.auth_profiles, {"models": {"providers": {}}})
        if isinstance(profiles, dict):
            models = profiles.get("models") if isinstance(profiles.get("models"), dict) else {}
            providers = models.get("providers") if isinstance(models.get("providers"), dict) else {}
            if isinstance(providers, dict):
                for provider_id, provider in list(providers.items()):
                    if isinstance(provider, dict) and provider.get("managedBy") in MANAGED_ACCOUNT_SOURCES:
                        providers.pop(provider_id, None)
                if models.get("primary") not in providers:
                    models["primary"] = next(iter(providers), "")
                    write_json(self.paths.auth_profiles, profiles)

        for path in (self.paths.image_config, self.paths.video_config, os.path.join(self.paths.base_path, "videoapi_config.json")):
            data = read_json(path, {})
            if isinstance(data, dict) and data.get("managedBy") in MANAGED_ACCOUNT_SOURCES:
                write_json(path, {})
