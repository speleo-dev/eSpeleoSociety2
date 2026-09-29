"""Application configuration loaded from environment variables (prefix ESS_).

Secrets are never stored in the repository. In Cloud Run they are injected from Secret Manager
as environment variables.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ESS_", extra="ignore")

    environment: str = "dev"  # dev | test | prod

    # PostgreSQL connection string, e.g. postgresql://user:pass@host:5432/eSpeleoSoc2
    database_url: str | None = None
    db_pool_size: int = 3
    db_max_overflow: int = 2
    # "require" in all deployed environments; "disable" only for a local/CI database without SSL.
    db_sslmode: str = "require"

    # Field encryption keys for personal data: "key_id:base64key,key_id2:base64key".
    # The first key is active for new data; the others are kept to decrypt older values.
    pii_keys: str | None = None
    # Key for blind indexes (HMAC-SHA256), base64. Changing it requires re-indexing all rows.
    blind_index_key: str | None = None

    # Comma-separated Google account e-mails of the main administrators.
    super_admin_emails: str = ""

    # Google sign-in (OpenID Connect) for administrative access.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Public URL of the app, e.g. https://ess-xxxx.run.app (used for the OAuth redirect URI).
    public_base_url: str | None = None
    # Secret for signing session cookies (random, at least 32 characters).
    session_secret: str | None = None
    session_max_age_seconds: int = 8 * 3600

    # Google Wallet (eCP). IDs are not secret; the runtime service account signs and calls the API.
    wallet_issuer_id: str = "3388000000022877308"
    wallet_class: str = "member"
    # Cloud Storage bucket for face photos (random 64-char names) and SSS images.
    media_bucket: str | None = None

    # Outgoing e-mail (WebSupport SMTP for ess@sss.sk). Port 465 = implicit TLS, 587 = STARTTLS.
    smtp_host: str = "smtp.m1.websupport.sk"
    smtp_port: int = 465
    smtp_user: str = "ess@sss.sk"
    smtp_password: str | None = None
    mail_from: str = "Slovenská speleologická spoločnosť <ess@sss.sk>"

    # Shared secret of the Cloud Scheduler job that calls /internal/tick (cave trip reminders, batches).
    scheduler_token: str | None = None

    @property
    def wallet_class_id(self) -> str:
        """Full Google Wallet class id, e.g. 3388000000022877308.member."""
        return f"{self.wallet_issuer_id}.{self.wallet_class}"

    @field_validator("environment")
    @classmethod
    def _check_environment(cls, value: str) -> str:
        if value not in {"dev", "test", "prod"}:
            raise ValueError("ESS_ENVIRONMENT must be one of: dev, test, prod")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
