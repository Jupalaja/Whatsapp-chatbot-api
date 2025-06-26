import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors

from .handler import handle_tipo_de_interaccion as handle_tipo_de_interaccion

from src.database import models
from src.database.db import get_db
from src.shared.enums import InteractionType, CategoriaClasificacion
from src.shared.constants import (
    TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN,
    CLASSIFICATION_THRESHOLD,
)
from src.shared.schemas import (
    InteractionMessage,
    InteractionRequest,
    TipoDeInteraccionResponse,
)
from src.shared.tools import obtener_ayuda_humana

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/tipo-de-interaccion", response_model=TipoDeInteraccionResponse)
async def handle(
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

    user_message_count = sum(
        1 for msg in history_messages if msg.role == InteractionType.USER
    )

    if user_message_count >= TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN:
        logger.info(
            f"User with sessionId {interaction_request.sessionId} has sent more than {TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN} messages. Activating human help tool."
        )
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL,
            message=obtener_ayuda_humana(),
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
            messages=[assistant_message],
            toolCall="obtener_ayuda_humana",
            clasificacion=None,
            state=interaction.state,
        )

    try:
        (
            new_assistant_messages,
            clasificacion,
            tool_call_name,
        ) = await handle_tipo_de_interaccion(
            history_messages=history_messages,
            client=client,
        )

        history_messages.extend(new_assistant_messages)

        if interaction:
            interaction.messages = [msg.model_dump() for msg in history_messages]
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump() for msg in history_messages],
            )
            db.add(interaction)

        classified_as = None
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

        if classified_as:
            if interaction.interaction_data is None:
                interaction.interaction_data = {}
            interaction.interaction_data["classifiedAs"] = classified_as.value

        await db.commit()

        return TipoDeInteraccionResponse(
            sessionId=interaction_request.sessionId,
            messages=new_assistant_messages,
            toolCall=tool_call_name,
            clasificacion=clasificacion,
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
