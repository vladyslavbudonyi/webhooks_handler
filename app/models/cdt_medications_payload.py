from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.assessment_med_body import AssessmentMedBody
from app.models.constants import ADDED_BY_PARENT

if TYPE_CHECKING:
    from app.models.client_medication_body import ClientMedicationBody


class CdtMedicationsPayload(BaseModel):
    """POST body for the cdt-medications master CDT.

    Field mapping is defined once here via aliases; update this model
    if the upstream API field names change — no changes needed elsewhere.
    """

    model_config = ConfigDict(populate_by_name=True)

    auth_medication: Optional[Any] = Field(None, alias="cdtf-auth-medication")
    quantity: Optional[str] = Field(None, alias="cdtf-med-quantity")
    strength: Optional[str] = Field(None, alias="cdtf-med-strength")
    route: Optional[str] = Field(None, alias="cdtf-route")
    route_other: Optional[str] = Field(None, alias="cdtf-route-other")
    frequency_selector: Optional[str] = Field(None, alias="cdtf-med-frequency-selector")
    frequency_other: Optional[str] = Field(None, alias="cdtf-med-frequency-other")
    total_per_dose: Optional[str] = Field(None, alias="cdtf-total-per-dose")
    parents_comments: Optional[str] = Field(None, alias="cdtf-parents-comments")
    added_by: str = Field(ADDED_BY_PARENT, alias="cdtf-added-by")
    reconcile_status: str = Field(None, alias="cdtf-med-reconcile-status")
    physician_signature: Optional[str] = Field(None, alias="cdtf-physician-signature")
    administer_date: Optional[str] = Field(None, alias="cdtf-med-administer-date")

    @classmethod
    def from_assessment_med(cls, med: AssessmentMedBody) -> "CdtMedicationsPayload":
        """Build a cdt-medications payload from a parsed cdt-med-{n} record.

        Physician signature logic:
          cdtf-discontinued == "Yes"  → cdtf-physician-signature = None  (med is discontinued)
          cdtf-discontinued == None   → cdtf-physician-signature = "Yes" (active medication)
        """
        physician_signature = None if med.discontinued == "Yes" else "Yes"

        return cls(
            auth_medication=med.auth_medication,
            quantity=med.quantity,
            strength=med.strength,
            route=med.route,
            route_other=med.route_other,
            frequency_selector=med.frequency_selector,
            frequency_other=med.frequency_other,
            total_per_dose=med.total_per_dose,
            parents_comments=med.parents_comments,
            physician_signature=physician_signature,
        )

    @classmethod
    def from_client_medication(
        cls,
        med: ClientMedicationBody,
        administer_date: str,
        auth_medication_override: Optional[Any] = None,
    ) -> "CdtMedicationsPayload":
        """Build a cdt-medications payload from a cdt-client-medication-list record (Script 2).

        Called once per dose per day during reconciliation.
        administer_date: ISO datetime string, e.g. "2026-05-30T00:00:00.000Z"

        auth_medication_override: when provided, used instead of med.authorized_medication.
        This is necessary because Welkin normalises cdt-client-medication-list/cdtf-authorized-medication
        (pdt-medications) to {"id": "..."} on read — the full pdt-medispan reference required by
        cdt-medications/cdtf-auth-medication (including pdtf-mf2-tc-gpi_full-gpi_tcgpi-name) must be
        sourced from the original cdt-med-{n} assessment CDT records.
        """
        physician_signature = None if med.discontinued == "Yes" else "Yes"
        return cls(
            auth_medication=auth_medication_override if auth_medication_override is not None else med.authorized_medication,
            quantity=med.quantity,
            strength=med.strength,
            route=med.route,
            route_other=med.route_other,
            frequency_selector=med.frequency_selector,
            frequency_other=med.frequency_other,
            total_per_dose=med.total_per_dose,
            parents_comments=med.parents_comments,
            physician_signature=physician_signature,
            administer_date=administer_date,
        )
