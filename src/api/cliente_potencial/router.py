import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors

from ... import models
from ...db import get_db
from ...schemas import InteractionRequest, InteractionResponse, InteractionMessage
from .state import ClientePotencialState
from .handler import handle_interaction

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/cliente-potencial", response_model=InteractionResponse)
async def handle(
    interaction_request: InteractionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handles a user-assistant interaction for qualifying a potential client.

    This endpoint manages a stateful conversation by:
    1. Retrieving the conversation history and state from the database.
    2. Handling the initial greeting for a new conversation.
    3. Appending the new user message to the history.
    4. Delegating to a state machine handler to process the conversation logic.
    5. Persisting the updated conversation history and state.
    6. Returning the assistant's response to the user.
    """
    client: genai.Client = request.app.state.genai_client

    # Retrieve interaction from the database or initialize a new one.
    interaction = await db.get(models.Interaction, interaction_request.sessionId)

    history_messages: list[InteractionMessage] = []
    current_state = ClientePotencialState.AWAITING_NIT
    if interaction:
        history_messages = [
            InteractionMessage.model_validate(msg) for msg in interaction.messages
        ]
        if interaction.state:
            current_state = ClientePotencialState(interaction.state)

    # If this is the very first interaction, send a greeting and initialize state.
    if not history_messages:
        assistant_message = InteractionMessage(
            type="assistant",
            message="¡Hola! Soy Sotobot, tu asistente virtual. Para empezar, ¿podrías indicarme el NIT de tu empresa?",
        )
        history_messages.append(assistant_message)
        new_interaction = models.Interaction(
            session_id=interaction_request.sessionId,
            messages=[msg.model_dump() for msg in history_messages],
            state=current_state.value,
        )
        db.add(new_interaction)
        await db.commit()
        return InteractionResponse(
            sessionId=interaction_request.sessionId, messages=[assistant_message]
        )

    # Append the new user message to the history for processing.
    history_messages.append(interaction_request.message)

    try:
        # Delegate the core logic to the handler function.
        (
            new_assistant_messages,
            next_state,
            tool_call_name,
        ) = await handle_interaction(
            session_id=interaction_request.sessionId,
            history_messages=history_messages,
            current_state=current_state,
            client=client,
        )

        # Update the history with the new assistant messages.
        history_messages.extend(new_assistant_messages)

        # Persist the updated state and history to the database.
        if interaction:
            interaction.messages = [msg.model_dump() for msg in history_messages]
            interaction.state = next_state.value
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump() for msg in history_messages],
                state=next_state.value,
            )
            db.add(interaction)

        await db.commit()

        # Return the response to the user.
        return InteractionResponse(
            sessionId=interaction_request.sessionId,
            messages=new_assistant_messages,
            toolCall=tool_call_name,
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
