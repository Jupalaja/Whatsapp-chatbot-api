import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors

from .handler import handle

from src.database import models
from src.database.db import get_db
from src.shared.enums import InteractionType
from src.shared.constants import TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN
from src.shared.schemas import (
    InteractionMessage,
    InteractionRequest,
    TipoDeInteraccionResponse,
)

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
        1 for msg in history_messages if msg.type == InteractionType.USER
    )

    if user_message_count >= TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN:
        logger.info(
            f"User with sessionId {interaction_request.sessionId} has sent more than {TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN} messages. Activating human help tool."
        )
        assistant_message = InteractionMessage(
            type=InteractionType.ASSISTANT,
            message="OK. A human will be with you shortly.\n",
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
            toolCall="get_human_help",
            clasificacion=None,
        )

    try:
        (
            new_assistant_messages,
            clasificacion,
            tool_call_name,
        ) = await handle(
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

        await db.commit()

        return TipoDeInteraccionResponse(
            sessionId=interaction_request.sessionId,
            messages=new_assistant_messages,
            toolCall=tool_call_name,
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
