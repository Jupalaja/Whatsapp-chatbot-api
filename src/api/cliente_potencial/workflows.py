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
)
from .state import ClientePotencialState
from .tools import (
    cliente_solicito_correo,
    obtener_informacion_esencial_cliente_potencial,
    informacion_esencial_obtenida,
    obtener_informacion_adicional_cliente_potencial,
    es_persona_natural,
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
from src.shared.utils.history import get_genai_history
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.validations import (
    es_ciudad_valida,
    es_mercancia_valida,
    es_solicitud_de_mudanza,
    es_solicitud_de_paqueteo,
)
from src.shared.prompts import (
    PROMPT_SERVICIO_NO_PRESTADO_MUDANZA,
    PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO,
)
from src.shared.utils.functions import get_response_text

logger = logging.getLogger(__name__)


async def _write_cliente_potencial_to_sheet(
        interaction_data: dict, sheets_service: Optional[GoogleSheetsService]
):
    if (
            not settings.GOOGLE_SHEET_ID_EXPORT
            or not sheets_service
    ):
        logger.warning(
            "Spreadsheet ID for export not configured or sheets service not available. Skipping write."
        )
        return

    try:
        worksheet = sheets_service.get_worksheet(
            spreadsheet_id=settings.GOOGLE_SHEET_ID_EXPORT,
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


async def _execute_tool_calls_and_get_response(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    tools: list,
    system_prompt: str,
    max_turns: int = 10,
) -> Tuple[Optional[str], dict, list[str]]:
    """
    Executes a multi-turn conversation with tool calling until a text response is received.
    1.  Calls the model.
    2.  If the model returns a text response, the loop terminates.
    3.  If the model returns tool calls, they are executed, and their results are added to the history.
    4.  The loop continues until a text response is given or max_turns is reached.
    Returns the final text response, the results of all tools called, and a list of tool call names.
    """
    genai_history = await get_genai_history(history_messages)
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=system_prompt,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    all_tool_results = {}
    all_tool_call_names = []
    response = None

    for i in range(max_turns):
        logger.info(
            f"--- Calling Gemini for tool execution/response (Turn {i + 1}/{max_turns}) ---"
        )
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL, contents=genai_history, config=config
        )

        if not response.function_calls:
            logger.info(
                "--- No tool calls from Gemini. Returning direct text response. ---"
            )
            text_response = get_response_text(response)
            return text_response, all_tool_results, all_tool_call_names

        logger.info(
            f"--- Gemini returned {len(response.function_calls)} tool call(s). Executing them. ---"
        )

        # Add the model's turn (with function calls) to history before executing
        genai_history.append(response.candidates[0].content)

        function_response_parts = []

        for function_call in response.function_calls:
            tool_name = function_call.name
            tool_args = dict(function_call.args) if function_call.args else {}
            tool_function = next((t for t in tools if t.__name__ == tool_name), None)

            if tool_function:
                logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                result = tool_function(**tool_args)
                all_tool_results[tool_name] = result
                if tool_name not in all_tool_call_names:
                    all_tool_call_names.append(tool_name)
                logger.info(f"Tool {tool_name} returned: {result}")

                # The response must be a dict for from_function_response
                response_content = result
                if not isinstance(response_content, dict):
                    response_content = {"content": result}

                function_response_parts.append(
                    types.Part.from_function_response(
                        name=tool_name, response=response_content
                    )
                )
            else:
                logger.warning(f"Tool {tool_name} not found in available tools")

        # Add the tool results to history for the next turn
        if function_response_parts:
            genai_history.append(
                types.Content(role="tool", parts=function_response_parts)
            )
        else:
            # If no tools were actually executed, break to avoid infinite loop
            break

    # If loop finishes due to max_turns, it means we are in a tool-call loop.
    logger.warning(
        f"Max tool call turns ({max_turns}) reached. Returning last response."
    )
    text_response = get_response_text(response) if response else ""

    logger.info(
        f"Final text response from loop: '{text_response[:100]}...'"
        if len(text_response) > 100
        else f"Final text response: '{text_response}'"
    )
    logger.info(f"All tool results: {all_tool_results}")
    logger.info(f"All tool call names: {all_tool_call_names}")
    logger.info("--- End of Gemini call ---")

    return text_response, all_tool_results, all_tool_call_names


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
    return get_response_text(response)


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
            email = search_result.get("email")
            telefono = search_result.get("phoneNumber")

            contact_details = ""
            if email and telefono:
                contact_details = (
                    f" Lo puedes contactar al correo *{email}* o al teléfono *{telefono}*."
                )
            elif email:
                contact_details = f" Lo puedes contactar al correo *{email}*."
            elif telefono:
                contact_details = f" Lo puedes contactar al teléfono *{telefono}*."

            assistant_message_text = PROMPT_CONTACTAR_AGENTE_ASIGNADO.format(
                responsable_comercial=responsable_formateado,
                contact_details=contact_details,
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
                role=InteractionType.MODEL,
                message=assistant_message_text,
                tool_calls=[tool_call_name] if tool_call_name else None,
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
                        "phoneNumber": found_record.get("CELULAR"),
                        "email": found_record.get("CORREO"),
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

    tools = [
        buscar_nit,
        es_persona_natural,
        obtener_ayuda_humana,
        es_mercancia_valida,
        es_solicitud_de_mudanza,
        es_solicitud_de_paqueteo,
    ]

    text_response, tool_results, tool_call_names = await _execute_tool_calls_and_get_response(
        history_messages, client, tools, CLIENTE_POTENCIAL_SYSTEM_PROMPT
    )

    if tool_results.get("es_solicitud_de_mudanza"):
        interaction_data["discarded"] = "es_solicitud_de_mudanza"
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=PROMPT_SERVICIO_NO_PRESTADO_MUDANZA,
                    tool_calls=["es_solicitud_de_mudanza"],
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            "es_solicitud_de_mudanza",
            interaction_data,
        )

    if tool_results.get("es_solicitud_de_paqueteo"):
        interaction_data["discarded"] = "es_solicitud_de_paqueteo"
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO,
                    tool_calls=["es_solicitud_de_paqueteo"],
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            "es_solicitud_de_paqueteo",
            interaction_data,
        )

    validation_result_mercancia = tool_results.get("es_mercancia_valida")
    if validation_result_mercancia and isinstance(validation_result_mercancia, str):
        interaction_data["discarded"] = "no_es_mercancia_valida"
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=validation_result_mercancia,
                    tool_calls=["es_mercancia_valida"],
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            "es_mercancia_valida",
            interaction_data,
        )

    if "obtener_ayuda_humana" in tool_results:
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=obtener_ayuda_humana(),
                    tool_calls=["obtener_ayuda_humana"]
                )
            ],
            ClientePotencialState.HUMAN_ESCALATION,
            "obtener_ayuda_humana",
            interaction_data,
        )

    if "buscar_nit" in tool_results:
        search_result = tool_results["buscar_nit"]
        interaction_data["resultado_buscar_nit"] = search_result

        # Get NIT from the last function call args by parsing the conversation
        nit = None
        genai_history = await get_genai_history(history_messages)
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=genai_history,
            config=types.GenerateContentConfig(
                tools=tools,
                system_instruction=CLIENTE_POTENCIAL_SYSTEM_PROMPT,
                temperature=0.0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
        )

        if response.function_calls:
            for fc in response.function_calls:
                if fc.name == "buscar_nit":
                    nit = fc.args.get("nit")
                    break

        if "remaining_information" not in interaction_data:
            interaction_data["remaining_information"] = {}
        interaction_data["remaining_information"]["nit"] = nit

        assistant_message_text = await _get_final_text_response(
            history_messages, client, CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT
        )
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=assistant_message_text,
                    tool_calls=["buscar_nit"]
                )
            ],
            ClientePotencialState.AWAITING_REMAINING_INFORMATION,
            "buscar_nit",
            interaction_data,
        )

    if "es_persona_natural" in tool_results:
        assistant_message_text = await _get_final_text_response(
            history_messages, client, CLIENTE_POTENCIAL_SYSTEM_PROMPT
        )
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=assistant_message_text,
                    tool_calls=["es_persona_natural"]
                )
            ],
            ClientePotencialState.AWAITING_PERSONA_NATURAL_FREIGHT_INFO,
            "es_persona_natural",
            interaction_data,
        )

    # No tool call or unrecognized response
    assistant_message_text = (
            text_response or "Could you please provide your NIT or indicate if you are an individual?"
    )
    return (
        [
            InteractionMessage(
                role=InteractionType.MODEL,
                message=assistant_message_text
            )
        ],
        ClientePotencialState.AWAITING_NIT,
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

    text_response, tool_results, tool_call_names = await _execute_tool_calls_and_get_response(
        history_messages, client, tools, CLIENTE_POTENCIAL_SYSTEM_PROMPT
    )

    if "necesita_agente_de_carga" in tool_results:
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
        [InteractionMessage(
            role=InteractionType.MODEL,
            message=assistant_message_text,
            tool_calls=[tool_call_name] if tool_call_name else None
        )],
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
        obtener_informacion_esencial_cliente_potencial,
        informacion_esencial_obtenida,
        obtener_informacion_adicional_cliente_potencial,
        es_mercancia_valida,
        es_ciudad_valida,
        es_solicitud_de_mudanza,
        es_solicitud_de_paqueteo,
        obtener_ayuda_humana,
        cliente_solicito_correo,
    ]

    text_response, tool_results, tool_call_names = await _execute_tool_calls_and_get_response(
        history_messages, client, tools, CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT
    )

    logger.info(f"Workflow received from Gemini - Text: '{text_response}', Tools: {tool_call_names}")

    if "obtener_ayuda_humana" in tool_results:
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=obtener_ayuda_humana(),
                    tool_calls=["obtener_ayuda_humana"],
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
                    tool_calls=["es_solicitud_de_mudanza"],
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            "es_solicitud_de_mudanza",
            interaction_data,
        )

    if tool_results.get("es_solicitud_de_paqueteo"):
        interaction_data["discarded"] = "es_solicitud_de_paqueteo"
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO,
                    tool_calls=["es_solicitud_de_paqueteo"],
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            "es_solicitud_de_paqueteo",
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
                [
                    InteractionMessage(
                        role=InteractionType.MODEL, message=result, tool_calls=[check]
                    )
                ],
                ClientePotencialState.CONVERSATION_FINISHED,
                check,
                interaction_data,
            )

    if "cliente_solicito_correo" in tool_results:
        interaction_data["customer_requested_email_sent"] = True
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=PROMPT_CUSTOMER_REQUESTED_EMAIL,
                    tool_calls=["cliente_solicito_correo"],
                )
            ],
            ClientePotencialState.CUSTOMER_ASKED_FOR_EMAIL_DATA_SENT,
            "cliente_solicito_correo",
            interaction_data,
        )

    # Information gathering logic
    essential_info_provided = (
            "obtener_informacion_esencial_cliente_potencial" in tool_results
    )
    additional_info_provided = (
            "obtener_informacion_adicional_cliente_potencial" in tool_results
    )

    if essential_info_provided or additional_info_provided:
        if "remaining_information" not in interaction_data:
            interaction_data["remaining_information"] = {}

    if essential_info_provided:
        collected_info = tool_results["obtener_informacion_esencial_cliente_potencial"]
        interaction_data["remaining_information"].update(collected_info)

    if additional_info_provided:
        collected_info = tool_results[
            "obtener_informacion_adicional_cliente_potencial"
        ]
        interaction_data["remaining_information"].update(collected_info)

    if tool_results.get("informacion_esencial_obtenida"):
        return await _workflow_remaining_information_provided(
            interaction_data=interaction_data, sheets_service=sheets_service
        )

    # If no significant tool calls, continue conversation
    assistant_message_text = text_response
    if not assistant_message_text:
        logger.warning(
            "Model did not return text and no terminal tool was called. Escalating to human."
        )
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=obtener_ayuda_humana(),
                    tool_calls=["obtener_ayuda_humana"],
                )
            ],
            ClientePotencialState.HUMAN_ESCALATION,
            "obtener_ayuda_humana",
            interaction_data,
        )

    return (
        [
            InteractionMessage(
                role=InteractionType.MODEL,
                message=assistant_message_text,
                tool_calls=tool_call_names if tool_call_names else None,
            )
        ],
        ClientePotencialState.AWAITING_REMAINING_INFORMATION,
        tool_call_names[0] if tool_call_names else None,
        interaction_data,
    )


async def _workflow_customer_asked_for_email_data_sent(
        history_messages: list[InteractionMessage],
        interaction_data: dict,
        client: genai.Client,
        sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow after the user has requested to send info via email."""
    tools = [guardar_correo_cliente, obtener_ayuda_humana]

    text_response, tool_results, tool_call_names = await _execute_tool_calls_and_get_response(
        history_messages, client, tools, PROMPT_GET_CUSTOMER_EMAIL_SYSTEM_PROMPT
    )

    if "obtener_ayuda_humana" in tool_results:
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=obtener_ayuda_humana(),
                    tool_calls=["obtener_ayuda_humana"]
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
                    tool_calls=["guardar_correo_cliente"]
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            "guardar_correo_cliente",
            interaction_data,
        )

    # If the model called a different tool or failed, ask again.
    assistant_message_text = (
            text_response or "Por favor, indícame tu correo electrónico para continuar."
    )
    return (
        [
            InteractionMessage(
                role=InteractionType.MODEL,
                message=assistant_message_text,
                tool_calls=tool_call_names if tool_call_names else None
            )
        ],
        ClientePotencialState.CUSTOMER_ASKED_FOR_EMAIL_DATA_SENT,
        tool_call_names[0] if tool_call_names else None,
        interaction_data,
    )

