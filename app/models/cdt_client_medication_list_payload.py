from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.assessment_med_body import AssessmentMedBody
from app.models.constants import ADDED_BY_PARENT


class CdtClientMedicationListPayload(BaseModel):
    """POST body for the cdt-client-medication-list CDT.

    Written once per medication when the family's asm-medication-list is submitted.
    Does not include reconciliation or physician-signature fields — those belong to Script 2.
    """

    model_config = ConfigDict(populate_by_name=True)

    # cdtf-authorized-medication (not cdtf-auth-medication — that's the assessment CDT field name)
    authorized_medication: Optional[Any] = Field(None, alias="cdtf-authorized-medication")
    quantity: Optional[str] = Field(None, alias="cdtf-med-quantity")
    strength: Optional[str] = Field(None, alias="cdtf-med-strength")
    route: Optional[str] = Field(None, alias="cdtf-route")
    route_other: Optional[str] = Field(None, alias="cdtf-route-other")
    frequency_selector: Optional[str] = Field(None, alias="cdtf-med-frequency-selector")
    frequency_other: Optional[str] = Field(None, alias="cdtf-med-frequency-other")
    total_per_dose: Optional[str] = Field(None, alias="cdtf-total-per-dose")
    parents_comments: Optional[str] = Field(None, alias="cdtf-parents-comments")
    # cdtf-discontinued only accepts "Yes"; omit (None) when the med is active
    discontinued: Optional[str] = Field(None, alias="cdtf-discontinued")
    added_by: str = Field(ADDED_BY_PARENT, alias="cdtf-added-by")

    @classmethod
    def from_assessment_med(cls, med: AssessmentMedBody) -> "CdtClientMedicationListPayload":
        # Extract just the id reference; the profile data type differs between CDTs
        med_ref = {"id": med.auth_medication["id"]} if isinstance(med.auth_medication, dict) else med.auth_medication
        # Only write discontinued when explicitly "Yes" — the select has no "No" option
        discontinued = "Yes" if med.discontinued == "Yes" else None
        return cls(
            authorized_medication=med_ref,
            quantity=med.quantity,
            strength=med.strength,
            route=med.route,
            route_other=med.route_other,
            frequency_selector=med.frequency_selector,
            frequency_other=med.frequency_other,
            total_per_dose=med.total_per_dose,
            parents_comments=med.parents_comments,
            discontinued=discontinued,
        )
