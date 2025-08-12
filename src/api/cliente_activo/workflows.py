import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types, errors

from .prompts import (
    CLIENTE_ACTIVO_AWAITING_NIT_SYSTEM_PROMPT,
    CLIENTE_ACTIVO_SYSTEM_PROMPT,
    PROMPT_TRAZABILIDAD,
    PROMPT_BLOQUEOS_CARTERA,
    PROMPT_FACTURACION,
)
from .state import ClienteActivoState
from .tools import (
    obtener_nit,
    clasificar_solicitud_cliente_activo
)
from src.config import settings
from src.shared.constants import GEMINI_MODEL
from src.shared.enums import InteractionType, CategoriaClienteActivo
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.shared.utils.history import get_genai_history
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.functions import summarize_user_request, get_response_text, invoke_model_with_retries

logger = logging.getLogger(__name__)


async def _write_cliente_activo_to_sheet(
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
            worksheet_name="CLIENTES_ACTUALES",
        )
        if not worksheet:
            logger.error("Could not find CLIENTES_ACTUALES worksheet.")
            return

        fecha_perfilacion = datetime.now().strftime("%d/%m/%Y")
        nit = interaction_data.get("nit", "")
        tipo_de_solicitud = interaction_data.get("categoria", "")
        descripcion_de_necesidad = interaction_data.get("descripcion_de_necesidad", "")

        row_to_append = [
            fecha_perfilacion,
            nit,
            "",
            tipo_de_solicitud,
            descripcion_de_necesidad,
        ]

        sheets_service.append_row(worksheet, row_to_append)
        logger.info("Successfully wrote data for active client to Google Sheet.")

    except Exception as e:
        logger.error(f"Failed to write to Google Sheet: {e}", exc_info=True)


async def _workflow_awaiting_nit_cliente_activo(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
    interaction_data: dict,
) -> Tuple[list[InteractionMessage], ClienteActivoState, Optional[str], dict]:
    """Handles the workflow when the assistant is waiting for the user's NIT."""


    tools = [obtener_nit, obtener_ayuda_humana]

    genai_history = await get_genai_history(history_messages)
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_ACTIVO_AWAITING_NIT_SYSTEM_PROMPT,
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
        assistant_message_text = obtener_ayuda_humana()
        tool_call_name = "obtener_ayuda_humana"
        next_state = ClienteActivoState.HUMAN_ESCALATION
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )
        return [assistant_message], next_state, tool_call_name, interaction_data


    assistant_message = None
    tool_call_name = None
    next_state = ClienteActivoState.AWAITING_NIT

    if response.function_calls:
        function_call = response.function_calls[0]
        tool_call_name = function_call.name

        if function_call.name == "obtener_nit":
            nit = function_call.args.get("nit")
            if nit:
                interaction_data["nit"] = nit

            return await handle_in_progress_cliente_activo(
                history_messages, client, sheets_service, interaction_data
            )
        elif function_call.name == "obtener_ayuda_humana":
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
            next_state = ClienteActivoState.HUMAN_ESCALATION

    if not assistant_message:
        assistant_message_text = get_response_text(response)
        if not assistant_message_text:
            assistant_message_text = (
                "Para continuar, por favor, indícame el NIT de tu empresa."
            )
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )

    return [assistant_message], next_state, tool_call_name, interaction_data


async def handle_in_progress_cliente_activo(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
    interaction_data: dict,
) -> Tuple[list[InteractionMessage], ClienteActivoState, Optional[str], dict]:
    """
    Handles the conversation flow for an active client who is in an in-progress state.

    Args:
        history_messages: The full message history of the conversation.
        client: The configured Google GenAI client.
        sheets_service: The service for interacting with Google Sheets.
        interaction_data: The stored data from the interaction.

    Returns:
        A tuple containing:
        - A list of new messages from the assistant to be sent to the user.
        - The next state of the conversation.
        - The name of a tool call if one was triggered for special client-side handling.
        - The updated interaction data.
    """
    genai_history = await get_genai_history(history_messages)
    model = GEMINI_MODEL

    tools = [
        clasificar_solicitud_cliente_activo,
        obtener_ayuda_humana,
    ]

    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_ACTIVO_SYSTEM_PROMPT,
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
        assistant_message_text = obtener_ayuda_humana()
        tool_call_name = "obtener_ayuda_humana"
        next_state = ClienteActivoState.HUMAN_ESCALATION
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )
        return [assistant_message], next_state, tool_call_name, interaction_data

    assistant_message = None
    tool_call_name = None
    next_state = ClienteActivoState.AWAITING_RESOLUTION

    if response.function_calls:
        function_call = response.function_calls[0]
        tool_call_name = function_call.name

        if function_call.name == "clasificar_solicitud_cliente_activo":
            categoria = function_call.args.get("categoria")
            interaction_data["categoria"] = categoria
            user_message = history_messages[-1].message if history_messages else ""
            if user_message:
                summary = await summarize_user_request(user_message, client)
                interaction_data["descripcion_de_necesidad"] = summary
            else:
                interaction_data["descripcion_de_necesidad"] = ""

            if categoria == CategoriaClienteActivo.TRAZABILIDAD.value:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_TRAZABILIDAD
                )
                next_state = ClienteActivoState.CONVERSATION_FINISHED
            elif categoria == CategoriaClienteActivo.BLOQUEOS_CARTERA.value:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_BLOQUEOS_CARTERA
                )
                next_state = ClienteActivoState.CONVERSATION_FINISHED
            elif categoria == CategoriaClienteActivo.FACTURACION.value:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=PROMPT_FACTURACION
                )
                next_state = ClienteActivoState.CONVERSATION_FINISHED
            else:  # OTRO
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=obtener_ayuda_humana()
                )
                tool_call_name = "obtener_ayuda_humana"
                next_state = ClienteActivoState.HUMAN_ESCALATION

            if next_state == ClienteActivoState.CONVERSATION_FINISHED:
                await _write_cliente_activo_to_sheet(
                    interaction_data, sheets_service
                )

        elif function_call.name == "obtener_ayuda_humana":
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
            next_state = ClienteActivoState.HUMAN_ESCALATION

    if not assistant_message:
        assistant_message_text = get_response_text(response)
        if assistant_message_text:
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=assistant_message_text
            )
            next_state = ClienteActivoState.AWAITING_RESOLUTION
        else:
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
            tool_call_name = "obtener_ayuda_humana"
            next_state = ClienteActivoState.HUMAN_ESCALATION

    return [assistant_message], next_state, tool_call_name, interaction_data
