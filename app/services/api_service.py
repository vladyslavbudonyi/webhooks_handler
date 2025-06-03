import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.services.token_service import TokenService


class ApiService:

    def __init__(self, http_client: httpx.AsyncClient, token_service: TokenService):
        self._client = http_client
        self._token_service = token_service

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
        token = await self._token_service.get_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": token,
        }
        resp = await self._client.post(url, json=task_body, headers=headers, timeout=10.0)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Creating task failed: {exc.response.status_code} - {exc.response.text}",
            )
        return resp

    async def post_cdt(self, patient_id: str, cdt_body: dict, cdt_name: str) -> httpx.Response:
        url = f"{settings.API_URL}/{settings.API_TENANT}/{settings.API_INSTANCE}/patients/{patient_id}/cdts/{cdt_name}"
        token = await self._token_service.get_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": token,
        }
        resp = await self._client.post(url, json=cdt_body, headers=headers, timeout=10.0)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Creating task failed: {exc.response.status_code} - {exc.response.text}",
            )
        return resp
