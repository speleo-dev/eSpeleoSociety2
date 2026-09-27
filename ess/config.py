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

    @field_validator("environment")
    @classmethod
    def _check_environment(cls, value: str) -> str:
        if value not in {"dev", "test", "prod"}:
            raise ValueError("ESS_ENVIRONMENT must be one of: dev, test, prod")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
