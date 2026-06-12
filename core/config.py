from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import (
    AnyHttpUrl,
    EmailStr,
    Field,
    PostgresDsn,
    RedisDsn,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Project root (two levels up from this file: core/config.py → core/ → /) ──
BASE_DIR: Path = Path(__file__).resolve().parent.parent


# ══════════════════════════════════════════════════════════════════════════════
#  Base settings — every environment inherits these
# ══════════════════════════════════════════════════════════════════════════════


class BaseAppSettings(BaseSettings):
    """
    Shared settings inherited by all environment-specific classes.
    Reads from environment variables and the .env file at BASE_DIR/.env.
    Field names map 1-to-1 with the keys in .env.example.
    """

    model_config = SettingsConfigDict(
        # Load from .env in the project root
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        # Do not raise an error for extra env vars that have no field defined.
        # This allows OS-level env vars (PATH, HOME, etc.) to coexist cleanly.
        extra="ignore",
        # Make the settings object immutable after construction.
        # This prevents accidental mutation of config at runtime.
        frozen=True,
        # Case-insensitive env var matching
        case_sensitive=False,
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_env: str = Field("development", pattern="^(development|test|production)$")
    app_secret_key: str = Field(..., min_length=64)
    app_debug: bool = False
    app_base_url: AnyHttpUrl = Field("http://localhost:8000")
    cors_origins: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """
        Accept either a Python list (when set programmatically in tests)
        or a comma-separated string (when read from .env).
        """
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        raise ValueError("cors_origins must be a list or comma-separated string")

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [h.strip() for h in v.split(",") if h.strip()]
        raise ValueError("allowed_hosts must be a list or comma-separated string")

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "chatserver"
    postgres_user: str = "chatuser"
    postgres_password: str = Field(..., min_length=1)

    # Full async URL — used by SQLAlchemy + asyncpg
    database_url: PostgresDsn = Field(...)

    # Sync URL — used by Alembic (does not support asyncpg driver)
    database_sync_url: PostgresDsn = Field(...)

    # Test database URL — used by pytest fixtures
    database_test_url: PostgresDsn = Field(...)

    # Connection pool
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""

    redis_db_app: int = 0
    redis_db_celery: int = 1
    redis_db_streams: int = 2
    redis_db_test: int = 3

    redis_url: RedisDsn = Field(...)
    redis_stream_url: RedisDsn = Field(...)
    redis_test_url: RedisDsn = Field(...)

    redis_max_connections: int = 50
    redis_socket_timeout: int = 5
    redis_socket_connect_timeout: int = 5
    redis_retry_on_timeout: bool = True

    # Redis Stream settings
    stream_max_len: int = 10000
    stream_consumer_group: str = "chat_cg"
    stream_block_ms: int = 5000

    # ── RabbitMQ / Celery ─────────────────────────────────────────────────────
    rabbitmq_host: str = "127.0.0.1"
    rabbitmq_port: int = 5672
    rabbitmq_vhost: str = "chatserver"
    rabbitmq_user: str = "chatworker"
    rabbitmq_password: str = Field(..., min_length=1)

    celery_broker_url: str = Field(...)
    celery_result_backend: str = Field(...)
    celery_task_serializer: str = "json"
    celery_result_serializer: str = "json"
    celery_accept_content: list[str] = Field(default_factory=lambda: ["json"])
    celery_worker_concurrency: int = 4

    rabbitmq_management_url: AnyHttpUrl = Field("http://127.0.0.1:15672")
    rabbitmq_management_user: str = "chatadmin"
    rabbitmq_management_password: str = ""

    @field_validator("celery_accept_content", mode="before")
    @classmethod
    def parse_celery_accept_content(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        raise ValueError(
            "celery_accept_content must be a list or comma-separated string"
        )

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_secret_key: str = Field(..., min_length=64)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30
    jwt_refresh_family_prefix: str = "rt_family:"
    jwt_blacklist_prefix: str = "bl:"

    # ── CSRF ──────────────────────────────────────────────────────────────────
    csrf_secret_key: str = Field(..., min_length=64)
    csrf_cookie_name: str = "csrftoken"
    csrf_header_name: str = "X-CSRFToken"
    csrf_cookie_secure: bool = False
    csrf_cookie_samesite: str = "strict"
    csrf_cookie_max_age: int = 3600

    # ── Auth cookies ──────────────────────────────────────────────────────────
    auth_cookie_name: str = "access_token"
    auth_cookie_secure: bool = False
    auth_cookie_httponly: bool = True
    auth_cookie_samesite: str = "strict"
    auth_cookie_max_age: int = 900

    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool = False
    refresh_cookie_httponly: bool = True
    refresh_cookie_samesite: str = "strict"
    refresh_cookie_max_age: int = 2592000

    # ── Email ─────────────────────────────────────────────────────────────────
    smtp_host: str = "smtp.mailtrap.io"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    emails_from_address: EmailStr = "noreply@chatserver.com"
    emails_from_name: str = "Chat Server"

    verification_code_ttl: int = 600
    verification_resend_cooldown: int = 60

    # ── Media ─────────────────────────────────────────────────────────────────
    media_root: Path = BASE_DIR / "media"
    max_upload_size_mb: int = 10
    max_voice_size_mb: int = 25

    allowed_avatar_mime_types: list[str] = Field(
        default_factory=lambda: ["image/jpeg", "image/png", "image/webp", "image/gif"]
    )
    allowed_attachment_mime_types: list[str] = Field(
        default_factory=lambda: [
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/gif",
            "application/pdf",
            "text/plain",
        ]
    )
    avatar_thumb_sizes: list[int] = Field(default_factory=lambda: [64, 128, 256])

    @field_validator(
        "allowed_avatar_mime_types", "allowed_attachment_mime_types", mode="before"
    )
    @classmethod
    def parse_mime_types(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        raise ValueError("MIME type lists must be a list or comma-separated string")

    @field_validator("avatar_thumb_sizes", mode="before")
    @classmethod
    def parse_thumb_sizes(cls, v: Any) -> list[int]:
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        raise ValueError(
            "avatar_thumb_sizes must be a list or comma-separated string of integers"
        )

    @field_validator("media_root", mode="before")
    @classmethod
    def resolve_media_root(cls, v: Any) -> Path:
        p = Path(v)
        # Relative paths are resolved from the project root
        if not p.is_absolute():
            p = BASE_DIR / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_register_capacity: int = 5
    rate_limit_register_refill_rate: float = 1.0

    rate_limit_verify_capacity: int = 5
    rate_limit_verify_refill_rate: float = 1.0

    rate_limit_resend_verify_capacity: int = 3
    rate_limit_resend_verify_refill_rate: float = 0.05

    rate_limit_login_capacity: int = 10
    rate_limit_login_refill_rate: float = 2.0

    rate_limit_refresh_capacity: int = 20
    rate_limit_refresh_refill_rate: float = 5.0

    rate_limit_profile_edit_capacity: int = 10
    rate_limit_profile_edit_refill_rate: float = 1.0

    rate_limit_follow_capacity: int = 30
    rate_limit_follow_refill_rate: float = 5.0

    rate_limit_post_create_capacity: int = 20
    rate_limit_post_create_refill_rate: float = 2.0

    rate_limit_reply_create_capacity: int = 30
    rate_limit_reply_create_refill_rate: float = 5.0

    rate_limit_like_capacity: int = 60
    rate_limit_like_refill_rate: float = 10.0

    rate_limit_search_capacity: int = 20
    rate_limit_search_refill_rate: float = 3.0

    rate_limit_message_global_capacity: int = 60
    rate_limit_message_global_refill_rate: float = 10.0

    rate_limit_message_per_chat_capacity: int = 30
    rate_limit_message_per_chat_refill_rate: float = 5.0

    rate_limit_interest_capacity: int = 10
    rate_limit_interest_refill_rate: float = 1.0

    rate_limit_key_prefix: str = "rl:"

    # ── Idempotency ───────────────────────────────────────────────────────────
    idempotency_ttl: int = 86400
    idempotency_key_prefix: str = "idem:"

    # ── Username change cooldown ──────────────────────────────────────────────
    username_change_cooldown_days: int = 30
    username_change_key_prefix: str = "uname_cd:"

    # ── Presence ──────────────────────────────────────────────────────────────
    presence_ttl: int = 60
    presence_key_prefix: str = "presence:"
    last_seen_key_prefix: str = "last_seen:"
    dau_key_prefix: str = "dau:"

    # ── WebSocket ─────────────────────────────────────────────────────────────
    ws_ping_interval: int = 25
    ws_ping_timeout: int = 10
    ws_max_message_size: int = 1_048_576  # 1 MB

    # ── Content ───────────────────────────────────────────────────────────────
    message_max_length: int = 4000
    reply_max_depth: int = 10

    # ── Push notifications ────────────────────────────────────────────────────
    fcm_server_key: str = ""
    apns_key_file: str = ""
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_topic: str = ""

    # ── IP geolocation ────────────────────────────────────────────────────────
    ip_api_url: AnyHttpUrl = Field("http://ip-api.com/json")
    ip_api_timeout: int = 3

    # ── Search ranking ────────────────────────────────────────────────────────
    search_location_boost: float = 1.5
    search_mutual_boost: float = 2.0
    search_popularity_weight: float = 0.3

    # ── Sentry ────────────────────────────────────────────────────────────────
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    # ── Feature flags ─────────────────────────────────────────────────────────
    feature_content_moderation: bool = False
    feature_push_notifications: bool = False
    feature_e2e_encryption: bool = False
    feature_message_edit_history: bool = True
    feature_show_deleted_placeholder: bool = True
    feature_public_search: bool = False
    feature_registration_open: bool = True
    feature_voice_messages: bool = True
    feature_file_attachments: bool = True

    # ── Computed helpers ──────────────────────────────────────────────────────

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def max_voice_size_bytes(self) -> int:
        return self.max_voice_size_mb * 1024 * 1024

    @model_validator(mode="after")
    def enforce_production_rules(self) -> "BaseAppSettings":
        """
        Catch dangerous misconfigurations at startup time, not at runtime.
        These checks run after all fields are populated and validated.
        """
        if self.is_production:
            errors: list[str] = []

            if self.app_debug:
                errors.append("APP_DEBUG must be false in production")

            if not self.auth_cookie_secure:
                errors.append("AUTH_COOKIE_SECURE must be true in production")

            if not self.refresh_cookie_secure:
                errors.append("REFRESH_COOKIE_SECURE must be true in production")

            if not self.csrf_cookie_secure:
                errors.append("CSRF_COOKIE_SECURE must be true in production")

            if "changeme" in str(self.postgres_password).lower():
                errors.append(
                    "POSTGRES_PASSWORD appears to be a placeholder — set a real password"
                )

            if "changeme" in self.app_secret_key.lower():
                errors.append(
                    "APP_SECRET_KEY appears to be a placeholder — generate a real key"
                )

            if errors:
                raise ValueError(
                    "Production misconfiguration detected:\n"
                    + "\n".join(f"  • {e}" for e in errors)
                )

        return self


# ══════════════════════════════════════════════════════════════════════════════
#  Environment-specific overrides
# ══════════════════════════════════════════════════════════════════════════════


class DevelopmentSettings(BaseAppSettings):
    """
    Development environment.
    Verbose logging, debug mode on, relaxed security (no HTTPS cookies).
    All defaults in BaseAppSettings already target development.
    """

    app_env: str = "development"
    app_debug: bool = True

    # Show full SQL queries in logs during dev
    # (consumed by db/session.py when building the engine)
    db_echo_sql: bool = True


class TestSettings(BaseAppSettings):
    """
    Test environment — used exclusively by the pytest suite.
    Points to the test database and a higher-numbered Redis DB.
    Disables external side-effects (email, push, moderation).
    """

    app_env: str = "test"
    app_debug: bool = True

    # Override the active database to the test DB
    # (pytest fixtures also set this via environment variable
    #  before settings are instantiated)
    db_echo_sql: bool = False

    # Disable all external I/O in tests
    feature_content_moderation: bool = False
    feature_push_notifications: bool = False

    # Shorten token TTLs so expiry tests don't need to sleep long
    jwt_access_token_expire_minutes: int = 1
    verification_code_ttl: int = 5
    verification_resend_cooldown: int = 1

    # Use aggressive rate limits so rate-limit tests trigger quickly
    rate_limit_login_capacity: int = 3
    rate_limit_register_capacity: int = 3


class ProductionSettings(BaseAppSettings):
    """
    Production environment.
    Enforces secure cookies, disables debug, enables Sentry.
    The model_validator in BaseAppSettings will raise at startup
    if any required production value is missing or misconfigured.
    """

    app_env: str = "production"
    app_debug: bool = False

    # Cookies must be secure (HTTPS only) in production
    auth_cookie_secure: bool = True
    refresh_cookie_secure: bool = True
    csrf_cookie_secure: bool = True

    # No SQL echo in production logs
    db_echo_sql: bool = False

    # Tighten connection pool for production traffic
    db_pool_size: int = 20
    db_max_overflow: int = 40

    redis_max_connections: int = 100


# ══════════════════════════════════════════════════════════════════════════════
#  Settings factory — returns the right class for APP_ENV
# ══════════════════════════════════════════════════════════════════════════════

_ENV_CLASS_MAP: dict[str, type[BaseAppSettings]] = {
    "development": DevelopmentSettings,
    "test": TestSettings,
    "production": ProductionSettings,
}


@lru_cache(maxsize=1)
def get_settings() -> BaseAppSettings:
    """
    Read APP_ENV from the environment (not from the .env file — this
    must be set before Python starts so the right class is selected).
    Instantiate and return the matching settings class.

    The result is cached by lru_cache so the .env file is parsed
    exactly once per process lifetime, no matter how many modules
    call get_settings().
    """
    import os

    env = os.getenv("APP_ENV", "development").lower().strip()

    settings_class = _ENV_CLASS_MAP.get(env)
    if settings_class is None:
        raise ValueError(
            f"Unknown APP_ENV '{env}'. "
            f"Must be one of: {', '.join(_ENV_CLASS_MAP.keys())}"
        )

    instance = settings_class()

    # Emit a single startup log so you can always confirm which
    # environment and config file were loaded.
    logging.getLogger(__name__).info(
        "Settings loaded",
        extra={
            "env": instance.app_env,
            "debug": instance.app_debug,
            "db_host": instance.postgres_host,
            "redis_host": instance.redis_host,
        },
    )

    return instance


# ── Module-level singleton ────────────────────────────────────────────────────
# Every module does: from core.config import settings
# Nothing else in the project calls get_settings() or os.getenv() directly.
settings: BaseAppSettings = get_settings()
