import json
import logging

from fastapi import FastAPI, HTTPException, Body, Depends, status

from app.config import settings
from app.models import WebhookPayload
from app.services import medication_service_client
from app.services.medication_service import MedicationService


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "logger": record.name, "msg": record.getMessage()})


_handler = logging.StreamHandler()
_handler.setFormatter(_JsonFormatter())
logging.basicConfig(handlers=[_handler], level=logging.INFO, force=True)

logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook_medications")
async def receive_webhook_medications(
    payload: WebhookPayload = Body(...),
    med_service: MedicationService = Depends(medication_service_client),
):
    logger.info(f"[webhook_medications] received patientId={payload.patientId} sourceId={payload.sourceId}")

    if payload.tenantName != settings.API_TENANT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tenant mismatch: got '{payload.tenantName}', expected '{settings.API_TENANT}'",
        )

    meds = await med_service.fetch_assessment_medications(payload.patientId, payload.sourceId)

    if not meds:
        return {
            "status": "ok",
            "message": "No medications found in assessment",
            "created": [],
            "errors": [],
        }

    created, errors = await med_service.create_client_medication_list(payload.patientId, meds)

    return {"status": "ok", "created": created, "errors": errors}


@app.post("/webhook_reconciliation")
async def receive_webhook_reconciliation(
    payload: WebhookPayload = Body(...),
    med_service: MedicationService = Depends(medication_service_client),
):
    logger.info(f"[webhook_reconciliation] received patientId={payload.patientId} sourceId={payload.sourceId}")
