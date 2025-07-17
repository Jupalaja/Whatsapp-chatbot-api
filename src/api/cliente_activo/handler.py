import logging
from typing import Optional, Any

import google.genai as genai

from src.shared.state import GlobalState
from .prompts import CLIENTE_ACTIVO_AUTOPILOT_SYSTEM_PROMPT
from .state import ClienteActivoState
from .workflows import (
    handle_in_progress_cliente_activo,
    _workflow_awaiting_nit_cliente_activo,
)
from src.services.google_sheets import GoogleSheetsService
from src.shared.schemas import InteractionMessage
from src.shared.utils.functions import handle_conversation_finished
from src.shared.tools import obtener_ayuda_humana
from src.shared.enums import InteractionType

logger = logging.getLogger(__name__)


async def handle_cliente_activo(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: ClienteActivoState,
    interaction_data: Optional[dict],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> tuple[list[InteractionMessage], GlobalState, str | None, dict] | tuple[
    list[InteractionMessage], Any, str | None, dict
]:

    interaction_data = dict(interaction_data) if interaction_data else {}

    if current_state == ClienteActivoState.CONVERSATION_FINISHED:
        return await handle_conversation_finished(
            session_id=session_id,
            history_messages=history_messages,
            interaction_data=interaction_data,
            client=client,
            autopilot_system_prompt=CLIENTE_ACTIVO_AUTOPILOT_SYSTEM_PROMPT,
        )

    if current_state == ClienteActivoState.AWAITING_NIT:
        return await _workflow_awaiting_nit_cliente_activo(
            history_messages, client, sheets_service, interaction_data
        )

    if current_state == ClienteActivoState.AWAITING_RESOLUTION:
        return await handle_in_progress_cliente_activo(
            history_messages, client, sheets_service, interaction_data
        )

    logger.warning(
        f"Unhandled in-progress state for active client: {current_state}. Escalating to human."
    )
    assistant_message_text = obtener_ayuda_humana()
    tool_call_name = "obtener_ayuda_humana"
    next_state = GlobalState.HUMAN_ESCALATION
    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )
    return [assistant_message], next_state, tool_call_name, interaction_data
