import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types

from .prompts import (
    CLIENTE_ACTIVO_SYSTEM_PROMPT,
    PROMPT_TRAZABILIDAD,
    PROMPT_BLOQUEOS_CARTERA,
    PROMPT_FACTURACION,
)
from .state import ClienteActivoState
from .tools import clasificar_solicitud_cliente_activo
from src.shared.constants import GEMINI_MODEL
from src.shared.enums import InteractionType, CategoriaClienteActivo
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.shared.utils.history import get_genai_history

logger = logging.getLogger(__name__)


async def handle_in_progress_cliente_activo(
    history_messages: list[InteractionMessage], client: genai.Client
) -> Tuple[list[InteractionMessage], Optional[str], ClienteActivoState]:
    """
    Handles the conversation flow for an active client who is in an in-progress state.

    Args:
        history_messages: The full message history of the conversation.
        client: The configured Google GenAI client.

    Returns:
        A tuple containing:
        - A list of new messages from the assistant to be sent to the user.
        - The name of a tool call if one was triggered for special client-side handling.
        - The next state of the conversation.
    """
    genai_history = await get_genai_history(history_messages)
    model = GEMINI_MODEL

    tools = [
        clasificar_solicitud_cliente_activo,
        obtener_ayuda_humana,
    ]

    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_ACTIVO_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    response = await client.aio.models.generate_content(
        model=model, contents=genai_history, config=config
    )

    assistant_message = None
    tool_call_name = None
    next_state = ClienteActivoState.AWAITING_RESOLUTION

    if response.function_calls:
        function_call = response.function_calls[0]
        tool_call_name = function_call.name

        if function_call.name == "clasificar_solicitud_cliente_activo":
            categoria = function_call.args.get("categoria")
            if categoria == CategoriaClienteActivo.TRAZABILIDAD.value:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_TRAZABILIDAD
                )
                next_state = ClienteActivoState.CONVERSATION_FINISHED
            elif categoria == CategoriaClienteActivo.BLOQUEOS_CARTERA.value:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_BLOQUEOS_CARTERA
                )
                next_state = ClienteActivoState.CONVERSATION_FINISHED
            elif categoria == CategoriaClienteActivo.FACTURACION.value:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_FACTURACION
                )
                next_state = ClienteActivoState.CONVERSATION_FINISHED
            else:  # OTRO
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=obtener_ayuda_humana()
                )
                tool_call_name = "obtener_ayuda_humana"
                next_state = ClienteActivoState.HUMAN_ESCALATION
        elif function_call.name == "obtener_ayuda_humana":
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
            next_state = ClienteActivoState.HUMAN_ESCALATION

    if not assistant_message:
        if response.text:
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=response.text
            )
            next_state = ClienteActivoState.AWAITING_RESOLUTION
        else:
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
            tool_call_name = "obtener_ayuda_humana"
            next_state = ClienteActivoState.HUMAN_ESCALATION

    return [assistant_message], tool_call_name, next_state
