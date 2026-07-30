"""Account ownership helpers for launcher jobs."""

from __future__ import annotations

import copy
import hashlib
import hmac
from dataclasses import dataclass
from typing import Any


JOB_OWNER_BINDING_SCHEMA = "loom.job.owner.v1"
_INTERNAL_OWNER_KEYS = frozenset({"ownerAccountId", "ownerAccountBinding"})


@dataclass(frozen=True, slots=True)
class AccountRuntimeIdentity:
    """Immutable identity used to drain one account's local runtime."""

    account_id: str
    owner_binding: str
    logged_in: bool = True

    @property
    def resolved(self) -> bool:
        return bool(self.account_id and self.owner_binding)

    def matches(self, other: "AccountRuntimeIdentity") -> bool:
        if not self.resolved or not other.resolved:
            return False
        return hmac.compare_digest(
            self.account_id.encode("utf-8"),
            other.account_id.encode("utf-8"),
        ) and hmac.compare_digest(
            self.owner_binding.encode("utf-8"),
            other.owner_binding.encode("utf-8"),
        )


def account_job_binding(account_id: object, install_id: object) -> str:
    account = str(account_id or "").strip()
    install = str(install_id or "").strip()
    if not account or not install:
        return ""
    payload = f"{JOB_OWNER_BINDING_SCHEMA}\0{install}\0{account}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def account_job_binding_for_context(ctx: Any, account_id: object) -> str:
    account = str(account_id or "").strip()
    if not account:
        return ""
    return account_job_binding(account, _install_identity(ctx))


def current_account_job_identity(ctx: Any) -> tuple[str, str]:
    manager_getter = getattr(ctx, "get_entitlement_mgr", None)
    manager = manager_getter() if callable(manager_getter) else None
    current_state = getattr(manager, "current_state", None)
    current: dict[str, Any] = {}
    if callable(current_state):
        try:
            candidate = current_state("matrix.devices")
        except Exception:
            candidate = {}
        if isinstance(candidate, dict):
            current = candidate
    lease = current.get("lease") if isinstance(current.get("lease"), dict) else {}
    account_id = str(current.get("accountId") or lease.get("accountId") or "").strip()
    install_id = str(lease.get("installId") or "").strip() or _install_identity(
        ctx,
        manager=manager,
    )
    return account_id, account_job_binding(account_id, install_id)


def capture_account_runtime_identity(
    ctx: Any,
    session: Any = None,
) -> AccountRuntimeIdentity:
    public_session = dict(session) if isinstance(session, dict) else {}
    logged_in = (
        public_session.get("loggedIn") is True
        if public_session
        else False
    )
    entitlement = (
        public_session.get("accountEntitlement")
        if isinstance(public_session.get("accountEntitlement"), dict)
        else {}
    )
    account_id = str(
        entitlement.get("accountId")
        or public_session.get("accountId")
        or ""
    ).strip()
    current_account_id, current_binding = current_account_job_identity(ctx)
    if not account_id and current_account_id:
        account_id = current_account_id
    if not account_id:
        member_id = str(public_session.get("memberId") or "").strip()
        if member_id.startswith("newapi:"):
            account_id = member_id.partition(":")[2].strip()
    if account_id and current_account_id == account_id and current_binding:
        owner_binding = current_binding
    else:
        owner_binding = account_job_binding_for_context(ctx, account_id)
    if not public_session and account_id:
        logged_in = True
    return AccountRuntimeIdentity(
        account_id=account_id,
        owner_binding=owner_binding,
        logged_in=logged_in,
    )


def coerce_account_runtime_identity(value: Any) -> AccountRuntimeIdentity:
    if isinstance(value, AccountRuntimeIdentity):
        return value
    if isinstance(value, dict):
        return AccountRuntimeIdentity(
            account_id=str(
                value.get("accountId")
                or value.get("account_id")
                or ""
            ).strip(),
            owner_binding=str(
                value.get("ownerBinding")
                or value.get("owner_binding")
                or value.get("binding")
                or ""
            ).strip(),
            logged_in=value.get("loggedIn", value.get("logged_in", True))
            is True,
        )
    return AccountRuntimeIdentity(
        account_id="",
        owner_binding="",
        logged_in=False,
    )


def job_requires_account_scope(job: dict[str, Any]) -> bool:
    progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    if progress.get("requiresPhoneEntitlement") is True:
        return True
    if any(str(progress.get(key) or "").strip() for key in _INTERNAL_OWNER_KEYS):
        return True
    identifiers = (
        job.get("kind"),
        job.get("type"),
        job.get("phase"),
        progress.get("commandId"),
        progress.get("phase"),
    )
    kind = str(job.get("kind") or "").strip().lower()
    if kind in {"publish", "media.transfer"}:
        return True
    return any(
        str(value or "").strip().lower().startswith(("phone.", "matrix."))
        for value in identifiers
    )


def job_visible_to_account(
    job: dict[str, Any],
    *,
    account_id: str,
    owner_binding: str,
) -> bool:
    if not job_requires_account_scope(job):
        return True
    progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    stored_binding = str(progress.get("ownerAccountBinding") or "").strip()
    if stored_binding:
        return bool(owner_binding) and hmac.compare_digest(stored_binding, owner_binding)
    legacy_account_id = str(progress.get("ownerAccountId") or "").strip()
    if legacy_account_id:
        return bool(account_id) and hmac.compare_digest(legacy_account_id, account_id)
    return False


def public_job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return _drop_internal_owner_fields(copy.deepcopy(job), include_binding=True)


def persisted_job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return _drop_internal_owner_fields(copy.deepcopy(job), include_binding=False)


def _drop_internal_owner_fields(value: Any, *, include_binding: bool) -> Any:
    if isinstance(value, dict):
        blocked = {"ownerAccountId"}
        if include_binding:
            blocked.add("ownerAccountBinding")
        return {
            key: _drop_internal_owner_fields(item, include_binding=include_binding)
            for key, item in value.items()
            if str(key) not in blocked
        }
    if isinstance(value, list):
        return [
            _drop_internal_owner_fields(item, include_binding=include_binding)
            for item in value
        ]
    return value


def _install_identity(ctx: Any, *, manager: Any = None) -> str:
    if manager is None:
        manager_getter = getattr(ctx, "get_entitlement_mgr", None)
        manager = manager_getter() if callable(manager_getter) else None
    legacy = getattr(manager, "legacy", None)
    get_install_id = getattr(legacy, "get_install_id", None)
    if callable(get_install_id):
        try:
            install_id = str(get_install_id() or "").strip()
        except Exception:
            install_id = ""
        if install_id:
            return install_id
    paths = getattr(ctx, "paths", None)
    return str(
        getattr(paths, "base_path", "")
        or getattr(paths, "launcher_dir", "")
        or "loom-local-install"
    ).strip()
