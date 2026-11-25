"""The Welkin API client secret is read from AWS Secrets Manager once, at cold start.

API_SECRET_ARN set   -> secret comes from Secrets Manager (one get_secret_value call).
API_SECRET_ARN unset -> fall back to the plain API_SECRET env var (local dev).
"""

import sys
import types

import pytest

from app import config

SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:welikan-webhooks-handler-jh/api-secret-AbCdEf"


class FakeSecretsManager:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get_secret_value(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


@pytest.fixture
def fake_boto3(monkeypatch):
    """Install a stub boto3 module and return a factory to set the Secrets Manager response."""
    state = {"client": FakeSecretsManager({"SecretString": "secret-from-sm"}), "services": []}

    def client(service_name, *args, **kwargs):
        state["services"].append(service_name)
        return state["client"]

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=client))
    return state


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("API_SECRET", "API_SECRET_ARN"):
        monkeypatch.delenv(name, raising=False)
    # Don't let a developer's local .env leak into these tests.
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    return monkeypatch


def test_secret_loaded_from_secrets_manager_when_arn_set(clean_env, fake_boto3):
    clean_env.setenv("API_SECRET_ARN", SECRET_ARN)
    clean_env.setenv("API_SECRET", "old-plain-env-value")

    loaded = config.load_settings()

    assert loaded.API_SECRET.get_secret_value() == "secret-from-sm"
    assert fake_boto3["services"] == ["secretsmanager"]
    assert fake_boto3["client"].calls == [{"SecretId": SECRET_ARN}]


def test_falls_back_to_env_var_when_arn_not_set(clean_env, fake_boto3):
    clean_env.setenv("API_SECRET", "plain-env-value")

    loaded = config.load_settings()

    assert loaded.API_SECRET.get_secret_value() == "plain-env-value"
    assert fake_boto3["services"] == []


def test_empty_secret_string_raises(clean_env, fake_boto3):
    clean_env.setenv("API_SECRET_ARN", SECRET_ARN)
    fake_boto3["client"] = FakeSecretsManager({"SecretBinary": b"x"})

    with pytest.raises(RuntimeError, match="no SecretString"):
        config.load_settings()


def test_secret_is_not_exposed_in_repr(clean_env, fake_boto3):
    clean_env.setenv("API_SECRET_ARN", SECRET_ARN)

    loaded = config.load_settings()

    assert "secret-from-sm" not in repr(loaded)
    assert "secret-from-sm" not in str(loaded.API_SECRET)


def test_token_request_uses_secret_from_secrets_manager(clean_env, fake_boto3):
    """End to end: the auth call to Welkin sends the value from Secrets Manager, fetched only once."""
    import asyncio

    import httpx

    from app.services import token_service

    clean_env.setenv("API_SECRET_ARN", SECRET_ARN)
    loaded = config.load_settings()
    loaded.API_URL = "https://api.live.welkincloud.io"
    loaded.API_TENANT = "jh"
    loaded.API_CLIENT = "client-id"

    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"token": "tok"})

    clean_env.setattr(token_service, "settings", loaded)
    clean_env.setattr(token_service, "_cached_token", None)
    clean_env.setattr(token_service, "_token_refresh_lock", None)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            svc = token_service.TokenService(client)
            await svc.get_token()
            await svc.get_token(force_refresh=True)

    asyncio.run(run())

    assert len(sent) == 2
    assert all(b'"secret":"secret-from-sm"' in r.content.replace(b" ", b"") for r in sent)
    # Secrets Manager hit once at load time, not per token request.
    assert len(fake_boto3["client"].calls) == 1


def test_secrets_client_uses_short_timeouts_and_bounded_retries(clean_env, monkeypatch):
    seen = {}

    def client(service_name, config=None, **kwargs):
        seen["config"] = config
        return FakeSecretsManager({"SecretString": "s"})

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=client))

    config.fetch_api_secret(SECRET_ARN)

    cfg = seen["config"]
    assert cfg.connect_timeout == 2 and cfg.read_timeout == 2
    assert cfg.retries == {"max_attempts": 3, "mode": "standard"}


def test_secrets_manager_error_is_logged_and_reraised(clean_env, fake_boto3, caplog):
    class Boom(FakeSecretsManager):
        def get_secret_value(self, **kwargs):
            raise ConnectionError("secrets manager unavailable")

    fake_boto3["client"] = Boom({})
    clean_env.setenv("API_SECRET_ARN", SECRET_ARN)

    with caplog.at_level("ERROR", logger="app.config"), pytest.raises(ConnectionError):
        config.load_settings()

    assert "failed to load API secret from Secrets Manager" in caplog.text


def test_pytest_never_loads_secret_from_aws_at_import():
    # tests/conftest.py blanks API_SECRET_ARN before app.config is imported.
    assert config.settings.API_SECRET_ARN == ""


# --- rotation: warm Lambda re-reads the secret when Welkin rejects the cached one ---


class RotatingSecretsManager(FakeSecretsManager):
    def __init__(self, values):
        super().__init__(None)
        self.values = list(values)

    def get_secret_value(self, **kwargs):
        self.calls.append(kwargs)
        return {"SecretString": self.values.pop(0)}


def _run_token_fetch(clean_env, loaded, valid_secret):
    import asyncio

    import httpx

    from app.services import token_service

    loaded.API_URL = "https://api.live.welkincloud.io"
    loaded.API_TENANT = "jh"
    loaded.API_CLIENT = "client-id"
    sent_secrets = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        secret = json.loads(request.content)["secret"]
        sent_secrets.append(secret)
        if secret == valid_secret:
            return httpx.Response(200, json={"token": "tok"})
        return httpx.Response(401, text="bad secret")

    clean_env.setattr(token_service, "settings", loaded)
    clean_env.setattr(token_service, "_cached_token", None)
    clean_env.setattr(token_service, "_token_refresh_lock", None)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await token_service.TokenService(client).get_token()

    return asyncio.run(run()), sent_secrets


def test_rotated_secret_is_reread_once_on_auth_rejection(clean_env, fake_boto3):
    fake_boto3["client"] = RotatingSecretsManager(["old-secret", "new-secret"])
    clean_env.setenv("API_SECRET_ARN", SECRET_ARN)
    loaded = config.load_settings()

    token, sent = _run_token_fetch(clean_env, loaded, valid_secret="new-secret")

    assert token == "Bearer tok"
    assert sent == ["old-secret", "new-secret"]
    assert loaded.API_SECRET.get_secret_value() == "new-secret"
    assert len(fake_boto3["client"].calls) == 2  # cold start + one re-read


def test_unchanged_secret_is_not_retried(clean_env, fake_boto3):
    from fastapi import HTTPException

    fake_boto3["client"] = RotatingSecretsManager(["same", "same"])
    clean_env.setenv("API_SECRET_ARN", SECRET_ARN)
    loaded = config.load_settings()

    with pytest.raises(HTTPException) as exc:
        _run_token_fetch(clean_env, loaded, valid_secret="something-else")

    assert exc.value.status_code == 502
    assert len(fake_boto3["client"].calls) == 2


def test_no_secrets_manager_call_on_auth_rejection_without_arn(clean_env, fake_boto3):
    from fastapi import HTTPException

    clean_env.setenv("API_SECRET", "env-secret")
    loaded = config.load_settings()

    with pytest.raises(HTTPException):
        _run_token_fetch(clean_env, loaded, valid_secret="something-else")

    assert fake_boto3["services"] == []
