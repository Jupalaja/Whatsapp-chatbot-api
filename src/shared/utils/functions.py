import logging

import google.genai as genai
from google.genai import types

from src.shared.constants import GEMINI_MODEL
from src.shared.prompts import PROMPT_RESUMIDOR

logger = logging.getLogger(__name__)


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
        return response.text
    except Exception as e:
        logger.error(f"Failed to summarize user request: {e}", exc_info=True)
        return user_message  # Fallback to original message on error

