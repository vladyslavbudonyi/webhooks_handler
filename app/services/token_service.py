import asyncio
import logging
from typing import Optional

import httpx
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level cache — survives across Lambda warm invocations
_cached_token: Optional[str] = None

# Created lazily on first use so it's always bound to the running event loop.
# Asyncio's cooperative scheduling makes the None-check + assignment atomic.
_token_refresh_lock: Optional[asyncio.Lock] = None


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
        logger.info(f"token value: Bearer {token_value}")
        return f"Bearer {token_value}"

    async def get_token(self, force_refresh: bool = False) -> str:
        global _cached_token, _token_refresh_lock
        # Fast path — return cached token without acquiring the lock
        if _cached_token and not force_refresh:
            return _cached_token
        # Lazy init: always bound to the currently running event loop
        if _token_refresh_lock is None:
            _token_refresh_lock = asyncio.Lock()
        # Slow path — only one coroutine should fetch at a time
        async with _token_refresh_lock:
            # Re-check inside the lock: another coroutine may have already refreshed
            if _cached_token and not force_refresh:
                return _cached_token
            _cached_token = await self._fetch_token()
            return _cached_token
