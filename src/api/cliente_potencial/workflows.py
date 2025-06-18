import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types

from .prompts import (
    CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT,
    CLIENTE_POTENCIAL_SYSTEM_PROMPT,
    PROMPT_AGENCIAMIENTO_DE_CARGA,
    PROMPT_DISCARD_PERSONA_NATURAL,
)
from .state import ClientePotencialState
from .tools import (
    get_informacion_cliente_potencial,
    is_persona_natural,
    is_valid_city,
    is_valid_item,
    needs_freight_forwarder,
    search_nit,
)
from src.shared.constants import GEMINI_MODEL
from src.shared.enums import InteractionType
from src.shared.schemas import InteractionMessage
from src.shared.tools import get_human_help
from src.shared.utils.history import (
    genai_content_to_interaction_messages,
    get_genai_history,
)

logger = logging.getLogger(__name__)


async def _get_final_text_response(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    system_prompt: str,
) -> str:
    """Gets a final conversational response from the model without using tools."""
    final_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.0,
    )
    updated_genai_history = await get_genai_history(history_messages)
    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=updated_genai_history,
        config=final_config,
    )
    return response.text


async def _workflow_awaiting_nit(
    history_messages: list[InteractionMessage],
    interaction_data: dict,
    client: genai.Client,
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow when the assistant is waiting for the user's NIT."""
    tools = [search_nit, is_persona_natural, get_human_help]
    genai_history = await get_genai_history(history_messages)
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=config
    )

    if not response.function_calls:
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=response.text)],
            ClientePotencialState.AWAITING_NIT,
            None,
            interaction_data,
        )

    model_turn_content = response.candidates[0].content
    history_messages.extend(genai_content_to_interaction_messages([model_turn_content]))

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

    if "get_human_help" in tool_results:
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=get_human_help())],
            ClientePotencialState.HUMAN_ESCALATION,
            "get_human_help",
            interaction_data,
        )

    if "search_nit" in tool_results:
        interaction_data["search_nit_result"] = tool_results["search_nit"]
        assistant_message_text = await _get_final_text_response(
            history_messages, client, CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT
        )
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=assistant_message_text
                )
            ],
            ClientePotencialState.AWAITING_REMAINING_INFORMATION,
            None,
            interaction_data,
        )

    if "is_persona_natural" in tool_results:
        assistant_message_text = await _get_final_text_response(
            history_messages, client, CLIENTE_POTENCIAL_SYSTEM_PROMPT
        )
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=assistant_message_text
                )
            ],
            ClientePotencialState.AWAITING_PERSONA_NATURAL_FREIGHT_INFO,
            None,
            interaction_data,
        )

    assistant_message_text = await _get_final_text_response(
        history_messages, client, CLIENTE_POTENCIAL_SYSTEM_PROMPT
    )
    return (
        [InteractionMessage(role=InteractionType.MODEL, message=assistant_message_text)],
        ClientePotencialState.AWAITING_NIT,
        None,
        interaction_data,
    )


async def _workflow_awaiting_persona_natural_freight_info(
    history_messages: list[InteractionMessage],
    interaction_data: dict,
    client: genai.Client,
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow when waiting for freight info from a natural person."""
    tools = [needs_freight_forwarder, get_human_help]
    genai_history = await get_genai_history(history_messages)
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=config
    )

    if (
        response.function_calls
        and response.function_calls[0].name == "needs_freight_forwarder"
    ):
        assistant_message_text = PROMPT_AGENCIAMIENTO_DE_CARGA
        next_state = ClientePotencialState.CONVERSATION_FINISHED
        tool_call_name = "needs_freight_forwarder"
        interaction_data["messages_after_finished_count"] = 0
    else:
        # If no tool call or a different one, we assume they don't need it.
        assistant_message_text = PROMPT_DISCARD_PERSONA_NATURAL
        next_state = ClientePotencialState.CONVERSATION_FINISHED
        tool_call_name = None
        interaction_data["messages_after_finished_count"] = 0

    return (
        [InteractionMessage(role=InteractionType.MODEL, message=assistant_message_text)],
        next_state,
        tool_call_name,
        interaction_data,
    )


async def _workflow_awaiting_remaining_information(
    history_messages: list[InteractionMessage],
    interaction_data: dict,
    client: genai.Client,
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow for gathering detailed information from a potential client."""
    tools = [
        get_informacion_cliente_potencial,
        is_valid_item,
        is_valid_city,
        get_human_help,
    ]
    genai_history = await get_genai_history(history_messages)

    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=config
    )

    if not response.function_calls:
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=response.text)],
            ClientePotencialState.AWAITING_REMAINING_INFORMATION,
            None,
            interaction_data,
        )

    model_turn_content = response.candidates[0].content
    history_messages.extend(genai_content_to_interaction_messages([model_turn_content]))

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

    if "get_human_help" in tool_results:
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=get_human_help())],
            ClientePotencialState.HUMAN_ESCALATION,
            "get_human_help",
            interaction_data,
        )

    if "get_informacion_cliente_potencial" in tool_results:
        interaction_data["cliente_potencial_info"] = tool_results[
            "get_informacion_cliente_potencial"
        ]
        assistant_message_text = await _get_final_text_response(
            history_messages, client, CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT
        )
        interaction_data["messages_after_finished_count"] = 0
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=assistant_message_text
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            None,
            interaction_data,
        )

    assistant_message_text = await _get_final_text_response(
        history_messages, client, CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT
    )

    return (
        [InteractionMessage(role=InteractionType.MODEL, message=assistant_message_text)],
        ClientePotencialState.AWAITING_REMAINING_INFORMATION,
        None,
        interaction_data,
    )
