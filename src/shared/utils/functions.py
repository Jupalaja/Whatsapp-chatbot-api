import logging
from typing import Awaitable, Callable, Optional, Tuple, Any
import asyncio

import google.genai as genai
from google.genai import types, errors

from src.services.google_sheets import GoogleSheetsService
from src.shared.constants import (
    GEMINI_MODEL,
    GEMINI_FALLBACK_MODEL,
    MESSAGES_AFTER_CONVERSATION_FINISHED,
)
from src.shared.enums import InteractionType
from src.shared.prompts import AYUDA_HUMANA_PROMPT, PROMPT_RESUMIDOR
from src.shared.schemas import InteractionMessage
from src.shared.state import GlobalState
from src.shared.tools import obtener_ayuda_humana, nueva_interaccion_requerida
from src.shared.utils.history import get_genai_history

logger = logging.getLogger(__name__)


async def invoke_model_with_retries(
    generate_content_func: Callable[..., Awaitable[types.GenerateContentResponse]],
    *args: Any,
    **kwargs: Any,
) -> types.GenerateContentResponse:
    """
    Invokes a Gemini model's generate_content method with retries for server-side errors.
    If the primary model fails, it attempts to use a fallback model.
    """
    max_retries_per_model: int = 2  # 3 attempts per model
    initial_delay: float = 1.0
    backoff_factor: float = 2.0

    primary_model = kwargs.get("model", GEMINI_MODEL)
    models_to_try = [primary_model]
    if primary_model != GEMINI_FALLBACK_MODEL and GEMINI_FALLBACK_MODEL:
        models_to_try.append(GEMINI_FALLBACK_MODEL)

    last_exception = None

    for model_name in models_to_try:
        kwargs["model"] = model_name
        delay = initial_delay
        logger.info(f"Attempting to use model: {model_name}")

        for attempt in range(max_retries_per_model + 1):
            try:
                return await generate_content_func(*args, **kwargs)
            except errors.ServerError as e:
                last_exception = e
                logger.warning(
                    f"Server error on attempt {attempt + 1}/{max_retries_per_model + 1} with model {model_name}: {e}. Retrying in {delay}s..."
                )
                if attempt < max_retries_per_model:
                    await asyncio.sleep(delay)
                    delay *= backoff_factor
                else:
                    logger.error(f"All retries failed for model {model_name}.")
                    break  # Go to the next model

    logger.error("All retries for all models failed for model invocation.")
    if last_exception:
        raise last_exception

    raise RuntimeError("This line should not be reachable.")  # For mypy


def get_response_text(response: types.GenerateContentResponse) -> str:
    """
    Safely extracts text from a Gemini response, avoiding warnings for non-text parts.
    Also logs the full response parts for debugging purposes.
    """
    texts = []
    if not response.candidates:
        logger.info("No candidates in response")
        return ""

    for candidate_idx, candidate in enumerate(response.candidates):
        logger.info(f"Candidate {candidate_idx}: finish_reason={candidate.finish_reason}")

        if candidate.content and candidate.content.parts:
            logger.info(f"Candidate {candidate_idx} has {len(candidate.content.parts)} parts")

            # Log detailed information about each part
            for part_idx, part in enumerate(candidate.content.parts):
                part_info = {}

                # Check all possible part types
                if hasattr(part, 'text') and part.text:
                    part_info['text'] = part.text
                    texts.append(part.text)

                if hasattr(part, 'function_call') and part.function_call:
                    part_info['function_call'] = {
                        'name': part.function_call.name,
                        'args': dict(part.function_call.args) if part.function_call.args else {}
                    }

                if hasattr(part, 'function_response') and part.function_response:
                    part_info['function_response'] = str(part.function_response)

                # Log any other attributes that might be present
                part_dict = part.model_dump(exclude_none=True) if hasattr(part, 'model_dump') else {}
                part_dict.pop("thought_signature", None)
                for key, value in part_dict.items():
                    if key not in ['text', 'function_call', 'function_response']:
                        part_info[key] = str(value)

                logger.info(f"Part {part_idx}: {part_info}")
        else:
            logger.info(f"Candidate {candidate_idx} has no content or parts")

    result = "".join(texts)
    logger.info(
        f"Final extracted text: '{result}'")
    return result


async def summarize_user_request(user_message: str, client: genai.Client) -> str:
    """Summarizes the user's request using the Gemini model."""
    if not user_message:
        return ""

    prompt = PROMPT_RESUMIDOR.format(user_message=user_message)

    try:
        response = await invoke_model_with_retries(
            client.aio.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        return get_response_text(response)
    except errors.ServerError as e:
        logger.error(f"Failed to summarize user request after retries: {e}", exc_info=True)
        return user_message  # Fallback to original message on error
    except Exception as e:
        logger.error(f"Failed to summarize user request: {e}", exc_info=True)
        return user_message  # Fallback to original message on error


async def handle_conversation_finished(
    session_id: str,
    history_messages: list[InteractionMessage],
    interaction_data: dict,
    client: genai.Client,
    autopilot_system_prompt: str,
) -> Tuple[list[InteractionMessage], GlobalState, Optional[str], dict]:
    """Handles interactions after the main conversation flow has finished."""
    messages_after_finished_count = (
        interaction_data.get("messages_after_finished_count", 0) + 1
    )
    interaction_data["messages_after_finished_count"] = messages_after_finished_count

    if messages_after_finished_count >= MESSAGES_AFTER_CONVERSATION_FINISHED:
        logger.warning(
            f"User with sessionId {session_id} has sent more than {MESSAGES_AFTER_CONVERSATION_FINISHED} messages. Activating human help tool."
        )
        assistant_message_text = obtener_ayuda_humana()
        tool_call_name = "obtener_ayuda_humana"
        next_state = GlobalState.HUMAN_ESCALATION
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )
        return [assistant_message], next_state, tool_call_name, interaction_data

    genai_history = await get_genai_history(history_messages)

    autopilot_config = types.GenerateContentConfig(
        tools=[obtener_ayuda_humana, nueva_interaccion_requerida],
        system_instruction=autopilot_system_prompt,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    try:
        response = await invoke_model_with_retries(
            client.aio.models.generate_content,
            model=GEMINI_MODEL,
            contents=genai_history,
            config=autopilot_config,
        )
    except errors.ServerError as e:
        logger.error(f"Gemini API Server Error after retries: {e}", exc_info=True)
        assistant_message_text = obtener_ayuda_humana()
        tool_call_name = "obtener_ayuda_humana"
        next_state = GlobalState.HUMAN_ESCALATION
        assistant_message = InteractionMessage(
            role=InteractionType.MODEL, message=assistant_message_text
        )
        return [assistant_message], next_state, tool_call_name, interaction_data

    tool_call_name = None
    assistant_message_text = None
    next_state = GlobalState.CONVERSATION_FINISHED

    if response.function_calls:
        fc_name = response.function_calls[0].name
        if fc_name == "nueva_interaccion_requerida":
            tool_call_name = "nueva_interaccion_requerida"
            interaction_data.pop("classifiedAs", None)
            interaction_data.pop("special_list_sent", None)
            interaction_data["messages_after_finished_count"] = 0
            next_state = GlobalState.AWAITING_RECLASSIFICATION
            assistant_message_text = "Claro, ¿en qué más puedo ayudarte?"
        elif fc_name == "obtener_ayuda_humana":
            tool_call_name = "obtener_ayuda_humana"
            assistant_message_text = obtener_ayuda_humana()
            next_state = GlobalState.HUMAN_ESCALATION

    if not assistant_message_text:
        assistant_message_text = get_response_text(response)

    if not assistant_message_text:
        assistant_message_text = AYUDA_HUMANA_PROMPT
        tool_call_name = "obtener_ayuda_humana"
        next_state = GlobalState.HUMAN_ESCALATION

    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )

    return [assistant_message], next_state, tool_call_name, interaction_data


async def execute_tool_calls_and_get_response(
    history_messages: list[InteractionMessage],
    client: genai.Client,
    tools: list,
    system_prompt: str,
    max_turns: int = 10,
) -> Tuple[Optional[str], dict, list[str], dict]:
    """
    Executes a multi-turn conversation with tool calling until a text response is received.
    1.  Calls the model.
    2.  If the model returns a text response, the loop terminates.
    3.  If the model returns tool calls, they are executed, and their results are added to the history.
    4.  The loop continues until a text response is given or max_turns is reached.
    Returns the final text response, the results of all tools called, a list of tool call names, and tool arguments.
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
    all_tool_args_map = {}
    response = None

    for i in range(max_turns):
        logger.info(
            f"--- Calling Gemini for tool execution/response (Turn {i + 1}/{max_turns}) ---"
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
            return (
                obtener_ayuda_humana(),
                {"obtener_ayuda_humana": True},
                ["obtener_ayuda_humana"],
                {},
            )

        if not response.function_calls:
            logger.info(
                "--- No tool calls from Gemini. Returning direct text response. ---"
            )
            text_response = get_response_text(response)
            return text_response, all_tool_results, all_tool_call_names, all_tool_args_map

        logger.info(
            f"--- Gemini returned {len(response.function_calls)} tool call(s). Executing them. ---"
        )

        # Add the model's turn (with function calls) to history before executing
        genai_history.append(response.candidates[0].content)

        function_response_parts = []

        for function_call in response.function_calls:
            tool_name = function_call.name
            tool_args = dict(function_call.args) if function_call.args else {}
            all_tool_args_map[tool_name] = tool_args
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
    logger.info(f"All tool args: {all_tool_args_map}")
    logger.info("--- End of Gemini call ---")

    return text_response, all_tool_results, all_tool_call_names, all_tool_args_map


async def handle_in_progress_conversation(
    history_messages: list[InteractionMessage],
    current_state: any,
    in_progress_state: any,
    interaction_data: dict,
    client: genai.Client,
    sheets_service: Optional[GoogleSheetsService],
    workflow_function: Callable[
        [list[InteractionMessage], genai.Client, Optional[GoogleSheetsService], dict],
        Awaitable[Tuple[list[InteractionMessage], any, Optional[str], dict]],
    ],
) -> Tuple[list[InteractionMessage], any, Optional[str], dict]:
    """
    Handles the main, in-progress conversation states by dispatching to the
    appropriate workflow function based on the current state.
    """
    if current_state == in_progress_state:
        (
            messages,
            next_state,
            tool_call,
            interaction_data,
        ) = await workflow_function(
            history_messages, client, sheets_service, interaction_data
        )
        return messages, next_state, tool_call, interaction_data

    logger.warning(
        f"Unhandled in-progress state: {current_state}. Escalating to human."
    )
    assistant_message_text = obtener_ayuda_humana()
    tool_call_name = "obtener_ayuda_humana"
    next_state = GlobalState.HUMAN_ESCALATION
    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )
    return [assistant_message], next_state, tool_call_name, interaction_data

async def get_final_text_response(
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
    try:
        response = await invoke_model_with_retries(
            client.aio.models.generate_content,
            model=GEMINI_MODEL, contents=genai_history, config=config
        )
        return get_response_text(response)
    except errors.ServerError as e:
        logger.error(f"Gemini API Server Error after retries: {e}", exc_info=True)
        return obtener_ayuda_humana()