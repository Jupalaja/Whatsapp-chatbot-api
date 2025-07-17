from datetime import datetime, timezone

from pydantic import BaseModel, Field
from typing import List, Literal, Optional

from src.shared.enums import InteractionType, CategoriaClasificacion


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str


class HealthResponse(BaseModel):
    status: str
    db_connection: str
    sheets_connection: str


class InteractionMessage(BaseModel):
    role: InteractionType
    message: str
    tool_calls: Optional[List[str]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InteractionRequest(BaseModel):
    sessionId: str = Field(..., min_length=4)
    message: InteractionMessage
    userData: Optional[dict] = None


class InteractionResponse(BaseModel):
    sessionId: str
    messages: List[InteractionMessage]
    toolCall: Optional[str] = None
    state: Optional[str] = None
    classifiedAs: Optional[CategoriaClasificacion] = None


CategoriaClasificacionLiteral = Literal[
    "CLIENTE_POTENCIAL",
    "CLIENTE_ACTIVO",
    "TRANSPORTISTA_TERCERO",
    "PROVEEDOR_POTENCIAL",
    "USUARIO_ADMINISTRATIVO",
    "CANDIDATO_A_EMPLEO",
]


class CategoriaPuntuacion(BaseModel):
    categoria: CategoriaClasificacionLiteral
    puntuacionDeConfianza: float
    razonamiento: str
    indicadoresClave: Optional[List[str]] = None


class Clasificacion(BaseModel):
    puntuacionesPorCategoria: List[CategoriaPuntuacion]
    clasificacionPrimaria: CategoriaClasificacionLiteral
    clasificacionesAlternativas: List[CategoriaClasificacionLiteral]


class TipoDeInteraccionResponse(InteractionResponse):
    clasificacion: Optional[Clasificacion] = None
