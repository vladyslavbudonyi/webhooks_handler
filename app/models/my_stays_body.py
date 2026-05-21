from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class MyStaysBody(BaseModel):
    """Parsed jsonBody from a cdt-my-stays CDT record.

    Dates are stored by Welkin as ISO datetime strings, e.g. "2026-05-30T00:00:00.000Z".
    """

    model_config = ConfigDict(populate_by_name=True)

    start_date: Optional[str] = Field(None, alias="cdtf-start-date")
    end_date: Optional[str] = Field(None, alias="cdtf-end-date")
    # Formula field computed by Welkin; not used for date generation (we use the actual dates).
    length_of_stay: Optional[Any] = Field(None, alias="cdtf-length-of-stay")
    med_list_received: Optional[str] = Field(None, alias="cdtf-med-list-received")
