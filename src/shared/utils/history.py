import json
import base64

from google.genai import types
from pydantic import ValidationError

from src.shared.enums import InteractionType
from src.shared.schemas import InteractionMessage


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
        try:
            parts_data = json.loads(msg.message)
            for p_data in parts_data:
                if (
                    "inline_data" in p_data
                    and "data" in p_data["inline_data"]
                    and isinstance(p_data["inline_data"]["data"], str)
                ):
                    try:
                        # Attempt to decode if it is a base64 string.
                        p_data["inline_data"]["data"] = base64.b64decode(
                            p_data["inline_data"]["data"]
                        )
                    except (ValueError, TypeError):
                        # Not a valid base64 string, leave as is.
                        # model_validate will likely fail later, which is expected.
                        pass

            parts = [types.Part.model_validate(p) for p in parts_data]
        except (json.JSONDecodeError, TypeError, ValidationError):
            parts = [types.Part(text=msg.message)]
        genai_history.append(types.Content(role=msg.role, parts=parts))
    return genai_history


def _convert_bytes_to_base64(obj):
    """
    Recursively converts bytes objects to base64 strings in a nested structure.
    """
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    elif isinstance(obj, dict):
        return {key: _convert_bytes_to_base64(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_convert_bytes_to_base64(item) for item in obj]
    else:
        return obj


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
        tool_calls = []
        if content.role == "model":
            # Check for function calls in the content
            for part in content.parts:
                if part.function_call:
                    tool_calls.append(part.function_call.name)
        
        if len(content.parts) == 1 and content.parts[0].text is not None:
            message_str = content.parts[0].text
        else:
            parts_json_list = []
            for p in content.parts:
                part_dump = p.model_dump(exclude_none=True)
                part_dump.pop("thought_signature", None)
                
                # Convert any bytes objects to base64 strings recursively
                part_dump = _convert_bytes_to_base64(part_dump)
                
                parts_json_list.append(part_dump)
            message_str = json.dumps(parts_json_list)

        messages.append(
            InteractionMessage(
                role=InteractionType(content.role), 
                message=message_str,
                tool_calls=tool_calls if tool_calls else None
            )
        )
    return messages
