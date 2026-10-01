from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class WeekendScheduleBody(BaseModel):
    """Parsed jsonBody from a cdt-weekend-schedule CDT record.

    Dates are stored by Welkin as ISO datetime strings, e.g. "2026-05-30T00:00:00.000Z".
    """

    model_config = ConfigDict(populate_by_name=True)

    start_date: Optional[str] = Field(None, alias="cdtf-start-of-scheduled-stay-date")
    end_date: Optional[str] = Field(None, alias="cdtf-end-of-scheduled-stay-date")
    # Formula field computed by Welkin; drives the number of days written by Script 2.
    length_of_stay: Optional[Any] = Field(None, alias="cdtf-length-of-stay")
    schedule_meds: Optional[str] = Field(None, alias="cdtf-schedule-meds")
