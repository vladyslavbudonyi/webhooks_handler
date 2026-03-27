from fastapi import FastAPI, HTTPException, Body, Depends, status

from app.config import settings
from app.models import WebhookPayload
from app.services import medication_service_client
from app.services.medication_service import MedicationService

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook_medications")
async def receive_webhook_medications(
    payload: WebhookPayload = Body(...),
    med_service: MedicationService = Depends(medication_service_client),
):
    print(f"[webhook] received: {payload.model_dump()}")

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

    created, errors = await med_service.create_medications_cdts(payload.patientId, meds)

    return {"status": "ok", "created": created, "errors": errors}


@app.post("/webhook_reconciliation")
async def receive_webhook_reconciliation(
    payload: WebhookPayload = Body(...),
    med_service: MedicationService = Depends(medication_service_client),
):
    pass