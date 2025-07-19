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
from src.shared.utils.validations import (
    es_ciudad_valida,
    es_mercancia_valida,
    es_solicitud_de_mudanza,
    es_solicitud_de_paqueteo,
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
            message=obtener_ayuda_humana(reason=f"Error de API: {e}"),
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
                        message=obtener_ayuda_humana(reason="Error de clasificación"),
                        tool_calls=["obtener_ayuda_humana"],
                    )
                    return [assistant_message], None, "obtener_ayuda_humana"
                break

        # Process other function calls that might generate a terminating response.
        for function_call in response.function_calls:
            if function_call.name == "clasificar_interaccion":
                continue

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
            elif function_call.name == "obtener_ayuda_humana":
                terminating_message = obtener_ayuda_humana()

            if terminating_message:
                assistant_message = InteractionMessage(
                    role=InteractionType.MODEL,
                    message=terminating_message,
                    tool_calls=[tool_call_name],
                )
                return [assistant_message], clasificacion, tool_call_name

    # If no terminating tool was called, use the text response from the model.
    if not assistant_message:
        assistant_message_text = get_response_text(response)
        if assistant_message_text:
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=assistant_message_text
            )

    if not assistant_message:
        # If no text response and no terminating tool, use autopilot to get more info.
        logger.info(
            "No text response from model. Using autopilot to get more information."
        )

        autopilot_config = types.GenerateContentConfig(
            tools=[obtener_ayuda_humana],
            system_instruction=TIPO_DE_INTERACCION_AUTOPILOT_SYSTEM_PROMPT,
            temperature=0.0,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
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
                and autopilot_response.function_calls[0].name == "obtener_ayuda_humana"
            ):
                tool_call_name = "obtener_ayuda_humana"
                assistant_message_text = obtener_ayuda_humana()
            else:
                assistant_message_text = get_response_text(autopilot_response)

            if not assistant_message_text:
                logger.warning(
                    "Autopilot also returned no text. Escalating to human."
                )
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
                message=obtener_ayuda_humana(reason=f"Error de API: {e}"),
                tool_calls=["obtener_ayuda_humana"],
            )
            tool_call_name = "obtener_ayuda_humana"

    # Determine tool_call_name if not already set by a terminating tool.
    if not tool_call_name and response.function_calls:
        non_classifying_calls = [
            fc.name
            for fc in response.function_calls
            if fc.name != "clasificar_interaccion"
        ]
        if non_classifying_calls:
            tool_call_name = non_classifying_calls[0]

    return [assistant_message], clasificacion, tool_call_name
