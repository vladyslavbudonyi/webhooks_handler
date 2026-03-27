import httpx
from fastapi import Depends

from app.services.api_service import ApiService
from app.services.medication_service import MedicationService
from app.services.token_service import TokenService


async def http_client():
    async with httpx.AsyncClient() as client:
        yield client


async def api_service_client(
    client: httpx.AsyncClient = Depends(http_client),
) -> ApiService:
    token_service_client = TokenService(client)
    return ApiService(client, token_service_client)


async def medication_service_client(
    api: ApiService = Depends(api_service_client),
) -> MedicationService:
    return MedicationService(api)


__all__ = [
    "api_service_client",
    "medication_service_client",
]
