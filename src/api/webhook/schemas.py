from pydantic import BaseModel
from typing import List, Optional


class WebhookDeviceListMetadata(BaseModel):
    senderKeyHash: Optional[str] = None


class WebhookMessageContextInfo(BaseModel):
    deviceListMetadata: Optional[WebhookDeviceListMetadata] = None


class ListResponseMessage(BaseModel):
    title: str


class WebhookMessage(BaseModel):
    conversation: Optional[str] = None
    messageContextInfo: Optional[WebhookMessageContextInfo] = None
    listResponseMessage: Optional[ListResponseMessage] = None


class WebhookKey(BaseModel):
    remoteJid: str
    fromMe: bool
    id: str


class WebhookData(BaseModel):
    key: WebhookKey
    message: Optional[WebhookMessage] = None
    pushName: Optional[str] = None


class WebhookEvent(BaseModel):
    event: str
    data: WebhookData


WebhookPayload = List[WebhookEvent]
