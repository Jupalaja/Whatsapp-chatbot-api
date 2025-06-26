import logging
from typing import Optional, Tuple

import google.genai as genai

from .conversation_flow import (
    handle_conversation_finished,
    handle_in_progress_conversation,
)
from .state import CandidatoAEmpleoState
from src.shared.schemas import InteractionMessage
from src.services.google_sheets import GoogleSheetsService

logger = logging.getLogger(__name__)


async def handle_candidato_a_empleo(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: CandidatoAEmpleoState,
    interaction_data: Optional[dict],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], CandidatoAEmpleoState, Optional[str], dict]:
    """
    Handles the core logic of the conversation based on its current state.

    This function orchestrates the interaction with the generative model,
    including tool selection, model calls, and state transitions, by delegating
    to the appropriate function based on the conversation's state.

    Args:
        session_id: The ID of the current conversation session.
        history_messages: The full message history of the conversation.
        current_state: The current state of the conversation state machine.
        interaction_data: The stored data from the interaction.
        client: The configured Google GenAI client.
        sheets_service: The service for interacting with Google Sheets.

    Returns:
        A tuple containing:
        - A list of new messages from the assistant to be sent to the user.
        - The next state of the conversation.
        - The name of a tool call if one was triggered for special client-side handling.
        - The updated interaction data.
    """
    interaction_data = dict(interaction_data) if interaction_data else {}

    if current_state == CandidatoAEmpleoState.CONVERSATION_FINISHED:
        return await handle_conversation_finished(
            session_id=session_id,
            history_messages=history_messages,
            interaction_data=interaction_data,
            client=client,
        )
    else:
        return await handle_in_progress_conversation(
            history_messages=history_messages,
            current_state=current_state,
            interaction_data=interaction_data,
            client=client,
            sheets_service=sheets_service,
        )
