import logging
from typing import Optional, Tuple
from datetime import datetime

import google.genai as genai
from google.genai import types, errors

from .prompts import (
    TRANSPORTISTA_SYSTEM_PROMPT,
    PROMPT_PAGO_DE_MANIFIESTOS,
    PROMPT_ENTURNAMIENTOS,
)
from .state import TransportistaState
from .tools import obtener_tipo_de_solicitud
from src.config import settings
from src.shared.constants import GEMINI_MODEL
from src.shared.enums import InteractionType, CategoriaTransportista
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.shared.utils.history import get_genai_history
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.functions import get_response_text, invoke_model_with_retries

logger = logging.getLogger(__name__)


async def _write_transportista_to_sheet(
    interaction_data: dict, sheets_service: Optional[GoogleSheetsService]
):
    if not settings.GOOGLE_SHEET_ID_EXPORT or not sheets_service:
        logger.warning(
            "Spreadsheet ID for export not configured or sheets service not available. Skipping write."
        )
        return

    try:
        worksheet = sheets_service.get_worksheet(
            spreadsheet_id=settings.GOOGLE_SHEET_ID_EXPORT,
            worksheet_name="TRANSPORTISTAS",
        )
        if not worksheet:
            logger.error("Could not find TRANSPORTISTAS worksheet.")
            return

        fecha_perfilacion = datetime.now().strftime("%d/%m/%Y")
        tipo_de_solicitud = interaction_data.get("tipo_de_solicitud", "")

        row_to_append = [
            fecha_perfilacion,
            "",
            "",
            tipo_de_solicitud,
        ]

        sheets_service.append_row(worksheet, row_to_append)
        logger.info("Successfully wrote data for carrier to Google Sheet.")

    except Exception as e:
        logger.error(f"Failed to write to Google Sheet: {e}", exc_info=True)


async def handle_in_progress_transportista(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
    interaction_data: dict,
) -> Tuple[list[InteractionMessage], TransportistaState, Optional[str], dict]:
    """
    Handles the conversation flow for a carrier who is in an in-progress state.
    """
    genai_history = await get_genai_history(history_messages)
    model = GEMINI_MODEL

    tools = [
        obtener_tipo_de_solicitud,
        obtener_ayuda_humana,
    ]

    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=TRANSPORTISTA_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    
    try:
        response = await invoke_model_with_retries(
            client.aio.models.generate_content,
            model=model, contents=genai_history, config=config
        )
    except errors.ServerError as e:
        logger.error(f"Gemini API Server Error after retries: {e}", exc_info=True)
        assistant_message_text = obtener_ayuda_humana(reason=f"Error de API: {e}")
        tool_call_name = "obtener_ayuda_humana"
        next_state = TransportistaState.HUMAN_ESCALATION
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )
        return [assistant_message], next_state, tool_call_name, interaction_data

    assistant_message = None
    tool_call_name = None
    next_state = TransportistaState.AWAITING_REQUEST_TYPE

    if response.function_calls:
        function_call = response.function_calls[0]
        tool_call_name = function_call.name

        if function_call.name == "obtener_tipo_de_solicitud":
            categoria = function_call.args.get("categoria")
            interaction_data["tipo_de_solicitud"] = categoria

            if categoria == CategoriaTransportista.MANIFIESTOS.value:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_PAGO_DE_MANIFIESTOS
                )
                next_state = TransportistaState.CONVERSATION_FINISHED
            elif categoria == CategoriaTransportista.ENTURNAMIENTOS.value:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_ENTURNAMIENTOS
                )
                next_state = TransportistaState.CONVERSATION_FINISHED
            elif categoria == CategoriaTransportista.APP_CONDUCTORES.value:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=obtener_ayuda_humana()
                )
                tool_call_name = "obtener_ayuda_humana"
                next_state = TransportistaState.HUMAN_ESCALATION

            if next_state == TransportistaState.CONVERSATION_FINISHED:
                await _write_transportista_to_sheet(interaction_data, sheets_service)

        elif function_call.name == "obtener_ayuda_humana":
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
            next_state = TransportistaState.HUMAN_ESCALATION

    if not assistant_message:
        assistant_message_text = get_response_text(response)
        if assistant_message_text:
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=assistant_message_text
            )
            next_state = TransportistaState.AWAITING_REQUEST_TYPE
        else:
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
            tool_call_name = "obtener_ayuda_humana"
            next_state = TransportistaState.HUMAN_ESCALATION

    return [assistant_message], next_state, tool_call_name, interaction_data
