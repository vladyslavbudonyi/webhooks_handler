"""cdt-client-medication-list/cdtf-schedule-y-n.

Script 1 writes "Yes" for every medication; Script 2 only transfers medications whose
current value is "Yes" to cdt-medications.
"""

import asyncio
import json

import httpx

from app.models.assessment_med_body import AssessmentMedBody
from app.models.cdt_client_medication_list_payload import CdtClientMedicationListPayload
from app.models.client_medication_body import ClientMedicationBody
from app.models.weekend_schedule_body import WeekendScheduleBody
from app.services.api_service import ApiService
from app.services.medication_service import MedicationService


class _FakeTokenService:
    async def get_token(self, force_refresh: bool = False) -> str:
        return "token"


def _recording_service() -> tuple[MedicationService, list[tuple[str, dict]]]:
    posted: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append((request.url.path, json.loads(request.content)))
        return httpx.Response(201, json={})

    api = ApiService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), _FakeTokenService())
    return MedicationService(api), posted


def _client_med(name: str, schedule_y_n) -> ClientMedicationBody:
    body = {"cdtf-authorized-medications": {"name": name}, "cdtf-med-frequency-selector": "Daily"}
    if schedule_y_n is not None:
        body["cdtf-schedule-y-n"] = schedule_y_n
    return ClientMedicationBody.model_validate(body)


# --- Script 1 -----------------------------------------------------------------------------------


def test_client_medication_list_payload_defaults_schedule_y_n_to_yes():
    med = AssessmentMedBody.model_validate({"cdtf-authorized-medications": {"name": "Tylenol"}})
    body = CdtClientMedicationListPayload.from_assessment_med(med).model_dump(by_alias=True, exclude_none=True)
    assert body["cdtf-schedule-y-n"] == "Yes"


def test_script1_posts_schedule_y_n_yes_for_every_med():
    service, posted = _recording_service()
    meds = [
        AssessmentMedBody.model_validate({"cdtf-authorized-medications": {"name": n}})
        for n in ("Tylenol", "Advil", "Zyrtec")
    ]

    created, errors = asyncio.run(service.create_client_medication_list("patient", meds))

    assert errors == []
    assert len(created) == 3
    assert [body["cdtf-schedule-y-n"] for _, body in posted] == ["Yes", "Yes", "Yes"]


# --- Script 2 -----------------------------------------------------------------------------------


def test_scheduled_medications_keeps_only_yes():
    meds = [_client_med("A", "Yes"), _client_med("B", "No"), _client_med("C", None), _client_med("D", "yes")]
    assert [m.authorized_medication["name"] for m in MedicationService.scheduled_medications(meds)] == ["A"]


def test_script2_transfers_only_scheduled_meds():
    service, posted = _recording_service()
    meds = MedicationService.scheduled_medications([_client_med("Tylenol", "Yes"), _client_med("Advil", "No")])
    schedule = WeekendScheduleBody.model_validate(
        {"cdtf-start-of-scheduled-stay-date": "2026-05-20", "cdtf-length-of-stay": "2"}
    )

    created, errors = asyncio.run(service.create_reconciled_medications("patient", meds, schedule))

    assert errors == []
    assert len(created) == 2  # Tylenol, daily, 2 days
    assert {body["cdtf-authorized-medications"]["name"] for _, body in posted} == {"Tylenol"}


# --- Webhook end-to-end ---------------------------------------------------------------------------


def test_reconciliation_webhook_posts_only_scheduled_meds(monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app
    from app.services import medication_service_client

    api_url, tenant, instance = "https://api.live.welkincloud.io", "jh", "jills-live"
    monkeypatch.setattr(settings, "API_URL", api_url)
    monkeypatch.setattr(settings, "API_TENANT", tenant)
    monkeypatch.setattr(settings, "API_INSTANCE", instance)
    stays_url = f"{api_url}/{tenant}/{instance}/patients/patient/cdts/cdt-weekend-schedule/stay-1"

    def record(cdt_name: str, body: dict) -> dict:
        return {"id": "r", "patientId": "patient", "cdtId": "c", "version": 1, "jsonBody": body, "cdtName": cdt_name}

    posted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            posted.append(json.loads(request.content))
            return httpx.Response(201, json={})
        if path.endswith("/cdt-weekend-schedule/stay-1"):
            return httpx.Response(
                200,
                json=record(
                    "cdt-weekend-schedule",
                    {
                        "cdtf-schedule-meds": "Yes",
                        "cdtf-start-of-scheduled-stay-date": "2026-05-20",
                        "cdtf-length-of-stay": "1",
                    },
                ),
            )
        if path.endswith("/cdts/cdt-client-medication-list"):
            meds = [
                {"cdtf-authorized-medications": {"name": "Tylenol"}, "cdtf-schedule-y-n": "Yes"},
                {"cdtf-authorized-medications": {"name": "Advil"}, "cdtf-schedule-y-n": "No"},
                {"cdtf-authorized-medications": {"name": "Zyrtec"}},
            ]
            return httpx.Response(
                200,
                json={
                    "name": "cdt-client-medication-list",
                    "data": {"content": [record("cdt-client-medication-list", m) for m in meds], "empty": False},
                },
            )
        return httpx.Response(404, json={})

    service = MedicationService(
        ApiService(httpx.AsyncClient(transport=httpx.MockTransport(handler)), _FakeTokenService())
    )
    app.dependency_overrides[medication_service_client] = lambda: service
    try:
        payload = {
            k: "x"
            for k in (
                "sourceId", "initiatedByObjectType", "initiatedByName", "eventSubtype", "initiatedByObjectId",
                "eventEntity", "initiatedTime", "initiatedByClientType", "sourceName", "initiatedBy",
            )
        }
        payload.update(instanceName=instance, patientId="patient", url=stays_url, tenantName=tenant)
        resp = TestClient(app).post("/webhook_reconciliation", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["created"]) == 1
    assert [b["cdtf-authorized-medications"]["name"] for b in posted] == ["Tylenol"]
