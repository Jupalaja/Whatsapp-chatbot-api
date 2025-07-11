import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types

from .prompts import TIPO_DE_INTERACCION_SYSTEM_PROMPT
from .tools import clasificar_interaccion

from src.shared.enums import InteractionType
from src.shared.constants import GEMINI_MODEL
from src.shared.prompts import CONTACTO_BASE_SYSTEM_PROMPT
from src.shared.tools import obtener_ayuda_humana
from src.shared.schemas import Clasificacion, InteractionMessage
from src.shared.utils.history import get_genai_history
from src.shared.utils.validations import (
    es_ciudad_valida,
    es_mercancia_valida,
    es_solicitud_de_mudanza,
    es_solicitud_de_paqueteo,
)
from src.shared.utils.functions import get_response_text


logger = logging.getLogger(__name__)


async def workflow_tipo_de_interaccion(
    history_messages: list[InteractionMessage],
    client: genai.Client,
) -> Tuple[list[InteractionMessage], Optional[Clasificacion], Optional[str]]:
    genai_history = await get_genai_history(history_messages)

    model = GEMINI_MODEL

    classification_tool_config = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY,
            allowed_function_names=["clasificar_interaccion"],
        )
    )
    classification_tools = [clasificar_interaccion]
    classification_config = types.GenerateContentConfig(
        tools=classification_tools,
        system_instruction=TIPO_DE_INTERACCION_SYSTEM_PROMPT,
        tool_config=classification_tool_config,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    response_classification = await client.aio.models.generate_content(
        model=model, contents=genai_history, config=classification_config
    )
    logger.debug(f"Classification response from model: {response_classification}")

    clasificacion = None
    if response_classification.function_calls:
        last_function_call = response_classification.function_calls[0]
        if last_function_call.name == "clasificar_interaccion":
            clasificacion = Clasificacion.model_validate(last_function_call.args)

    assistant_message = None
    tool_call_name = None

    tools = [
        obtener_ayuda_humana,
        es_ciudad_valida,
        es_mercancia_valida,
        es_solicitud_de_mudanza,
        es_solicitud_de_paqueteo,
    ]
    chat_config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=CONTACTO_BASE_SYSTEM_PROMPT,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    response_chat = await client.aio.models.generate_content(
        model=model, contents=genai_history, config=chat_config
    )

    if response_chat.function_calls:
        # Check if any validation function was called and handle the results
        for function_call in response_chat.function_calls:
            if function_call.name == "es_mercancia_valida":
                # Get the merchandise type from the function args
                mercancia = function_call.args.get("tipo_mercancia", "")
                validation_result = es_mercancia_valida(mercancia)
                
                # If validation returns a string, it means the merchandise is invalid
                if isinstance(validation_result, str):
                    assistant_message = InteractionMessage(
                        role=InteractionType.MODEL,
                        message=validation_result,
                        tool_calls=[function_call.name],
                    )
                    return [assistant_message], clasificacion, function_call.name
                    
            elif function_call.name == "es_ciudad_valida":
                # Get the city from the function args
                ciudad = function_call.args.get("ciudad", "")
                validation_result = es_ciudad_valida(ciudad)
                
                # If validation returns a string, it means the city is invalid
                if isinstance(validation_result, str):
                    assistant_message = InteractionMessage(
                        role=InteractionType.MODEL,
                        message=validation_result,
                        tool_calls=[function_call.name],
                    )
                    return [assistant_message], clasificacion, function_call.name
                    
            elif function_call.name == "es_solicitud_de_mudanza":
                # Get the boolean value from the function args
                es_mudanza = function_call.args.get("es_mudanza", False)
                validation_result = es_solicitud_de_mudanza(es_mudanza)
                
                # If it's a moving request, show appropriate message
                if validation_result:
                    from src.shared.prompts import PROMPT_SERVICIO_NO_PRESTADO_MUDANZA
                    assistant_message = InteractionMessage(
                        role=InteractionType.MODEL,
                        message=PROMPT_SERVICIO_NO_PRESTADO_MUDANZA,
                        tool_calls=[function_call.name],
                    )
                    return [assistant_message], clasificacion, function_call.name
                    
            elif function_call.name == "es_solicitud_de_paqueteo":
                # Get the boolean value from the function args
                es_paqueteo = function_call.args.get("es_paqueteo", False)
                validation_result = es_solicitud_de_paqueteo(es_paqueteo)
                
                # If it's a package request, show appropriate message
                if validation_result:
                    from src.shared.prompts import PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO
                    assistant_message = InteractionMessage(
                        role=InteractionType.MODEL,
                        message=PROMPT_SERVICIO_NO_PRESTADO_PAQUETEO,
                        tool_calls=[function_call.name],
                    )
                    return [assistant_message], clasificacion, function_call.name
                    
            elif function_call.name == "obtener_ayuda_humana":
                # Only call human help if explicitly requested or if there's a genuine need
                # Don't call it just because we can't classify with high confidence
                user_message = history_messages[-1].message.lower() if history_messages else ""
                
                # Check if user explicitly requested human help
                human_help_keywords = ["ayuda", "humano", "persona", "agente", "hablar con alguien"]
                if any(keyword in user_message for keyword in human_help_keywords):
                    tool_call_name = "obtener_ayuda_humana"
                    logger.info("User explicitly requested human help.")
                    assistant_message = InteractionMessage(
                        role=InteractionType.MODEL, message=obtener_ayuda_humana()
                    )
                    return [assistant_message], clasificacion, tool_call_name

    if not assistant_message:
        assistant_message_text = get_response_text(response_chat)
        if assistant_message_text:
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=assistant_message_text
            )

    if not assistant_message:
        # This fallback is for cases where the model fails to generate any response or tool call.
        return [], clasificacion, None

    return [assistant_message], clasificacion, tool_call_name
