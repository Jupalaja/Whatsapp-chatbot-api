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
    type: Literal["user", "assistant", "tool"]
    message: str

class InteractionRequest(BaseModel):
    sessionId: str
    message: InteractionMessage

class InteractionResponse(BaseModel):
    sessionId: str
    messages: List[InteractionMessage]
    toolCall: Optional[str] = None

class CategoriaPuntuacion(BaseModel):
    categoria: Literal[
        "CLIENTE_POTENCIAL",
        "CLIENTE_ACTIVO",
        "TRANSPORTISTA_TERCERO",
        "PROVEEDOR_POTENCIAL",
        "USUARIO_ADMINISTRATIVO",
        "CANDIDATO_A_EMPLEO",
    ]
    puntuacionDeConfianza: float
    razonamiento: str
    indicadoresClave: List[str]

class Clasificacion(BaseModel):
    puntuacionesPorCategoria: List[CategoriaPuntuacion]
    clasificacionPrimaria: str
    clasificacionesAlternativas: List[str]

class TipoDeInteraccionResponse(InteractionResponse):
    clasificacion: Optional[Clasificacion] = None
