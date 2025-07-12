import logging
from typing import Awaitable, Callable, Optional, Tuple

import google.genai as genai
from google.genai import types

from src.services.google_sheets import GoogleSheetsService
from src.shared.constants import (
    GEMINI_MODEL,
    MESSAGES_AFTER_CONVERSATION_FINISHED,
)
from src.shared.enums import InteractionType
from src.shared.prompts import AYUDA_HUMANA_PROMPT, PROMPT_RESUMIDOR
from src.shared.schemas import InteractionMessage
from src.shared.state import GlobalState
from src.shared.tools import obtener_ayuda_humana
from src.shared.utils.history import get_genai_history

logger = logging.getLogger(__name__)


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
                    part_info['text'] = part.text[:100] + "..." if len(part.text) > 100 else part.text
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
                for key, value in part_dict.items():
                    if key not in ['text', 'function_call', 'function_response']:
                        part_info[key] = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)

                logger.info(f"Part {part_idx}: {part_info}")
        else:
            logger.info(f"Candidate {candidate_idx} has no content or parts")

    result = "".join(texts)
    logger.info(
        f"Final extracted text: '{result[:100]}...'" if len(result) > 100 else f"Final extracted text: '{result}'")
    return result


async def summarize_user_request(user_message: str, client: genai.Client) -> str:
    """Summarizes the user's request using the Gemini model."""
    if not user_message:
        return ""

    prompt = PROMPT_RESUMIDOR.format(user_message=user_message)

    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        return get_response_text(response)
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
        tools=[obtener_ayuda_humana],
        system_instruction=autopilot_system_prompt,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL, contents=genai_history, config=autopilot_config
    )

    tool_call_name = None
    assistant_message_text = None
    next_state = GlobalState.CONVERSATION_FINISHED

    if (
            response.function_calls
            and response.function_calls[0].name == "obtener_ayuda_humana"
    ):
        tool_call_name = "obtener_ayuda_humana"
        assistant_message_text = obtener_ayuda_humana()
        next_state = GlobalState.HUMAN_ESCALATION
    else:
        assistant_message_text = get_response_text(response)

    if not assistant_message_text:
        assistant_message_text = AYUDA_HUMANA_PROMPT
        tool_call_name = "obtener_ayuda_humana"
        next_state = GlobalState.HUMAN_ESCALATION

    assistant_message = InteractionMessage(
        role=InteractionType.MODEL, message=assistant_message_text
    )

    return [assistant_message], next_state, tool_call_name, interaction_data


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
