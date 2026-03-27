from pydantic import BaseModel


class CdtRecord(BaseModel):
    """A single CDT record returned inside a paginated list response."""

    id: str
    patientId: str
    cdtId: str
    version: int
    jsonBody: dict
    cdtName: str


class CdtListData(BaseModel):
    """Paginated data wrapper from the CDT list API."""

    content: list[CdtRecord]
    empty: bool


class CdtListResponse(BaseModel):
    """Top-level response from GET /patients/{id}/cdts/{name}?sourceId=..."""

    name: str
    data: CdtListData
