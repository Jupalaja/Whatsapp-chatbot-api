import logging
from typing import Optional, Tuple
from datetime import datetime

import google.genai as genai
from google.genai import types, errors

from .prompts import (
    CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT,
    CLIENTE_POTENCIAL_PERSONA_NATURAL_PROMPT,
    CLIENTE_POTENCIAL_SYSTEM_PROMPT,
    PROMPT_AGENCIAMIENTO_DE_CARGA,
    PROMPT_ASIGNAR_AGENTE_COMERCIAL,
    PROMPT_CONTACTAR_AGENTE_ASIGNADO,
    PROMPT_CUSTOMER_REQUESTED_EMAIL,
    PROMPT_DISCARD_PERSONA_NATURAL,
    PROMPT_EMAIL_GUARDADO_Y_FINALIZAR,
    PROMPT_GET_CUSTOMER_EMAIL_SYSTEM_PROMPT,
    PROMPT_ENVIO_INTERNACIONAL
)
from .state import ClientePotencialState
from .tools import (
    cliente_solicito_correo,
    informacion_de_contacto_esencial_obtenida,
    informacion_de_servicio_esencial_obtenida,
    es_persona_natural,
    necesita_agente_de_carga,
    guardar_correo_cliente,
    buscar_nit as buscar_nit_tool,
    limpiar_datos_agente_comercial,
    obtener_tipo_de_servicio,
    obtener_informacion_empresa_contacto,
    obtener_informacion_servicio,
)
from src.config import settings
from src.shared.constants import GEMINI_MODEL
from src.shared.enums import CategoriaClasificacion, InteractionType, MotivoDeDescarte
from src.shared.schemas import InteractionMessage
from src.shared.tools import obtener_ayuda_humana
from src.services.google_sheets import GoogleSheetsService
from src.shared.utils.validations import (
    es_ciudad_valida,
    es_mercancia_valida,
    es_solicitud_de_mudanza,
    es_solicitud_de_paqueteo,
    es_envio_internacional,
)
from src.shared.prompts import (
    PROMPT_SERVICIO_NO_PRESTADO_MUDANZA,
    PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO,
)
from src.shared.utils.functions import (
    invoke_model_with_retries,
    execute_tool_calls_and_get_response,
    get_final_text_response,
)
from ..cliente_activo.handler import handle_cliente_activo
from ..cliente_activo.state import ClienteActivoState

logger = logging.getLogger(__name__)


async def _write_cliente_potencial_to_sheet(
        interaction_data: dict, user_data: Optional[dict], sheets_service: Optional[GoogleSheetsService]
):
    if interaction_data.get("sheet_row_added"):
        logger.info("Data for potential client has already been written to Google Sheet. Skipping.")
        return

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
        nombre_decisor = remaining_info.get("nombre_persona_contacto", "")
        cargo = remaining_info.get("cargo", "")
        celular = user_data.get("phoneNumber", "") if user_data else ""
        correo = remaining_info.get("correo") or customer_email or ""
        tipo_servicio = remaining_info.get("tipo_de_servicio", "")
        tipo_mercancia = remaining_info.get("tipo_mercancia", "")
        peso = remaining_info.get("peso_de_mercancia", "")
        origen = remaining_info.get("ciudad_origen", "")
        destino = remaining_info.get("ciudad_destino", "")
        potencial_viajes = remaining_info.get("promedio_viajes_mensuales", "")
        descripcion_necesidad = remaining_info.get("detalles_mercancia", "")
        perfilado = "NO" if "discarded" in interaction_data else "YES"
        motivo_descarte = interaction_data.get("discarded", "")
        if not motivo_descarte and customer_email:
            motivo_descarte = "Prefirió correo"
        
        # Use cleaned commercial agent name if available
        comercial_asignado = interaction_data.get("agente_comercial_formateado", "")
        if not comercial_asignado:
            comercial_asignado_raw = search_result.get("responsable_comercial", "")
            if comercial_asignado_raw:
                # Fallback to simple title case if cleaning wasn't performed
                comercial_asignado = comercial_asignado_raw.title()

        row_to_append = [
            fecha_perfilacion,
            nit,
            estado_cliente,
            razon_social,
            nombre_decisor,
            cargo,
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
        interaction_data["sheet_row_added"] = True
        logger.info(f"Successfully wrote data for NIT {nit} to Google Sheet and marked as added.")

    except Exception as e:
        logger.error(f"Failed to write to Google Sheet: {e}", exc_info=True)


async def _clean_commercial_agent_data(
    search_result: dict,
    client: genai.Client
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
        return {
            "agente_valido": False,
            "razon": "No se encontró responsable comercial"
        }
    
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
            config=config
        )
        
        if response.function_calls:
            function_call = response.function_calls[0]
            if function_call.name == "limpiar_datos_agente_comercial":
                return dict(function_call.args)
        
        # Fallback if no function call
        return {
            "agente_valido": False,
            "razon": "No se pudo procesar los datos del agente"
        }
        
    except Exception as e:
        logger.error(f"Error cleaning commercial agent data: {e}")
        return {
            "agente_valido": False,
            "razon": "Error al procesar los datos del agente"
        }


async def _workflow_remaining_information_provided(
        interaction_data: dict,
        user_data: Optional[dict],
        sheets_service: Optional[GoogleSheetsService],
        client: genai.Client,
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """
    Handles the logic after all client information has been provided and stored.
    It determines the next step based on the client's existing status.
    """
    await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
    search_result = interaction_data.get("resultado_buscar_nit", {})
    estado = search_result.get("estado")
    assistant_message_text = ""
    tool_call_name = None
    next_state = ClientePotencialState.CONVERSATION_FINISHED

    if estado == "PROSPECTO":
        assistant_message_text = PROMPT_ASIGNAR_AGENTE_COMERCIAL
        tool_call_name = "obtener_ayuda_humana"
    elif isinstance(estado, str):
        # Clean the commercial agent data before using it
        cleaned_data = await _clean_commercial_agent_data(search_result, client)
        
        if cleaned_data.get("agente_valido", False):
            nombre_formateado = cleaned_data.get("nombre_formateado", "")
            email_valido = cleaned_data.get("email_valido", "")
            telefono_valido = cleaned_data.get("telefono_valido", "")
            
            # Store the cleaned name for the sheet
            interaction_data["agente_comercial_formateado"] = nombre_formateado
            
            contact_details = ""
            if email_valido and telefono_valido:
                contact_details = f" Lo puedes contactar al correo *{email_valido}* o al teléfono *{telefono_valido}*."
            elif email_valido:
                contact_details = f" Lo puedes contactar al correo *{email_valido}*."
            elif telefono_valido:
                contact_details = f" Lo puedes contactar al teléfono *{telefono_valido}*."
            
            assistant_message_text = PROMPT_CONTACTAR_AGENTE_ASIGNADO.format(
                responsable_comercial=nombre_formateado,
                contact_details=contact_details,
            )
        else:
            logger.warn(f"Invalid commercial agent data: {cleaned_data.get('razon', 'Unknown reason')}")
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
        session_id: str,
        history_messages: list[InteractionMessage],
        interaction_data: dict,
        user_data: Optional[dict],
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
                    logger.info(f"Columns found in sheet for NIT {nit}: {list(found_record.keys())}")
                    logger.info(f"Found NIT {nit} in Google Sheet: {found_record}")
                    search_result = {
                        "cliente": found_record.get(" CLIENTE"),
                        "estado": found_record.get(" ESTADO DEL CLIENTE"),
                        "responsable_comercial": found_record.get(" RESPONSABLE COMERCIAL"),
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

    buscar_nit.__doc__ = buscar_nit_tool.__doc__

    tools = [
        buscar_nit,
        es_persona_natural,
        obtener_ayuda_humana,
        es_mercancia_valida,
        es_solicitud_de_mudanza,
        es_solicitud_de_paqueteo,
        es_ciudad_valida,
        es_envio_internacional,
        obtener_informacion_empresa_contacto,
        obtener_informacion_servicio,
    ]

    (
        text_response,
        tool_results,
        tool_call_names,
        tool_args_map,
    ) = await execute_tool_calls_and_get_response(
        history_messages, client, tools, CLIENTE_POTENCIAL_SYSTEM_PROMPT
    )

    if tool_results.get("es_solicitud_de_mudanza"):
        interaction_data["discarded"] = MotivoDeDescarte.SERVICIO_NO_PRESTADO.value
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
        interaction_data["discarded"] = MotivoDeDescarte.SERVICIO_NO_PRESTADO.value
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

    if tool_results.get("es_envio_internacional"):
        interaction_data["discarded"] = MotivoDeDescarte.SERVICIO_NO_PRESTADO.value
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=PROMPT_ENVIO_INTERNACIONAL,
                    tool_calls=["es_envio_internacional"],
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            "es_envio_internacional",
            interaction_data,
        )

    validation_checks = {
        "es_mercancia_valida": tool_results.get("es_mercancia_valida"),
        "es_ciudad_valida": tool_results.get("es_ciudad_valida"),
    }
    terminating_tool_name = None
    for check, result in validation_checks.items():
        if result and isinstance(result, str):
            terminating_tool_name = check
            if check == "es_mercancia_valida":
                interaction_data["discarded"] = MotivoDeDescarte.PRODUCTO_NO_VALIDO.value
            elif check == "es_ciudad_valida":
                interaction_data["discarded"] = MotivoDeDescarte.RUTA_FUERA_DE_COBERTURA.value
            break

    if terminating_tool_name:
        final_message = text_response or tool_results[terminating_tool_name]
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=final_message,
                    tool_calls=[terminating_tool_name],
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            terminating_tool_name,
            interaction_data,
        )

    if "obtener_ayuda_humana" in tool_results:
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
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

    # Process information gathering
    if "remaining_information" not in interaction_data:
        interaction_data["remaining_information"] = {}

    if "obtener_informacion_empresa_contacto" in tool_results:
        collected_info = tool_results["obtener_informacion_empresa_contacto"]
        interaction_data["remaining_information"].update(collected_info)

    if "obtener_informacion_servicio" in tool_results:
        collected_info = tool_results[
            "obtener_informacion_servicio"
        ]
        interaction_data["remaining_information"].update(collected_info)

    if "buscar_nit" in tool_results:
        search_result = tool_results["buscar_nit"]
        interaction_data["resultado_buscar_nit"] = search_result
        nit = tool_args_map.get("buscar_nit", {}).get("nit")
        if nit:
            interaction_data["remaining_information"]["nit"] = nit

        estado_cliente = search_result.get("estado")
        nit_was_found = estado_cliente not in [
            "No encontrado",
            "Error de sistema",
            "No verificado",
        ]

        if nit_was_found and estado_cliente not in ["PERDIDO", "PERDIDO MÁS DE 2 AÑOS"]:
            logger.info(
                f"Client with NIT {nit} is an active client (estado={estado_cliente}). Re-routing to cliente_activo flow."
            )
            interaction_data["classifiedAs"] = CategoriaClasificacion.CLIENTE_ACTIVO.value

            return await handle_cliente_activo(
                session_id=session_id,
                history_messages=history_messages,
                current_state=ClienteActivoState.AWAITING_RESOLUTION,
                interaction_data=interaction_data,
                client=client,
                sheets_service=sheets_service,
            )

    # Check if we have all info and can finish
    essential_keys = [
        "nombre_persona_contacto",
        "tipo_mercancia",
        "ciudad_origen",
        "ciudad_destino",
    ]
    remaining_info = interaction_data.get("remaining_information", {})
    has_nit = "nit" in remaining_info
    has_all_essential_info = all(k in remaining_info for k in essential_keys)

    if has_nit and has_all_essential_info:
        logger.info("All essential information collected in the initial workflow. Finalizing.")
        return await _workflow_remaining_information_provided(
            interaction_data=interaction_data,
            user_data=user_data,
            sheets_service=sheets_service,
            client=client,
        )

    if "buscar_nit" in tool_results:
        # After finding the NIT, we need to ask for the next piece of information
        # using the more specific prompt that defines the question order.
        assistant_message_text = await get_final_text_response(
            history_messages, client, CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT
        )

        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=assistant_message_text,
                    tool_calls=["buscar_nit"],
                )
            ],
            ClientePotencialState.AWAITING_REMAINING_INFORMATION,
            "buscar_nit",
            interaction_data,
        )

    if tool_results.get("es_persona_natural"):
        assistant_message_text = await get_final_text_response(
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
        user_data: Optional[dict],
        client: genai.Client,
        sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow when waiting for freight info from a natural person."""
    tools = [necesita_agente_de_carga, obtener_ayuda_humana]

    (
        text_response,
        tool_results,
        tool_call_names,
        _,
    ) = await execute_tool_calls_and_get_response(
        history_messages, client, tools, CLIENTE_POTENCIAL_PERSONA_NATURAL_PROMPT
    )

    if "obtener_ayuda_humana" in tool_results:
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
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

    if text_response:
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=text_response,
                )
            ],
            ClientePotencialState.AWAITING_PERSONA_NATURAL_FREIGHT_INFO,
            None,
            interaction_data,
        )

    if tool_results.get("necesita_agente_de_carga"):
        interaction_data["discarded"] = MotivoDeDescarte.SERVICIO_NO_PRESTADO.value
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
        assistant_message_text = PROMPT_AGENCIAMIENTO_DE_CARGA
        next_state = ClientePotencialState.CONVERSATION_FINISHED
        tool_call_name = "necesita_agente_de_carga"
        interaction_data["messages_after_finished_count"] = 0
    else:
        # If no tool call or a different one, we assume they don't need it.
        interaction_data["discarded"] = MotivoDeDescarte.SERVICIO_NO_PRESTADO.value
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
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
        user_data: Optional[dict],
        client: genai.Client,
        sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow for gathering detailed information from a potential client."""
    tools = [
        obtener_informacion_empresa_contacto,
        obtener_informacion_servicio,
        informacion_de_contacto_esencial_obtenida,
        informacion_de_servicio_esencial_obtenida,
        es_mercancia_valida,
        es_ciudad_valida,
        es_solicitud_de_mudanza,
        es_solicitud_de_paqueteo,
        obtener_ayuda_humana,
        cliente_solicito_correo,
        obtener_tipo_de_servicio,
        es_envio_internacional,
    ]

    (
        text_response,
        tool_results,
        tool_call_names,
        _,
    ) = await execute_tool_calls_and_get_response(
        history_messages, client, tools, CLIENTE_POTENCIAL_GATHER_INFO_SYSTEM_PROMPT
    )

    logger.info(f"Workflow received from Gemini - Text: '{text_response}', Tools: {tool_call_names}")

    if "obtener_ayuda_humana" in tool_results:
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
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

    if tool_results.get("es_envio_internacional"):
        interaction_data["discarded"] = MotivoDeDescarte.SERVICIO_NO_PRESTADO.value
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL,
                    message=PROMPT_ENVIO_INTERNACIONAL,
                    tool_calls=["es_envio_internacional"],
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            "es_envio_internacional",
            interaction_data,
        )

    if tool_results.get("es_solicitud_de_mudanza"):
        interaction_data["discarded"] = MotivoDeDescarte.SERVICIO_NO_PRESTADO.value
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
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
        interaction_data["discarded"] = MotivoDeDescarte.SERVICIO_NO_PRESTADO.value
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
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

    terminating_tool_name = None
    for check, result in validation_checks.items():
        if result and (isinstance(result, str)):
            terminating_tool_name = check
            if check == "es_mercancia_valida":
                interaction_data["discarded"] = MotivoDeDescarte.PRODUCTO_NO_VALIDO.value
            elif check == "es_ciudad_valida":
                interaction_data["discarded"] = MotivoDeDescarte.RUTA_FUERA_DE_COBERTURA.value
            break

    if terminating_tool_name:
        interaction_data["messages_after_finished_count"] = 0
        final_message = text_response or tool_results[terminating_tool_name]
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
        return (
            [
                InteractionMessage(
                    role=InteractionType.MODEL, message=final_message, tool_calls=[terminating_tool_name]
                )
            ],
            ClientePotencialState.CONVERSATION_FINISHED,
            terminating_tool_name,
            interaction_data,
        )

    if tool_results.get("cliente_solicito_correo"):
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
    empresa_contacto_info_provided = (
            "obtener_informacion_empresa_contacto" in tool_results
    )
    servicio_info_provided = (
            "obtener_informacion_servicio" in tool_results
    )

    if empresa_contacto_info_provided or servicio_info_provided:
        if "remaining_information" not in interaction_data:
            interaction_data["remaining_information"] = {}

    if empresa_contacto_info_provided:
        collected_info = tool_results["obtener_informacion_empresa_contacto"]
        interaction_data["remaining_information"].update(collected_info)

    if servicio_info_provided:
        collected_info = tool_results[
            "obtener_informacion_servicio"
        ]
        interaction_data["remaining_information"].update(collected_info)
    
    if "obtener_tipo_de_servicio" in tool_results:
        tipo_de_servicio = tool_results["obtener_tipo_de_servicio"]
        if "remaining_information" not in interaction_data:
            interaction_data["remaining_information"] = {}
        interaction_data["remaining_information"]["tipo_de_servicio"] = tipo_de_servicio

    if tool_results.get("informacion_de_servicio_esencial_obtenida"):
        return await _workflow_remaining_information_provided(
            interaction_data=interaction_data, 
            user_data=user_data,
            sheets_service=sheets_service, 
            client=client
        )

    # If no significant tool calls, continue conversation
    assistant_message_text = text_response
    if not assistant_message_text:
        logger.warning(
            "Model did not return text and no terminal tool was called. Escalating to human."
        )
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
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
        user_data: Optional[dict],
        client: genai.Client,
        sheets_service: Optional[GoogleSheetsService],
) -> Tuple[list[InteractionMessage], ClientePotencialState, Optional[str], dict]:
    """Handles the workflow after the user has requested to send info via email."""
    tools = [guardar_correo_cliente, obtener_ayuda_humana]

    (
        text_response,
        tool_results,
        tool_call_names,
        _,
    ) = await execute_tool_calls_and_get_response(
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
        await _write_cliente_potencial_to_sheet(interaction_data, user_data, sheets_service)
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
