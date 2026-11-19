import logging

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    API_URL: str = ""
    API_TENANT: str = ""
    API_INSTANCE: str = ""
    API_CLIENT: str = ""
    # Local/dev fallback. In Lambda the secret comes from Secrets Manager (API_SECRET_ARN).
    API_SECRET: SecretStr = SecretStr("")
    API_SECRET_ARN: str = ""
    LOG_LEVEL: str = "INFO"


def fetch_api_secret(secret_arn: str) -> SecretStr:
    """Read the Welkin API client secret from AWS Secrets Manager."""
    import boto3  # imported lazily so local runs without AWS don't need it loaded

    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    value = response.get("SecretString")
    if not value:
        raise RuntimeError(f"Secret {secret_arn} has no SecretString value")
    return SecretStr(value)


def load_settings() -> Settings:
    loaded = Settings()
    if loaded.API_SECRET_ARN:
        # Runs once at import time (Lambda cold start); the value stays in memory for warm invocations.
        loaded.API_SECRET = fetch_api_secret(loaded.API_SECRET_ARN)
        logger.info("loaded API secret from Secrets Manager")
    return loaded


__all__ = ["settings"]

settings = load_settings()
