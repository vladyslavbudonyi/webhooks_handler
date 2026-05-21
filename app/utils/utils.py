import datetime
import logging
from typing import Tuple
from urllib.parse import urlparse

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def parse_url_components(full_url: str) -> Tuple[str, str, str]:
    parsed = urlparse(full_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    parts = parsed.path.lstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Expected at least tenant/instance in URL path: {full_url}")
    tenant = parts[0]
    instance = parts[1]
    return base, tenant, instance


def get_cdt_value(json_body, key, default=None):
    return json_body.get(key, default)


def calculate_total_days(duration, duration_unit):
    try:
        duration_int = int(duration)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid duration value: {duration}"
        )
    unit_lower = duration_unit.strip().lower()
    if unit_lower in ("day", "days"):
        total_days = duration_int
    elif unit_lower in ("month", "months"):
        total_days = duration_int * 30
    else:
        total_days = 1
    if total_days < 1:
        total_days = 1
    return total_days, duration_int


def build_description(dosage_per_unit, medication_name, times_per_unit, duration_int, duration_unit):
    if all([dosage_per_unit, medication_name, times_per_unit]):
        return (
            f"Take {times_per_unit}× {medication_name} "
            f"({dosage_per_unit}) {times_per_unit} times per day for {duration_int} {duration_unit.lower()}"
        )
    else:
        return f"{medication_name or 'Medication'} – {duration_int} {duration_unit.lower()}"


def iso_midnight_utc(dt: datetime.datetime) -> str:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def parse_welkin_date(s: str | None) -> datetime.date:
    """Parse a Welkin ISO datetime string (e.g. "2026-05-30T00:00:00.000Z") to a date.

    Raises ValueError with a descriptive message if the value is missing or malformed.
    """
    if not s:
        raise ValueError("stay date is missing or empty; expected an ISO 8601 string")
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"invalid stay date format: {s!r}; expected an ISO 8601 string") from exc


def date_range(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Return all dates from start to end inclusive.

    If end is before start (data error), logs a warning and returns [start] so
    callers always receive at least one date rather than silently getting nothing.
    """
    if end < start:
        logger.warning("date_range called with end (%s) < start (%s); returning [start] only", end, start)
        return [start]
    days = (end - start).days + 1
    return [start + datetime.timedelta(days=i) for i in range(days)]
