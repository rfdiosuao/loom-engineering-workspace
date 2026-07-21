from dataclasses import dataclass
import os


DEFAULT_ADMIN_CORS_ORIGINS = frozenset({
    "http://127.0.0.1:18791", "http://localhost:18791",
    "http://118.145.98.220", "http://118.145.98.220:80",
    "https://118.145.98.220", "https://license.heang.top",
})


def bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class Settings:
    db_path: str
    backup_dir: str
    private_key_file: str
    admin_token_file: str
    logo_file: str
    host: str
    port: int
    admin_session_ttl_days: int
    admin_cors_allowed_origins: frozenset[str]
    public_url: str
    support_url: str
    gateway_base_url: str
    gateway_image_base_url: str
    gateway_video_base_url: str
    gateway_token: str
    gateway_image_token: str
    gateway_video_token: str
    gateway_default_model: str
    gateway_image_model: str
    gateway_video_model: str
    gateway_models: tuple[str, ...]
    login_rate_limit_attempts: int
    login_rate_limit_window_seconds: int
    login_rate_limit_lockout_seconds: int
    register_rate_limit_attempts: int
    register_rate_limit_window_seconds: int
    register_rate_limit_lockout_seconds: int
    publish_relay_token: str
    publish_relay_default_lease_ms: int
    publish_relay_default_wait_ms: int
    publish_relay_max_attempts: int
    max_bulk_code_hashes: int

    @classmethod
    def from_env(cls) -> "Settings":
        base = os.environ.get("LICENSE_BASE_DIR", "/opt/openclaw-license")
        origins = frozenset(
            item.strip().rstrip("/")
            for item in os.environ.get("LICENSE_ADMIN_CORS_ORIGINS", "").split(",")
            if item.strip()
        ) or DEFAULT_ADMIN_CORS_ORIGINS
        gateway_models = tuple(
            item.strip()
            for item in os.environ.get("MEMBER_GATEWAY_MODELS", "").replace("\uFF0C", ",").split(",")
            if item.strip()
        )
        public_url = os.environ.get("LICENSE_PUBLIC_URL", "https://license.heang.top/").strip()
        return cls(
            db_path=os.environ.get("LICENSE_DB", os.path.join(base, "license.db")),
            backup_dir=os.environ.get("LICENSE_BACKUP_DIR", os.path.join(base, "backups")),
            private_key_file=os.environ.get("LICENSE_PRIVATE_KEY_FILE", os.path.join(base, "private_key.b64")),
            admin_token_file=os.environ.get("LICENSE_ADMIN_TOKEN_FILE", os.path.join(base, "admin_token.txt")),
            logo_file=os.environ.get("LICENSE_LOGO_FILE", os.path.join(base, "logo.ico")),
            host=os.environ.get("LICENSE_HOST", "0.0.0.0"),
            port=int(os.environ.get("LICENSE_PORT", "18791")),
            admin_session_ttl_days=bounded_int_env("LICENSE_ADMIN_SESSION_TTL_DAYS", 30, 1, 3650),
            admin_cors_allowed_origins=origins,
            public_url=public_url,
            support_url=os.environ.get("LICENSE_SUPPORT_URL", public_url).strip(),
            gateway_base_url=os.environ.get("MEMBER_GATEWAY_BASE_URL", "").strip().rstrip("/"),
            gateway_image_base_url=os.environ.get("MEMBER_GATEWAY_IMAGE_BASE_URL", "").strip().rstrip("/"),
            gateway_video_base_url=os.environ.get("MEMBER_GATEWAY_VIDEO_BASE_URL", "").strip().rstrip("/"),
            gateway_token=os.environ.get("MEMBER_GATEWAY_TOKEN", "").strip(),
            gateway_image_token=os.environ.get("MEMBER_GATEWAY_IMAGE_TOKEN", "").strip(),
            gateway_video_token=os.environ.get("MEMBER_GATEWAY_VIDEO_TOKEN", "").strip(),
            gateway_default_model=os.environ.get("MEMBER_GATEWAY_DEFAULT_MODEL", "").strip(),
            gateway_image_model=os.environ.get("MEMBER_GATEWAY_IMAGE_MODEL", "").strip(),
            gateway_video_model=os.environ.get("MEMBER_GATEWAY_VIDEO_MODEL", "").strip(),
            gateway_models=gateway_models,
            login_rate_limit_attempts=bounded_int_env("LICENSE_LOGIN_RATE_LIMIT_ATTEMPTS", 10, 1, 100),
            login_rate_limit_window_seconds=bounded_int_env("LICENSE_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 600, 60, 86400),
            login_rate_limit_lockout_seconds=bounded_int_env("LICENSE_LOGIN_RATE_LIMIT_LOCKOUT_SECONDS", 900, 60, 86400),
            register_rate_limit_attempts=bounded_int_env("LICENSE_REGISTER_RATE_LIMIT_ATTEMPTS", 8, 1, 100),
            register_rate_limit_window_seconds=bounded_int_env("LICENSE_REGISTER_RATE_LIMIT_WINDOW_SECONDS", 600, 60, 86400),
            register_rate_limit_lockout_seconds=bounded_int_env("LICENSE_REGISTER_RATE_LIMIT_LOCKOUT_SECONDS", 900, 60, 86400),
            publish_relay_token=(os.environ.get("OPENCLAW_PUBLISH_RELAY_TOKEN") or os.environ.get("PUBLISH_RELAY_TOKEN") or "").strip(),
            publish_relay_default_lease_ms=bounded_int_env("PUBLISH_RELAY_DEFAULT_LEASE_MS", 30000, 1000, 900000),
            publish_relay_default_wait_ms=bounded_int_env("PUBLISH_RELAY_DEFAULT_WAIT_MS", 15000, 0, 900000),
            publish_relay_max_attempts=bounded_int_env("PUBLISH_RELAY_MAX_ATTEMPTS", 5, 1, 20),
            max_bulk_code_hashes=bounded_int_env("LICENSE_MAX_BULK_CODE_HASHES", 1000, 1, 5000),
        )


SETTINGS = Settings.from_env()
