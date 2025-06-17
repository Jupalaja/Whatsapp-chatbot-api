from pydantic import BaseModel
from typing import List, Optional

from src.shared.enums import CategoriaClasificacion, InteractionType


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str


class HealthResponse(BaseModel):
    status: str
    db_connection: str


class InteractionMessage(BaseModel):
    type: InteractionType
    message: str


class InteractionRequest(BaseModel):
    sessionId: str
    message: InteractionMessage


class InteractionResponse(BaseModel):
    sessionId: str
    messages: List[InteractionMessage]
    toolCall: Optional[str] = None


class CategoriaPuntuacion(BaseModel):
    categoria: CategoriaClasificacion
    puntuacionDeConfianza: float
    razonamiento: str
    indicadoresClave: List[str]


class Clasificacion(BaseModel):
    puntuacionesPorCategoria: List[CategoriaPuntuacion]
    clasificacionPrimaria: str
    clasificacionesAlternativas: List[str]


class TipoDeInteraccionResponse(InteractionResponse):
    clasificacion: Optional[Clasificacion] = None
