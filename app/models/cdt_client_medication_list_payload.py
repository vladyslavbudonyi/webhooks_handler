from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.assessment_med_body import AssessmentMedBody
from app.models.constants import ADDED_BY_PARENT, DISCONTINUED_DEFAULT, LOW_INVENTORY_DEFAULT, PHYS_SIG_DEFAULT


class CdtClientMedicationListPayload(BaseModel):
    """POST body for the cdt-client-medication-list CDT.

    Written once per medication when the family's asm-medication-list is submitted.
    Does not include reconciliation or physician-signature fields — those belong to Script 2.
    """

    model_config = ConfigDict(populate_by_name=True)

    authorized_medication: Optional[Any] = Field(None, alias="cdtf-authorized-medications")
    quantity: Optional[str] = Field(None, alias="cdtf-med-quantity")
    strength: Optional[str] = Field(None, alias="cdtf-med-strength")
    route: Optional[str] = Field(None, alias="cdtf-route")
    route_other: Optional[str] = Field(None, alias="cdtf-route-other")
    frequency_selector: Optional[str] = Field(None, alias="cdtf-med-frequency-selector")
    frequency_other: Optional[int] = Field(None, alias="cdtf-med-frequency-other")
    total_per_dose: Optional[str] = Field(None, alias="cdtf-total-per-dose")
    parents_comments: Optional[str] = Field(None, alias="cdtf-parents-comments")
    discontinued: str = Field(DISCONTINUED_DEFAULT, alias="cdtf-discontinued")
    low_inventory: str = Field(LOW_INVENTORY_DEFAULT, alias="cdtf-low-inventory")
    phys_sig: str = Field(PHYS_SIG_DEFAULT, alias="cdtf-phys-sig")
    scheduled_times: Optional[Any] = Field(None, alias="cdtf-scheduled-times")
    added_by: str = Field(ADDED_BY_PARENT, alias="cdtf-added-by")

    @classmethod
    def from_assessment_med(cls, med: AssessmentMedBody) -> "CdtClientMedicationListPayload":
        # Pass the full auth_medication object unchanged (including pdtf-mf2-tc-gpi_full-gpi_tcgpi-name).
        # cdt-medications/cdtf-auth-medication (pdt-medispan) requires this field when writing,
        # so Script 2 needs the complete reference available when it reads from this CDT.
        return cls(
            authorized_medication=med.auth_medication,
            quantity=med.quantity,
            strength=med.strength,
            route=med.route,
            route_other=med.route_other,
            frequency_selector=med.frequency_selector,
            frequency_other=int(med.frequency_other) if med.frequency_other is not None else None,
            total_per_dose=med.total_per_dose,
            parents_comments=med.parents_comments,
            scheduled_times=med.scheduled_times,
        )
