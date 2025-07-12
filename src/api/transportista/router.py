import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors

from .handler import handle_transportista
from .state import TransportistaState
from src.database import models
from src.database.db import get_db
from src.shared.enums import InteractionType
from src.shared.schemas import (
    InteractionMessage,
    InteractionRequest,
    InteractionResponse,
)
from src.shared.constants import TRANSPORTISTA_MESSAGES_UNTIL_HUMAN
from src.shared.tools import obtener_ayuda_humana
from src.services.google_sheets import GoogleSheetsService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/transportista", response_model=InteractionResponse)
async def handle(
    interaction_request: InteractionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handles a user-assistant interaction for a carrier,
    continuing a conversation by loading history from the database,
    appending the new message, and saving the updated history.
    """
    logger.debug(
        f"Handling 'transportista' request for session: {interaction_request.sessionId}"
    )
    client: genai.Client = request.app.state.genai_client
    sheets_service: Optional[GoogleSheetsService] = request.app.state.sheets_service

    interaction = await db.get(models.Interaction, interaction_request.sessionId)

    history_messages: list[InteractionMessage] = []
    current_state = TransportistaState.AWAITING_REQUEST_TYPE
    interaction_data: Optional[dict] = None
    if interaction:
        history_messages = [
            InteractionMessage.model_validate(msg) for msg in interaction.messages
        ]
        if interaction.state:
            current_state = TransportistaState(interaction.state)
        if interaction.interaction_data:
            interaction_data = interaction.interaction_data

    history_messages.append(interaction_request.message)

    user_message_count = sum(
        1 for msg in history_messages if msg.role == InteractionType.USER
    )

    if user_message_count >= TRANSPORTISTA_MESSAGES_UNTIL_HUMAN:
        logger.warning(
            f"User with sessionId {interaction_request.sessionId} has sent more than {TRANSPORTISTA_MESSAGES_UNTIL_HUMAN} messages. Activating human help tool."
        )
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL,
            message=obtener_ayuda_humana(),
        )
        history_messages.append(assistant_message)
        next_state = TransportistaState.HUMAN_ESCALATION

        if interaction:
            interaction.messages = [msg.model_dump(mode="json") for msg in history_messages]
            interaction.state = next_state.value
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump(mode="json") for msg in history_messages],
                state=next_state.value,
            )
            db.add(interaction)
        await db.commit()

        return InteractionResponse(
            sessionId=interaction_request.sessionId,
            messages=[assistant_message],
            toolCall="obtener_ayuda_humana",
            state=interaction.state,
        )

    try:
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

        history_messages.extend(new_assistant_messages)

        if interaction:
            interaction.messages = [msg.model_dump(mode="json") for msg in history_messages]
            interaction.state = next_state.value
            interaction.interaction_data = new_interaction_data
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump(mode="json") for msg in history_messages],
                state=next_state.value,
                interaction_data=new_interaction_data,
            )
            db.add(interaction)

        await db.commit()

        return InteractionResponse(
            sessionId=interaction_request.sessionId,
            messages=new_assistant_messages,
            toolCall=tool_call_name,
            state=interaction.state,
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
