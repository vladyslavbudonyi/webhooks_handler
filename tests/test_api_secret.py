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
