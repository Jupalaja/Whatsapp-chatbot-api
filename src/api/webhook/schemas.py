from pydantic import BaseModel
from typing import List, Optional


class WebhookMessageContextInfo(BaseModel):
    senderKeyHash: Optional[str] = None


class WebhookMessage(BaseModel):
    conversation: Optional[str] = None
    messageContextInfo: Optional[WebhookMessageContextInfo] = None


class WebhookKey(BaseModel):
    remoteJid: str
    fromMe: bool
    id: str


class WebhookData(BaseModel):
    key: WebhookKey
    message: Optional[WebhookMessage] = None


class WebhookBody(BaseModel):
    event: str
    data: WebhookData


class WebhookEvent(BaseModel):
    body: WebhookBody


WebhookPayload = List[WebhookEvent]
