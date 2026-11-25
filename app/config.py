import logging

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Keep the cold-start lookup well inside Lambda's 10s init window: short timeouts, a few
# retries with backoff for throttling / transient errors (botocore "standard" retry mode).
_SECRETS_CLIENT_CONFIG = {
    "connect_timeout": 2,
    "read_timeout": 2,
    "retries": {"max_attempts": 3, "mode": "standard"},
}


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
    from botocore.config import Config

    try:
        client = boto3.client("secretsmanager", config=Config(**_SECRETS_CLIENT_CONFIG))
        response = client.get_secret_value(SecretId=secret_arn)
    except Exception:
        # Surface it clearly in CloudWatch; the error is re-raised so Lambda fails init
        # instead of running with an empty secret.
        logger.exception("failed to load API secret from Secrets Manager (%s)", secret_arn)
        raise
    value = response.get("SecretString")
    if not value:
        raise RuntimeError(f"Secret {secret_arn} has no SecretString value")
    return SecretStr(value)


def refresh_api_secret(target: "Settings") -> bool:
    """Re-read the secret from Secrets Manager (e.g. after rotation). Returns True if it changed."""
    if not target.API_SECRET_ARN:
        return False
    new_secret = fetch_api_secret(target.API_SECRET_ARN)
    changed = new_secret.get_secret_value() != target.API_SECRET.get_secret_value()
    target.API_SECRET = new_secret
    logger.info("re-read API secret from Secrets Manager (changed=%s)", changed)
    return changed


def load_settings() -> Settings:
    loaded = Settings()
    if loaded.API_SECRET_ARN:
        # Runs once at import time (Lambda cold start); the value stays in memory for warm invocations.
        loaded.API_SECRET = fetch_api_secret(loaded.API_SECRET_ARN)
        logger.info("loaded API secret from Secrets Manager")
    return loaded


__all__ = ["settings"]

settings = load_settings()
