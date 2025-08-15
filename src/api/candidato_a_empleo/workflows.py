import logging
from typing import Optional, Tuple
from datetime import datetime

import google.genai as genai
from google.genai import types, errors

from .prompts import (
    CANDIDATO_A_EMPLEO_SYSTEM_PROMPT,
    PROMPT_CONTACTO_HOJA_DE_VIDA,
)
from .state import CandidatoAEmpleoState
from .tools import obtener_informacion_candidato
from src.config import settings
from src.shared.constants import GEMINI_MODEL
from src.shared.enums import InteractionType
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.shared.utils.history import get_genai_history
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.functions import (
    get_response_text,
    invoke_model_with_retries,
)

logger = logging.getLogger(__name__)


async def _write_candidato_a_empleo_to_sheet(
    interaction_data: dict, sheets_service: Optional[GoogleSheetsService]
):
    if interaction_data.get("sheet_row_added"):
        logger.info("Data for job candidate has already been written to Google Sheet. Skipping.")
        return

    if not settings.GOOGLE_SHEET_ID_EXPORT or not sheets_service:
        logger.warning(
            "Spreadsheet ID for export not configured or sheets service not available. Skipping write."
        )
        return

    try:
        worksheet = sheets_service.get_worksheet(
            spreadsheet_id=settings.GOOGLE_SHEET_ID_EXPORT,
            worksheet_name="ASPIRANTES_EMPLEO",
        )
        if not worksheet:
            logger.error("Could not find ASPIRANTES_EMPLEO worksheet.")
            return

        fecha_perfilacion = datetime.now().strftime("%d/%m/%Y")
        nombre = interaction_data.get("nombre", "")
        cedula = interaction_data.get("cedula", "")
        vacante = interaction_data.get("vacante", "")

        row_to_append = [
            fecha_perfilacion,
            nombre,
            cedula,
            vacante,
        ]

        sheets_service.append_row(worksheet, row_to_append)
        interaction_data["sheet_row_added"] = True
        logger.info("Successfully wrote data for job candidate to Google Sheet and marked as added.")

    except Exception as e:
        logger.error(f"Failed to write to Google Sheet: {e}", exc_info=True)


async def handle_in_progress_candidato_a_empleo(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
    interaction_data: dict,
) -> Tuple[list[InteractionMessage], CandidatoAEmpleoState, Optional[str], dict]:
    """
    Handles the conversation flow for a job candidate.
    """
    genai_history = await get_genai_history(history_messages)

    tools = [
        obtener_informacion_candidato,
        obtener_ayuda_humana,
    ]

    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CANDIDATO_A_EMPLEO_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    try:
        response = await invoke_model_with_retries(
            client.aio.models.generate_content,
            model=GEMINI_MODEL, contents=genai_history, config=config
        )
    except errors.ServerError as e:
        logger.error(f"Gemini API Server Error after retries: {e}", exc_info=True)
        await _write_candidato_a_empleo_to_sheet(interaction_data, sheets_service)
        assistant_message_text = obtener_ayuda_humana()
        tool_call_name = "obtener_ayuda_humana"
        next_state = CandidatoAEmpleoState.HUMAN_ESCALATION
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )
        return [assistant_message], next_state, tool_call_name, interaction_data

    assistant_message = None
    tool_call_name = None
    next_state = CandidatoAEmpleoState.AWAITING_CANDIDATE_INFO

    if response.function_calls:
        function_call = response.function_calls[0]
        tool_call_name = function_call.name

        if function_call.name == "obtener_informacion_candidato":
            info = dict(function_call.args)
            interaction_data.update({k: v for k, v in info.items() if v is not None})

            await _write_candidato_a_empleo_to_sheet(interaction_data, sheets_service)
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=PROMPT_CONTACTO_HOJA_DE_VIDA
            )
            next_state = CandidatoAEmpleoState.CONVERSATION_FINISHED

        elif function_call.name == "obtener_ayuda_humana":
            await _write_candidato_a_empleo_to_sheet(interaction_data, sheets_service)
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
            next_state = CandidatoAEmpleoState.HUMAN_ESCALATION

    if not assistant_message:
        assistant_message_text = (
            get_response_text(response)
            or "Para continuar, ¿podrías indicarme tu nombre y número de cédula?"
        )
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )

    return [assistant_message], next_state, tool_call_name, interaction_data
