import logging
from typing import Optional, Tuple
from datetime import datetime

import google.genai as genai

from .prompts import (
    USUARIO_ADMINISTRATIVO_SYSTEM_PROMPT,
    PROMPT_RETEFUENTE,
    PROMPT_CERTIFICADO_LABORAL,
)
from .state import UsuarioAdministrativoState
from .tools import es_consulta_retefuente, es_consulta_certificado_laboral
from src.config import settings
from src.shared.enums import InteractionType, CategoriaUsuarioAdministrativo
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.functions import execute_tool_calls_and_get_response

logger = logging.getLogger(__name__)


async def _write_usuario_administrativo_to_sheet(
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
            worksheet_name="ADMON",
        )
        if not worksheet:
            logger.error("Could not find ADMON worksheet.")
            return

        fecha_perfilacion = datetime.now().strftime("%d/%m/%Y")
        tipo_de_necesidad = interaction_data.get("tipo_de_necesidad", "")

        row_to_append = [
            fecha_perfilacion,
            "",
            "",
            tipo_de_necesidad,
        ]

        sheets_service.append_row(worksheet, row_to_append)
        logger.info("Successfully wrote data for administrative user to Google Sheet.")

    except Exception as e:
        logger.error(f"Failed to write to Google Sheet: {e}", exc_info=True)


async def handle_in_progress_usuario_administrativo(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
    interaction_data: dict,
) -> Tuple[list[InteractionMessage], UsuarioAdministrativoState, Optional[str], dict]:
    tools = [
        es_consulta_retefuente,
        es_consulta_certificado_laboral,
        obtener_ayuda_humana,
    ]

    (
        text_response,
        tool_results,
        tool_call_names,
        _,
    ) = await execute_tool_calls_and_get_response(
        history_messages, client, tools, USUARIO_ADMINISTRATIVO_SYSTEM_PROMPT
    )

    if "obtener_ayuda_humana" in tool_results:
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=obtener_ayuda_humana()
                )
            ],
            UsuarioAdministrativoState.HUMAN_ESCALATION,
            "obtener_ayuda_humana",
            interaction_data,
        )

    if tool_results.get("es_consulta_retefuente"):
        interaction_data[
            "tipo_de_necesidad"
        ] = CategoriaUsuarioAdministrativo.RETEFUENTE.value
        await _write_usuario_administrativo_to_sheet(interaction_data, sheets_service)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_RETEFUENTE
                )
            ],
            UsuarioAdministrativoState.CONVERSATION_FINISHED,
            "es_consulta_retefuente",
            interaction_data,
        )

    if tool_results.get("es_consulta_certificado_laboral"):
        interaction_data[
            "tipo_de_necesidad"
        ] = CategoriaUsuarioAdministrativo.CERTIFICADO_LABORAL.value
        await _write_usuario_administrativo_to_sheet(interaction_data, sheets_service)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_CERTIFICADO_LABORAL
                )
            ],
            UsuarioAdministrativoState.CONVERSATION_FINISHED,
            "es_consulta_certificado_laboral",
            interaction_data,
        )

    if text_response:
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=text_response)],
            UsuarioAdministrativoState.AWAITING_NECESITY_TYPE,
            None,
            interaction_data,
        )

    logger.warning(
        "Usuario administrativo workflow did not result in a clear action. Escalating."
    )
    return (
        [
            InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
        ],
        UsuarioAdministrativoState.HUMAN_ESCALATION,
        "obtener_ayuda_humana",
        interaction_data,
    )
