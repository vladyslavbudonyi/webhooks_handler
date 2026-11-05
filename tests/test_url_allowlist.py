"""The reconciliation webhook GETs payload.url with the Welkin API token attached.

These tests make sure only URLs on our Welkin API tenant/instance are ever fetched,
so the token can't be sent to a server someone else controls.
"""

import asyncio

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import medication_service_client
from app.services.api_service import ApiService, is_allowed_api_url
from app.services.medication_service import MedicationService

API_URL = "https://api.live.welkincloud.io"
TENANT = "jh"
INSTANCE = "jills-live"
PREFIX = f"{API_URL}/{TENANT}/{INSTANCE}"
GOOD_URL = f"{PREFIX}/patients/11111111-1111-1111-1111-111111111111/cdts/cdt-weekend-schedule/22222222"


@pytest.fixture(autouse=True)
def welkin_settings(monkeypatch):
    monkeypatch.setattr(settings, "API_URL", API_URL)
    monkeypatch.setattr(settings, "API_TENANT", TENANT)
    monkeypatch.setattr(settings, "API_INSTANCE", INSTANCE)


ALLOWED = [
    GOOD_URL,
    f"{PREFIX}/patients/abc/cdts/cdt-weekend-schedule/123?sourceId=xyz",
    f"{PREFIX}/patients/abc/cdts/cdt-client-medication-list",
]

BLOCKED = {
    # different host
    "other_host": f"https://evil.com/{TENANT}/{INSTANCE}/x",
    "api_url_in_query": f"https://evil.com/?x={PREFIX}/x",
    "api_url_in_path": f"https://evil.com/{PREFIX}/x",
    "api_url_in_fragment": f"https://evil.com/#{PREFIX}/x",
    "suffix_domain": f"{API_URL}.evil.com/{TENANT}/{INSTANCE}/x",
    "suffix_domain_dash": f"{API_URL}-evil.com/{TENANT}/{INSTANCE}/x",
    "userinfo_then_evil_host": f"{API_URL}@evil.com/{TENANT}/{INSTANCE}/x",
    "evil_userinfo_then_api_host": f"https://evil.com@api.live.welkincloud.io/{TENANT}/{INSTANCE}/x",
    "backslash_userinfo": f"{API_URL}\\@evil.com/{TENANT}/{INSTANCE}/x",
    "similar_host": f"https://api.live.welkincloud.io.evil/{TENANT}/{INSTANCE}/x",
    "other_welkin_env": f"https://api.sandbox.welkincloud.io/{TENANT}/{INSTANCE}/x",
    "lookalike_unicode_host": f"https://api.live.welkinclоud.io/{TENANT}/{INSTANCE}/x",  # Cyrillic "о"
    "ip_address": f"https://127.0.0.1/{TENANT}/{INSTANCE}/x",
    "localhost": f"http://localhost/{TENANT}/{INSTANCE}/x",
    "aws_metadata": f"http://169.254.169.254/latest/meta-data/",
    # scheme / port
    "plain_http": f"http://api.live.welkincloud.io/{TENANT}/{INSTANCE}/x",
    "custom_port": f"{API_URL}:8443/{TENANT}/{INSTANCE}/x",
    "scheme_relative": f"//api.live.welkincloud.io/{TENANT}/{INSTANCE}/x",
    "file_scheme": "file:///etc/passwd",
    "javascript_scheme": "javascript:alert(1)",
    # same host but wrong tenant / instance
    "other_tenant": f"{API_URL}/other/{INSTANCE}/x",
    "other_instance": f"{API_URL}/{TENANT}/other-live/x",
    "instance_prefix_lookalike": f"{API_URL}/{TENANT}/{INSTANCE}X/x",
    "tenant_without_instance": f"{API_URL}/{TENANT}/x",
    "admin_endpoint": f"{API_URL}/{TENANT}/admin/api_clients/x",
    "prefix_without_trailing_slash": PREFIX,
    "root": f"{API_URL}/",
    "bare_api_url": API_URL,
    # dot segments: httpx/the server resolve these, escaping the tenant/instance prefix
    "dot_dot_to_other_tenant": f"{PREFIX}/../../other/live/x",
    "dot_dot_to_admin": f"{PREFIX}/../admin/api_clients/x",
    "dot_dot_trailing": f"{PREFIX}/..",
    "encoded_dot_dot": f"{PREFIX}/%2e%2e/%2e%2e/other/x",
    "encoded_dot_dot_upper": f"{PREFIX}/%2E%2E/x",
    "mixed_encoded_dot_dot": f"{PREFIX}/.%2e/x",
    # formatting tricks
    "leading_space": f" {GOOD_URL}",
    "leading_newline": f"\n{GOOD_URL}",
    "uppercase_scheme": GOOD_URL.replace("https", "HTTPS", 1),
    "empty": "",
    "relative_path": f"/{TENANT}/{INSTANCE}/x",
}


@pytest.mark.parametrize("url", ALLOWED)
def test_allows_welkin_tenant_urls(url):
    assert is_allowed_api_url(url)


@pytest.mark.parametrize("url", BLOCKED.values(), ids=BLOCKED.keys())
def test_blocks_risky_urls(url):
    assert not is_allowed_api_url(url)


def test_dots_inside_a_segment_are_fine():
    assert is_allowed_api_url(f"{PREFIX}/patients/abc/cdts/cdt.v2..x/1")


def test_api_url_with_trailing_slash_still_allows_webhook_urls(monkeypatch):
    monkeypatch.setattr(settings, "API_URL", f"{API_URL}/")
    assert is_allowed_api_url(GOOD_URL)
    assert not is_allowed_api_url(f"{API_URL}//{TENANT}/{INSTANCE}/x")


def test_http_api_url_is_never_allowed(monkeypatch):
    """A misconfigured http:// API_URL must not make us send the token over plaintext."""
    monkeypatch.setattr(settings, "API_URL", "http://api.live.welkincloud.io")
    assert not is_allowed_api_url(f"http://api.live.welkincloud.io/{TENANT}/{INSTANCE}/x")


@pytest.mark.parametrize("field", ["API_URL", "API_TENANT", "API_INSTANCE"])
def test_blocks_everything_when_settings_missing(monkeypatch, field):
    monkeypatch.setattr(settings, field, "")
    assert not is_allowed_api_url(GOOD_URL)
    assert not is_allowed_api_url("https://evil.com/")


# --- ApiService.get_resource: second line of defence --------------------------------------------


class _FakeTokenService:
    def __init__(self):
        self.calls = 0

    async def get_token(self, force_refresh: bool = False) -> str:
        self.calls += 1
        return "Bearer secret-token"


def _api_service(requests: list[httpx.Request]) -> tuple[ApiService, _FakeTokenService]:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    tokens = _FakeTokenService()
    return ApiService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), tokens), tokens


@pytest.mark.parametrize("url", BLOCKED.values(), ids=BLOCKED.keys())
def test_get_resource_never_sends_token_outside_welkin(url):
    requests: list[httpx.Request] = []
    api, tokens = _api_service(requests)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.get_resource(url))

    assert exc.value.status_code == 400
    assert requests == []
    assert tokens.calls == 0


def test_get_resource_sends_token_to_welkin():
    requests: list[httpx.Request] = []
    api, _ = _api_service(requests)

    asyncio.run(api.get_resource(GOOD_URL))

    assert len(requests) == 1
    assert str(requests[0].url) == GOOD_URL
    assert requests[0].headers["Authorization"] == "Bearer secret-token"


# --- /webhook_reconciliation endpoint ------------------------------------------------------------


class _FakeMedicationService:
    def __init__(self):
        self.fetched: list[str] = []

    async def fetch_stays_record(self, url: str, patient_id: str):
        self.fetched.append(url)
        raise AssertionError("should not be reached in these tests")


def _payload(url: str) -> dict:
    return {
        "sourceId": "src",
        "instanceName": INSTANCE,
        "patientId": "patient",
        "initiatedByObjectType": "x",
        "url": url,
        "initiatedByName": "x",
        "eventSubtype": "x",
        "initiatedByObjectId": "x",
        "tenantName": TENANT,
        "eventEntity": "x",
        "initiatedTime": "x",
        "initiatedByClientType": "x",
        "sourceName": "x",
        "initiatedBy": "x",
    }


@pytest.fixture
def client_and_service():
    service = _FakeMedicationService()
    app.dependency_overrides[medication_service_client] = lambda: service
    try:
        yield TestClient(app), service
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("url", BLOCKED.values(), ids=BLOCKED.keys())
def test_reconciliation_skips_untrusted_url(client_and_service, url):
    client, service = client_and_service

    resp = client.post("/webhook_reconciliation", json=_payload(url))

    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"
    assert service.fetched == []


def test_reconciliation_fetches_welkin_url(client_and_service):
    client, service = client_and_service

    with pytest.raises(AssertionError, match="should not be reached"):
        client.post("/webhook_reconciliation", json=_payload(GOOD_URL))

    assert service.fetched == [GOOD_URL]


# --- schedule record must belong to the webhook's patient ---------------------------------------


def _stays_service(record_patient_id: str) -> MedicationService:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "22222222",
                "patientId": record_patient_id,
                "cdtId": "cdt",
                "version": 1,
                "jsonBody": {},
                "cdtName": "cdt-weekend-schedule",
            },
        )

    api = ApiService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), _FakeTokenService())
    return MedicationService(api)


def test_fetch_stays_record_rejects_other_patients_record():
    service = _stays_service(record_patient_id="other-patient")
    assert asyncio.run(service.fetch_stays_record(GOOD_URL, "patient")) is None


def test_fetch_stays_record_returns_matching_patients_record():
    service = _stays_service(record_patient_id="patient")
    assert asyncio.run(service.fetch_stays_record(GOOD_URL, "patient")) is not None


def test_reconciliation_skips_when_schedule_is_for_other_patient():
    app.dependency_overrides[medication_service_client] = lambda: _stays_service(record_patient_id="other-patient")
    try:
        resp = TestClient(app).post("/webhook_reconciliation", json=_payload(GOOD_URL))
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "skipped",
        "reason": "cdt-weekend-schedule record belongs to a different patient",
    }
