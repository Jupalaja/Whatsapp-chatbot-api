import logging
from typing import Optional, Any

import google.genai as genai

from src.shared.enums import InteractionType
from src.shared.state import GlobalState
from .prompts import USUARIO_ADMINISTRATIVO_AUTOPILOT_SYSTEM_PROMPT
from .state import UsuarioAdministrativoState
from .workflows import (
    handle_in_progress_usuario_administrativo,
    _workflow_awaiting_admin_info,
)
from src.services.google_sheets import GoogleSheetsService
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.shared.utils.functions import (
    handle_conversation_finished,
)

logger = logging.getLogger(__name__)


async def handle_usuario_administrativo(
    session_id: str,
    history_messages: list[InteractionMessage],
    current_state: UsuarioAdministrativoState,
    interaction_data: Optional[dict],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> tuple[list[InteractionMessage], GlobalState, str | None, dict] | tuple[
    list[InteractionMessage], Any, str | None, dict
]:

    interaction_data = dict(interaction_data) if interaction_data else {}

    if current_state == UsuarioAdministrativoState.CONVERSATION_FINISHED:
        return await handle_conversation_finished(
            session_id=session_id,
            history_messages=history_messages,
            interaction_data=interaction_data,
            client=client,
            autopilot_system_prompt=USUARIO_ADMINISTRATIVO_AUTOPILOT_SYSTEM_PROMPT,
        )

    if current_state == UsuarioAdministrativoState.AWAITING_NECESITY_TYPE:
        return await handle_in_progress_usuario_administrativo(
            history_messages, client, sheets_service, interaction_data
        )

    if current_state == UsuarioAdministrativoState.AWAITING_ADMIN_INFO:
        return await _workflow_awaiting_admin_info(
            history_messages, client, sheets_service, interaction_data
        )

    logger.warning(
        f"Unhandled in-progress state: {current_state}. Escalating to human."
    )
    assistant_message_text = obtener_ayuda_humana()
    tool_call_name = "obtener_ayuda_humana"
    next_state = GlobalState.HUMAN_ESCALATION
    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )
    return [assistant_message], next_state, tool_call_name, interaction_data
