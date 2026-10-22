"""Server-only configuration. Secrets must never enter the frontend build."""
from functools import lru_cache
from uuid import NAMESPACE_URL, uuid5

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

OWNER_EMAIL = "splitineu@gmail.com"
OWNER_ID = str(uuid5(NAMESPACE_URL, f"splitin:map-studio:{OWNER_EMAIL}"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAP_STUDIO_", env_file=".env", extra="ignore")
    environment: str = "production"
    origin: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    session_secret: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    public_manifests_enabled: bool = False
    session_hours: int = 8
    frontend_dir: str = "frontend/dist"

    @field_validator("origin", "supabase_url")
    @classmethod
    def absolute_origin(cls, value):
        from urllib.parse import urlsplit
        if not value:
            return value
        url = urlsplit(value)
        local = url.hostname in {"localhost", "127.0.0.1"}
        if (url.scheme != "https" and not (url.scheme == "http" and local)) or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
            raise ValueError("Expected an HTTPS origin without credentials, path, or query")
        return value.rstrip("/")

    def missing(self) -> list[str]:
        required = ["origin", "github_client_id", "github_client_secret",
                    "session_secret", "supabase_url", "supabase_service_role_key"]
        missing = [name for name in required if not getattr(self, name)]
        if self.session_secret and len(self.session_secret) < 32:
            missing.append("session_secret_too_short")
        return missing


settings = Settings()
