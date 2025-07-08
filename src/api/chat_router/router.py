import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors

from src.database.db import get_db
from src.shared.enums import CategoriaClasificacion
from src.shared.schemas import InteractionMessage, InteractionRequest, InteractionResponse
from src.api.tipo_de_interaccion.handler import handle_tipo_de_interaccion
from src.api.cliente_potencial.handler import handle_cliente_potencial
from src.api.cliente_activo.handler import handle_cliente_activo
from src.api.proveedor_potencial.handler import handle_proveedor_potencial
from src.api.usuario_administrativo.handler import handle_usuario_administrativo
from src.api.candidato_a_empleo.handler import handle_candidato_a_empleo
from src.api.transportista.handler import handle_transportista
from src.api.cliente_potencial.state import ClientePotencialState
from src.api.cliente_activo.state import ClienteActivoState
from src.api.proveedor_potencial.state import ProveedorPotencialState
from src.api.usuario_administrativo.state import UsuarioAdministrativoState
from src.api.candidato_a_empleo.state import CandidatoAEmpleoState
from src.api.transportista.state import TransportistaState
from src.database import models
from src.services.google_sheets import GoogleSheetsService
from src.shared.constants import CLASSIFICATION_THRESHOLD
from src.shared.state import GlobalState

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat-router", response_model=InteractionResponse)
async def chat_router(
    interaction_request: InteractionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Routes chat messages through classification logic, mimicking the n8n workflow.
    First classifies the interaction type, then routes to the appropriate handler.
    """
    client: genai.Client = request.app.state.genai_client
    sheets_service: GoogleSheetsService = request.app.state.sheets_service

    interaction = await db.get(models.Interaction, interaction_request.sessionId)
    
    history_messages = []
    classified_as = None
    
    if interaction:
        history_messages = [
            InteractionMessage.model_validate(msg) for msg in interaction.messages
        ]
        if (
            interaction.interaction_data
            and "classifiedAs" in interaction.interaction_data
        ):
            classified_as = CategoriaClasificacion(
                interaction.interaction_data["classifiedAs"]
            )

    history_messages.append(interaction_request.message)

    if classified_as:
        return await _route_to_specific_handler(
            classified_as=classified_as,
            interaction_request=interaction_request,
            client=client,
            sheets_service=sheets_service,
            db=db,
            history_messages=history_messages,
        )

    try:
        (
            classification_messages,
            clasificacion,
            tool_call_name,
        ) = await handle_tipo_de_interaccion(
            history_messages=history_messages,
            client=client,
        )

        validation_tools = [
            "es_mercancia_valida", 
            "es_ciudad_valida", 
            "es_solicitud_de_mudanza", 
            "es_solicitud_de_paqueteo",
            "obtener_ayuda_humana"
        ]
        
        if clasificacion:
            high_confidence_categories = [
                p.categoria
                for p in clasificacion.puntuacionesPorCategoria
                if p.puntuacionDeConfianza > CLASSIFICATION_THRESHOLD
            ]
            if len(high_confidence_categories) == 1:
                classified_as = CategoriaClasificacion(high_confidence_categories[0])
            elif len(high_confidence_categories) > 1:
                classified_as = CategoriaClasificacion.OTRO
                
                logger.info(f"Ambiguous interaction for sessionId {interaction_request.sessionId} due to multiple high confidence categories, escalating to human.")
                from src.shared.tools import obtener_ayuda_humana
                from src.shared.enums import InteractionType
                
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL,
                    message=obtener_ayuda_humana(),
                )
                history_messages.append(assistant_message)

                if not interaction:
                    interaction = models.Interaction(
                        session_id=interaction_request.sessionId,
                        messages=[],
                    )
                    db.add(interaction)
                
                interaction.messages = [msg.model_dump(mode="json") for msg in history_messages]
                interaction.state = GlobalState.HUMAN_ESCALATION.value
                if interaction.interaction_data is None:
                    interaction.interaction_data = {}
                interaction.interaction_data["classifiedAs"] = classified_as.value
                
                await db.commit()

                return InteractionResponse(
                    sessionId=interaction_request.sessionId,
                    messages=[assistant_message],
                    toolCall="obtener_ayuda_humana",
                    state=interaction.state,
                    classifiedAs=classified_as,
                )

        # If a specific classification is found (and not OTRO), route to the specific handler without using the generic message.
        if classified_as and classified_as != CategoriaClasificacion.OTRO and tool_call_name not in validation_tools:
            if not interaction:
                interaction = models.Interaction(
                    session_id=interaction_request.sessionId,
                    messages=[msg.model_dump(mode="json") for msg in history_messages],
                )
                db.add(interaction)

            if interaction.interaction_data is None:
                interaction.interaction_data = {}
            interaction.interaction_data["classifiedAs"] = classified_as.value
            await db.commit()

            return await _route_to_specific_handler(
                classified_as=classified_as,
                interaction_request=interaction_request,
                client=client,
                sheets_service=sheets_service,
                db=db,
                history_messages=history_messages,
            )

        # Otherwise, use the response from the classification step (handles validation tools, OTRO, and no classification).
        history_messages.extend(classification_messages)

        if interaction:
            interaction.messages = [msg.model_dump(mode="json") for msg in history_messages]
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump(mode="json") for msg in history_messages],
            )
            db.add(interaction)

        validation_function_tools = [
            "es_mercancia_valida",
            "es_ciudad_valida",
            "es_solicitud_de_mudanza",
            "es_solicitud_de_paqueteo",
        ]
        if tool_call_name in validation_function_tools:
            interaction.state = GlobalState.CONVERSATION_FINISHED.value
        elif tool_call_name == "obtener_ayuda_humana":
            interaction.state = GlobalState.HUMAN_ESCALATION.value

        if classified_as:
            if interaction.interaction_data is None:
                interaction.interaction_data = {}
            interaction.interaction_data["classifiedAs"] = classified_as.value

        await db.commit()

        return InteractionResponse(
            sessionId=interaction_request.sessionId,
            messages=classification_messages,
            toolCall=tool_call_name,
            state=interaction.state,
            classifiedAs=classified_as,
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


async def _route_to_specific_handler(
    classified_as: CategoriaClasificacion,
    interaction_request: InteractionRequest,
    client: genai.Client,
    sheets_service: GoogleSheetsService,
    db: AsyncSession,
    history_messages: List[InteractionMessage],
) -> InteractionResponse:
    """Routes the request to the appropriate specific handler based on classification."""
    
    interaction = await db.get(models.Interaction, interaction_request.sessionId)
    
    interaction_data = None
    if interaction and interaction.interaction_data:
        interaction_data = interaction.interaction_data

    try:
        if classified_as == CategoriaClasificacion.CLIENTE_POTENCIAL:
            current_state = ClientePotencialState.AWAITING_NIT
            if interaction and interaction.state:
                current_state = ClientePotencialState(interaction.state)
                
            (
                new_assistant_messages,
                next_state,
                tool_call_name,
                new_interaction_data,
            ) = await handle_cliente_potencial(
                session_id=interaction_request.sessionId,
                history_messages=history_messages,
                current_state=current_state,
                interaction_data=interaction_data,
                client=client,
                sheets_service=sheets_service,
            )

        elif classified_as == CategoriaClasificacion.CLIENTE_ACTIVO:
            current_state = ClienteActivoState.AWAITING_RESOLUTION
            if interaction and interaction.state:
                current_state = ClienteActivoState(interaction.state)
                
            (
                new_assistant_messages,
                next_state,
                tool_call_name,
                new_interaction_data,
            ) = await handle_cliente_activo(
                session_id=interaction_request.sessionId,
                history_messages=history_messages,
                current_state=current_state,
                interaction_data=interaction_data,
                client=client,
                sheets_service=sheets_service,
            )

        elif classified_as == CategoriaClasificacion.PROVEEDOR_POTENCIAL:
            current_state = ProveedorPotencialState.AWAITING_SERVICE_TYPE
            if interaction and interaction.state:
                current_state = ProveedorPotencialState(interaction.state)
                
            (
                new_assistant_messages,
                next_state,
                tool_call_name,
                new_interaction_data,
            ) = await handle_proveedor_potencial(
                session_id=interaction_request.sessionId,
                history_messages=history_messages,
                current_state=current_state,
                interaction_data=interaction_data,
                client=client,
                sheets_service=sheets_service,
            )

        elif classified_as == CategoriaClasificacion.USUARIO_ADMINISTRATIVO:
            current_state = UsuarioAdministrativoState.AWAITING_NECESITY_TYPE
            if interaction and interaction.state:
                current_state = UsuarioAdministrativoState(interaction.state)
                
            (
                new_assistant_messages,
                next_state,
                tool_call_name,
                new_interaction_data,
            ) = await handle_usuario_administrativo(
                session_id=interaction_request.sessionId,
                history_messages=history_messages,
                current_state=current_state,
                interaction_data=interaction_data,
                client=client,
                sheets_service=sheets_service,
            )

        elif classified_as == CategoriaClasificacion.CANDIDATO_A_EMPLEO:
            current_state = CandidatoAEmpleoState.AWAITING_VACANCY
            if interaction and interaction.state:
                current_state = CandidatoAEmpleoState(interaction.state)
                
            (
                new_assistant_messages,
                next_state,
                tool_call_name,
                new_interaction_data,
            ) = await handle_candidato_a_empleo(
                session_id=interaction_request.sessionId,
                history_messages=history_messages,
                current_state=current_state,
                interaction_data=interaction_data,
                client=client,
                sheets_service=sheets_service,
            )

        elif classified_as == CategoriaClasificacion.TRANSPORTISTA_TERCERO:
            current_state = TransportistaState.AWAITING_REQUEST_TYPE
            if interaction and interaction.state:
                current_state = TransportistaState(interaction.state)
                
            (
                new_assistant_messages,
                next_state,
                tool_call_name,
                new_interaction_data,
            ) = await handle_transportista(
                session_id=interaction_request.sessionId,
                history_messages=history_messages,
                current_state=current_state,
                interaction_data=interaction_data,
                client=client,
                sheets_service=sheets_service,
            )

        else:  # OTRO or any other case
            from src.shared.tools import obtener_ayuda_humana
            from src.shared.enums import InteractionType
            
            new_assistant_messages = [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=obtener_ayuda_humana()
                )
            ]
            next_state = "HUMAN_ESCALATION"
            tool_call_name = "obtener_ayuda_humana"
            new_interaction_data = interaction_data or {}

        # Update history with new messages
        history_messages.extend(new_assistant_messages)

        # Save to database
        if interaction:
            interaction.messages = [msg.model_dump(mode="json") for msg in history_messages]
            interaction.state = next_state.value if hasattr(next_state, 'value') else next_state
            interaction.interaction_data = new_interaction_data
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump(mode="json") for msg in history_messages],
                state=next_state.value if hasattr(next_state, 'value') else next_state,
                interaction_data=new_interaction_data,
            )
            db.add(interaction)

        await db.commit()

        return InteractionResponse(
            sessionId=interaction_request.sessionId,
            messages=new_assistant_messages,
            toolCall=tool_call_name,
            state=interaction.state,
            classifiedAs=classified_as,
        )

    except Exception as e:
        logger.error(f"Error in specific handler for {classified_as}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error handling {classified_as.value} request",
        )
