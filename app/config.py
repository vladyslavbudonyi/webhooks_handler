from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    API_URL: str = ""
    API_TENANT: str = ""
    API_INSTANCE: str = ""
    API_CLIENT: str = ""
    API_SECRET: SecretStr = SecretStr("")


__all__ = ["settings"]

settings = Settings()
