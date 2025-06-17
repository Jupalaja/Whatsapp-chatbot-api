import logging
import json
import enum
from typing import Literal, Optional

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
    AWAITING_REMAINING_INFORMATION = "AWAITING_REMAINING_INFORMATION"
    NIT_PROVIDED = "NIT_PROVIDED"
    CUSTOMER_DISCARDED = "CUSTOMER_DISCARDED"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"


async def _get_genai_history(
    history_messages: list[InteractionMessage],
) -> list[types.Content]:
    """Converts a list of InteractionMessage objects to a list of genai.Content objects."""
    genai_history = []
    for msg in history_messages:
        role = "user"
        if msg.type == "assistant":
            role = "model"
        elif msg.type == "tool":
            role = "tool"

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
        role: Literal["user", "assistant", "tool"] = "user"
        if content.role == "model":
            role = "assistant"
        elif content.role == "tool":
            role = "tool"

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

    history_messages: list[InteractionMessage] = []
    current_state = ClientePotencialState.AWAITING_NIT
    if interaction:
        history_messages = [
            InteractionMessage.model_validate(msg) for msg in interaction.messages
        ]
        current_state = (
            interaction.state if interaction.state else ClientePotencialState.AWAITING_NIT
        )

    if not history_messages:
        assistant_message = InteractionMessage(
            type="assistant",
            message="¡Hola! Soy Sotobot, tu asistente virtual. Para empezar, ¿podrías indicarme el NIT de tu empresa?",
        )
        history_messages.append(assistant_message)
        new_interaction = models.Interaction(
            session_id=interaction_request.sessionId,
            messages=[msg.model_dump() for msg in history_messages],
            state=current_state,
        )
        db.add(new_interaction)
        await db.commit()
        return InteractionResponse(
            sessionId=interaction_request.sessionId, messages=[assistant_message]
        )

    history_messages.append(interaction_request.message)

    try:
        genai_history = await _get_genai_history(history_messages)

        if current_state == ClientePotencialState.AWAITING_NIT:
            tools = [search_nit, is_persona_natural, get_human_help]
        elif current_state == ClientePotencialState.AWAITING_REMAINING_INFORMATION:
            tools = [
                needs_freight_forwarder,
                get_human_help,
            ]
        else:
            tools = [get_human_help]

        config = types.GenerateContentConfig(
            tools=tools,
            system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT,
            temperature=0.0,
        )

        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL, contents=genai_history, config=config
        )

        assistant_message: Optional[InteractionMessage] = None
        tool_call_name: Optional[str] = None
        next_state = current_state

        if response.function_calls:
            model_turn_content = response.candidates[0].content
            history_messages.extend(
                _genai_content_to_interaction_messages([model_turn_content])
            )

            tool_results = {}
            fr_parts = []

            for part in model_turn_content.parts:
                fc = part.function_call
                tool_name = fc.name
                tool_args = dict(fc.args) if fc.args else {}
                tool_function = next((t for t in tools if t.__name__ == tool_name), None)

                if tool_function:
                    result = tool_function(**tool_args)
                    tool_results[tool_name] = result
                    fr_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=tool_name, response={'result': result}
                            )
                        )
                    )

            tool_turn_content = types.Content(role='tool', parts=fr_parts)
            history_messages.extend(
                _genai_content_to_interaction_messages([tool_turn_content])
            )
            updated_genai_history = await _get_genai_history(history_messages)

            if 'get_human_help' in tool_results:
                next_state = ClientePotencialState.HUMAN_ESCALATION
                assistant_message_text = get_human_help()
                tool_call_name = 'get_human_help'
            elif 'needs_freight_forwarder' in tool_results:
                next_state = ClientePotencialState.CUSTOMER_DISCARDED
                assistant_message_text = "Para consultas sobre agenciamiento de carga contacta a nuestro ejecutivo comercial  **Luis Alberto Beltrán** al correo **labeltran@cargadirecta.co** o al teléfono **312 390 0599**."
                tool_call_name = 'needs_freight_forwarder'
            else:
                if 'is_persona_natural' in tool_results:
                    next_state = ClientePotencialState.AWAITING_REMAINING_INFORMATION
                elif 'search_nit' in tool_results:
                    next_state = ClientePotencialState.NIT_PROVIDED

                # After a tool call, get the model's textual response
                response2 = await client.aio.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=updated_genai_history,
                    config=config,
                )
                assistant_message_text = response2.text
        else:
            assistant_message_text = response.text

        assistant_message = InteractionMessage(
            type='assistant', message=assistant_message_text
        )
        history_messages.append(assistant_message)

        if interaction:
            interaction.messages = [msg.model_dump() for msg in history_messages]
            interaction.state = next_state
        else:
            interaction = models.Interaction(
                session_id=interaction_request.sessionId,
                messages=[msg.model_dump() for msg in history_messages],
                state=next_state,
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
