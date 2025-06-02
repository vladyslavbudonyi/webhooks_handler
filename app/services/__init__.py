import httpx
from fastapi import Depends

from app.services.api_service import ApiService
from app.services.token_service import TokenService


async def http_client():
    async with httpx.AsyncClient() as client:
        yield client


async def api_service_client(
    client: httpx.AsyncClient = Depends(http_client),
) -> ApiService:
    token_service_client = TokenService(client)
    return ApiService(client, token_service_client)


__all__ = [
    "api_service_client",
]
