from datetime import timedelta, datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Request, status, Depends, Body
from app.config import settings
from app.models import WebhookPayload
from app.services.api_service import ApiService
from app.services.token_service import TokenService
from app.utils.utils import parse_url_components

app = FastAPI()

async def get_http_client():
    async with httpx.AsyncClient() as client:
        yield client

async def get_api_service(
    client: httpx.AsyncClient = Depends(get_http_client),
) -> ApiService:
    token_service = TokenService(client)
    return ApiService(client, token_service)

@app.post("/webhook")
async def receive_webhook(
    request: Request,
    payload: WebhookPayload = Body(...),
    client: ApiService = Depends(get_api_service),
):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")
    try:
        payload = WebhookPayload(**body)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Payload validation error: {e}",
        )
    try:
        base_url, api_tenant, api_instance = parse_url_components(payload.url)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(ve),
        )
    if api_tenant != settings.API_TENANT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook tenant '{api_tenant}' does not match expected '{settings.API_TENANT}'",
        )
    try:
        upstream_resp = await client.get_resource(payload.url)
    except HTTPException as http_exc:
        raise http_exc
    upstream_data = upstream_resp.json()
    json_body = upstream_data.get("jsonBody", {})
    dosage_per_unit = json_body.get("cdtf-dosage-per-unit")
    medication_name = json_body.get("cdtf-medication-name")
    times_per_unit = json_body.get("cdtf-times-per-unit")
    duration = json_body.get("cdtf-duration")
    duration_unit = json_body.get("cdtf-duration-unit")
    if duration is None or duration_unit is None:
        duration = 1
        duration_unit = "Days"
    try:
        duration_int = int(duration)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid duration value: {duration}"
        )
    unit_lower = duration_unit.strip().lower()
    if unit_lower in ("day", "days"):
        total_days = duration_int
    elif unit_lower in ("month", "months"):
        total_days = duration_int * 30
    else:
        total_days = 1
    if total_days < 1:
        total_days = 1
    if all([dosage_per_unit, medication_name, times_per_unit]):
        description = (
            f"Take {times_per_unit}× {medication_name} "
            f"({dosage_per_unit}) {times_per_unit} times per day for {duration_int} {duration_unit.lower()}"
        )
    else:
        description = f"{medication_name or 'Medication'} – {duration_int} {duration_unit.lower()}"
    def iso_midnight_utc(dt: datetime) -> str:
        return (
            dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.000Z")
        )
    today_utc = datetime.now(timezone.utc)
    patient_id = payload.patientId
    initiated_by = payload.initiatedBy
    created_tasks = []
    errors = []
    for i in range(total_days):
        due_date_iso = iso_midnight_utc(today_utc + timedelta(days=i))
        task_payload = {
            "name": "Medication Task",
            "description": description,
            "assignee": {"id": initiated_by},
            "dueDate": due_date_iso,
            "priority": "HIGH",
            "watchersType": "POINT_OF_CONTACT",
            "templateName": "ttmp-task-template",
            "patient": {"id": patient_id},
            "status": "TODO",
        }
        try:
            resp = await client.post_tasks(task_payload)
            created_tasks.append({"day_index": i, "dueDate": due_date_iso, "status": resp.status_code})
        except HTTPException as exc:
            errors.append({"day_index": i, "dueDate": due_date_iso, "error": exc.detail})
    return {
        "status": "ok",
        "message": f"Attempted to create {total_days} task(s).",
        "tasks_created": created_tasks,
        "errors": errors,
    }
