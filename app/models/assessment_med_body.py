from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssessmentMedBody(BaseModel):
    """Parsed jsonBody from a cdt-med-{n} CDT record filled by the parent in the assessment."""

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

    @field_validator(
        "quantity",
        "strength",
        "route",
        "route_other",
        "frequency_selector",
        "frequency_other",
        "total_per_dose",
        "parents_comments",
        "discontinued",
        mode="before",
    )
    @classmethod
    def coerce_to_str(cls, v: Any) -> Optional[str]:
        """Welkin may return numeric defaults for free-text fields; coerce to str."""
        return str(v) if v is not None else None
