import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors, types

from .. import models
from ..db import get_db
from ..model.constants import GEMINI_MODEL
from ..model.prompts import CLIENTE_POTENCIAL_SYSTEM_PROMPT
from ..model.tools import (
    get_human_help,
    is_persona_natural,
    search_nit,
    needs_freight_forwarder,
)
from ..schemas import InteractionRequest, InteractionResponse, InteractionMessage

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/cliente-potencial", response_model=InteractionResponse)
async def handle(
    interaction_request: InteractionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handles a user-assistant interaction, following a conversation
    guideline for extracting user data and verify it using
    tool calls
    """
    client: genai.Client = request.app.state.genai_client

    # Step 1: Retrieve existing conversation history from the database.
    interaction = await db.get(models.Interaction, interaction_request.sessionId)

    history_messages = []
    if interaction:
        # Load previous messages if a session exists.
        history_messages = [
            InteractionMessage.model_validate(msg) for msg in interaction.messages
        ]

    # Step 2: Append the new user message to the history for this turn.
    history_messages.append(interaction_request.message)

    try:
        model = GEMINI_MODEL

        # Step 3: Prepare the full conversation history for the Gemini API call.
        # This ensures the model has context of the entire conversation.
        genai_history = [
            types.Content(
                role="user" if msg.type == "user" else "model",
                parts=[types.Part(text=msg.message)],
            )
            for msg in history_messages
        ]

        tools = [get_human_help, search_nit, is_persona_natural, needs_freight_forwarder]
        config = types.GenerateContentConfig(
            tools=tools,
            system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        # Step 4: Call the model with the complete history.
        response = await client.aio.models.generate_content(
            model=model, contents=genai_history, config=config
        )

        assistant_message = None
        tool_call_name = None

        if response.function_calls:
            function_call = response.function_calls[0]
            # TODO: Implement tool call handling for search_nit, is_persona_natural, and needs_freight_forwarder
            if function_call.name == "get_human_help":
                tool_call_name = function_call.name
                logger.info(
                    f"The user with sessionId: {interaction_request.sessionId} requires human help"
                )
                assistant_text = get_human_help()
                assistant_message = InteractionMessage(
                    type="assistant", message=assistant_text
                )

        if response.text and not assistant_message:
            assistant_message = InteractionMessage(
                type="assistant",
                message=response.text,
            )

        # Step 5: Append the assistant's response to the history for persistence.
        if assistant_message:
            history_messages.append(assistant_message)

        # Step 6: Save the updated conversation history back to the database.
        if interaction:
            interaction.messages = [msg.model_dump() for msg in history_messages]
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump() for msg in history_messages],
            )
            db.add(interaction)

        await db.commit()

        return InteractionResponse(
            sessionId=interaction_request.sessionId,
            messages=[assistant_message] if assistant_message else [],
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
