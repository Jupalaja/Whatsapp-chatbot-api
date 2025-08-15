import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors
from sqlalchemy.orm.attributes import flag_modified

from src.database.db import get_db
from src.shared.enums import CategoriaClasificacion, InteractionType
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
from src.shared.constants import (
    CLASSIFICATION_THRESHOLD,
    TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN,
)
from src.shared.state import GlobalState
from src.shared.tools import obtener_ayuda_humana

router = APIRouter()
logger = logging.getLogger(__name__)


async def _chat_router_logic(
    interaction_request: InteractionRequest,
    client: genai.Client,
    sheets_service: GoogleSheetsService,
    db: AsyncSession,
) -> InteractionResponse:
    session_id = interaction_request.sessionId
    logger.debug(f"Chat router logic triggered for session_id: {session_id}")

    interaction = await db.get(models.Interaction, session_id)

    # Check if the interaction is soft deleted
    if interaction and interaction.is_deleted:
        logger.debug(f"Session {session_id} is marked as deleted, treating as new conversation")
        interaction.is_deleted = False
        interaction.messages = []
        interaction.state = None
        interaction.interaction_data = {}

    # Handle reclassification if needed
    if interaction and interaction.state == GlobalState.AWAITING_RECLASSIFICATION.value:
        logger.debug(f"Session {session_id} is awaiting reclassification. Resetting message history and state for new interaction.")
        interaction.messages = []
        interaction.state = None
        if interaction.interaction_data:
            interaction.interaction_data.pop("classifiedAs", None)
            interaction.interaction_data.pop("special_list_sent", None)
            interaction.interaction_data.pop("messages_after_finished_count", None)

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

    user_message_count = sum(
        1 for msg in history_messages if msg.role == InteractionType.USER
    )

    if classified_as:
        logger.debug(
            f"Session {session_id} already classified as '{classified_as.value}'. Routing to specific handler."
        )
        return await _route_to_specific_handler(
            classified_as=classified_as,
            interaction_request=interaction_request,
            client=client,
            sheets_service=sheets_service,
            db=db,
            history_messages=history_messages,
        )

    if user_message_count >= TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN:
        logger.warning(
            f"User with sessionId {session_id} has sent more than {TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN} messages without being classified. Activating human help tool."
        )
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL,
            message=obtener_ayuda_humana(),
        )
        history_messages.append(assistant_message)

        if not interaction:
            interaction = models.Interaction(
                session_id=session_id,
                messages=[],
                user_data=interaction_request.userData,
            )
            db.add(interaction)
        elif interaction_request.userData:
            interaction.user_data = interaction_request.userData

        interaction.messages = [msg.model_dump(mode="json") for msg in history_messages]
        interaction.state = GlobalState.HUMAN_ESCALATION.value
        if interaction.interaction_data is None:
            interaction.interaction_data = {}
        interaction.interaction_data["classifiedAs"] = CategoriaClasificacion.OTRO.value
        flag_modified(interaction, "interaction_data")

        await db.commit()

        return InteractionResponse(
            sessionId=session_id,
            messages=[assistant_message],
            toolCall="obtener_ayuda_humana",
            state=interaction.state,
            classifiedAs=CategoriaClasificacion.OTRO,
        )

    try:
        logger.debug(
            f"Session {session_id} not classified. Calling 'handle_tipo_de_interaccion'."
        )
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
            "obtener_ayuda_humana",
            "es_envio_internacional",
        ]

        if clasificacion:
            high_confidence_categories = [
                p.categoria
                for p in clasificacion.puntuacionesPorCategoria
                if p.puntuacionDeConfianza > CLASSIFICATION_THRESHOLD
            ]
            if len(high_confidence_categories) == 1:
                classified_as = CategoriaClasificacion(high_confidence_categories[0])
                logger.debug(
                    f"Session {session_id} classified as '{classified_as.value}' with high confidence."
                )
            elif len(high_confidence_categories) > 1:
                classified_as = CategoriaClasificacion.OTRO

                logger.warning(
                    f"Ambiguous interaction for sessionId {session_id} due to multiple high confidence categories, escalating to human."
                )

                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL,
                    message=obtener_ayuda_humana(),
                )
                history_messages.append(assistant_message)

                if not interaction:
                    interaction = models.Interaction(
                        session_id=session_id,
                        messages=[],
                        user_data=interaction_request.userData,
                    )
                    db.add(interaction)
                elif interaction_request.userData:
                    interaction.user_data = interaction_request.userData

                interaction.messages = [
                    msg.model_dump(mode="json") for msg in history_messages
                ]
                interaction.state = GlobalState.HUMAN_ESCALATION.value
                if interaction.interaction_data is None:
                    interaction.interaction_data = {}
                interaction.interaction_data["classifiedAs"] = classified_as.value
                flag_modified(interaction, "interaction_data")

                await db.commit()

                return InteractionResponse(
                    sessionId=session_id,
                    messages=[assistant_message],
                    toolCall="obtener_ayuda_humana",
                    state=interaction.state,
                    classifiedAs=classified_as,
                )
            else:
                logger.debug(
                    f"Session {session_id} could not be classified with high confidence."
                )

        if user_message_count == 1 and not classified_as:
            special_list_sent = (
                interaction
                and interaction.interaction_data
                and interaction.interaction_data.get("special_list_sent")
            )
            if not special_list_sent:
                logger.debug(
                    f"Session {session_id} is a first-time unclassified interaction. Sending special list message."
                )
                if not interaction:
                    interaction = models.Interaction(
                        session_id=session_id,
                        messages=[msg.model_dump(mode="json") for msg in history_messages],
                        user_data=interaction_request.userData,
                        interaction_data={"special_list_sent": True},
                    )
                    db.add(interaction)
                else:
                    if interaction.interaction_data is None:
                        interaction.interaction_data = {}
                    interaction.interaction_data["special_list_sent"] = True
                    flag_modified(interaction, "interaction_data")
                    interaction.messages = [
                        msg.model_dump(mode="json") for msg in history_messages
                    ]
                    if interaction_request.userData:
                        interaction.user_data = interaction_request.userData

                await db.commit()

                return InteractionResponse(
                    sessionId=session_id,
                    messages=[],
                    toolCall="send_special_list_message",
                    state=interaction.state,
                    classifiedAs=None,
                )

        # If a specific classification is found (and not OTRO), route to the specific handler if no message was generated by the classification step.
        if (
            classified_as
            and classified_as != CategoriaClasificacion.OTRO
            and not classification_messages
        ):
            logger.debug(
                f"Routing session {session_id} to handler for '{classified_as.value}' because classification was successful and no immediate message was generated."
            )
            if not interaction:
                interaction = models.Interaction(
                    session_id=session_id,
                    messages=[msg.model_dump(mode="json") for msg in history_messages],
                    user_data=interaction_request.userData,
                )
                db.add(interaction)
            elif interaction_request.userData:
                interaction.user_data = interaction_request.userData

            if interaction.interaction_data is None:
                interaction.interaction_data = {}
            interaction.interaction_data["classifiedAs"] = classified_as.value
            flag_modified(interaction, "interaction_data")
            await db.commit()

            return await _route_to_specific_handler(
                classified_as=classified_as,
                interaction_request=interaction_request,
                client=client,
                sheets_service=sheets_service,
                db=db,
                history_messages=history_messages,
            )

        # Otherwise, use the response from the classification step (handles validation tools, OTRO, and no classification/low confidence).
        history_messages.extend(classification_messages)

        if interaction:
            interaction.messages = [
                msg.model_dump(mode="json") for msg in history_messages
            ]
            if interaction_request.userData:
                interaction.user_data = interaction_request.userData
        else:
            interaction = models.Interaction(
                session_id=session_id,
                messages=[msg.model_dump(mode="json") for msg in history_messages],
                user_data=interaction_request.userData,
            )
            db.add(interaction)

        validation_function_tools = [
            "es_mercancia_valida",
            "es_ciudad_valida",
            "es_solicitud_de_mudanza",
            "es_solicitud_de_paqueteo",
            "es_envio_internacional",
        ]
        if tool_call_name in validation_function_tools:
            interaction.state = GlobalState.CONVERSATION_FINISHED.value
        elif tool_call_name == "obtener_ayuda_humana":
            interaction.state = GlobalState.HUMAN_ESCALATION.value

        if classified_as:
            if interaction.interaction_data is None:
                interaction.interaction_data = {}
            interaction.interaction_data["classifiedAs"] = classified_as.value
            flag_modified(interaction, "interaction_data")

        await db.commit()

        return InteractionResponse(
            sessionId=session_id,
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
    session_id = interaction_request.sessionId
    logger.debug(f"Chat router triggered for session_id: {session_id}")
    client: genai.Client = request.app.state.genai_client
    sheets_service: GoogleSheetsService = request.app.state.sheets_service
    return await _chat_router_logic(interaction_request, client, sheets_service, db)


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

    if interaction and interaction_request.userData:
        interaction.user_data = interaction_request.userData
    
    interaction_data = None
    if interaction and interaction.interaction_data:
        interaction_data = interaction.interaction_data

    user_data = None
    if interaction and interaction.user_data:
        user_data = interaction.user_data

    try:
        if classified_as == CategoriaClasificacion.CLIENTE_POTENCIAL:
            logger.debug(f"Routing to 'cliente_potencial' handler for session_id: {interaction_request.sessionId}")
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
                user_data=user_data,
                client=client,
                sheets_service=sheets_service,
            )

        elif classified_as == CategoriaClasificacion.CLIENTE_ACTIVO:
            logger.debug(f"Routing to 'cliente_activo' handler for session_id: {interaction_request.sessionId}")
            current_state = ClienteActivoState.AWAITING_NIT
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
            logger.debug(f"Routing to 'proveedor_potencial' handler for session_id: {interaction_request.sessionId}")
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
            logger.debug(f"Routing to 'usuario_administrativo' handler for session_id: {interaction_request.sessionId}")
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
            logger.debug(f"Routing to 'candidato_a_empleo' handler for session_id: {interaction_request.sessionId}")
            current_state = CandidatoAEmpleoState.AWAITING_CANDIDATE_INFO
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
            logger.debug(f"Routing to 'transportista' handler for session_id: {interaction_request.sessionId}")
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
            
            logger.debug(f"Routing to 'human_escalation' for session_id: {interaction_request.sessionId}")
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
            flag_modified(interaction, "interaction_data")
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump(mode="json") for msg in history_messages],
                state=next_state.value if hasattr(next_state, 'value') else next_state,
                interaction_data=new_interaction_data,
                user_data=interaction_request.userData,
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
