import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.services.token_service import TokenService


class ApiService:

    def __init__(self, http_client: httpx.AsyncClient, token_service: TokenService):
        self._client = http_client
        self._token_service = token_service

    async def _post_with_auth_retry(self, url: str, body: dict, error_label: str) -> httpx.Response:
        """POST with automatic token-refresh retry on 401/403.

        Shared by post_tasks and post_cdt to keep auth-retry behaviour consistent.
        """
        token = await self._token_service.get_token()
        headers = {"Content-Type": "application/json", "Authorization": token}

        resp = await self._client.post(url, json=body, headers=headers, timeout=10.0)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                token = await self._token_service.get_token(force_refresh=True)
                headers["Authorization"] = token
                resp = await self._client.post(url, json=body, headers=headers, timeout=10.0)
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc2:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"{error_label} failed after token refresh: {exc2.response.status_code} - {exc2.response.text}",
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"{error_label} failed: {exc.response.status_code} - {exc.response.text}",
                )
        return resp

    async def get_resource(self, resource_url: str) -> httpx.Response:
        token = await self._token_service.get_token()
        headers = {
            "Accept": "application/json",
            "Authorization": token,
        }

        resp = await self._client.get(resource_url, headers=headers, timeout=10.0)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                token = await self._token_service.get_token(force_refresh=True)
                headers["Authorization"] = token
                resp = await self._client.get(resource_url, headers=headers, timeout=10.0)
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc2:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            f"Upstream GET failed after token refresh: "
                            f"{exc2.response.status_code}: {exc2.response.text}"
                        ),
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Upstream GET failed: {exc.response.status_code}: {exc.response.text}",
                )

        return resp

    async def post_tasks(self, task_body: dict) -> httpx.Response:
        url = f"{settings.API_URL}/{settings.API_TENANT}/{settings.API_INSTANCE}/tasks"
        return await self._post_with_auth_retry(url, task_body, "POST tasks")

    async def get_patient_cdt(self, patient_id: str, cdt_name: str, source_id: str) -> httpx.Response:
        """GET /patients/{patient_id}/cdts/{cdt_name}?sourceId={source_id}

        Reuses get_resource for auth + automatic token-refresh logic.
        """
        url = (
            f"{settings.API_URL}/{settings.API_TENANT}/{settings.API_INSTANCE}"
            f"/patients/{patient_id}/cdts/{cdt_name}?sourceId={source_id}"
        )
        return await self.get_resource(url)

    async def post_cdt(self, patient_id: str, cdt_body: dict, cdt_name: str) -> httpx.Response:
        url = f"{settings.API_URL}/{settings.API_TENANT}/{settings.API_INSTANCE}/patients/{patient_id}/cdts/{cdt_name}"
        return await self._post_with_auth_retry(url, cdt_body, f"POST cdt {cdt_name}")

    async def get_all_patient_cdts(self, patient_id: str, cdt_name: str) -> httpx.Response:
        """GET all CDT records for a patient without sourceId filter.

        Used to retrieve the full cdt-client-medication-list for a patient
        regardless of which assessment session created each entry.
        """
        url = f"{settings.API_URL}/{settings.API_TENANT}/{settings.API_INSTANCE}/patients/{patient_id}/cdts/{cdt_name}"
        return await self.get_resource(url)
