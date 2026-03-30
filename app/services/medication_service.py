import asyncio
import logging

from app.models.assessment_med_body import AssessmentMedBody
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

    async def _post_one_cdt(self, patient_id: str, i: int, med: AssessmentMedBody) -> dict:
        cdt_med_name = f"cdt-med-{i + 1}"
        payload = CdtMedicationsPayload.from_assessment_med(med)
        body = payload.model_dump(by_alias=True)
        try:
            resp = await self._api.post_cdt(patient_id, body, "cdt-medications")
            resp.raise_for_status()
            return {"ok": {"source": cdt_med_name, "status": resp.status_code}}
        except Exception as exc:
            return {"err": {"source": cdt_med_name, "error": str(exc)}}

    async def create_medications_cdts(self, patient_id: str, meds: list[AssessmentMedBody]) -> tuple[list, list]:
        """POST a cdt-medications record for every parsed medication (concurrent).

        Returns (created, errors) where each entry contains the source cdt-med name
        and either the HTTP status code or the error message.
        """
        results = await asyncio.gather(*[self._post_one_cdt(patient_id, i, m) for i, m in enumerate(meds)])
        created = [r["ok"] for r in results if "ok" in r]
        errors = [r["err"] for r in results if "err" in r]
        return created, errors
