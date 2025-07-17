import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors, types

from src.database import models
from src.database.db import get_db
from src.shared.enums import InteractionType, CategoriaClasificacion
from src.shared.constants import GEMINI_MODEL
from src.shared.prompts import CONTACTO_BASE_SYSTEM_PROMPT
from src.shared.tools import obtener_ayuda_humana
from src.shared.schemas import InteractionRequest, InteractionResponse, InteractionMessage
from src.shared.utils.history import get_genai_history
from src.shared.utils.functions import get_response_text, invoke_model_with_retries

router = APIRouter()
logger = logging.getLogger(__name__)


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
        model = GEMINI_MODEL

        genai_history = await get_genai_history(history_messages)

        tools = [obtener_ayuda_humana]
        config = types.GenerateContentConfig(
            tools=tools,
            system_instruction=CONTACTO_BASE_SYSTEM_PROMPT,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        response = await invoke_model_with_retries(
            client.aio.models.generate_content,
            model=model, contents=genai_history, config=config
        )

        assistant_message = None
        tool_call_name = None

        if response.function_calls:
            function_call = response.function_calls[0]
            if function_call.name == "obtener_ayuda_humana":
                tool_call_name = function_call.name
                logger.warning(
                    f"The user with sessionId: {interaction_request.sessionId} requires human help"
                )
                assistant_text = obtener_ayuda_humana()
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=assistant_text
                )

        if not assistant_message:
            assistant_text = get_response_text(response)
            if assistant_text:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL,
                    message=assistant_text,
                )

        if assistant_message:
            history_messages.append(assistant_message)

        # Upsert interaction
        if interaction:
            interaction.messages = [msg.model_dump(mode="json") for msg in history_messages]
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump(mode="json") for msg in history_messages],
            )
            db.add(interaction)

        await db.commit()

        return InteractionResponse(
            sessionId=interaction_request.sessionId,
            messages=[assistant_message] if assistant_message else [],
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

    classified_as = None
    if interaction.interaction_data:
        classified_as_value = interaction.interaction_data.get("classifiedAs")
        if classified_as_value:
            classified_as = CategoriaClasificacion(classified_as_value)

    return InteractionResponse(
        sessionId=sessionID,
        messages=history_messages,
        state=interaction.state,
        classifiedAs=classified_as,
    )
