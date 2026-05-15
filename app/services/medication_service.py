import asyncio
import logging

import httpx
from fastapi import HTTPException

from app.models.assessment_med_body import AssessmentMedBody
from app.models.cdt_client_medication_list_payload import CdtClientMedicationListPayload
from app.models.cdt_list_response import CdtListResponse
from app.models.cdt_medications_payload import CdtMedicationsPayload
from app.services.api_service import ApiService

logger = logging.getLogger(__name__)


class MedicationService:
    """Handles all medication-related business logic.

    Responsible for:
    - Fetching medications filled by parents in the assessment (cdt-med-1..20).
    - Creating master cdt-medications CDT records for doctor review.

    Single Responsibility: this class contains no HTTP or framework details;
    all network calls are delegated to ApiService.
    """

    CDT_MED_NAMES: list[str] = [f"cdt-med-{i}" for i in range(1, 21)]

    _FREQUENCY_COUNTS: dict[str, int] = {
        "Daily": 1,
        "Twice a day": 2,
        "Three times a day": 3,
        "Four times a day": 4,
        "PRN": 1,
    }

    _MAX_FREQUENCY_COUNT = 100

    @classmethod
    def _cdt_count_for_med(cls, med: AssessmentMedBody) -> int:
        if med.frequency_selector == "Other":
            try:
                return max(1, min(int(med.frequency_other), cls._MAX_FREQUENCY_COUNT))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 1
        return cls._FREQUENCY_COUNTS.get(med.frequency_selector, 1)

    def __init__(self, api: ApiService) -> None:
        self._api = api

    async def fetch_assessment_medications(self, patient_id: str, source_id: str) -> list[AssessmentMedBody]:
        """Loop cdt-med-1..20 for the given assessment sourceId.

        Stops at the first CDT whose content is empty — medications are filled
        sequentially so a gap means no further entries exist.

        Returns a list of parsed AssessmentMedBody instances.
        """
        meds: list[AssessmentMedBody] = []

        for cdt_name in self.CDT_MED_NAMES:
            resp = await self._api.get_patient_cdt(patient_id, cdt_name, source_id)
            cdt_list = CdtListResponse.model_validate(resp.json())

            logger.info(f"[{cdt_name}] content count: {len(cdt_list.data.content)}")

            if cdt_list.data.empty or not cdt_list.data.content:
                break

            med = AssessmentMedBody.model_validate(cdt_list.data.content[0].jsonBody)
            logger.info(f"[{cdt_name}] parsed med: {med}")
            meds.append(med)

        return meds

    # Max concurrent CDT POSTs — keeps load on the downstream API controlled.
    _MAX_CONCURRENCY = 5

    @staticmethod
    def _exc_message(exc: Exception) -> str:
        return exc.detail if isinstance(exc, HTTPException) else str(exc)

    async def _post_one_cdt(self, patient_id: str, i: int, med: AssessmentMedBody, semaphore: asyncio.Semaphore) -> dict:
        cdt_med_name = f"cdt-med-{i + 1}"
        payload = CdtMedicationsPayload.from_assessment_med(med)
        body = payload.model_dump(by_alias=True)
        try:
            async with semaphore:
                resp = await self._api.post_cdt(patient_id, body, "cdt-medications")
            return {"ok": {"source": cdt_med_name, "status": resp.status_code}}
        except (httpx.HTTPError, HTTPException) as exc:
            msg = self._exc_message(exc)
            logger.error(f"[cdt-medications] failed for {cdt_med_name}: {msg}")
            return {"err": {"source": cdt_med_name, "error": msg}}

    async def _post_one_client_med(
        self, patient_id: str, i: int, med: AssessmentMedBody, semaphore: asyncio.Semaphore
    ) -> dict:
        source = f"cdt-client-medication-list-{i + 1}"
        payload = CdtClientMedicationListPayload.from_assessment_med(med)
        body = payload.model_dump(by_alias=True, exclude_none=True)
        try:
            async with semaphore:
                resp = await self._api.post_cdt(patient_id, body, "cdt-client-medication-list")
            return {"ok": {"source": source, "status": resp.status_code}}
        except (httpx.HTTPError, HTTPException) as exc:
            msg = self._exc_message(exc)
            logger.error(f"[cdt-client-medication-list] failed for {source}: {msg}")
            return {"err": {"source": source, "error": msg}}

    async def create_client_medication_list(
        self, patient_id: str, meds: list[AssessmentMedBody]
    ) -> tuple[list[dict], list[dict]]:
        """POST one cdt-client-medication-list record per medication (Script 1).

        Skips medications where auth_medication is None.
        Each medication is written exactly once — no frequency multiplication.
        """
        semaphore = asyncio.Semaphore(self._MAX_CONCURRENCY)
        tasks = [
            self._post_one_client_med(patient_id, i, med, semaphore)
            for i, med in enumerate(meds)
            if med.auth_medication is not None
        ]
        results = await asyncio.gather(*tasks)
        created = [r["ok"] for r in results if "ok" in r]
        errors = [r["err"] for r in results if "err" in r]
        return created, errors

    async def create_medications_cdts(self, patient_id: str, meds: list[AssessmentMedBody]) -> tuple[list, list]:
        """POST cdt-medications records for every parsed medication (concurrent, bounded).

        Skips medications where auth_medication is None.
        Creates N records per medication based on frequency_selector.
        Concurrency is capped at _MAX_CONCURRENCY to avoid overwhelming the downstream API.
        Returns (created, errors) where each entry contains the source cdt-med name
        and either the HTTP status code or the error message.
        """
        semaphore = asyncio.Semaphore(self._MAX_CONCURRENCY)
        tasks = []
        task_index = 0
        for i, med in enumerate(meds):
            if med.auth_medication is None:
                continue
            count = self._cdt_count_for_med(med)
            for _ in range(count):
                tasks.append(self._post_one_cdt(patient_id, task_index, med, semaphore))
                task_index += 1
        results = await asyncio.gather(*tasks)
        created = [r["ok"] for r in results if "ok" in r]
        errors = [r["err"] for r in results if "err" in r]
        return created, errors
