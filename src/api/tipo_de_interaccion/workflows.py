import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types, errors

from .prompts import (
    TIPO_DE_INTERACCION_SYSTEM_PROMPT,
    TIPO_DE_INTERACCION_AUTOPILOT_SYSTEM_PROMPT,
)
from .tools import clasificar_interaccion

from src.shared.enums import InteractionType
from src.shared.constants import GEMINI_MODEL
from src.shared.tools import obtener_ayuda_humana
from src.shared.schemas import Clasificacion, InteractionMessage
from src.shared.utils.history import get_genai_history
from src.api.cliente_potencial.prompts import PROMPT_ENVIO_INTERNACIONAL
from src.shared.utils.validations import (
    es_ciudad_valida,
    es_mercancia_valida,
    es_solicitud_de_mudanza,
    es_solicitud_de_paqueteo,
    es_envio_internacional,
)
from src.shared.utils.functions import get_response_text, invoke_model_with_retries


logger = logging.getLogger(__name__)


async def workflow_tipo_de_interaccion(
    history_messages: list[InteractionMessage],
    client: genai.Client,
) -> Tuple[list[InteractionMessage], Optional[Clasificacion], Optional[str]]:
    genai_history = await get_genai_history(history_messages)

    model = GEMINI_MODEL

    tools = [
        clasificar_interaccion,
        obtener_ayuda_humana,
        es_ciudad_valida,
        es_mercancia_valida,
        es_solicitud_de_mudanza,
        es_solicitud_de_paqueteo,
        es_envio_internacional,
    ]
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=TIPO_DE_INTERACCION_SYSTEM_PROMPT,
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
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL,
            message=obtener_ayuda_humana(),
            tool_calls=["obtener_ayuda_humana"],
        )
        return [assistant_message], None, "obtener_ayuda_humana"

    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
        try:
            parts_for_logging = []
            for part in response.candidates[0].content.parts:
                part_dump = part.model_dump(exclude_none=True)
                part_dump.pop("thought_signature", None)
                parts_for_logging.append(part_dump)
            logger.info(f"Interaction response parts: {parts_for_logging}")
        except Exception as e:
            logger.error(f"Could not serialize response parts for logging: {e}")
    else:
        logger.info("Interaction response has no candidates or parts.")

    clasificacion = None
    assistant_message = None
    tool_call_name = None

    if response.function_calls:
        # Extract classification if present; it's a non-terminating side effect.
        for function_call in response.function_calls:
            if function_call.name == "clasificar_interaccion":
                try:
                    clasificacion = Clasificacion.model_validate(function_call.args)
                except Exception as e:
                    logger.error(f"Error validating clasificacion: {e}", exc_info=True)
                    assistant_message = InteractionMessage(
                        role=InteractionType.MODEL,
                        message=obtener_ayuda_humana(),
                        tool_calls=["obtener_ayuda_humana"],
                    )
                    return [assistant_message], None, "obtener_ayuda_humana"
                break

        # Process validation function calls that generate terminating responses.
        # These should be processed in priority order to handle cases where multiple validations fail.
        validation_priority = [
            "es_envio_internacional",
            "es_mercancia_valida", 
            "es_ciudad_valida",
            "es_solicitud_de_mudanza",
            "es_solicitud_de_paqueteo",
            "obtener_ayuda_humana"
        ]
        
        for validation_tool in validation_priority:
            for function_call in response.function_calls:
                if function_call.name == validation_tool:
                    terminating_message = None
                    tool_call_name = function_call.name

                    if function_call.name == "es_mercancia_valida":
                        mercancia = function_call.args.get("tipo_mercancia", "")
                        validation_result = es_mercancia_valida(mercancia)
                        if isinstance(validation_result, str):
                            terminating_message = validation_result
                    elif function_call.name == "es_ciudad_valida":
                        ciudad = function_call.args.get("ciudad", "")
                        validation_result = es_ciudad_valida(ciudad)
                        if isinstance(validation_result, str):
                            terminating_message = validation_result
                    elif function_call.name == "es_solicitud_de_mudanza":
                        es_mudanza = function_call.args.get("es_mudanza", False)
                        if es_solicitud_de_mudanza(es_mudanza):
                            from src.shared.prompts import PROMPT_SERVICIO_NO_PRESTADO_MUDANZA
                            terminating_message = PROMPT_SERVICIO_NO_PRESTADO_MUDANZA
                    elif function_call.name == "es_solicitud_de_paqueteo":
                        es_paqueteo = function_call.args.get("es_paqueteo", False)
                        if es_solicitud_de_paqueteo(es_paqueteo):
                            from src.shared.prompts import PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO
                            terminating_message = PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO
                    elif function_call.name == "es_envio_internacional":
                        es_internacional = function_call.args.get("es_internacional", False)
                        if es_internacional:
                            terminating_message = PROMPT_ENVIO_INTERNACIONAL
                    elif function_call.name == "obtener_ayuda_humana":
                        terminating_message = obtener_ayuda_humana()

                    if terminating_message:
                        assistant_message = InteractionMessage(
                            role=InteractionType.MODEL,
                            message=terminating_message,
                            tool_calls=[tool_call_name],
                        )
                        return [assistant_message], clasificacion, tool_call_name
                    break

    # If no terminating tool was called, use the text response from the model.
    if not assistant_message:
        assistant_message_text = get_response_text(response)
        if assistant_message_text:
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=assistant_message_text
            )

    # Check if any tool other than 'clasificar_interaccion' was called.
    meaningful_tool_called = False
    if response.function_calls:
        meaningful_tool_called = any(
            fc.name != "clasificar_interaccion" for fc in response.function_calls
        )

    if not assistant_message and not meaningful_tool_called:
        # If no text response and no meaningful tool was called, it could be a vague user input.
        # However, if we got a classification, we should trust it and not ask for more info.
        if not clasificacion:
            # This typically happens for vague user inputs like "hola".
            logger.info(
                "No text response, no meaningful tools, and no classification. Using autopilot to get more information."
            )

            autopilot_config = types.GenerateContentConfig(
                tools=[obtener_ayuda_humana],
                system_instruction=TIPO_DE_INTERACCION_AUTOPILOT_SYSTEM_PROMPT,
                temperature=0.0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            )
            try:
                autopilot_response = await invoke_model_with_retries(
                    client.aio.models.generate_content,
                    model=model,
                    contents=genai_history,
                    config=autopilot_config,
                )

                if (
                    autopilot_response.function_calls
                    and autopilot_response.function_calls[0].name
                    == "obtener_ayuda_humana"
                ):
                    tool_call_name = "obtener_ayuda_humana"
                    assistant_message_text = obtener_ayuda_humana()
                else:
                    assistant_message_text = get_response_text(autopilot_response)

                if not assistant_message_text:
                    logger.warning("Autopilot also returned no text. Escalating to human.")
                    assistant_message_text = obtener_ayuda_humana()
                    tool_call_name = "obtener_ayuda_humana"

                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL,
                    message=assistant_message_text,
                    tool_calls=[tool_call_name] if tool_call_name else None,
                )

            except errors.ServerError as e:
                logger.error(
                    f"Gemini API Server Error during autopilot call: {e}", exc_info=True
                )
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL,
                    message=obtener_ayuda_humana(),
                    tool_calls=["obtener_ayuda_humana"],
                )
                tool_call_name = "obtener_ayuda_humana"

    return [assistant_message] if assistant_message else [], clasificacion, tool_call_name
