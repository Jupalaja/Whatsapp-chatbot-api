import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types

from ...model.constants import GEMINI_MODEL
from ...model.prompts import CLIENTE_POTENCIAL_SYSTEM_PROMPT
from ...model.tools import (
    get_human_help,
    is_persona_natural,
    needs_freight_forwarder,
    search_nit,
)
from ...schemas import InteractionMessage
from .history import get_genai_history, genai_content_to_interaction_messages
from .state import ClientePotencialState

logger = logging.getLogger(__name__)


async def handle_interaction(
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
    # 1. Convert internal message history to the format required by the GenAI SDK.
    genai_history = await get_genai_history(history_messages)

    # 2. Select the appropriate tools based on the current conversation state.
    #    This implements the state machine logic for tool availability.
    if current_state == ClientePotencialState.AWAITING_NIT:
        tools = [search_nit, is_persona_natural, get_human_help]
    elif current_state == ClientePotencialState.AWAITING_REMAINING_INFORMATION:
        tools = [
            needs_freight_forwarder,
            get_human_help,
        ]
    else:
        # In terminal or other states, only allow escalating to a human.
        tools = [get_human_help]

    # 3. Configure the model call with tools and system prompt.
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT,
        temperature=0.0,  # Use low temperature for more deterministic, guided responses.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    # 4. Call the generative model with the history and configuration.
    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=config
    )

    assistant_message_text: Optional[str] = None
    tool_call_name: Optional[str] = None
    next_state = current_state

    # 5. Process the model's response.
    if not response.function_calls:
        # The model did not call a tool.
        if current_state == ClientePotencialState.AWAITING_REMAINING_INFORMATION:
            # Model didn't call 'needs_freight_forwarder', so we assume they don't need it.
            next_state = ClientePotencialState.CUSTOMER_DISCARDED
            assistant_message_text = (
                "Actualmente, nuestro enfoque está dirigido exclusivamente al mercado empresarial (B2B), "
                "por lo que no atendemos solicitudes de personas naturales. Por la naturaleza de la necesidad "
                "logística que mencionas, te recomendamos contactar una empresa especializada en servicios "
                "para personas naturales. Quedamos atentos en caso de que en el futuro surja alguna necesidad "
                "relacionada con transporte de carga pesada para empresas."
            )
        else:
            assistant_message_text = response.text
    else:
        # The model did call one or more tools.
        model_turn_content = response.candidates[0].content
        history_messages.extend(
            genai_content_to_interaction_messages([model_turn_content])
        )

        tool_results = {}
        fr_parts = []

        # 6. Execute tool calls.
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

        # 7. Add tool results to history.
        if fr_parts:
            tool_turn_content = types.Content(role='tool', parts=fr_parts)
            history_messages.extend(
                genai_content_to_interaction_messages([tool_turn_content])
            )

        # 8. Determine next state and response based on tool results.
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

            # After a tool call, get the model's final textual response.
            updated_genai_history = await get_genai_history(history_messages)
            response2 = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=updated_genai_history,
                config=config,
            )
            assistant_message_text = response2.text

    # Fallback for any case where we still don't have a message.
    if assistant_message_text is None:
        logger.warning(
            f"No response text generated for session {session_id}. Escalating to human."
        )
        assistant_message_text = get_human_help()
        tool_call_name = "get_human_help"
        next_state = ClientePotencialState.HUMAN_ESCALATION

    # 9. Formulate the final assistant message.
    assistant_message = InteractionMessage(
        type='assistant', message=assistant_message_text
    )

    return [assistant_message], next_state, tool_call_name
