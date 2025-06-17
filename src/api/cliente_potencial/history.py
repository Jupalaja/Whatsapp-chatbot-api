import json
from typing import List, Literal

from google.genai import types
from pydantic import ValidationError

from ...schemas import InteractionMessage


async def get_genai_history(
    history_messages: list[InteractionMessage],
) -> list[types.Content]:
    """
    Converts the application's internal message history format to the
    format required by the Google GenAI SDK.

    Args:
        history_messages: A list of messages in the application's format.

    Returns:
        A list of `genai.Content` objects ready to be sent to the model.
    """
    genai_history = []
    for msg in history_messages:
        role = "user"
        if msg.type == "assistant":
            role = "model"
        elif msg.type == "tool":
            role = "tool"

        try:
            parts_data = json.loads(msg.message)
            parts = [types.Part.model_validate(p) for p in parts_data]
        except (json.JSONDecodeError, TypeError, ValidationError):
            parts = [types.Part(text=msg.message)]
        genai_history.append(types.Content(role=role, parts=parts))
    return genai_history


def genai_content_to_interaction_messages(
    history: list[types.Content],
) -> list[InteractionMessage]:
    """
    Converts a list of genai.Content objects from the SDK back to the
    application's internal InteractionMessage format.

    Args:
        history: A list of `genai.Content` objects from the model response.

    Returns:
        A list of messages in the application's internal format.
    """
    messages = []
    for content in history:
        role: Literal["user", "assistant", "tool"] = "user"
        if content.role == "model":
            role = "assistant"
        elif content.role == "tool":
            role = "tool"

        if len(content.parts) == 1 and content.parts[0].text is not None:
            message_str = content.parts[0].text
        else:
            parts_json_list = [p.model_dump(exclude_none=True) for p in content.parts]
            message_str = json.dumps(parts_json_list)

        messages.append(InteractionMessage(type=role, message=message_str))
    return messages
