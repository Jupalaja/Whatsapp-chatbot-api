import logging
from typing import Optional, Any, Literal

import google.genai as genai

from src.shared.state import GlobalState

from .prompts import CLIENTE_POTENCIAL_AUTOPILOT_SYSTEM_PROMPT
from .state import ClientePotencialState
from .workflows import (
    _workflow_awaiting_nit,
    _workflow_awaiting_persona_natural_freight_info,
    _workflow_awaiting_remaining_information,
    _workflow_customer_asked_for_email_data_sent,
)
from src.services.google_sheets import GoogleSheetsService
from src.shared.enums import InteractionType
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.shared.utils.functions import handle_conversation_finished

logger = logging.getLogger(__name__)


async def handle_cliente_potencial(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: ClientePotencialState,
    interaction_data: Optional[dict],
    user_data: Optional[dict],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> tuple[list[InteractionMessage], GlobalState, str | None, dict] | tuple[
    list[InteractionMessage], ClientePotencialState, str | None, dict] | tuple[
         list[InteractionMessage], Literal[ClientePotencialState.HUMAN_ESCALATION], str, dict[str, str] | dict[
             Any, Any]]:

    interaction_data = dict(interaction_data) if interaction_data else {}

    if current_state == ClientePotencialState.CONVERSATION_FINISHED:
        return await handle_conversation_finished(
            session_id=session_id,
            history_messages=history_messages,
            interaction_data=interaction_data,
            client=client,
            autopilot_system_prompt=CLIENTE_POTENCIAL_AUTOPILOT_SYSTEM_PROMPT,
        )

    if current_state == ClientePotencialState.AWAITING_NIT:
        return await _workflow_awaiting_nit(
            session_id, history_messages, interaction_data, user_data, client, sheets_service
        )
    if current_state == ClientePotencialState.AWAITING_PERSONA_NATURAL_FREIGHT_INFO:
        return await _workflow_awaiting_persona_natural_freight_info(
            history_messages, interaction_data, user_data, client, sheets_service
        )
    if current_state == ClientePotencialState.CUSTOMER_ASKED_FOR_EMAIL_DATA_SENT:
        return await _workflow_customer_asked_for_email_data_sent(
            history_messages, interaction_data, user_data, client, sheets_service
        )
    if current_state == ClientePotencialState.AWAITING_REMAINING_INFORMATION:
        return await _workflow_awaiting_remaining_information(
            history_messages, interaction_data, user_data, client, sheets_service
        )

    logger.warning(
        f"Unhandled in-progress state: {current_state}. Escalating to human."
    )
    assistant_message_text = obtener_ayuda_humana()
    tool_call_name = "obtener_ayuda_humana"
    next_state = ClientePotencialState.HUMAN_ESCALATION
    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )
    return [assistant_message], next_state, tool_call_name, interaction_data
