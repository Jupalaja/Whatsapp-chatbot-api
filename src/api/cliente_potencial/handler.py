import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types

from .prompts import (
    CLIENTE_POTENCIAL_SYSTEM_PROMPT,
    PROMPT_AGENCIAMIENTO_DE_CARGA,
    PROMPT_DISCARD_PERSONA_NATURAL,
)
from .tools import (
    is_persona_natural,
    needs_freight_forwarder,
    search_nit,
)
from .state import ClientePotencialState

from src.shared.constants import GEMINI_MODEL
from src.shared.tools import get_human_help
from src.shared.schemas import InteractionMessage
from src.shared.enums import InteractionType
from src.shared.utils.history import get_genai_history, genai_content_to_interaction_messages

logger = logging.getLogger(__name__)


async def handle_cliente_potencial(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: ClientePotencialState,
    client: genai.Client,
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str]]:
    """
    Handles the core logic of the conversation based on its current state.

    This function orchestrates the interaction with the generative model,
    including tool selection, model calls, and state transitions.

    Args:
        session_id: The ID of the current conversation session.
        history_messages: The full message history of the conversation.
        current_state: The current state of the conversation state machine.
        client: The configured Google GenAI client.

    Returns:
        A tuple containing:
        - A list of new messages from the assistant to be sent to the user.
        - The next state of the conversation.
        - The name of a tool call if one was triggered for special client-side handling.
    """
    genai_history = await get_genai_history(history_messages)

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
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=config
    )

    assistant_message_text: Optional[str] = None
    tool_call_name: Optional[str] = None
    next_state = current_state

    if not response.function_calls:
        if current_state == ClientePotencialState.AWAITING_REMAINING_INFORMATION:
            next_state = ClientePotencialState.CONVERSATION_FINISHED
            assistant_message_text = PROMPT_DISCARD_PERSONA_NATURAL
        else:
            assistant_message_text = response.text
    else:
        model_turn_content = response.candidates[0].content
        history_messages.extend(
            genai_content_to_interaction_messages([model_turn_content])
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

        if fr_parts:
            tool_turn_content = types.Content(role='tool', parts=fr_parts)
            history_messages.extend(
                genai_content_to_interaction_messages([tool_turn_content])
            )

        if 'get_human_help' in tool_results:
            next_state = ClientePotencialState.HUMAN_ESCALATION
            assistant_message_text = get_human_help()
            tool_call_name = 'get_human_help'
        elif 'needs_freight_forwarder' in tool_results:
            next_state = ClientePotencialState.CONVERSATION_FINISHED
            assistant_message_text = PROMPT_AGENCIAMIENTO_DE_CARGA
            tool_call_name = 'needs_freight_forwarder'
        else:
            if 'is_persona_natural' in tool_results:
                next_state = ClientePotencialState.AWAITING_REMAINING_INFORMATION
            elif 'search_nit' in tool_results:
                next_state = ClientePotencialState.NIT_PROVIDED

            updated_genai_history = await get_genai_history(history_messages)
            response2 = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=updated_genai_history,
                config=config,
            )
            assistant_message_text = response2.text

    if assistant_message_text is None:
        logger.warning(
            f"No response text generated for session {session_id}. Escalating to human."
        )
        assistant_message_text = get_human_help()
        tool_call_name = "get_human_help"
        next_state = ClientePotencialState.HUMAN_ESCALATION

    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )

    return [assistant_message], next_state, tool_call_name
