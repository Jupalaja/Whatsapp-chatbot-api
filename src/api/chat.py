import logging
from fastapi import APIRouter, HTTPException, Request
import google.genai as genai
from google.genai import errors

from ..model.constants import GEMINI_MODEL
from ..schemas import ChatRequest, ChatResponse

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/chat", response_model=ChatResponse)
async def chat_with_gemini(chat_request: ChatRequest, request: Request):
    """
    Sends a message to a Gemini model and returns its response.
    """
    client: genai.Client = request.app.state.genai_client
    try:
        model = GEMINI_MODEL

        response = await client.aio.models.generate_content(
            model=model, contents=chat_request.message
        )

        return ChatResponse(response=response.text)
    except errors.APIError as e:
        logger.error(f"Gemini API Error: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini API Error: {e!s}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        # This can happen if the API key is not set or invalid.
        # The google-genai library can raise various exceptions for auth.
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Check server logs and environment variables.",
        )
