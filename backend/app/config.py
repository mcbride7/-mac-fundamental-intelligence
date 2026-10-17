"""Application settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _db_url(url: str) -> str:
    """Accept the plain postgres:// URLs that Railway, Render and Heroku hand out."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass
class Settings:
    app_name: str = "Mac Fundamental Intelligence"
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))

    # Database / cache
    database_url: str = field(
        default_factory=lambda: _db_url(os.getenv("DATABASE_URL", "postgresql+psycopg://mfi:mfi@localhost:5432/mfi"))
    )
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    use_timescale: bool = field(default_factory=lambda: _bool("USE_TIMESCALE", True))

    # Security
    # API_TOKEN: for scripts and the /docs test page. APP_PASSWORD: what you type on the login page
    # (defaults to API_TOKEN, so an existing deployment keeps working). SECRET_KEY signs login sessions.
    api_token: str | None = field(default_factory=lambda: os.getenv("API_TOKEN") or None)
    app_password: str | None = field(default_factory=lambda: os.getenv("APP_PASSWORD") or os.getenv("API_TOKEN") or None)
    secret_key: str | None = field(default_factory=lambda: os.getenv("SECRET_KEY") or None)
    session_days: int = field(default_factory=lambda: int(os.getenv("SESSION_DAYS", "30")))
    cors_origins: list[str] = field(
        default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:3000")
    )

    # Uploads
    storage_dir: str = field(default_factory=lambda: os.getenv("STORAGE_DIR", "./storage"))
    s3_bucket: str | None = field(default_factory=lambda: os.getenv("S3_BUCKET") or None)
    s3_endpoint_url: str | None = field(default_factory=lambda: os.getenv("S3_ENDPOINT_URL") or None)
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "20")))

    # AI (LLM abstraction layer)
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "none"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "claude-sonnet-5-5"))
    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None)
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
    # Free option: LLM_PROVIDER=gemini + GEMINI_API_KEY from aistudio.google.com/apikey
    gemini_api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or None)
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    # Data providers
    fred_api_key: str | None = field(default_factory=lambda: os.getenv("FRED_API_KEY") or None)
    finnhub_api_key: str | None = field(default_factory=lambda: os.getenv("FINNHUB_API_KEY") or None)
    twelvedata_api_key: str | None = field(default_factory=lambda: os.getenv("TWELVEDATA_API_KEY") or None)

    # Phone alerts (Telegram). Create a bot with @BotFather, then message it once and get your chat id.
    telegram_bot_token: str | None = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN") or None)
    telegram_chat_id: str | None = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID") or None)
    # Which alerts to send: HIGH severity always, plus these kinds (comma list; "all" sends everything)
    telegram_alert_kinds: str = field(default_factory=lambda: os.getenv(
        "TELEGRAM_ALERT_KINDS",
        "high_conviction_setup,thesis_invalidation,bias_change,economic_surprise,cb_surprise,policy_shift,"
        "data_conflict,source_failure,missing_data"))
    public_url: str | None = field(default_factory=lambda: os.getenv("PUBLIC_URL") or None)

    # Verification
    verification_retry_minutes: int = field(
        default_factory=lambda: int(os.getenv("VERIFICATION_RETRY_MINUTES", "30"))
    )
    verification_tolerance: float = field(
        default_factory=lambda: float(os.getenv("VERIFICATION_TOLERANCE", "0.05"))
    )

    # Run recompute inline (tests / small deployments) instead of via Celery
    recompute_inline: bool = field(default_factory=lambda: _bool("RECOMPUTE_INLINE", True))


settings = Settings()
