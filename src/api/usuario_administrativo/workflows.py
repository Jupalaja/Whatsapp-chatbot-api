import logging
from typing import Optional, Tuple
from datetime import datetime

import google.genai as genai
from google.genai import types, errors

from .prompts import (
    USUARIO_ADMINISTRATIVO_GATHER_INFO_SYSTEM_PROMPT,
    USUARIO_ADMINISTRATIVO_SYSTEM_PROMPT,
    PROMPT_RETEFUENTE,
    PROMPT_CERTIFICADO_LABORAL,
)
from .state import UsuarioAdministrativoState
from .tools import (
    es_consulta_retefuente,
    es_consulta_certificado_laboral,
    obtener_informacion_administrativo,
)
from src.config import settings
from src.shared.constants import GEMINI_MODEL
from src.shared.enums import InteractionType, CategoriaUsuarioAdministrativo
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.functions import (
    execute_tool_calls_and_get_response,
    get_final_text_response,
    invoke_model_with_retries,
)
from ...shared.utils.history import get_genai_history

logger = logging.getLogger(__name__)


async def _write_usuario_administrativo_to_sheet(
    interaction_data: dict, sheets_service: Optional[GoogleSheetsService]
):
    if interaction_data.get("sheet_row_added"):
        logger.info("Data for administrative user has already been written to Google Sheet. Skipping.")
        return

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
        nit_cedula = interaction_data.get("nit_cedula", "")
        nombre = interaction_data.get("nombre", "")

        row_to_append = [
            fecha_perfilacion,
            nit_cedula,
            nombre,
            tipo_de_necesidad,
        ]

        sheets_service.append_row(worksheet, row_to_append)
        interaction_data["sheet_row_added"] = True
        logger.info("Successfully wrote data for administrative user to Google Sheet and marked as added.")

    except Exception as e:
        logger.error(f"Failed to write to Google Sheet: {e}", exc_info=True)


async def _workflow_awaiting_admin_info(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
    interaction_data: dict,
) -> Tuple[list[InteractionMessage], UsuarioAdministrativoState, Optional[str], dict]:
    """Handles the workflow for gathering admin info from an administrative user."""
    genai_history = await get_genai_history(history_messages)

    tools = [
        obtener_informacion_administrativo,
        obtener_ayuda_humana,
    ]

    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=USUARIO_ADMINISTRATIVO_GATHER_INFO_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    try:
        response = await invoke_model_with_retries(
            client.aio.models.generate_content,
            model=GEMINI_MODEL,
            contents=genai_history,
            config=config,
        )
    except errors.ServerError as e:
        logger.error(f"Gemini API Server Error after retries: {e}", exc_info=True)
        interaction_data[
            "tipo_de_necesidad"
        ] = CategoriaUsuarioAdministrativo.OTRO.value
        await _write_usuario_administrativo_to_sheet(interaction_data, sheets_service)
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

    tool_call_name = None
    if response.function_calls:
        function_call = response.function_calls[0]
        tool_call_name = function_call.name

        if function_call.name == "obtener_informacion_administrativo":
            info = dict(function_call.args)
            interaction_data["nit_cedula"] = info.get("nit_cedula")
            interaction_data["nombre"] = info.get("nombre")

        elif function_call.name == "obtener_ayuda_humana":
            interaction_data[
                "tipo_de_necesidad"
            ] = CategoriaUsuarioAdministrativo.OTRO.value
            await _write_usuario_administrativo_to_sheet(
                interaction_data, sheets_service
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

    await _write_usuario_administrativo_to_sheet(interaction_data, sheets_service)

    final_prompt = ""
    if (
        interaction_data.get("tipo_de_necesidad")
        == CategoriaUsuarioAdministrativo.RETEFUENTE.value
    ):
        final_prompt = PROMPT_RETEFUENTE
    elif (
        interaction_data.get("tipo_de_necesidad")
        == CategoriaUsuarioAdministrativo.CERTIFICADO_LABORAL.value
    ):
        final_prompt = PROMPT_CERTIFICADO_LABORAL
    else:
        logger.error(
            f"Could not determine final prompt for tipo_de_necesidad: {interaction_data.get('tipo_de_necesidad')}. Escalating."
        )
        final_prompt = obtener_ayuda_humana()
        interaction_data[
            "tipo_de_necesidad"
        ] = CategoriaUsuarioAdministrativo.OTRO.value
        await _write_usuario_administrativo_to_sheet(interaction_data, sheets_service)
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=final_prompt)],
            UsuarioAdministrativoState.HUMAN_ESCALATION,
            "obtener_ayuda_humana",
            interaction_data,
        )

    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=final_prompt
    )
    return (
        [assistant_message],
        UsuarioAdministrativoState.CONVERSATION_FINISHED,
        tool_call_name,
        interaction_data,
    )


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
        interaction_data[
            "tipo_de_necesidad"
        ] = CategoriaUsuarioAdministrativo.OTRO.value
        await _write_usuario_administrativo_to_sheet(interaction_data, sheets_service)
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

    next_state = UsuarioAdministrativoState.AWAITING_NECESITY_TYPE
    tool_call_name = None

    if tool_results.get("es_consulta_retefuente"):
        interaction_data[
            "tipo_de_necesidad"
        ] = CategoriaUsuarioAdministrativo.RETEFUENTE.value
        next_state = UsuarioAdministrativoState.AWAITING_ADMIN_INFO
        tool_call_name = "es_consulta_retefuente"
    elif tool_results.get("es_consulta_certificado_laboral"):
        interaction_data[
            "tipo_de_necesidad"
        ] = CategoriaUsuarioAdministrativo.CERTIFICADO_LABORAL.value
        next_state = UsuarioAdministrativoState.AWAITING_ADMIN_INFO
        tool_call_name = "es_consulta_certificado_laboral"

    if next_state == UsuarioAdministrativoState.AWAITING_ADMIN_INFO:
        assistant_message_text = await get_final_text_response(
            history_messages, client, USUARIO_ADMINISTRATIVO_GATHER_INFO_SYSTEM_PROMPT
        )
        if not assistant_message_text:
            assistant_message_text = (
                "Para continuar, ¿podrías indicarme tu nombre y NIT/Cédula?"
            )

        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=assistant_message_text
                )
            ],
            next_state,
            tool_call_name,
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
    interaction_data["tipo_de_necesidad"] = CategoriaUsuarioAdministrativo.OTRO.value
    await _write_usuario_administrativo_to_sheet(interaction_data, sheets_service)
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
