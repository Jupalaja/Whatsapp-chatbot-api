from pydantic import BaseModel
from typing import List, Literal

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
    sessionID: str
    messages: List[InteractionMessage]

class InteractionResponseMessage(BaseModel):
    type: Literal["user", "assistant"]
    message: str
