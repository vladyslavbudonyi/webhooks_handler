from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.assessment_med_body import AssessmentMedBody
from app.models.constants import ADDED_BY_PARENT


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
