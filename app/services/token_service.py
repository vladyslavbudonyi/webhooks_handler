import logging
from typing import Optional

import httpx
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level cache — survives across Lambda warm invocations
_cached_token: Optional[str] = None


class TokenService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._client = http_client
        self._settings = settings

    async def _fetch_token(self) -> str:
        url = f"{self._settings.API_URL}/{self._settings.API_TENANT}/admin/api_clients/{self._settings.API_CLIENT}"
        headers = {"Content-Type": "application/json"}
        body = {"secret": self._settings.API_SECRET.get_secret_value()}

        resp = await self._client.post(url, json=body, headers=headers, timeout=10.0)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Auth service returned {exc.response.status_code}: {exc.response.text}",
            )

        payload = resp.json()
        token_value = payload.get("token")
        if not token_value:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Auth response did not contain 'token' field",
            )
        logger.info("fetched new OAuth token")
        return f"Bearer {token_value}"

    async def get_token(self, force_refresh: bool = False) -> str:
        global _cached_token
        if not _cached_token or force_refresh:
            _cached_token = await self._fetch_token()
        return _cached_token
