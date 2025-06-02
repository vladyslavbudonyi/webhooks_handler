from pydantic import BaseModel


class WebhookPayload(BaseModel):
    sourceId: str
    instanceName: str
    patientId: str
    initiatedByObjectType: str
    url: str
    initiatedByName: str
    eventSubtype: str
    initiatedByObjectId: str
    tenantName: str
    eventEntity: str
    initiatedTime: str
    initiatedByClientType: str
    sourceName: str
    initiatedBy: str
