import logging
from typing import Optional, Tuple
from datetime import datetime

import google.genai as genai
from google.genai import types

from .prompts import (
    CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT,
    CLIENTE_POTENCIAL_SYSTEM_PROMPT,
    PROMPT_AGENCIAMIENTO_DE_CARGA,
    PROMPT_ASIGNAR_AGENTE_COMERCIAL,
    PROMPT_CONTACTAR_AGENTE_ASIGNADO,
    PROMPT_CUSTOMER_REQUESTED_EMAIL,
    PROMPT_DISCARD_PERSONA_NATURAL,
    PROMPT_EMAIL_GUARDADO_Y_FINALIZAR,
    PROMPT_GET_CUSTOMER_EMAIL_SYSTEM_PROMPT,
    PROMPT_SERVICIO_NO_PRESTADO_MUDANZA,
    PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO,
)
from .state import ClientePotencialState
from .tools import (
    cliente_solicito_correo,
    es_solicitud_de_mudanza,
    es_solicitud_de_paqueteo,
    obtener_informacion_cliente_potencial,
    inferir_tipo_de_servicio,
    es_persona_natural,
    es_ciudad_valida,
    es_mercancia_valida,
    necesita_agente_de_carga,
    guardar_correo_cliente,
    buscar_nit as buscar_nit_tool,
    formatear_nombre_responsable,
)
from src.config import settings
from src.shared.constants import GEMINI_MODEL
from src.shared.enums import InteractionType
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.shared.utils.history import (
    genai_content_to_interaction_messages,
    get_genai_history,
)
from src.services.google_sheets import GoogleSheetsService

logger = logging.getLogger(__name__)


async def _write_cliente_potencial_to_sheet(
    interaction_data: dict, sheets_service: Optional[GoogleSheetsService]
):
    if (
        not settings.GOOGLE_SHEET_ID_CLIENTES_POTENCIALES_EXPORT
        or not sheets_service
    ):
        logger.warning(
            "Spreadsheet ID for export not configured or sheets service not available. Skipping write."
        )
        return

    try:
        worksheet = sheets_service.get_worksheet(
            spreadsheet_id=settings.GOOGLE_SHEET_ID_CLIENTES_POTENCIALES_EXPORT,
            worksheet_name="CLIENTES_POTENCIALES",
        )
        if not worksheet:
            logger.error("Could not find CLIENTES_POTENCIALES worksheet.")
            return

        remaining_info = interaction_data.get("remaining_information", {})
        search_result = interaction_data.get("resultado_buscar_nit", {})
        customer_email = interaction_data.get("customer_email")

        if not remaining_info and not customer_email:
            logger.info("Not enough information to write to sheet.")
            return

        # Mapping data
        fecha_perfilacion = datetime.now().strftime("%d/%m/%Y")
        nit = remaining_info.get(
            "nit"
        ) or interaction_data.get("remaining_information", {}).get("nit", "")
        estado_cliente = search_result.get("estado", "")
        razon_social = remaining_info.get("nombre_legal", "")
        ciudad = ""  # Not specified in requirements
        nombre_decisor = remaining_info.get("nombre_persona_contacto", "")
        celular = remaining_info.get("telefono", "")
        correo = remaining_info.get("correo") or customer_email or ""
        tipo_servicio = remaining_info.get("tipo_de_servicio", "")
        tipo_mercancia = remaining_info.get("tipo_mercancia", "")
        peso = remaining_info.get("peso_de_mercancia", "")
        origen = remaining_info.get("ciudad_origen", "")
        destino = remaining_info.get("ciudad_destino", "")
        potencial_viajes = remaining_info.get("promedio_viajes_mensuales", "")
        descripcion_necesidad = remaining_info.get("detalles_mercancia", "")
        perfilado = "SI" if razon_social else "NO"
        motivo_descarte = interaction_data.get("discarded", "")
        if not motivo_descarte and customer_email:
            motivo_descarte = "Prefirió correo"
        comercial_asignado_raw = search_result.get("responsable_comercial", "")
        comercial_asignado = (
            formatear_nombre_responsable(comercial_asignado_raw)
            if comercial_asignado_raw
            else ""
        )

        row_to_append = [
            fecha_perfilacion,
            nit,
            estado_cliente,
            razon_social,
            ciudad,
            nombre_decisor,
            celular,
            correo,
            tipo_servicio,
            tipo_mercancia,
            peso,
            origen,
            destino,
            str(potencial_viajes),
            descripcion_necesidad,
            perfilado,
            motivo_descarte,
            comercial_asignado,
        ]

        sheets_service.append_row(worksheet, row_to_append)
        logger.info(f"Successfully wrote data for NIT {nit} to Google Sheet.")

    except Exception as e:
        logger.error(f"Failed to write to Google Sheet: {e}", exc_info=True)


async def _execute_tool_calls(
    model_turn_content: types.Content,
    tools: list,
) -> Tuple[dict, list[types.Part]]:
    """Executes function calls from the model's response and returns the results."""
    tool_results = {}
    fr_parts = []
    for part in model_turn_content.parts:
        fc = part.function_call
        if not fc:
            continue

        tool_name = fc.name
        tool_args = dict(fc.args) if fc.args else {}
        tool_function = next((t for t in tools if t.__name__ == tool_name), None)

        if tool_function:
            result = tool_function(**tool_args)
            tool_results[tool_name] = result
            fr_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=tool_name, response={'result': result}
                    )
                )
            )
    return tool_results, fr_parts


async def _get_final_text_response(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    system_prompt: str,
) -> str:
    """Gets a final text response from the model without tools."""
    genai_history = await get_genai_history(history_messages)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.0,
    )
    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=config
    )
    return response.text


async def _workflow_remaining_information_provided(
    interaction_data: dict,
    sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """
    Handles the logic after all client information has been provided and stored.
    It determines the next step based on the client's existing status.
    """
    await _write_cliente_potencial_to_sheet(interaction_data, sheets_service)
    search_result = interaction_data.get("resultado_buscar_nit", {})
    estado = search_result.get("estado")
    assistant_message_text = ""
    tool_call_name = None
    next_state = ClientePotencialState.CONVERSATION_FINISHED

    if estado == "PROSPECTO":
        assistant_message_text = PROMPT_ASIGNAR_AGENTE_COMERCIAL
        tool_call_name = "obtener_ayuda_humana"
    elif estado in ["PERDIDO", "PERDIDO MÁS DE 2 AÑOS"]:
        responsable = search_result.get("responsable_comercial")
        if responsable:
            responsable_formateado = formatear_nombre_responsable(responsable)
            assistant_message_text = PROMPT_CONTACTAR_AGENTE_ASIGNADO.format(
                responsable_comercial=responsable_formateado
            )
        else:  # Fallback if contact info is missing
            assistant_message_text = PROMPT_ASIGNAR_AGENTE_COMERCIAL
            tool_call_name = "obtener_ayuda_humana"
    else:  # New client or any other status
        assistant_message_text = PROMPT_ASIGNAR_AGENTE_COMERCIAL
        tool_call_name = "obtener_ayuda_humana"

    interaction_data["messages_after_finished_count"] = 0
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


async def _workflow_awaiting_nit(
    history_messages: list[InteractionMessage],
    interaction_data: dict,
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
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
                    logger.info(f"Found NIT {nit} in Google Sheet: {found_record}")
                    search_result = {
                        "cliente": found_record.get(" Cliente"),
                        "estado": found_record.get(" Estado del cliente"),
                        "responsable_comercial": found_record.get(
                            " RESPONSABLE COMERCIAL"
                        ),
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

    buscar_nit.__doc__ = buscar_nit_tool.__doc__

    tools = [buscar_nit, es_persona_natural, obtener_ayuda_humana]
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    while True:
        genai_history = await get_genai_history(history_messages)
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL, contents=genai_history, config=config
        )

        if not response.function_calls:
            assistant_message_text = (
                response.text
                or "Could you please provide your NIT or indicate if you are an individual?"
            )
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL, message=assistant_message_text
                    )
                ],
                ClientePotencialState.AWAITING_NIT,
                None,
                interaction_data,
            )

        model_turn_content = response.candidates[0].content
        history_messages.extend(
            genai_content_to_interaction_messages([model_turn_content])
        )

        tool_results, fr_parts = await _execute_tool_calls(model_turn_content, tools)

        if not fr_parts:
            # Model hallucinated a tool call, let's get a text response
            logger.warning(
                f"Model returned a function call that was not executed: {response.function_calls}"
            )
            continue  # The history now includes the bad function call, let model retry.

        tool_turn_content = types.Content(role="tool", parts=fr_parts)
        history_messages.extend(
            genai_content_to_interaction_messages([tool_turn_content])
        )

        if "obtener_ayuda_humana" in tool_results:
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL, message=obtener_ayuda_humana()
                    )
                ],
                ClientePotencialState.HUMAN_ESCALATION,
                "obtener_ayuda_humana",
                interaction_data,
            )

        if "buscar_nit" in tool_results:
            search_result = tool_results["buscar_nit"]
            interaction_data["resultado_buscar_nit"] = search_result

            nit = model_turn_content.parts[0].function_call.args.get("nit")

            if "remaining_information" not in interaction_data:
                interaction_data["remaining_information"] = {}
            interaction_data["remaining_information"]["nit"] = nit

            assistant_message_text = await _get_final_text_response(
                history_messages, client, CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT
            )
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL, message=assistant_message_text
                    )
                ],
                ClientePotencialState.AWAITING_REMAINING_INFORMATION,
                None,
                interaction_data,
            )

        if "es_persona_natural" in tool_results:
            assistant_message_text = await _get_final_text_response(
                history_messages, client, CLIENTE_POTENCIAL_SYSTEM_PROMPT
            )
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL, message=assistant_message_text
                    )
                ],
                ClientePotencialState.AWAITING_PERSONA_NATURAL_FREIGHT_INFO,
                None,
                interaction_data,
            )


async def _workflow_awaiting_persona_natural_freight_info(
    history_messages: list[InteractionMessage],
    interaction_data: dict,
    client: genai.Client,
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow when waiting for freight info from a natural person."""
    tools = [necesita_agente_de_carga, obtener_ayuda_humana]
    genai_history = await get_genai_history(history_messages)
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=config
    )

    if (
        response.function_calls
        and response.function_calls[0].name == "necesita_agente_de_carga"
    ):
        assistant_message_text = PROMPT_AGENCIAMIENTO_DE_CARGA
        next_state = ClientePotencialState.CONVERSATION_FINISHED
        tool_call_name = "necesita_agente_de_carga"
        interaction_data["messages_after_finished_count"] = 0
    else:
        # If no tool call or a different one, we assume they don't need it.
        assistant_message_text = PROMPT_DISCARD_PERSONA_NATURAL
        next_state = ClientePotencialState.CONVERSATION_FINISHED
        tool_call_name = None
        interaction_data["messages_after_finished_count"] = 0

    return (
        [InteractionMessage(role=InteractionType.MODEL, message=assistant_message_text)],
        next_state,
        tool_call_name,
        interaction_data,
    )


async def _workflow_awaiting_remaining_information(
    history_messages: list[InteractionMessage],
    interaction_data: dict,
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow for gathering detailed information from a potential client."""
    tools = [
        obtener_informacion_cliente_potencial,
        es_mercancia_valida,
        es_ciudad_valida,
        es_solicitud_de_mudanza,
        es_solicitud_de_paqueteo,
        obtener_ayuda_humana,
        inferir_tipo_de_servicio,
        cliente_solicito_correo,
    ]

    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    while True:
        genai_history = await get_genai_history(history_messages)
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL, contents=genai_history, config=config
        )

        if not response.function_calls:
            assistant_message_text = response.text
            if not assistant_message_text:
                logger.warning(
                    "Model did not return text or function call. Escalating to human."
                )
                return (
                    [
                        InteractionMessage(
                            role=InteractionType.MODEL, message=obtener_ayuda_humana()
                        )
                    ],
                    ClientePotencialState.HUMAN_ESCALATION,
                    "obtener_ayuda_humana",
                    interaction_data,
                )
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL, message=assistant_message_text
                    )
                ],
                ClientePotencialState.AWAITING_REMAINING_INFORMATION,
                None,
                interaction_data,
            )

        model_turn_content = response.candidates[0].content
        history_messages.extend(
            genai_content_to_interaction_messages([model_turn_content])
        )

        tool_results, fr_parts = await _execute_tool_calls(model_turn_content, tools)

        if "obtener_ayuda_humana" in tool_results:
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL, message=obtener_ayuda_humana()
                    )
                ],
                ClientePotencialState.HUMAN_ESCALATION,
                "obtener_ayuda_humana",
                interaction_data,
            )

        if tool_results.get("es_solicitud_de_mudanza"):
            interaction_data["discarded"] = "es_solicitud_de_mudanza"
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL,
                        message=PROMPT_SERVICIO_NO_PRESTADO_MUDANZA,
                    )
                ],
                ClientePotencialState.CONVERSATION_FINISHED,
                None,
                interaction_data,
            )

        if tool_results.get("es_solicitud_de_paqueteo"):
            interaction_data["discarded"] = "es_solicitud_de_paqueteo"
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL,
                        message=PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO,
                    )
                ],
                ClientePotencialState.CONVERSATION_FINISHED,
                None,
                interaction_data,
            )

        validation_checks = {
            "es_mercancia_valida": tool_results.get("es_mercancia_valida"),
            "es_ciudad_valida": tool_results.get("es_ciudad_valida"),
        }

        for check, result in validation_checks.items():
            if result and (isinstance(result, str)):
                if check == "es_mercancia_valida":
                    interaction_data["discarded"] = "no_es_mercancia_valida"
                elif check == "es_ciudad_valida":
                    interaction_data["discarded"] = "no_es_ciudad_valida"
                interaction_data["messages_after_finished_count"] = 0
                return (
                    [InteractionMessage(role=InteractionType.MODEL, message=result)],
                    ClientePotencialState.CONVERSATION_FINISHED,
                    None,
                    interaction_data,
                )

        if "cliente_solicito_correo" in tool_results:
            interaction_data["customer_requested_email_sent"] = True
            return (
                [
                    InteractionMessage(
                        role=InteractionType.MODEL,
                        message=PROMPT_CUSTOMER_REQUESTED_EMAIL,
                    )
                ],
                ClientePotencialState.CUSTOMER_ASKED_FOR_EMAIL_DATA_SENT,
                None,
                interaction_data,
            )

        if "obtener_informacion_cliente_potencial" in tool_results:
            collected_info = tool_results["obtener_informacion_cliente_potencial"]
            if "remaining_information" not in interaction_data:
                interaction_data["remaining_information"] = {}
            interaction_data["remaining_information"].update(collected_info)
            return await _workflow_remaining_information_provided(
                interaction_data=interaction_data, sheets_service=sheets_service
            )

        if fr_parts:
            tool_turn_content = types.Content(role="tool", parts=fr_parts)
            history_messages.extend(
                genai_content_to_interaction_messages([tool_turn_content])
            )
        else:
            # If no valid tool was called, but function_calls was not empty,
            # it might be an error. Let's get a text response by continuing the loop.
            logger.warning(
                "Model returned a function call that was not executed:"
                f" {response.function_calls}"
            )
            continue


async def _workflow_customer_asked_for_email_data_sent(
    history_messages: list[InteractionMessage],
    interaction_data: dict,
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow after the user has requested to send info via email."""
    tools = [guardar_correo_cliente, obtener_ayuda_humana]
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=PROMPT_GET_CUSTOMER_EMAIL_SYSTEM_PROMPT,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    genai_history = await get_genai_history(history_messages)
    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=config
    )

    if not response.function_calls:
        assistant_message_text = (
            response.text
            or "Por favor, indícame tu correo electrónico para continuar."
        )
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=assistant_message_text
                )
            ],
            ClientePotencialState.CUSTOMER_ASKED_FOR_EMAIL_DATA_SENT,
            None,
            interaction_data,
        )

    model_turn_content = response.candidates[0].content
    tool_results, _ = await _execute_tool_calls(model_turn_content, tools)

    if "obtener_ayuda_humana" in tool_results:
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=obtener_ayuda_humana()
                )
            ],
            ClientePotencialState.HUMAN_ESCALATION,
            "obtener_ayuda_humana",
            interaction_data,
        )

    if "guardar_correo_cliente" in tool_results:
        interaction_data["customer_email"] = tool_results["guardar_correo_cliente"]
        interaction_data["messages_after_finished_count"] = 0
        await _write_cliente_potencial_to_sheet(interaction_data, sheets_service)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=PROMPT_EMAIL_GUARDADO_Y_FINALIZAR,
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            None,
            interaction_data,
        )

    # If the model called a different tool or failed, ask again.
    assistant_message_text = await _get_final_text_response(
        history_messages, client, PROMPT_GET_CUSTOMER_EMAIL_SYSTEM_PROMPT
    )
    return (
        [
            InteractionMessage(
                role=InteractionType.MODEL, message=assistant_message_text
            )
        ],
        ClientePotencialState.CUSTOMER_ASKED_FOR_EMAIL_DATA_SENT,
        None,
        interaction_data,
    )
