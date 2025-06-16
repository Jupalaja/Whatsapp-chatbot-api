import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors, types

from .. import models
from ..db import get_db
from ..schemas import InteractionRequest, InteractionResponse, InteractionMessage

router = APIRouter()
logger = logging.getLogger(__name__)


def get_human_help():
    """Use this function when the user explicitly asks for human help or to talk to a human."""
    return "A human will be with you shortly."


@router.post("/interaction", response_model=InteractionResponse)
async def handle_interaction(
    interaction_request: InteractionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handles a user-assistant interaction, continuing a conversation by
    loading history from the database, appending the new message,
    and saving the updated history.
    """
    client: genai.Client = request.app.state.genai_client

    # Get interaction from DB
    interaction = await db.get(models.Interaction, interaction_request.sessionId)

    history_messages = []
    if interaction:
        history_messages = [
            InteractionMessage.model_validate(msg) for msg in interaction.messages
        ]

    # Append new user message
    history_messages.append(interaction_request.message)

    try:
        model = "gemini-1.5-flash-latest"

        genai_history = []
        for msg in history_messages:
            # The 'assistant' role from the API maps to the 'model' role in the genai library
            role = "user" if msg.type == "user" else "model"
            genai_history.append(
                types.Content(role=role, parts=[types.Part(text=msg.message)])
            )

        tools = [get_human_help]
        config = types.GenerateContentConfig(tools=tools)

        response = await client.aio.models.generate_content(
            model=model, contents=genai_history, config=config
        )

        assistant_message = None
        tool_call_name = None

        # When AFC is used, inspect automatic_function_calling_history to find the last tool call.
        if response.automatic_function_calling_history:
            # Find the last function call from the model in the history.
            function_calls = (
                part.function_call
                for content in reversed(response.automatic_function_calling_history)
                if content.role == "model" and content.parts
                for part in content.parts
                if part.function_call
            )
            # The `next` function gets the first item from an iterator, or None if it's empty.
            # Since we reversed the history, this is the last function call made.
            last_function_call = next(function_calls, None)
            if last_function_call:
                tool_call_name = last_function_call.name

        if tool_call_name == "get_human_help":
            logger.info(
                f"The user with sessionId: {interaction_request.sessionId} requires human help"
            )

        if response.text:
            assistant_message = InteractionMessage(
                type="assistant",
                message=response.text,
            )
            history_messages.append(assistant_message)

        # Upsert interaction
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


@router.get("/interaction", response_model=InteractionResponse)
async def get_interaction_history(sessionID: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieves the message history for a given sessionID.
    """
    interaction = await db.get(models.Interaction, sessionID)
    if not interaction:
        raise HTTPException(status_code=404, detail="Session not found")

    history_messages = [
        InteractionMessage.model_validate(msg) for msg in interaction.messages
    ]

    return InteractionResponse(sessionId=sessionID, messages=history_messages)
