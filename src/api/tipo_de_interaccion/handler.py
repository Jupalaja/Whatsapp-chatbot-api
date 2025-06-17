import logging
from typing import Optional, Tuple

import google.genai as genai
from google.genai import types

from .prompts import TIPO_DE_INTERACCION_SYSTEM_PROMPT
from .tools import clasificar_interaccion

from src.shared.enums import InteractionType
from src.shared.constants import GEMINI_MODEL
from src.shared.prompts import CONTACTO_BASE_SYSTEM_PROMPT
from src.shared.tools import get_human_help
from src.shared.schemas import Clasificacion, InteractionMessage
from src.shared.utils.history import get_genai_history


logger = logging.getLogger(__name__)


async def handle_tipo_de_interaccion(
    history_messages: list[InteractionMessage],
    client: genai.Client,
) -> Tuple[list[InteractionMessage], Optional[Clasificacion], Optional[str]]:
    genai_history = await get_genai_history(history_messages)

    model = GEMINI_MODEL

    # First, classify the interaction
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

    # Second, get a conversational response
    assistant_message = None
    tool_call_name = None

    chat_config = types.GenerateContentConfig(
        tools=[get_human_help],
        system_instruction=CONTACTO_BASE_SYSTEM_PROMPT,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    response_chat = await client.aio.models.generate_content(
        model=model, contents=genai_history, config=chat_config
    )

    if response_chat.function_calls:
        function_call = response_chat.function_calls[0]
        if function_call.name == "get_human_help":
            tool_call_name = function_call.name
            logger.info("User requires human help")
            assistant_text = get_human_help()
            assistant_message = InteractionMessage(
                type=InteractionType.ASSISTANT, message=assistant_text
            )

    if response_chat.text and not assistant_message:
        assistant_message = InteractionMessage(
            type=InteractionType.ASSISTANT, message=response_chat.text
        )

    if not assistant_message:
        assistant_message = InteractionMessage(
            type=InteractionType.ASSISTANT,
            message="No he podido procesar tu solicitud. Un humano te ayudará.",
        )
        tool_call_name = "get_human_help"

    return [assistant_message], clasificacion, tool_call_name
