import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types

from .prompts import TRANSPORTISTA_AUTOPILOT_SYSTEM_PROMPT
from .state import TransportistaState
from .workflows import handle_in_progress_transportista
from src.shared.constants import GEMINI_MODEL, MESSAGES_AFTER_CONVERSATION_FINISHED
from src.shared.tools import obtener_ayuda_humana
from src.shared.schemas import InteractionMessage
from src.shared.enums import InteractionType
from src.shared.prompts import AYUDA_HUMANA_PROMPT
from src.shared.utils.history import get_genai_history
from src.services.google_sheets import GoogleSheetsService

logger = logging.getLogger(__name__)


async def handle_conversation_finished(
    session_id: str,
    history_messages: list[InteractionMessage],
    interaction_data: dict,
    client: genai.Client,
) -> Tuple[list[InteractionMessage], TransportistaState, Optional[str], dict]:
    """Handles interactions after the main conversation flow has finished."""
    messages_after_finished_count = (
        interaction_data.get("messages_after_finished_count", 0) + 1
    )
    interaction_data["messages_after_finished_count"] = messages_after_finished_count

    if messages_after_finished_count >= MESSAGES_AFTER_CONVERSATION_FINISHED:
        logger.info(
            f"User with sessionId {session_id} has sent more than {MESSAGES_AFTER_CONVERSATION_FINISHED} messages. Activating human help tool."
        )
        assistant_message_text = obtener_ayuda_humana()
        tool_call_name = "obtener_ayuda_humana"
        next_state = TransportistaState.HUMAN_ESCALATION
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )
        return [assistant_message], next_state, tool_call_name, interaction_data

    genai_history = await get_genai_history(history_messages)

    autopilot_config = types.GenerateContentConfig(
        tools=[obtener_ayuda_humana],
        system_instruction=TRANSPORTISTA_AUTOPILOT_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=autopilot_config
    )

    tool_call_name = None
    assistant_message_text = None
    next_state = TransportistaState.CONVERSATION_FINISHED

    if (
        response.function_calls
        and response.function_calls[0].name == "obtener_ayuda_humana"
    ):
        tool_call_name = "obtener_ayuda_humana"
        assistant_message_text = obtener_ayuda_humana()
        next_state = TransportistaState.HUMAN_ESCALATION
    else:
        assistant_message_text = response.text

    if not assistant_message_text:
        assistant_message_text = AYUDA_HUMANA_PROMPT
        tool_call_name = "obtener_ayuda_humana"
        next_state = TransportistaState.HUMAN_ESCALATION

    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )

    return [assistant_message], next_state, tool_call_name, interaction_data


async def handle_in_progress_conversation(
    history_messages: list[InteractionMessage],
    current_state: TransportistaState,
    interaction_data: dict,
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], TransportistaState, Optional[str], dict]:
    """
    Handles the main, in-progress conversation states by dispatching to the
    appropriate workflow function based on the current state.
    """
    if current_state == TransportistaState.AWAITING_REQUEST_TYPE:
        (
            messages,
            next_state,
            tool_call,
            interaction_data,
        ) = await handle_in_progress_transportista(
            history_messages, client, sheets_service, interaction_data
        )
        return messages, next_state, tool_call, interaction_data

    logger.warning(
        f"Unhandled in-progress state: {current_state}. Escalating to human."
    )
    assistant_message_text = obtener_ayuda_humana()
    tool_call_name = "obtener_ayuda_humana"
    next_state = TransportistaState.HUMAN_ESCALATION
    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )
    return [assistant_message], next_state, tool_call_name, interaction_data
