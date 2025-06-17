import logging
import json
import enum
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai
from google.genai import errors, types
from pydantic import ValidationError

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


class ClientePotencialState(str, enum.Enum):
    AWAITING_NIT = "AWAITING_NIT"
    AWAITING_FREIGHT_FORWARDER_CONFIRMATION = (
        "AWAITING_FREIGHT_FORWARDER_CONFIRMATION"
    )
    COMPLETE = "COMPLETE"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"


async def _get_genai_history(
    history_messages: list[InteractionMessage],
) -> list[types.Content]:
    """Converts a list of InteractionMessage objects to a list of genai.Content objects."""
    genai_history = []
    for msg in history_messages:
        role = "user" if msg.type == "user" else "model"
        try:
            # Assumes complex parts are stored as JSON strings
            parts_data = json.loads(msg.message)
            parts = [types.Part.model_validate(p) for p in parts_data]
        except (json.JSONDecodeError, TypeError, ValidationError):
            # Fallback for simple text messages
            parts = [types.Part(text=msg.message)]
        genai_history.append(types.Content(role=role, parts=parts))
    return genai_history


def _genai_content_to_interaction_messages(
    history: list[types.Content],
) -> list[InteractionMessage]:
    """Converts a list of genai.Content objects to a list of InteractionMessage objects."""
    messages = []
    for content in history:
        role = "user" if content.role == "user" else "assistant"
        # Serialize complex parts to a JSON string to fit the current schema
        if len(content.parts) == 1 and content.parts[0].text is not None:
            message_str = content.parts[0].text
        else:
            parts_json_list = [
                p.model_dump(exclude_none=True) for p in content.parts
            ]
            message_str = json.dumps(parts_json_list)
        messages.append(InteractionMessage(type=role, message=message_str))
    return messages


@router.post("/cliente-potencial", response_model=InteractionResponse)
async def handle(
    interaction_request: InteractionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handles a user-assistant interaction, following a conversation
    guideline for extracting user data and verify it using
    tool calls.
    """
    client: genai.Client = request.app.state.genai_client

    interaction = await db.get(models.Interaction, interaction_request.sessionId)

    history_messages = []
    current_state = None
    if interaction:
        history_messages = [
            InteractionMessage.model_validate(msg) for msg in interaction.messages
        ]
        current_state = interaction.state

    if current_state is None:
        current_state = ClientePotencialState.AWAITING_NIT

    if not history_messages:
        assistant_message = InteractionMessage(
            type="assistant",
            message="¡Hola! Soy Sotobot, tu asistente virtual. Para empezar, ¿podrías indicarme el NIT de tu empresa, por favor?",
        )
        history_messages.append(assistant_message)

        new_interaction = models.Interaction(
            session_id=interaction_request.sessionId,
            messages=[msg.model_dump() for msg in history_messages],
            state=ClientePotencialState.AWAITING_NIT,
        )
        db.add(new_interaction)
        await db.commit()
        return InteractionResponse(
            sessionId=interaction_request.sessionId, messages=[assistant_message]
        )

    history_messages.append(interaction_request.message)

    try:
        genai_history = await _get_genai_history(history_messages)

        tools = []
        if current_state == ClientePotencialState.AWAITING_NIT:
            tools = [search_nit, is_persona_natural, get_human_help]
        elif (
            current_state
            == ClientePotencialState.AWAITING_FREIGHT_FORWARDER_CONFIRMATION
        ):
            tools = [needs_freight_forwarder, get_human_help]
        else:  # COMPLETE or HUMAN_ESCALATION
            tools = [get_human_help]

        config = types.GenerateContentConfig(
            tools=tools, system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT
        )

        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL, contents=genai_history, config=config
        )

        assistant_message_text = response.text
        next_state: ClientePotencialState = current_state  # type: ignore
        tool_call_name = None

        afc_history = response.automatic_function_calling_history or []
        if afc_history:
            for content in reversed(afc_history):
                if (
                    content.role == "model"
                    and content.parts
                    and content.parts[0].function_call
                ):
                    last_tool_call_name = content.parts[0].function_call.name
                    tool_call_name = last_tool_call_name
                    if last_tool_call_name == "is_persona_natural":
                        next_state = (
                            ClientePotencialState.AWAITING_FREIGHT_FORWARDER_CONFIRMATION
                        )
                        assistant_message_text = "¿Busca servicios de agenciamiento de carga o es un agente de carga?"
                    elif last_tool_call_name == "needs_freight_forwarder":
                        next_state = ClientePotencialState.COMPLETE
                        assistant_message_text = "Entendido. Un especialista en agenciamiento de carga se pondrá en contacto con usted."
                    elif last_tool_call_name == "search_nit":
                        next_state = ClientePotencialState.COMPLETE
                    elif last_tool_call_name == "get_human_help":
                        next_state = ClientePotencialState.HUMAN_ESCALATION
                    break

        final_genai_history = afc_history if afc_history else genai_history
        if assistant_message_text != response.text:
            # Our custom logic overrode the model's text response, so we append it to the history.
            final_genai_history.append(
                types.Content(
                    role="model", parts=[types.Part(text=assistant_message_text)]
                )
            )
        elif response.candidates:
            final_genai_history.append(response.candidates[0].content)

        final_interaction_messages = _genai_content_to_interaction_messages(
            final_genai_history
        )

        if interaction:
            interaction.messages = [
                msg.model_dump() for msg in final_interaction_messages
            ]
            interaction.state = next_state
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[
                    msg.model_dump() for msg in final_interaction_messages
                ],
                state=next_state,
            )
            db.add(interaction)

        await db.commit()

        return InteractionResponse(
            sessionId=interaction_request.sessionId,
            messages=[
                InteractionMessage(type="assistant", message=assistant_message_text)
            ],
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
