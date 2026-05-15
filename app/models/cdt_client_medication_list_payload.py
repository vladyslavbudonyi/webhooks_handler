from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.assessment_med_body import AssessmentMedBody


class CdtClientMedicationListPayload(BaseModel):
    """POST body for the cdt-client-medication-list CDT.

    Written once per medication when the family's asm-medication-list is submitted.
    Does not include reconciliation or physician-signature fields — those belong to Script 2.
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
    discontinued: Optional[str] = Field(None, alias="cdtf-discontinued")
    added_by: str = Field("Parent", alias="cdtf-added-by")

    @classmethod
    def from_assessment_med(cls, med: AssessmentMedBody) -> "CdtClientMedicationListPayload":
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
            discontinued=med.discontinued,
        )
