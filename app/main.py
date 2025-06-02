from datetime import timedelta, datetime, timezone

from fastapi import FastAPI, HTTPException, Request, status, Depends, Body
from app.config import settings
from app.models import WebhookPayload
from app.services import api_service_client
from app.services.api_service import ApiService
from app.utils import parse_url_components, calculate_total_days, get_cdt_value, build_description, iso_midnight_utc

app = FastAPI()


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    payload: WebhookPayload = Body(...),
    client: ApiService = Depends(api_service_client),
):
    try:
        body = await request.json()
        print(body)
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

    dosage_per_unit = get_cdt_value(json_body, "cdtf-dosage-per-unit")
    medication_name = get_cdt_value(json_body, "cdtf-medication-name")
    times_per_unit = get_cdt_value(json_body, "cdtf-times-per-unit")
    duration = get_cdt_value(json_body, "cdtf-duration")
    duration_unit = get_cdt_value(json_body, "cdtf-duration-unit")
    if duration is None or duration_unit is None:
        duration = 1
        duration_unit = "Days"
    total_days, duration_int = calculate_total_days(duration, duration_unit)
    description = build_description(dosage_per_unit, medication_name, times_per_unit, duration_int, duration_unit)

    today_utc = datetime.now(timezone.utc)
    patient_id = payload.patientId
    initiated_by = payload.initiatedBy
    created_tasks = []
    errors = []
    for i in range(total_days):
        due_date_iso = iso_midnight_utc(today_utc + timedelta(days=i))
        task_payload = {
            "name": description,
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
