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
from src.shared.utils.history import (
    get_genai_history,
    genai_content_to_interaction_messages,
)
from src.shared.utils.validations import es_ciudad_valida


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

    clasificacion = None
    if response_classification.function_calls:
        last_function_call = response_classification.function_calls[0]
        if last_function_call.name == "clasificar_interaccion":
            clasificacion = Clasificacion.model_validate(last_function_call.args)

    assistant_message = None
    tool_call_name = None

    chat_tools = [obtener_ayuda_humana, es_ciudad_valida]
    chat_config = types.GenerateContentConfig(
        tools=chat_tools,
        system_instruction=CONTACTO_BASE_SYSTEM_PROMPT,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    response_chat = await client.aio.models.generate_content(
        model=model, contents=genai_history, config=chat_config
    )

    if response_chat.function_calls:
        if any(fc.name == "obtener_ayuda_humana" for fc in response_chat.function_calls):
            tool_call_name = "obtener_ayuda_humana"
            logger.info("User requires human help")
            assistant_message = InteractionMessage(
                role=InteractionType.MODEL, message=obtener_ayuda_humana()
            )
        else:
            city_validation_calls = [fc for fc in response_chat.function_calls if fc.name == "es_ciudad_valida"]
            if city_validation_calls:
                model_turn_content = response_chat.candidates[0].content
                history_messages.extend(genai_content_to_interaction_messages([model_turn_content]))

                fr_parts = []
                for fc in city_validation_calls:
                    ciudad = fc.args.get("ciudad", "")
                    validation_result = es_ciudad_valida(ciudad)
                    fr_parts.append(types.Part(function_response=types.FunctionResponse(name="es_ciudad_valida", response={"result": validation_result})))

                tool_turn_content = types.Content(role="tool", parts=fr_parts)
                history_messages.extend(genai_content_to_interaction_messages([tool_turn_content]))

                genai_history_with_tool_resp = await get_genai_history(history_messages)
                final_response_chat = await client.aio.models.generate_content(
                    model=model,
                    contents=genai_history_with_tool_resp,
                    config=types.GenerateContentConfig(system_instruction=CONTACTO_BASE_SYSTEM_PROMPT, temperature=0.0)
                )

                if final_response_chat.text:
                    assistant_message = InteractionMessage(role=InteractionType.MODEL, message=final_response_chat.text)

    if not assistant_message and response_chat.text:
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=response_chat.text
        )

    if not assistant_message:
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL,
            message="No he podido procesar tu solicitud. Un humano te ayudará.",
        )
        tool_call_name = "obtener_ayuda_humana"

    return [assistant_message], clasificacion, tool_call_name
