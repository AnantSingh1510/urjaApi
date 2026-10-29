from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="URJA_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    demo: bool = False
    base_url: str = "https://urja-ops.flockenergy.tech"
    username: str = ""
    password: SecretStr = SecretStr("")
    api_key: SecretStr = SecretStr("")
    catalog_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    readings_ttl_seconds: int = Field(default=60, ge=1, le=3600)
    portal_timezone: str = "Asia/Kolkata"
    timeout_seconds: float = Field(default=15, gt=0, le=60)
    operation_timeout_seconds: float = Field(default=60, gt=0, le=180)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Portal base URL must be HTTPS without embedded credentials")
        if url.path not in ("", "/") or url.query or url.fragment:
            raise ValueError("Portal base URL must be an origin, without path/query/fragment")
        return value.rstrip("/")

    @field_validator("portal_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def credentials(self):
        if not self.demo and (not self.username or not self.password.get_secret_value()):
            raise ValueError("Set URJA_USERNAME and URJA_PASSWORD, or URJA_DEMO=true")
        return self
