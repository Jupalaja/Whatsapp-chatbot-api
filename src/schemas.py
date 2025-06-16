from pydantic import BaseModel
from typing import List, Literal, Optional

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str

class HealthResponse(BaseModel):
    status: str
    db_connection: str

class InteractionMessage(BaseModel):
    type: Literal["user", "assistant"]
    message: str

class InteractionRequest(BaseModel):
    sessionId: str
    message: InteractionMessage

class InteractionResponse(BaseModel):
    sessionId: str
    messages: List[InteractionMessage]
    toolCall: Optional[str] = None
