import logging
from typing import Optional, Tuple

import google.genai as genai

from .state import ClientePotencialState
from .workflows import (
    handle_conversation_finished,
    handle_in_progress_conversation,
)
from src.shared.schemas import InteractionMessage

logger = logging.getLogger(__name__)


async def handle_cliente_potencial(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: ClientePotencialState,
    interaction_data: Optional[dict],
    client: genai.Client,
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], Optional[dict]]:
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

    Returns:
        A tuple containing:
        - A list of new messages from the assistant to be sent to the user.
        - The next state of the conversation.
        - The name of a tool call if one was triggered for special client-side handling.
        - The updated interaction data.
    """
    # Make a mutable copy of interaction_data to ensure changes are tracked
    interaction_data = dict(interaction_data) if interaction_data else {}

    if current_state == ClientePotencialState.CONVERSATION_FINISHED:
        return await handle_conversation_finished(
            session_id=session_id,
            history_messages=history_messages,
            current_state=current_state,
            interaction_data=interaction_data,
            client=client,
        )
    else:
        return await handle_in_progress_conversation(
            history_messages=history_messages,
            current_state=current_state,
            interaction_data=interaction_data,
            client=client,
        )
