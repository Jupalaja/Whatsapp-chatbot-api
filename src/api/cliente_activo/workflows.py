import logging
from typing import Optional, Tuple
from datetime import datetime

import google.genai as genai
from google.genai import types, errors

from .prompts import (
    CLIENTE_ACTIVO_AWAITING_NIT_SYSTEM_PROMPT,
    CLIENTE_ACTIVO_SYSTEM_PROMPT,
    PROMPT_TRAZABILIDAD,
    PROMPT_BLOQUEOS_CARTERA,
    PROMPT_FACTURACION,
    PROMPT_CLIENTE_ACTIVO_AGENTE_COMERCIAL,
    PROMPT_CLIENTE_ACTIVO_SIN_AGENTE_COMERCIAL,
)
from .state import ClienteActivoState
from .tools import (
    buscar_nit as buscar_nit_tool,
    es_consulta_trazabilidad,
    es_consulta_bloqueos_cartera,
    es_consulta_facturacion,
    es_consulta_cotizacion,
    limpiar_datos_agente_comercial,
    obtener_informacion_cliente_activo,
)
from src.config import settings
from src.shared.constants import GEMINI_MODEL
from src.shared.enums import InteractionType, CategoriaClienteActivo
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.shared.utils.history import get_genai_history
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.functions import (
    get_response_text,
    invoke_model_with_retries,
    execute_tool_calls_and_get_response,
    get_final_text_response,
)

logger = logging.getLogger(__name__)


async def _write_cliente_activo_to_sheet(
    interaction_data: dict, sheets_service: Optional[GoogleSheetsService]
):
    if interaction_data.get("sheet_row_added"):
        logger.info("Data for active client has already been written to Google Sheet. Skipping.")
        return

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
        nombre_empresa = interaction_data.get("nombre_empresa", "")
        tipo_de_solicitud = interaction_data.get("categoria", "")
        descripcion_de_necesidad = interaction_data.get("descripcion_de_necesidad", "")

        row_to_append = [
            fecha_perfilacion,
            nit,
            nombre_empresa,
            tipo_de_solicitud,
            descripcion_de_necesidad,
        ]

        sheets_service.append_row(worksheet, row_to_append)
        interaction_data["sheet_row_added"] = True
        logger.info("Successfully wrote data for active client to Google Sheet and marked as added.")

    except Exception as e:
        logger.error(f"Failed to write to Google Sheet: {e}", exc_info=True)


async def _clean_commercial_agent_data(
    search_result: dict, client: genai.Client
) -> dict:
    """
    Cleans commercial agent data using the model to determine if it's valid.

    Returns:
        dict with cleaned data or indication that no valid agent was found
    """
    responsable_comercial = search_result.get("responsable_comercial", "")
    email = search_result.get("email", "")
    telefono = search_result.get("phoneNumber", "")

    if not responsable_comercial:
        return {"agente_valido": False, "razon": "No se encontró responsable comercial"}

    # Create a simple prompt for the data cleaning
    cleaning_prompt = f"""
    Analiza los siguientes datos de un agente comercial obtenidos de Google Sheets y determina si representan un agente válido:
    
    Responsable comercial: "{responsable_comercial}"
    Email: "{email}"
    Teléfono: "{telefono}"
    
    Usa la herramienta limpiar_datos_agente_comercial para procesar estos datos.
    """

    tools = [limpiar_datos_agente_comercial]

    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction="Eres un experto en limpieza de datos. Analiza los datos del agente comercial y determina si son válidos.",
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    try:
        response = await invoke_model_with_retries(
            client.aio.models.generate_content,
            model=GEMINI_MODEL,
            contents=[{"role": "user", "parts": [{"text": cleaning_prompt}]}],
            config=config,
        )

        if response.function_calls:
            function_call = response.function_calls[0]
            if function_call.name == "limpiar_datos_agente_comercial":
                return dict(function_call.args)

        # Fallback if no function call
        return {"agente_valido": False, "razon": "No se pudo procesar los datos del agente"}

    except Exception as e:
        logger.error(f"Error cleaning commercial agent data: {e}")
        return {"agente_valido": False, "razon": "Error al procesar los datos del agente"}


async def _workflow_awaiting_nit_cliente_activo(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
    interaction_data: dict,
) -> Tuple[list[InteractionMessage], ClienteActivoState, Optional[str], dict]:
    """Handles the workflow when the assistant is waiting for the user's NIT."""

    def buscar_nit(nit: str):
        """Captura el NIT de la empresa proporcionado por el usuario y busca en Google Sheets."""
        search_result = {}
        if settings.GOOGLE_SHEET_ID_CLIENTES_POTENCIALES and sheets_service:
            worksheet = sheets_service.get_worksheet(
                spreadsheet_id=settings.GOOGLE_SHEET_ID_CLIENTES_POTENCIALES,
                worksheet_name="NITS",
            )
            if worksheet:
                records = sheets_service.read_data(worksheet)
                found_record = None
                for record in records:
                    if str(record.get("NIT - 10 DIGITOS")) == nit or str(
                        record.get("NIT - 9 DIGITOS")
                    ) == nit:
                        found_record = record
                        break

                if found_record:
                    logger.info(
                        f"Columns found in sheet for NIT {nit}: {list(found_record.keys())}"
                    )
                    logger.info(f"Found NIT {nit} in Google Sheet: {found_record}")
                    search_result = {
                        "cliente": found_record.get(" CLIENTE"),
                        "estado": found_record.get(" ESTADO DEL CLIENTE"),
                        "responsable_comercial": found_record.get(
                            " RESPONSABLE COMERCIAL"
                        ),
                        "phoneNumber": found_record.get(" CELULAR"),
                        "email": found_record.get(" CORREO"),
                    }
                    # Strip whitespace from string values
                    for key, value in search_result.items():
                        if isinstance(value, str):
                            search_result[key] = value.strip()
                else:
                    logger.info(f"NIT {nit} not found in Google Sheet.")
                    search_result = {
                        "cliente": "No encontrado",
                        "estado": "No encontrado",
                        "responsable_comercial": "No encontrado",
                    }
            else:
                logger.error("Could not access NITS worksheet.")
                search_result = {
                    "cliente": "Error de sistema",
                    "estado": "Error de sistema",
                    "responsable_comercial": "Error de sistema",
                }
        else:
            logger.warning(
                "GOOGLE_SHEET_ID_CLIENTES_POTENCIALES is not set or sheets_service is not available. Skipping NIT check."
            )
            search_result = {
                "cliente": "No verificado",
                "estado": "No verificado",
                "responsable_comercial": "No verificado",
            }
        return search_result

    tools = [
        buscar_nit_tool,
        obtener_informacion_cliente_activo,
        obtener_ayuda_humana
    ]

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
            model=GEMINI_MODEL,
            contents=genai_history,
            config=config,
        )
    except errors.ServerError as e:
        logger.error(f"Gemini API Server Error after retries: {e}", exc_info=True)
        interaction_data["categoria"] = CategoriaClienteActivo.OTRO.value
        await _write_cliente_activo_to_sheet(interaction_data, sheets_service)
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
    nit_provided = False

    if response.function_calls:
        for function_call in response.function_calls:
            if function_call.name == "buscar_nit":
                nit = function_call.args.get("nit")
                if nit:
                    interaction_data["nit"] = nit
                    search_result = buscar_nit(nit)
                    interaction_data["resultado_buscar_nit"] = search_result
                    nit_provided = True
                    tool_call_name = "buscar_nit"

            elif function_call.name == "obtener_informacion_cliente_activo":
                nombre_empresa = function_call.args.get("nombre_empresa")
                if nombre_empresa:
                    interaction_data["nombre_empresa"] = nombre_empresa
                if not tool_call_name:
                    tool_call_name = "obtener_informacion_cliente_activo"

            elif function_call.name == "obtener_ayuda_humana":
                interaction_data["categoria"] = CategoriaClienteActivo.OTRO.value
                await _write_cliente_activo_to_sheet(interaction_data, sheets_service)
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL, message=obtener_ayuda_humana()
                )
                next_state = ClienteActivoState.HUMAN_ESCALATION
                tool_call_name = "obtener_ayuda_humana"
                break

        if nit_provided:
            return await handle_in_progress_cliente_activo(
                history_messages, client, sheets_service, interaction_data
            )

    if not assistant_message:
        assistant_message_text = get_response_text(response)
        if not assistant_message_text:
            # If the model, following instructions, provides no text,
            # it means we should proceed without the NIT.
            return await handle_in_progress_cliente_activo(
                history_messages, client, sheets_service, interaction_data
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
    tools = [
        es_consulta_trazabilidad,
        es_consulta_bloqueos_cartera,
        es_consulta_facturacion,
        es_consulta_cotizacion,
        obtener_ayuda_humana,
    ]

    (
        text_response,
        tool_results,
        tool_call_names,
        _,
    ) = await execute_tool_calls_and_get_response(
        history_messages, client, tools, CLIENTE_ACTIVO_SYSTEM_PROMPT
    )

    if "obtener_ayuda_humana" in tool_results:
        interaction_data["categoria"] = CategoriaClienteActivo.OTRO.value
        await _write_cliente_activo_to_sheet(interaction_data, sheets_service)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=obtener_ayuda_humana()
                )
            ],
            ClienteActivoState.HUMAN_ESCALATION,
            "obtener_ayuda_humana",
            interaction_data,
        )

    base_message_text = None
    tool_call_name = None
    if tool_results.get("es_consulta_trazabilidad"):
        interaction_data["categoria"] = CategoriaClienteActivo.TRAZABILIDAD.value
        base_message_text = PROMPT_TRAZABILIDAD
        tool_call_name = "es_consulta_trazabilidad"
    elif tool_results.get("es_consulta_bloqueos_cartera"):
        interaction_data["categoria"] = CategoriaClienteActivo.BLOQUEOS_CARTERA.value
        base_message_text = PROMPT_BLOQUEOS_CARTERA
        tool_call_name = "es_consulta_bloqueos_cartera"
    elif tool_results.get("es_consulta_facturacion"):
        interaction_data["categoria"] = CategoriaClienteActivo.FACTURACION.value
        base_message_text = PROMPT_FACTURACION
        tool_call_name = "es_consulta_facturacion"
    elif tool_results.get("es_consulta_cotizacion"):
        interaction_data["categoria"] = CategoriaClienteActivo.COTIZACION.value
        tool_call_name = "es_consulta_cotizacion"
        next_state = ClienteActivoState.CONVERSATION_FINISHED
        search_result = interaction_data.get("resultado_buscar_nit", {})
        final_message_text = PROMPT_CLIENTE_ACTIVO_SIN_AGENTE_COMERCIAL

        if search_result.get("responsable_comercial") and search_result.get(
            "responsable_comercial"
        ) not in ["No encontrado", "Error de sistema", "SIN RESPONSABLE"]:
            cleaned_data = await _clean_commercial_agent_data(search_result, client)

            if cleaned_data.get("agente_valido"):
                nombre_formateado = cleaned_data.get("nombre_formateado", "")
                email_valido = cleaned_data.get("email_valido", "")
                telefono_valido = cleaned_data.get("telefono_valido", "")

                contact_details = ""
                if email_valido and telefono_valido:
                    contact_details = f" Lo puedes contactar al correo *{email_valido}* o al teléfono *{telefono_valido}*."
                elif email_valido:
                    contact_details = (
                        f" Lo puedes contactar al correo *{email_valido}*."
                    )
                elif telefono_valido:
                    contact_details = (
                        f" Lo puedes contactar al teléfono *{telefono_valido}*."
                    )

                final_message_text = PROMPT_CLIENTE_ACTIVO_AGENTE_COMERCIAL.format(
                    responsable_comercial=nombre_formateado,
                    contact_details=contact_details,
                )

        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=final_message_text
        )
        interaction_data["descripcion_de_necesidad"] = ""
        await _write_cliente_activo_to_sheet(interaction_data, sheets_service)

        return [assistant_message], next_state, tool_call_name, interaction_data

    if base_message_text:
        next_state = ClienteActivoState.CONVERSATION_FINISHED
        final_message_text = base_message_text
        search_result = interaction_data.get("resultado_buscar_nit", {})

        # Check if a valid commercial agent was found
        if search_result.get("responsable_comercial") and search_result.get(
            "responsable_comercial"
        ) not in ["No encontrado", "Error de sistema", "SIN RESPONSABLE"]:
            cleaned_data = await _clean_commercial_agent_data(search_result, client)

            if cleaned_data.get("agente_valido"):
                nombre_formateado = cleaned_data.get("nombre_formateado", "")
                email_valido = cleaned_data.get("email_valido", "")
                telefono_valido = cleaned_data.get("telefono_valido", "")

                contact_details = ""
                if email_valido and telefono_valido:
                    contact_details = f" Lo puedes contactar al correo *{email_valido}* o al teléfono *{telefono_valido}*."
                elif email_valido:
                    contact_details = (
                        f" Lo puedes contactar al correo *{email_valido}*."
                    )
                elif telefono_valido:
                    contact_details = (
                        f" Lo puedes contactar al teléfono *{telefono_valido}*."
                    )

                agent_info_text = PROMPT_CLIENTE_ACTIVO_AGENTE_COMERCIAL.format(
                    responsable_comercial=nombre_formateado,
                    contact_details=contact_details,
                )
                final_message_text += f"\n\n{agent_info_text}"

        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=final_message_text
        )
        interaction_data["descripcion_de_necesidad"] = ""
        await _write_cliente_activo_to_sheet(interaction_data, sheets_service)

        return [assistant_message], next_state, tool_call_name, interaction_data

    if text_response:
        return (
            [InteractionMessage(role=InteractionType.MODEL, message=text_response)],
            ClienteActivoState.AWAITING_RESOLUTION,
            None,
            interaction_data,
        )

    # Fallback to human if no other action was taken
    logger.warning(
        "Cliente activo workflow did not result in a clear action. Escalating."
    )
    interaction_data["categoria"] = CategoriaClienteActivo.OTRO.value
    await _write_cliente_activo_to_sheet(interaction_data, sheets_service)
    return (
        [
            InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
        ],
        ClienteActivoState.HUMAN_ESCALATION,
        "obtener_ayuda_humana",
        interaction_data,
    )
