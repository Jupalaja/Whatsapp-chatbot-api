import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors, types

from .. import models
from ..db import get_db
from ..model.constants import TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN, GEMINI_MODEL
from ..model.global_prompts import (
    TIPO_DE_INTERACCION_SYSTEM_PROMPT,
    CONTACTO_BASE_SYSTEM_PROMPT,
)
from ..model.global_tools import clasificar_interaccion, get_human_help
from ..schemas import (
    InteractionRequest,
    InteractionMessage,
    TipoDeInteraccionResponse,
    Clasificacion,
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

    user_message_count = sum(1 for msg in history_messages if msg.type == "user")

    if user_message_count >= TIPO_DE_INTERACCION_MESSAGES_UNTIL_HUMAN:
        logger.info(
            f"User with sessionId {interaction_request.sessionId} has sent more than 4 messages. Activating human help tool."
        )
        assistant_message = InteractionMessage(
            type="assistant", message="OK. A human will be with you shortly.\n"
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
        model = GEMINI_MODEL

        genai_history = [
            types.Content(
                role="user" if msg.type == "user" else "model",
                parts=[types.Part(text=msg.message)],
            )
            for msg in history_messages
        ]

        # First, classify the interaction
        classification_tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.ANY,
                allowed_function_names=["clasificar_interaccion"],
            )
        )
        classification_tools = [clasificar_interaccion]
        classification_config = types.GenerateContentConfig(
            tools=classification_tools,
            system_instruction=TIPO_DE_INTERACCION_SYSTEM_PROMPT,
            tool_config=classification_tool_config,
            temperature=0.0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        response_classification = await client.aio.models.generate_content(
            model=model, contents=genai_history, config=classification_config
        )

        clasificacion = None
        if response_classification.function_calls:
            last_function_call = response_classification.function_calls[0]
            if last_function_call.name == "clasificar_interaccion":
                clasificacion = Clasificacion.model_validate(last_function_call.args)

        # Second, get a conversational response
        assistant_message = None
        tool_call_name = None

        chat_config = types.GenerateContentConfig(
            tools=[get_human_help],
            system_instruction=CONTACTO_BASE_SYSTEM_PROMPT,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )
        response_chat = await client.aio.models.generate_content(
            model=model, contents=genai_history, config=chat_config
        )

        if response_chat.function_calls:
            function_call = response_chat.function_calls[0]
            if function_call.name == "get_human_help":
                tool_call_name = function_call.name
                logger.info(
                    f"The user with sessionId: {interaction_request.sessionId} requires human help"
                )
                assistant_text = get_human_help()
                assistant_message = InteractionMessage(
                    type="assistant", message=assistant_text
                )

        if response_chat.text and not assistant_message:
            assistant_message = InteractionMessage(
                type="assistant", message=response_chat.text
            )

        if assistant_message:
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
