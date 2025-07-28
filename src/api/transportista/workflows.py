import logging
from typing import Optional, Tuple
from datetime import datetime

import google.genai as genai

from .prompts import (
    TRANSPORTISTA_SYSTEM_PROMPT,
    PROMPT_PAGO_DE_MANIFIESTOS,
    PROMPT_ENTURNAMIENTOS,
)
from .state import TransportistaState
from .tools import (
    obtener_tipo_de_solicitud,
    enviar_video_registro_app,
    enviar_video_actualizacion_datos_app,
    enviar_video_enturno_app,
    enviar_video_reporte_eventos_app,
)
from src.config import settings
from src.shared.enums import InteractionType, CategoriaTransportista
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.functions import execute_tool_calls_and_get_response

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
    tools = [
        obtener_tipo_de_solicitud,
        obtener_ayuda_humana,
        enviar_video_registro_app,
        enviar_video_actualizacion_datos_app,
        enviar_video_enturno_app,
        enviar_video_reporte_eventos_app,
    ]

    (
        text_response,
        tool_results,
        tool_call_names,
        _,
    ) = await execute_tool_calls_and_get_response(
        history_messages, client, tools, TRANSPORTISTA_SYSTEM_PROMPT
    )

    # --- Process results ---

    # Handle data collection tool first
    if "obtener_tipo_de_solicitud" in tool_results:
        categoria = tool_results.get("obtener_tipo_de_solicitud", {}).get("categoria")
        if categoria:
            interaction_data["tipo_de_solicitud"] = categoria
            await _write_transportista_to_sheet(interaction_data, sheets_service)

    # Prioritize terminal/special actions
    if "obtener_ayuda_humana" in tool_results:
        return [
            InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
        ], TransportistaState.HUMAN_ESCALATION, "obtener_ayuda_humana", interaction_data

    video_tool_map = {
        "enviar_video_registro_app": "send_video_message",
        "enviar_video_actualizacion_datos_app": "send_video_message",
        "enviar_video_enturno_app": "send_video_message",
        "enviar_video_reporte_eventos_app": "send_video_message",
    }
    for tool, call_name in video_tool_map.items():
        if tool in tool_results:
            interaction_data["video_to_send"] = tool_results[tool]
            return [], TransportistaState.CONVERSATION_FINISHED, call_name, interaction_data

    # If there's a text response, it takes precedence (e.g., asking for clarification)
    if text_response:
        final_tool_call = tool_call_names[0] if tool_call_names else None
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=text_response)],
            TransportistaState.AWAITING_REQUEST_TYPE,
            final_tool_call,
            interaction_data,
        )

    # Handle tools that generate a text response if no direct text_response was given
    if "obtener_tipo_de_solicitud" in tool_results:
        categoria = tool_results.get("obtener_tipo_de_solicitud", {}).get("categoria")
        if categoria == CategoriaTransportista.MANIFIESTOS.value:
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL, message=PROMPT_PAGO_DE_MANIFIESTOS
                    )
                ],
                TransportistaState.CONVERSATION_FINISHED,
                "obtener_tipo_de_solicitud",
                interaction_data,
            )
        elif categoria == CategoriaTransportista.ENTURNAMIENTOS.value:
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL, message=PROMPT_ENTURNAMIENTOS
                    )
                ],
                TransportistaState.CONVERSATION_FINISHED,
                "obtener_tipo_de_solicitud",
                interaction_data,
            )

    # Fallback to human if no other action was taken
    logger.warning("Transportista workflow did not result in a clear action. Escalating.")
    return (
        [
            InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
        ],
        TransportistaState.HUMAN_ESCALATION,
        "obtener_ayuda_humana",
        interaction_data,
    )
