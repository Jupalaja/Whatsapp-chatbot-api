import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors, types

from .. import models
from ..db import get_db
from ..schemas import (
    InteractionRequest,
    InteractionMessage,
    TipoDeInteraccionResponse,
    Clasificacion,
    CategoriaPuntuacion,
)

router = APIRouter()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Eres un experto clasificador de mensajes para Botero Soto, una empresa líder en logística y transporte en Colombia.
|**CONTEXTO DE LA EMPRESA:**Botero Soto ofrece servicios logísticos integrales, incluidos el transporte, almacenamiento 
y gestión de la cadena de suministro. La empresa interactúa con diversas partes interesadas a través de diferentes 
canales de comunicación.**TU TAREA:**Analiza el mensaje del usuario y proporciona puntuaciones de confianza para TODAS 
las siguientes categorías. Cada mensaje podría pertenecer potencialmente a múltiples categorías, por lo que debes 
evaluar cada una de manera independiente.
**CATEGORÍAS A EVALUAR:**
   1. **CLIENTE_POTENCIAL** - Nuevos clientes que buscan:
      - Cotizaciones y precios de servicios   
      - Información sobre servicios logísticos   
      - Capacidades de transporte   
      - Información general de la empresa   
      - Contacto inicial para oportunidades de negocio
   2. **CLIENTE_ACTIVO** - Clientes existentes que necesitan:
      - Seguimiento de envíos y actualizaciones de estado
      - Soporte para servicios en curso
      - Resolución de problemas y quejas
      - Cambios en pedidos existentes
      - Gestión de cuentas
   3. **TRANSPORTISTA_TERCERO** 
      - Conductores/transportistas externos que preguntan sobre:  
      - Estado de pago y facturación   
      - Documentación de manifiestos   
      - Problemas y actualizaciones de la aplicación móvil   
      - Asignación de rutas y horarios   
       Registro y cumplimiento de vehículos
   4. **PROVEEDOR_POTENCIAL** - Empresas que ofrecen:   
      - Servicios a Botero Soto   
      - Oportunidades de asociación   
      - Solicitudes de proveedores   
      - Propuestas de negocio   
      - Soluciones para la cadena de suministro
   5. **USUARIO_ADMINISTRATIVO** 
      - Empleados que solicitan:   
      - Documentación legal (certificados, contratos)   
      - Documentos fiscales (formularios de impuestos, estados de ingresos)   
      - Documentación relacionada con RRHH   
      - Soporte administrativo interno   
      - Actualizaciones de datos personales
   6. **CANDIDATO_A_EMPLEO** 
      - Individuos interesados en:   
      - Oportunidades de empleo   
      - Solicitudes de trabajo   
      - Información sobre carreras   
      - Procesos de entrevista   
      - Cultura y beneficios de la empresa
      
    **CRITERIOS DE EVALUACIÓN:** Para cada categoría, considera:
    - **Palabras clave y terminología** utilizadas en el mensaje
    - **Intención y propósito** detrás de la comunicación
    - **Pistas contextuales** sobre la relación del remitente con la empresa
    - **Urgencia y tono** de la solicitud
    - **Referencias específicas** a servicios, procesos o áreas de la empresa
    
    **GUÍA DE PUNTUACIÓN DE CONFIANZA:**
     **0.9-1.0**: Muy alta confianza 
     - indicadores claros y lenguaje específico
     - **0.7-0.8**: Alta confianza 
     - indicadores fuertes con ambigüedad menor
     - **0.5-0.6**: Confianza moderada 
     - algunos indicadores pero podría interpretarse de manera diferente
     - **0.3-0.4**: Baja confianza 
     - indicadores débiles, probablemente no en esta categoría
     - **0.0-0.2**: Muy baja confianza 
     - no hay indicadores claros para esta categoría
     
     **IMPORTANTE:**
     - Sé conservador con las puntuaciones de alta confianza
     - Las puntuaciones NO necesitan sumar 1.0 (un mensaje puede tener alta confianza para múltiples categorías)
     - Proporciona un razonamiento específico para puntuaciones superiores a 0.7
     - Considera que algunos mensajes pueden ser ambiguos o poco claros
"""


def get_human_help():
    """Use this function when the user explicitly asks for human help or to talk to a human."""
    return "A human will be with you shortly."


def clasificar_interaccion(
    puntuacionesPorCategoria: List[CategoriaPuntuacion],
    clasificacionPrimaria: str,
    clasificacionesAlternativas: List[str],
):
    """Clasifica la interacción del usuario en una de varias categorías predefinidas."""
    # This is a dummy function for schema generation for the model.
    # The model will generate the arguments for this function.
    return locals()


@router.post("/tipo-de-interaccion", response_model=TipoDeInteraccionResponse)
async def handle_interaction(
    interaction_request: InteractionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handles a user-assistant interaction, classifying the interaction type,
    continuing a conversation by loading history from the database,
    appending the new message, and saving the updated history.
    """
    client: genai.Client = request.app.state.genai_client

    interaction = await db.get(models.Interaction, interaction_request.sessionId)

    history_messages = []
    if interaction:
        history_messages = [
            InteractionMessage.model_validate(msg) for msg in interaction.messages
        ]

    history_messages.append(interaction_request.message)

    try:
        model = "gemini-1.5-flash-latest"

        genai_history = [
            types.Content(
                role="user" if msg.type == "user" else "model",
                parts=[types.Part(text=msg.message)],
            )
            for msg in history_messages
        ]

        tools = [clasificar_interaccion, get_human_help]
        config = types.GenerateContentConfig(
            tools=tools,
            system_instruction=SYSTEM_PROMPT,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY,
                    allowed_function_names=["clasificar_interaccion"],
                )
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        response = await client.aio.models.generate_content(
            model=model, contents=genai_history, config=config
        )

        assistant_message = None
        tool_call_name = None
        clasificacion = None

        if response.automatic_function_calling_history:
            function_calls = (
                part.function_call
                for content in reversed(response.automatic_function_calling_history)
                if content.role == "model" and content.parts
                for part in content.parts
                if part.function_call
            )
            last_function_call = next(function_calls, None)

            if last_function_call:
                tool_call_name = last_function_call.name
                if tool_call_name == "clasificar_interaccion":
                    clasificacion = Clasificacion.model_validate(
                        last_function_call.args
                    )
                elif tool_call_name == "get_human_help":
                    logger.info(
                        f"The user with sessionId: {interaction_request.sessionId} requires human help"
                    )

        elif response.function_calls:
            last_function_call = response.function_calls[0]
            tool_call_name = last_function_call.name
            if tool_call_name == "clasificar_interaccion":
                clasificacion = Clasificacion.model_validate(last_function_call.args)

        if response.text:
            assistant_message = InteractionMessage(
                type="assistant", message=response.text
            )
            history_messages.append(assistant_message)

        if interaction:
            interaction.messages = [msg.model_dump() for msg in history_messages]
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump() for msg in history_messages],
            )
            db.add(interaction)

        await db.commit()

        return TipoDeInteraccionResponse(
            sessionId=interaction_request.sessionId,
            messages=[assistant_message] if assistant_message else [],
            toolCall=tool_call_name
            if tool_call_name != "clasificar_interaccion"
            else None,
            clasificacion=clasificacion,
        )
    except errors.APIError as e:
        logger.error(f"Gemini API Error: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini API Error: {e!s}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Check server logs and environment variables.",
        )
