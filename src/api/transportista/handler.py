import logging
from typing import Optional, Any

import google.genai as genai

from src.shared.state import GlobalState
from .prompts import TRANSPORTISTA_AUTOPILOT_SYSTEM_PROMPT
from .state import TransportistaState
from .workflows import (
    handle_in_progress_transportista,
    _workflow_video_sent,
    _workflow_awaiting_transportista_info,
)
from src.services.google_sheets import GoogleSheetsService
from src.shared.schemas import InteractionMessage
from src.shared.utils.functions import (
    handle_conversation_finished,
    handle_in_progress_conversation,
)
from src.shared.tools import obtener_ayuda_humana
from src.shared.enums import InteractionType

logger = logging.getLogger(__name__)


async def handle_transportista(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: TransportistaState,
    interaction_data: Optional[dict],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> tuple[list[InteractionMessage], GlobalState, str | None, dict] | tuple[
    list[InteractionMessage], Any, str | None, dict
]:

    interaction_data = dict(interaction_data) if interaction_data else {}

    if current_state == TransportistaState.CONVERSATION_FINISHED:
        return await handle_conversation_finished(
            session_id=session_id,
            history_messages=history_messages,
            interaction_data=interaction_data,
            client=client,
            autopilot_system_prompt=TRANSPORTISTA_AUTOPILOT_SYSTEM_PROMPT,
        )

    if current_state == TransportistaState.VIDEO_SENT:
        return await _workflow_video_sent(
            history_messages=history_messages,
            client=client,
            interaction_data=interaction_data,
            sheets_service=sheets_service,
        )

    if current_state == TransportistaState.AWAITING_TRANSPORTISTA_INFO:
        return await _workflow_awaiting_transportista_info(
            history_messages=history_messages,
            client=client,
            sheets_service=sheets_service,
            interaction_data=interaction_data,
        )

    if current_state == TransportistaState.AWAITING_REQUEST_TYPE:
        return await handle_in_progress_conversation(
            history_messages=history_messages,
            current_state=current_state,
            in_progress_state=TransportistaState.AWAITING_REQUEST_TYPE,
            interaction_data=interaction_data,
            client=client,
            sheets_service=sheets_service,
            workflow_function=handle_in_progress_transportista,
        )

    logger.warning(
        f"Unhandled transportista state: {current_state}. Escalating to human."
    )
    assistant_message_text = obtener_ayuda_humana()
    tool_call_name = "obtener_ayuda_humana"
    next_state = GlobalState.HUMAN_ESCALATION
    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )
    return [assistant_message], next_state, tool_call_name, interaction_data
