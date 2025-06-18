import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types

from .prompts import (
    CLIENTE_POTENCIAL_AUTOPILOT_SYSTEM_PROMPT,
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

from src.shared.constants import GEMINI_MODEL, MESSAGES_AFTER_CONVERSATION_FINISHED
from src.shared.tools import get_human_help
from src.shared.schemas import InteractionMessage
from src.shared.enums import InteractionType
from src.shared.utils.history import get_genai_history, genai_content_to_interaction_messages

logger = logging.getLogger(__name__)


async def handle_conversation_finished(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: ClientePotencialState,
    interaction_data: dict,
    client: genai.Client,
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles interactions after the main conversation flow has finished."""
    messages_after_finished_count = (
        interaction_data.get("messages_after_finished_count", 0) + 1
    )
    interaction_data["messages_after_finished_count"] = messages_after_finished_count

    if messages_after_finished_count >= MESSAGES_AFTER_CONVERSATION_FINISHED:
        logger.info(
            f"User with sessionId {session_id} has sent more than"
            f" {MESSAGES_AFTER_CONVERSATION_FINISHED} messages. Activating"
            " human help tool."
        )
        assistant_message_text = get_human_help()
        tool_call_name = "get_human_help"
        next_state = ClientePotencialState.HUMAN_ESCALATION
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )
        return [assistant_message], next_state, tool_call_name, interaction_data

    genai_history = await get_genai_history(history_messages)

    autopilot_config = types.GenerateContentConfig(
        tools=[get_human_help],
        system_instruction=CLIENTE_POTENCIAL_AUTOPILOT_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    )

    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=autopilot_config
    )

    tool_call_name = None
    assistant_message_text = None
    next_state = current_state

    if (
        response.function_calls
        and response.function_calls[0].name == "get_human_help"
    ):
        tool_call_name = "get_human_help"
        assistant_message_text = get_human_help()
        next_state = ClientePotencialState.HUMAN_ESCALATION
    else:
        assistant_message_text = response.text

    if not assistant_message_text:
        assistant_message_text = "I'm not sure how to help with that. Would you like to talk to a human agent?"
        tool_call_name = "get_human_help"
        next_state = ClientePotencialState.HUMAN_ESCALATION

    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )

    return [assistant_message], next_state, tool_call_name, interaction_data


async def handle_in_progress_conversation(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: ClientePotencialState,
    interaction_data: dict,
    client: genai.Client,
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the main, in-progress conversation states."""
    genai_history = await get_genai_history(history_messages)

    if current_state == ClientePotencialState.AWAITING_NIT:
        tools = [search_nit, is_persona_natural, get_human_help]
    elif current_state == ClientePotencialState.AWAITING_PERSONA_NATURAL_FREIGHT_INFO:
        tools = [needs_freight_forwarder, get_human_help]
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
        if current_state == ClientePotencialState.AWAITING_PERSONA_NATURAL_FREIGHT_INFO:
            next_state = ClientePotencialState.CONVERSATION_FINISHED
            assistant_message_text = PROMPT_DISCARD_PERSONA_NATURAL
            interaction_data["messages_after_finished_count"] = 0
        else:
            assistant_message_text = response.text
            if current_state == ClientePotencialState.AWAITING_REMAINING_INFORMATION:
                next_state = ClientePotencialState.CONVERSATION_FINISHED
                interaction_data["messages_after_finished_count"] = 0
    else:
        model_turn_content = response.candidates[0].content
        history_messages.extend(
            genai_content_to_interaction_messages([model_turn_content])
        )

        tool_results = {}
        fr_parts = []

        for part in model_turn_content.parts:
            fc = part.function_call
            if not fc:
                continue

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
            interaction_data["messages_after_finished_count"] = 0
        else:
            # Non-terminal tool calls, require another LLM call
            if 'search_nit' in tool_results:
                interaction_data['search_nit_result'] = tool_results['search_nit']
                next_state = ClientePotencialState.AWAITING_REMAINING_INFORMATION
            elif 'is_persona_natural' in tool_results:
                next_state = (
                    ClientePotencialState.AWAITING_PERSONA_NATURAL_FREIGHT_INFO
                )

            # Update config for the second call, disabling tool use to get a text response
            final_config = types.GenerateContentConfig(
                system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT,
                temperature=0.0,
            )

            updated_genai_history = await get_genai_history(history_messages)
            response2 = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=updated_genai_history,
                config=final_config,
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

    return [assistant_message], next_state, tool_call_name, interaction_data
