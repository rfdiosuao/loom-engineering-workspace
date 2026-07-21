from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..errors import ActivationError
from ..timeutils import add_days_date, utc_now


ConnectFn = Callable[[], sqlite3.Connection]
BetaConfigFn = Callable[[], dict[str, Any]]
BetaTodayFn = Callable[[], str]
ClaimsCountFn = Callable[[], int]
AccountIdFn = Callable[[], int]
NormalizePlanKeyFn = Callable[[Any], str]
PlanRowFn = Callable[[str], sqlite3.Row | None]
AccountDefaultsFn = Callable[..., dict[str, Any]]
CodeCreatorFn = Callable[..., list[str]]
TemplatePublicFn = Callable[[sqlite3.Row], dict[str, Any]]
JsonObjectParserFn = Callable[[Any], dict[str, Any]]
LoadJsonValueFn = Callable[[Any, Any], Any]
UtcNowFn = Callable[[], str]


BETA_CONFIG_KEY = "beta_claim"
BETA_DEFAULTS = {
    "enabled": True,
    "dailyQuota": 10,
    "validDays": 7,
    "edition": "trial",
    "licensee": "内测用户",
    "planTemplate": "",
}

TEMPLATE_KINDS = ("image", "video")
DEFAULT_TEMPLATES = [
    {
        "kind": "image",
        "title": "产品白底图",
        "prompt": "一张高清产品摄影，纯白背景，柔和棚拍光，居中构图，电商主图风格，细节锐利",
        "params": {"size": "1024x1024"},
        "tags": "电商,产品",
        "sort": 10,
    },
    {
        "kind": "image",
        "title": "国风插画",
        "prompt": "中国风工笔插画，青绿山水，留白，细腻线条，雅致配色，高分辨率",
        "params": {"size": "1024x1536"},
        "tags": "插画,国风",
        "sort": 20,
    },
    {
        "kind": "video",
        "title": "城市夜景延时",
        "prompt": "繁华都市夜景，车流光轨，霓虹灯，延时摄影质感，电影级色调，运镜平稳",
        "params": {"mode": "t2v", "resolution": "720P", "ratio": "16:9", "duration": 5},
        "tags": "城市,延时",
        "sort": 10,
    },
]


def beta_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_beta_config(*, connect_fn: ConnectFn | None = None) -> dict[str, Any]:
    cfg = dict(BETA_DEFAULTS)
    with (connect_fn or _missing_connect)() as conn:
        row = conn.execute("select value_json from settings where key = ?", (BETA_CONFIG_KEY,)).fetchone()
    if row:
        try:
            cfg.update(json.loads(row["value_json"]) or {})
        except Exception:
            pass
    cfg["enabled"] = bool(cfg.get("enabled", True))
    cfg["dailyQuota"] = max(0, int(cfg.get("dailyQuota", 10)))
    cfg["validDays"] = max(1, int(cfg.get("validDays", 7)))
    return cfg


def set_beta_config(
    patch: dict[str, Any],
    *,
    connect_fn: ConnectFn | None = None,
    get_beta_config_fn: BetaConfigFn | None = None,
    normalize_plan_key_fn: NormalizePlanKeyFn | None = None,
    utc_now_fn: UtcNowFn = utc_now,
) -> dict[str, Any]:
    cfg = (get_beta_config_fn or _missing_beta_config)()
    if "enabled" in patch:
        cfg["enabled"] = bool(patch["enabled"])
    if "dailyQuota" in patch:
        cfg["dailyQuota"] = max(0, min(int(patch["dailyQuota"]), 100000))
    if "validDays" in patch:
        cfg["validDays"] = max(1, min(int(patch["validDays"]), 3650))
    if "planTemplate" in patch:
        raw_tpl = str(patch.get("planTemplate") or "").strip()
        cfg["planTemplate"] = (normalize_plan_key_fn or _missing_plan_normalizer)(raw_tpl) if raw_tpl else ""
    with (connect_fn or _missing_connect)() as conn:
        conn.execute(
            "insert into settings (key, value_json, updated_at) values (?, ?, ?) "
            "on conflict(key) do update set value_json = excluded.value_json, updated_at = excluded.updated_at",
            (BETA_CONFIG_KEY, json.dumps(cfg, ensure_ascii=False), utc_now_fn()),
        )
        conn.commit()
    return cfg


def beta_owner_account_id(
    *,
    connect_fn: ConnectFn | None = None,
    account_role_super_admin: str = "super_admin",
    account_status_active: str = "active",
) -> int:
    with (connect_fn or _missing_connect)() as conn:
        row = conn.execute(
            "select id from accounts where role = ? and status = ? order by id asc limit 1",
            (account_role_super_admin, account_status_active),
        ).fetchone()
    return int(row["id"]) if row else 0


def beta_claims_count_today(
    *,
    connect_fn: ConnectFn | None = None,
    beta_today_fn: BetaTodayFn = beta_today,
) -> int:
    with (connect_fn or _missing_connect)() as conn:
        row = conn.execute("select count(*) as c from beta_claims where day = ?", (beta_today_fn(),)).fetchone()
    return int(row["c"]) if row else 0


def _insert_beta_claim(
    conn: sqlite3.Connection,
    *,
    day: str,
    ip: str,
    code: str,
    expires: str,
    created_at: str,
) -> None:
    conn.execute(
        "insert into beta_claims (day, ip, full_code, expires, created_at) values (?, ?, ?, ?, ?)",
        (day, ip, code, expires, created_at),
    )


def beta_status_snapshot(
    *,
    get_beta_config_fn: BetaConfigFn | None = None,
    beta_claims_count_today_fn: ClaimsCountFn | None = None,
) -> dict[str, Any]:
    cfg = (get_beta_config_fn or _missing_beta_config)()
    used = (beta_claims_count_today_fn or _missing_claims_count)()
    return {
        "enabled": cfg["enabled"],
        "quota": cfg["dailyQuota"],
        "remaining": max(0, cfg["dailyQuota"] - used),
        "validDays": cfg["validDays"],
    }


def beta_claim_code(
    ip: str,
    *,
    connect_fn: ConnectFn | None = None,
    get_beta_config_fn: BetaConfigFn | None = None,
    beta_today_fn: BetaTodayFn = beta_today,
    beta_claims_count_today_fn: ClaimsCountFn | None = None,
    beta_owner_account_id_fn: AccountIdFn | None = None,
    normalize_plan_key_fn: NormalizePlanKeyFn | None = None,
    get_plan_row_fn: PlanRowFn | None = None,
    apply_account_gateway_defaults_fn: AccountDefaultsFn | None = None,
    create_code_records_fn: CodeCreatorFn | None = None,
    load_json_value_fn: LoadJsonValueFn | None = None,
    default_features: list[str] | None = None,
    add_days_date_fn: Callable[[int], str] = add_days_date,
    utc_now_fn: UtcNowFn = utc_now,
) -> dict[str, Any]:
    cfg = (get_beta_config_fn or _missing_beta_config)()
    if not cfg["enabled"]:
        raise ActivationError("内测码发放暂时关闭，稍后再来", status=403)

    count_claims = beta_claims_count_today_fn or _missing_claims_count

    def _existing() -> sqlite3.Row | None:
        with (connect_fn or _missing_connect)() as conn:
            return conn.execute(
                "select full_code, expires from beta_claims where day = ? and ip = ?",
                (beta_today_fn(), ip),
            ).fetchone()

    def _result(code: str, expires: str, repeat: bool) -> dict[str, Any]:
        return {
            "code": code,
            "expires": expires,
            "repeat": repeat,
            "remaining": max(0, cfg["dailyQuota"] - count_claims()),
            "validDays": cfg["validDays"],
        }

    row = _existing()
    if row:
        return _result(row["full_code"], row["expires"], True)
    if count_claims() >= cfg["dailyQuota"]:
        raise ActivationError("今日内测码已领完，明天再来", status=429)

    owner_id = (beta_owner_account_id_fn or _missing_owner_account_id)()
    plan_key = str(cfg.get("planTemplate") or "").strip()
    plan_row = (
        (get_plan_row_fn or _missing_plan_row)((normalize_plan_key_fn or _missing_plan_normalizer)(plan_key))
        if plan_key
        else None
    )
    if plan_row is not None and not bool(plan_row["disabled"]):
        gw = {
            "gatewayBaseUrl": plan_row["gateway_base_url"],
            "gatewayImageBaseUrl": plan_row["gateway_image_base_url"],
            "gatewayVideoBaseUrl": plan_row["gateway_video_base_url"],
            "gatewayToken": plan_row["gateway_token"],
            "gatewayImageToken": plan_row["gateway_image_token"],
            "gatewayVideoToken": plan_row["gateway_video_token"],
            "gatewayDefaultModel": plan_row["gateway_default_model"],
            "gatewayImageModel": plan_row["gateway_image_model"],
            "gatewayVideoModel": plan_row["gateway_video_model"],
        }
        features = (load_json_value_fn or _missing_json_loader)(plan_row["features_json"], default_features or []) or list(default_features or [])
    else:
        gw = (apply_account_gateway_defaults_fn or _missing_account_defaults)({}, owner_id, explicit_body={})
        features = list(default_features or [])
    expires = add_days_date_fn(cfg["validDays"])
    creator = create_code_records_fn or _default_create_code_records
    codes = creator(
        count=1,
        licensee=str(cfg.get("licensee") or "内测用户"),
        edition=str(cfg.get("edition") or "trial"),
        features=features,
        expires=expires,
        max_activations=1,
        gateway_base_url=str(gw.get("gatewayBaseUrl") or ""),
        gateway_image_base_url=str(gw.get("gatewayImageBaseUrl") or gw.get("gateway_image_base_url") or ""),
        gateway_video_base_url=str(gw.get("gatewayVideoBaseUrl") or gw.get("gateway_video_base_url") or ""),
        gateway_token=str(gw.get("gatewayToken") or ""),
        gateway_image_token=str(gw.get("gatewayImageToken") or gw.get("gateway_image_token") or ""),
        gateway_video_token=str(gw.get("gatewayVideoToken") or gw.get("gateway_video_token") or ""),
        gateway_default_model=str(gw.get("gatewayDefaultModel") or ""),
        gateway_image_model=str(gw.get("gatewayImageModel") or gw.get("gateway_image_model") or ""),
        gateway_video_model=str(gw.get("gatewayVideoModel") or gw.get("gateway_video_model") or ""),
        member_mode=bool(str(gw.get("gatewayBaseUrl") or "").strip()),
        plan=(normalize_plan_key_fn or _missing_plan_normalizer)(plan_key) if plan_row is not None else "",
        owner_account_id=owner_id,
    )
    code = codes[0]
    try:
        with (connect_fn or _missing_connect)() as conn:
            _insert_beta_claim(
                conn,
                day=beta_today_fn(),
                ip=ip,
                code=code,
                expires=expires,
                created_at=utc_now_fn(),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        row = _existing()
        if row:
            return _result(row["full_code"], row["expires"], True)
        raise
    return _result(code, expires, False)


def template_public(row: sqlite3.Row, *, load_json_value_fn: LoadJsonValueFn | None = None) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "kind": str(row["kind"] or ""),
        "title": str(row["title"] or ""),
        "prompt": str(row["prompt"] or ""),
        "params": (load_json_value_fn or _missing_json_loader)(row["params_json"], {}) or {},
        "coverUrl": str(row["cover_url"] or ""),
        "tags": [tag.strip() for tag in str(row["tags"] or "").split(",") if tag.strip()],
        "sort": int(row["sort"] or 0),
        "enabled": bool(row["enabled"]),
        "updatedAt": str(row["updated_at"] or ""),
    }


def seed_default_templates(*, connect_fn: ConnectFn | None = None, utc_now_fn: UtcNowFn = utc_now) -> None:
    with (connect_fn or _missing_connect)() as conn:
        existing = conn.execute("select count(*) as c from prompt_templates").fetchone()["c"]
        if existing:
            return
        now = utc_now_fn()
        for template in DEFAULT_TEMPLATES:
            conn.execute(
                """
                insert into prompt_templates (kind, title, prompt, params_json, cover_url, tags, sort, enabled, created_at, updated_at)
                values (?, ?, ?, ?, '', ?, ?, 1, ?, ?)
                """,
                (
                    template["kind"], template["title"], template["prompt"],
                    json.dumps(template.get("params") or {}, ensure_ascii=False),
                    template.get("tags", ""), int(template.get("sort", 0)), now, now,
                ),
            )
        conn.commit()


def list_templates(
    kind: str = "",
    *,
    only_enabled: bool = False,
    connect_fn: ConnectFn | None = None,
    template_public_fn: TemplatePublicFn | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    args: list[Any] = []
    if kind in TEMPLATE_KINDS:
        clauses.append("kind = ?")
        args.append(kind)
    if only_enabled:
        clauses.append("enabled = 1")
    where = (" where " + " and ".join(clauses)) if clauses else ""
    with (connect_fn or _missing_connect)() as conn:
        rows = conn.execute(f"select * from prompt_templates{where} order by kind asc, sort asc, id asc", args).fetchall()
    formatter = template_public_fn or _missing_template_public
    return [formatter(row) for row in rows]


def save_template(
    body: dict[str, Any],
    *,
    connect_fn: ConnectFn | None = None,
    parse_json_object_fn: JsonObjectParserFn | None = None,
    template_public_fn: TemplatePublicFn | None = None,
    utc_now_fn: UtcNowFn = utc_now,
) -> dict[str, Any]:
    kind = str(body.get("kind", "")).strip().lower()
    if kind not in TEMPLATE_KINDS:
        raise ActivationError("kind 必须是 image 或 video")
    title = str(body.get("title", "")).strip()
    prompt = str(body.get("prompt", "")).strip()
    if not title or not prompt:
        raise ActivationError("标题和提示词不能为空")
    params = body.get("params")
    if isinstance(params, str):
        params = (parse_json_object_fn or _missing_json_object_parser)(params)
    if not isinstance(params, dict):
        params = {}
    cover_url = str(body.get("coverUrl", "")).strip()
    tags_value = body.get("tags", "")
    tags = ",".join(tag.strip() for tag in tags_value if str(tag).strip()) if isinstance(tags_value, list) else str(tags_value or "").strip()
    sort = int(body.get("sort", 0) or 0)
    enabled = 1 if body.get("enabled", True) else 0
    now = utc_now_fn()
    template_id = int(body.get("id", 0) or 0)
    with (connect_fn or _missing_connect)() as conn:
        if template_id > 0:
            conn.execute(
                """
                update prompt_templates set kind=?, title=?, prompt=?, params_json=?, cover_url=?, tags=?, sort=?, enabled=?, updated_at=?
                where id=?
                """,
                (kind, title, prompt, json.dumps(params, ensure_ascii=False), cover_url, tags, sort, enabled, now, template_id),
            )
        else:
            cur = conn.execute(
                """
                insert into prompt_templates (kind, title, prompt, params_json, cover_url, tags, sort, enabled, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (kind, title, prompt, json.dumps(params, ensure_ascii=False), cover_url, tags, sort, enabled, now, now),
            )
            template_id = int(cur.lastrowid)
        conn.commit()
        row = conn.execute("select * from prompt_templates where id=?", (template_id,)).fetchone()
    return (template_public_fn or _missing_template_public)(row)


def delete_template(template_id: int, *, connect_fn: ConnectFn | None = None) -> None:
    with (connect_fn or _missing_connect)() as conn:
        conn.execute("delete from prompt_templates where id=?", (int(template_id),))
        conn.commit()


def _default_create_code_records(**kwargs: Any) -> list[str]:
    from .licenses import create_code_records

    return create_code_records(**kwargs)


def _missing_connect() -> sqlite3.Connection:
    raise RuntimeError("connect_fn is required")


def _missing_beta_config() -> dict[str, Any]:
    raise RuntimeError("get_beta_config_fn is required")


def _missing_claims_count() -> int:
    raise RuntimeError("beta_claims_count_today_fn is required")


def _missing_owner_account_id() -> int:
    raise RuntimeError("beta_owner_account_id_fn is required")


def _missing_plan_normalizer(_value: Any) -> str:
    raise RuntimeError("normalize_plan_key_fn is required")


def _missing_plan_row(_plan_key: str) -> sqlite3.Row | None:
    raise RuntimeError("get_plan_row_fn is required")


def _missing_account_defaults(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("apply_account_gateway_defaults_fn is required")


def _missing_json_loader(_value: Any, _default: Any) -> Any:
    raise RuntimeError("load_json_value_fn is required")


def _missing_template_public(_row: sqlite3.Row) -> dict[str, Any]:
    raise RuntimeError("template_public_fn is required")


def _missing_json_object_parser(_value: Any) -> dict[str, Any]:
    raise RuntimeError("parse_json_object_fn is required")
