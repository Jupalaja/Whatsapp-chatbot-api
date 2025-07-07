import logging
from typing import Optional, Any

import google.genai as genai

from src.shared.state import GlobalState
from .prompts import TRANSPORTISTA_AUTOPILOT_SYSTEM_PROMPT
from .state import TransportistaState
from .workflows import handle_in_progress_transportista
from src.services.google_sheets import GoogleSheetsService
from src.shared.schemas import InteractionMessage
from src.shared.utils.functions import (
    handle_conversation_finished,
    handle_in_progress_conversation,
)

logger = logging.getLogger(__name__)


async def handle_transportista(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: TransportistaState,
    interaction_data: Optional[dict],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> tuple[list[InteractionMessage], GlobalState, str | None, dict] | tuple[
    list[InteractionMessage], Any, str | None, dict]:

    interaction_data = dict(interaction_data) if interaction_data else {}

    if current_state == TransportistaState.CONVERSATION_FINISHED:
        return await handle_conversation_finished(
            session_id=session_id,
            history_messages=history_messages,
            interaction_data=interaction_data,
            client=client,
            autopilot_system_prompt=TRANSPORTISTA_AUTOPILOT_SYSTEM_PROMPT,
        )
    else:
        return await handle_in_progress_conversation(
            history_messages=history_messages,
            current_state=current_state,
            in_progress_state=TransportistaState.AWAITING_REQUEST_TYPE,
            interaction_data=interaction_data,
            client=client,
            sheets_service=sheets_service,
            workflow_function=handle_in_progress_transportista,
        )
