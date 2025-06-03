from datetime import datetime, timezone

import httpx
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
    print(upstream_data)
    json_body = upstream_data.get("jsonBody", {})
    quantity = json_body.get("cdtf-med-quantity")
    med_start_iso = json_body.get("cdtf-med-start-date")
    time_list = json_body.get("cdtf-med--time-of-administration-list") or []
    medispan = json_body.get("cdtf-")
    internal_note = json_body.get("cdtf-internal-note")
    if not med_start_iso or not medispan:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing required cdtf-med-start-date or cdtf-medispan",
        )
    try:
        med_start_dt = datetime.fromisoformat(med_start_iso.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid med-start-date format: {med_start_iso}",
        )
    med_date = med_start_dt.date()
    patient_id = payload.patientId
    created_entries = []
    errors = []
    for entry in time_list:
        try:
            time_obj = datetime.strptime(entry, "%I:%M %p").time()
        except Exception:
            errors.append({"time": entry, "error": "Invalid time format"})
            continue
        combined = datetime(med_date.year, med_date.month, med_date.day, time_obj.hour, time_obj.minute,
                            tzinfo=timezone.utc)
        target_iso = combined.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        give_midnight = datetime(med_date.year, med_date.month, med_date.day, 0, 0, tzinfo=timezone.utc)
        give_iso = give_midnight.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload_tracker = {
            "cdtf-quantity": quantity,
            "cdtf-medispan": medispan,
            "cdtf-target-time": target_iso,
            "cdtf-give-date": give_iso,
            "cdtf-internal-note": internal_note,
            "cdtf-med-sign": False,
            "cdtf-action-taken": "To be given",
        }
        try:
            resp = await client.post_cdt(patient_id, payload_tracker, "cdt-emar-med-tracker")
            resp.raise_for_status()
            created_entries.append({"time": entry, "status": resp.status_code})
        except httpx.HTTPStatusError as exc:
            errors.append({"time": entry, "error": f"{exc.response.status_code} - {exc.response.text}"})
        except Exception as exc:
            errors.append({"time": entry, "error": str(exc)})
    return {
        "status": "ok",
        "entries_created": created_entries,
        "errors": errors,
    }