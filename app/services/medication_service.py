import asyncio
import datetime
import logging
from typing import Any, Optional

import httpx
from fastapi import HTTPException, status
from pydantic import ValidationError

from app.models.assessment_med_body import AssessmentMedBody
from app.models.cdt_client_medication_list_payload import CdtClientMedicationListPayload
from app.models.cdt_list_response import CdtListResponse, CdtRecord
from app.models.cdt_medications_payload import CdtMedicationsPayload
from app.models.client_medication_body import ClientMedicationBody
from app.models.my_stays_body import MyStaysBody
from app.services.api_service import ApiService
from app.utils.utils import date_range, iso_midnight_utc, parse_welkin_date

logger = logging.getLogger(__name__)


class MedicationService:
    """Handles all medication-related business logic.

    Responsible for:
    - Fetching medications filled by parents in the assessment (cdt-med-1..20).
    - Script 1: writing each medication once to cdt-client-medication-list.
    - Script 2: reading stay dates + meds, writing dated dose records to cdt-medications.

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
    def _frequency_count(cls, frequency_selector: Optional[str], frequency_other: Optional[str]) -> int:
        """Return the number of doses per day for a medication.

        Handles the named selector values and the "Other" free-text case.
        Clamps "Other" values to [1, _MAX_FREQUENCY_COUNT].
        """
        if frequency_selector == "Other":
            try:
                return max(1, min(int(frequency_other), cls._MAX_FREQUENCY_COUNT))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 1
        return cls._FREQUENCY_COUNTS.get(frequency_selector, 1)

    @classmethod
    def _cdt_count_for_med(cls, med: AssessmentMedBody) -> int:
        return cls._frequency_count(med.frequency_selector, med.frequency_other)

    def __init__(self, api: ApiService) -> None:
        self._api = api

    # -------------------------------------------------------------------------
    # Assessment fetch (shared by Script 1)
    # -------------------------------------------------------------------------

    async def fetch_assessment_medications(self, patient_id: str, source_id: str) -> list[AssessmentMedBody]:
        """Loop cdt-med-1..20 for the given assessment sourceId.

        Stops at the first CDT whose content is empty — medications are filled
        sequentially so a gap means no further entries exist.

        Returns a list of parsed AssessmentMedBody instances.
        """
        meds: list[AssessmentMedBody] = []

        for cdt_name in self.CDT_MED_NAMES:
            resp = await self._api.get_patient_cdt(patient_id, cdt_name, source_id)
            logger.info(f"[{cdt_name}] response JSON: {resp.json()}")
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
        return str(exc.detail) if isinstance(exc, HTTPException) else str(exc)

    # -------------------------------------------------------------------------
    # Script 1 — write each medication once to cdt-client-medication-list
    # -------------------------------------------------------------------------

    async def _post_one_client_med(
        self, patient_id: str, i: int, med: AssessmentMedBody, semaphore: asyncio.Semaphore
    ) -> dict:
        source = f"cdt-client-medication-list-{i + 1}"
        payload = CdtClientMedicationListPayload.from_assessment_med(med)
        body = payload.model_dump(by_alias=True, exclude_none=True)
        try:
            async with semaphore:
                resp = await self._api.post_cdt(patient_id, body, "cdt-client-medication-list")
            resp.raise_for_status()
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

    # -------------------------------------------------------------------------
    # Script 2 — reconciliation: read stay + meds, write dated dose records
    # -------------------------------------------------------------------------

    async def fetch_stays_record(self, stays_url: str) -> MyStaysBody:
        """GET the cdt-my-stays record directly by its URL (from webhook payload.url).

        The webhook URL points to the single-record endpoint (.../cdts/cdt-my-stays/{id}),
        which returns a bare CdtRecord (not a paginated list).
        """
        resp = await self._api.get_resource(stays_url)
        record = CdtRecord.model_validate(resp.json())
        return MyStaysBody.model_validate(record.jsonBody)

    async def fetch_client_medications(self, patient_id: str) -> list[ClientMedicationBody]:
        """GET all cdt-client-medication-list records for the patient (no sourceId filter).

        Returns every medication written by Script 1 across all assessments.
        """
        resp = await self._api.get_all_patient_cdts(patient_id, "cdt-client-medication-list")
        cdt_list = CdtListResponse.model_validate(resp.json())
        meds = [ClientMedicationBody.model_validate(r.jsonBody) for r in cdt_list.data.content]
        logger.info(f"[cdt-client-medication-list] fetched {len(meds)} medication(s) for patient {patient_id}")
        return meds

    async def fetch_assessment_med_refs(
        self, patient_id: str, target_ids: frozenset[str]
    ) -> dict[str, Any]:
        """Build a map of {medication_id → full_auth_medication_dict} from cdt-med-* CDTs.

        cdt-client-medication-list/cdtf-authorized-medication (pdt-medications) is normalised by
        Welkin to {"id": "..."} on read, losing the fields required by cdt-medications/cdtf-auth-medication
        (pdt-medispan, which requires pdtf-mf2-tc-gpi_full-gpi_tcgpi-name).

        Fetches cdt-med-{n} in order without a sourceId filter (so all assessments are covered) and
        stops as soon as every id in target_ids has been resolved — typically 2–3 GETs for a patient
        with a small number of medications rather than the full 20.  Falls back to stopping at the
        first empty CDT (medications are filled sequentially, so a gap means no further entries exist).
        """
        ref_map: dict[str, Any] = {}
        for cdt_name in self.CDT_MED_NAMES:
            if target_ids and ref_map.keys() >= target_ids:
                logger.info(
                    f"[assessment-med-refs] all {len(target_ids)} target id(s) resolved "
                    f"before reaching {cdt_name} — stopping early"
                )
                break

            resp = await self._api.get_all_patient_cdts(patient_id, cdt_name)
            logger.info(f"[assessment-med-refs][{cdt_name}] response JSON: {resp.json()}")
            cdt_list = CdtListResponse.model_validate(resp.json())

            if not cdt_list.data.content:
                logger.info(f"[assessment-med-refs] {cdt_name} is empty — stopping early")
                break

            for record in cdt_list.data.content:
                try:
                    med = AssessmentMedBody.model_validate(record.jsonBody)
                except ValidationError as exc:
                    logger.warning(
                        f"[assessment-med-refs] skipping record id={record.id!r} in {cdt_name}: "
                        f"validation failed — {exc}"
                    )
                    continue
                if med.auth_medication and isinstance(med.auth_medication, dict):
                    med_id = med.auth_medication.get("id")
                    if med_id and med_id not in ref_map:
                        ref_map[med_id] = med.auth_medication

        logger.info(f"[assessment-med-refs] built reference map with {len(ref_map)} unique medication id(s)")
        return ref_map

    async def _post_reconciled_med(
        self,
        patient_id: str,
        med: ClientMedicationBody,
        administer_date: str,
        semaphore: asyncio.Semaphore,
        auth_medication_override: Optional[dict[str, Any]] = None,
    ) -> dict:
        payload = CdtMedicationsPayload.from_client_medication(
            med, administer_date, auth_medication_override=auth_medication_override
        )
        body = payload.model_dump(by_alias=True, exclude_none=True)
        try:
            async with semaphore:
                resp = await self._api.post_cdt(patient_id, body, "cdt-medications")
            resp.raise_for_status()
            return {"ok": {"date": administer_date, "status": resp.status_code}}
        except (httpx.HTTPError, HTTPException) as exc:
            msg = self._exc_message(exc)
            logger.error(f"[cdt-medications] reconciliation failed date={administer_date}: {msg}")
            return {"err": {"date": administer_date, "error": msg}}

    async def create_reconciled_medications(
        self,
        patient_id: str,
        meds: list[ClientMedicationBody],
        stays: MyStaysBody,
    ) -> tuple[list[dict], list[dict]]:
        """Script 2 core: POST one cdt-medications record per medication × dose × day.

        For each medication, for each date in [start_date..end_date], posts
        frequency-count copies with cdtf-med-administer-date set to that date.

        Example: Tylenol 2×/day, stay May 20–21 → 4 records total.
        """
        try:
            start = parse_welkin_date(stays.start_date)
            end = parse_welkin_date(stays.end_date)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

        dates = date_range(start, end)

        logger.info(
            f"[reconciliation] stay {stays.start_date} → {stays.end_date} "
            f"({len(dates)} day(s)), {len(meds)} medication(s)"
        )

        # Build a {medication_id → full pdt-medispan dict} map from cdt-med-* CDTs.
        # cdt-client-medication-list/cdtf-authorized-medication (pdt-medications) is normalised to
        # {"id": "..."} by Welkin on read, so we must re-fetch the full reference from the source CDTs.
        target_ids = frozenset(
            med.authorized_medication["id"]
            for med in meds
            if isinstance(med.authorized_medication, dict) and med.authorized_medication.get("id")
        )
        med_refs = await self.fetch_assessment_med_refs(patient_id, target_ids)

        semaphore = asyncio.Semaphore(self._MAX_CONCURRENCY)
        tasks = []
        for med in meds:
            if med.authorized_medication is None:
                continue
            # Resolve the full pdt-medispan reference; fall back to the normalised dict if not found
            med_id = med.authorized_medication.get("id") if isinstance(med.authorized_medication, dict) else None
            full_auth = med_refs.get(med_id) if med_id else None
            if full_auth is None:
                logger.warning(
                    f"[reconciliation] no full pdt-medispan ref found for medication id={med_id!r}; "
                    "posting with normalised reference — may fail validation"
                )
            freq = self._frequency_count(med.frequency_selector, med.frequency_other)
            for date in dates:
                administer_date = iso_midnight_utc(datetime.datetime.combine(date, datetime.time.min))
                for _ in range(freq):
                    tasks.append(
                        self._post_reconciled_med(
                            patient_id, med, administer_date, semaphore, auth_medication_override=full_auth
                        )
                    )

        _TASK_WARN_THRESHOLD = 200
        if len(tasks) > _TASK_WARN_THRESHOLD:
            logger.warning(
                f"[reconciliation] large task batch: {len(tasks)} cdt-medications records "
                f"({len(meds)} meds × {len(dates)} days); verify stay dates are correct"
            )
        else:
            logger.info(f"[reconciliation] posting {len(tasks)} cdt-medications record(s)")
        results = await asyncio.gather(*tasks)
        created = [r["ok"] for r in results if "ok" in r]
        errors = [r["err"] for r in results if "err" in r]
        return created, errors

    # -------------------------------------------------------------------------
    # Legacy — kept for reference; not called by any active endpoint
    # -------------------------------------------------------------------------

    async def _post_one_cdt(self, patient_id: str, i: int, med: AssessmentMedBody, semaphore: asyncio.Semaphore) -> dict:
        cdt_med_name = f"cdt-med-{i + 1}"
        payload = CdtMedicationsPayload.from_assessment_med(med)
        body = payload.model_dump(by_alias=True)
        try:
            async with semaphore:
                resp = await self._api.post_cdt(patient_id, body, "cdt-medications")
            resp.raise_for_status()
            return {"ok": {"source": cdt_med_name, "status": resp.status_code}}
        except (httpx.HTTPError, HTTPException) as exc:
            msg = self._exc_message(exc)
            logger.error(f"[cdt-medications] failed for {cdt_med_name}: {msg}")
            return {"err": {"source": cdt_med_name, "error": msg}}

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
