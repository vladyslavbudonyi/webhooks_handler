from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Request, status, Depends, Body
from app.config import settings
from app.models import WebhookPayload
from app.services import api_service_client
from app.services.api_service import ApiService
from app.utils import parse_url_components

app = FastAPI()


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    payload: WebhookPayload = Body(...),
    client: ApiService = Depends(api_service_client),
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
    print(upstream_data)

    cdt_name = upstream_data.get("cdtName")
    json_body = upstream_data.get("jsonBody", {})
    quantity = json_body.get("cdtf-med-quantity")
    med_start_iso = json_body.get("cdtf-med-start-date")
    time_list = json_body.get("cdtf-med--time-of-administration-list") or []
    medispan = json_body.get("cdtf-auth-medication")
    reconcile_status = json_body.get("cdtf-med-reconcile-status")
    internal_note = json_body.get("cdtf-internal-note")

    if not med_start_iso or not medispan or not time_list and reconcile_status != "Reconciled":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"CDT: {cdt_name} - Missing required cdtf or status is not Reconciled",
        )
    try:
        med_start_dt = datetime.fromisoformat(med_start_iso.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid med-start-date format: {med_start_iso}",
        )
    local_tz = ZoneInfo("Europe/Warsaw")
    med_start_local = med_start_dt.astimezone(local_tz).date()
    patient_id = payload.patientId
    created_entries = []
    errors = []
    for entry in time_list:
        try:
            time_obj = datetime.strptime(entry, "%I:%M %p").time()
        except Exception:
            errors.append({"time": entry, "error": "Invalid time format"})
            continue
        local_dt = datetime(
            med_start_local.year,
            med_start_local.month,
            med_start_local.day,
            time_obj.hour,
            time_obj.minute,
            tzinfo=local_tz,
        )
        target_utc = local_dt.astimezone(timezone.utc)
        target_iso = target_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        give_midnight = datetime(
            med_start_local.year, med_start_local.month, med_start_local.day, 0, 0, tzinfo=local_tz
        ).astimezone(timezone.utc)
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
        print(f"CDT payload: {payload_tracker}")
        try:
            resp = await client.post_cdt(patient_id, payload_tracker, "cdt-med-tracker")
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
