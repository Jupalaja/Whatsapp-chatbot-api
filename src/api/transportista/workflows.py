import logging
from typing import Optional, Tuple
from datetime import datetime

import google.genai as genai

from .prompts import (
    TRANSPORTISTA_SYSTEM_PROMPT,
    PROMPT_PAGO_DE_MANIFIESTOS,
    PROMPT_ENTURNAMIENTOS,
    TRANSPORTISTA_VIDEO_SENT_SYSTEM_PROMPT,
    PROMPT_VIDEO_REGISTRO_USUARIO_NUEVO_INSTRUCTIONS,
    PROMPT_VIDEO_ACTUALIZACION_DATOS_INSTRUCTIONS,
    PROMPT_VIDEO_CREAR_TURNO_INSTRUCTIONS,
    PROMPT_VIDEO_REPORTE_EVENTOS_INSTRUCTIONS,
    PROMPT_FALLBACK_VIDEO,
)
from .state import TransportistaState
from .tools import (
    es_consulta_manifiestos,
    es_consulta_enturnamientos,
    es_consulta_app,
    enviar_video_registro_app,
    enviar_video_actualizacion_datos_app,
    enviar_video_enturno_app,
    enviar_video_reporte_eventos_app,
)
from src.config import settings
from src.shared.state import GlobalState
from src.shared.enums import InteractionType, CategoriaTransportista
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana, nueva_interaccion_requerida
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.functions import execute_tool_calls_and_get_response

logger = logging.getLogger(__name__)

VIDEO_INSTRUCTIONS_MAP = {
    "registro-usuario-nuevo.mp4": PROMPT_VIDEO_REGISTRO_USUARIO_NUEVO_INSTRUCTIONS,
    "actualizacion-de-datos.mp4": PROMPT_VIDEO_ACTUALIZACION_DATOS_INSTRUCTIONS,
    "crear-turno.mp4": PROMPT_VIDEO_CREAR_TURNO_INSTRUCTIONS,
    "reporte-de-eventos.mp4": PROMPT_VIDEO_REPORTE_EVENTOS_INSTRUCTIONS,
}


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


async def _workflow_video_sent(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    interaction_data: dict,
) -> Tuple[list[InteractionMessage], TransportistaState, Optional[str], dict]:
    """
    Handles the conversation flow after a video has been sent to the carrier.
    """
    video_file = interaction_data.get("video_to_send", {}).get("video_file")
    if not video_file or video_file not in VIDEO_INSTRUCTIONS_MAP:
        logger.warning(
            f"No valid video file found in interaction_data for video_sent state. Escalating."
        )
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

    instructions = VIDEO_INSTRUCTIONS_MAP[video_file]
    system_prompt = TRANSPORTISTA_VIDEO_SENT_SYSTEM_PROMPT.format(
        instructions=instructions
    )

    tools = [obtener_ayuda_humana, nueva_interaccion_requerida]

    (
        text_response,
        tool_results,
        tool_call_names,
        _,
    ) = await execute_tool_calls_and_get_response(
        history_messages, client, tools, system_prompt
    )

    if "obtener_ayuda_humana" in tool_results:
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

    if "nueva_interaccion_requerida" in tool_results:
        interaction_data.pop("classifiedAs", None)
        interaction_data.pop("special_list_sent", None)
        interaction_data.pop("messages_after_finished_count", None)
        interaction_data.pop("video_to_send", None)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message="Claro, ¿en qué más puedo ayudarte?",
                )
            ],
            GlobalState.AWAITING_RECLASSIFICATION,
            "nueva_interaccion_requerida",
            interaction_data,
        )

    if text_response:
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=text_response)],
            TransportistaState.VIDEO_SENT,
            None,
            interaction_data,
        )

    # Fallback if no text response and no tool call
    logger.warning("VIDEO_SENT workflow did not result in a clear action. Escalating.")
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
        es_consulta_manifiestos,
        es_consulta_enturnamientos,
        es_consulta_app,
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

    # Prioritize terminal/special actions
    if "obtener_ayuda_humana" in tool_results:
        return [
            InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
        ], TransportistaState.HUMAN_ESCALATION, "obtener_ayuda_humana", interaction_data

    # Handle classification tools that provide a direct response
    if tool_results.get("es_consulta_manifiestos"):
        interaction_data["tipo_de_solicitud"] = CategoriaTransportista.MANIFIESTOS.value
        await _write_transportista_to_sheet(interaction_data, sheets_service)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_PAGO_DE_MANIFIESTOS
                )
            ],
            TransportistaState.CONVERSATION_FINISHED,
            "es_consulta_manifiestos",
            interaction_data,
        )

    if tool_results.get("es_consulta_enturnamientos"):
        interaction_data[
            "tipo_de_solicitud"
        ] = CategoriaTransportista.ENTURNAMIENTOS.value
        await _write_transportista_to_sheet(interaction_data, sheets_service)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_ENTURNAMIENTOS
                )
            ],
            TransportistaState.CONVERSATION_FINISHED,
            "es_consulta_enturnamientos",
            interaction_data,
        )

    video_tool_map = {
        "enviar_video_registro_app": "send_video_message",
        "enviar_video_actualizacion_datos_app": "send_video_message",
        "enviar_video_enturno_app": "send_video_message",
        "enviar_video_reporte_eventos_app": "send_video_message",
    }
    video_tool_names = [tool for tool in video_tool_map if tool in tool_results]

    # Handle specific video-based app queries
    if video_tool_names:
        # It's an app query, so log it if not already logged.
        if (
            interaction_data.get("tipo_de_solicitud")
            != CategoriaTransportista.APP_CONDUCTORES.value
        ):
            interaction_data[
                "tipo_de_solicitud"
            ] = CategoriaTransportista.APP_CONDUCTORES.value
            await _write_transportista_to_sheet(interaction_data, sheets_service)

        # Only one video can be sent at a time
        video_tool_name = video_tool_names[0]
        call_name = video_tool_map[video_tool_name]

        video_info = tool_results[video_tool_name]
        message_text = text_response or video_info.get("caption")
        if not message_text:
            logger.warning(
                f"No text_response or caption for video tool {video_tool_name}. Using default message."
            )
            message_text = PROMPT_FALLBACK_VIDEO

        # Update the caption in the video info to match the final message text
        video_info["caption"] = message_text
        interaction_data["video_to_send"] = video_info

        return (
            [InteractionMessage(role=InteractionType.MODEL, message=message_text)],
            TransportistaState.VIDEO_SENT,
            call_name,
            interaction_data,
        )

    # Handle generic app queries that don't have a specific video tool
    if tool_results.get("es_consulta_app"):
        # We know from the check above that no specific video tool was called.
        if "app_query_turn_count" not in interaction_data:
            interaction_data["app_query_turn_count"] = 0

        interaction_data["app_query_turn_count"] += 1
        interaction_data[
            "tipo_de_solicitud"
        ] = CategoriaTransportista.APP_CONDUCTORES.value
        await _write_transportista_to_sheet(interaction_data, sheets_service)

        # If this is the second time we have a generic app query, escalate.
        if interaction_data["app_query_turn_count"] > 1:
            logger.warning(
                f"Generic app query detected for the second time. Escalating to human. Query: '{history_messages[-1].message}'"
            )
            # Cleanup
            interaction_data.pop("app_query_turn_count", None)
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

        # First generic app query, if there is a text response, use it to ask for more details.
        if text_response:
            return (
                [InteractionMessage(role=InteractionType.MODEL, message=text_response)],
                TransportistaState.AWAITING_REQUEST_TYPE,
                "es_consulta_app",
                interaction_data,
            )
        # If no text response on first try, this is unexpected. Escalate.
        else:
            logger.warning(
                f"Generic app query detected but no text response from model on first try. Escalating. Query: '{history_messages[-1].message}'"
            )
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

    # If we are here, it's not a generic app query. Reset counter if it exists.
    if "app_query_turn_count" in interaction_data:
        interaction_data.pop("app_query_turn_count", None)

    # If there's a text response, it's likely for ambiguity resolution (e.g., "enturnamiento" without "app")
    if text_response:
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=text_response)],
            TransportistaState.AWAITING_REQUEST_TYPE,
            None,
            interaction_data,
        )

    # Fallback to human if no other action was taken
    logger.warning(
        "Transportista workflow did not result in a clear action. Escalating."
    )
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
