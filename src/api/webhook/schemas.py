from pydantic import BaseModel
from typing import List, Optional


class WebhookDeviceListMetadata(BaseModel):
    senderKeyHash: Optional[str] = None


class WebhookMessageContextInfo(BaseModel):
    deviceListMetadata: Optional[WebhookDeviceListMetadata] = None


class ListResponseMessage(BaseModel):
    title: str


class AudioMessage(BaseModel):
    pass


class ImageMessage(BaseModel):
    pass


class videoMessage(BaseModel):
    pass


class WebhookMessage(BaseModel):
    conversation: Optional[str] = None
    messageContextInfo: Optional[WebhookMessageContextInfo] = None
    listResponseMessage: Optional[ListResponseMessage] = None
    audioMessage: Optional[AudioMessage] = None
    imageMessage: Optional[ImageMessage] = None
    videoMessage: Optional[videoMessage] = None


class WebhookKey(BaseModel):
    remoteJid: str
    fromMe: bool
    id: str


class WebhookData(BaseModel):
    key: WebhookKey
    message: Optional[WebhookMessage] = None
    pushName: Optional[str] = None
    source: Optional[str] = None


class WebhookEvent(BaseModel):
    event: str
    data: WebhookData


WebhookPayload = List[WebhookEvent]
