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
logging.basicConfig(handlers=[_handler], level=settings.LOG_LEVEL.upper(), force=True)

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
    # Log only non-PHI fields at INFO; patient identifiers and URL stay at DEBUG
    logger.info(
        f"[webhook_reconciliation] sourceId='{payload.sourceId}' tenantName='{payload.tenantName}' "
        f"eventEntity='{payload.eventEntity}' eventSubtype='{payload.eventSubtype}' "
        f"sourceName='{payload.sourceName}' initiatedByClientType='{payload.initiatedByClientType}' "
        f"initiatedTime='{payload.initiatedTime}'"
    )
    logger.debug(
        f"[webhook_reconciliation] patientId='{payload.patientId}' url='{payload.url}' "
        f"initiatedByName='{payload.initiatedByName}' initiatedBy='{payload.initiatedBy}'"
    )

    if payload.tenantName != settings.API_TENANT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tenant mismatch: got '{payload.tenantName}', expected '{settings.API_TENANT}'",
        )

    # Fetch the specific cdt-my-stays record from the URL embedded in the webhook
    stays = await med_service.fetch_stays_record(payload.url)

    if stays.med_list_received != "Yes":
        logger.info(
            f"[webhook_reconciliation] skipping patientId={payload.patientId}: "
            f"cdtf-med-list-received='{stays.med_list_received}'"
        )
        return {"status": "skipped", "reason": "cdtf-med-list-received is not Yes"}

    if not stays.start_date or not stays.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cdt-my-stays record is missing cdtf-start-date or cdtf-end-date",
        )

    meds = await med_service.fetch_client_medications(payload.patientId)

    if not meds:
        return {
            "status": "ok",
            "message": "No medications found in cdt-client-medication-list",
            "created": [],
            "errors": [],
        }

    created, errors = await med_service.create_reconciled_medications(payload.patientId, meds, stays)

    return {"status": "ok", "created": created, "errors": errors}
