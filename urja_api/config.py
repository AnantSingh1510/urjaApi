from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="URJA_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    base_url: str = "https://urja-ops.flockenergy.tech"
    username: str = ""
    password: SecretStr = SecretStr("")
    portal_timezone: str = "Asia/Kolkata"
    timeout_seconds: float = Field(default=15, gt=0, le=60)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError(
                "Portal base URL must be HTTPS without embedded credentials"
            )
        if url.path not in ("", "/") or url.query or url.fragment:
            raise ValueError(
                "Portal base URL must be an origin, without path/query/fragment"
            )
        return value.rstrip("/")

    @field_validator("portal_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @model_validator(mode="after")
    def credentials(self):
        if not self.username or not self.password.get_secret_value():
            raise ValueError("Set URJA_USERNAME and URJA_PASSWORD")
        return self
