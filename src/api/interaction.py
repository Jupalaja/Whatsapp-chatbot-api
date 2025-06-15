import logging
from typing import List
from fastapi import APIRouter, HTTPException, Request
import google.genai as genai
from google.genai import errors, types

from ..schemas import InteractionRequest, InteractionResponse, InteractionMessage

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/interaction", response_model=InteractionResponse)
async def handle_interaction(interaction_request: InteractionRequest, request: Request):
    """
    Handles a user-assistant interaction, continuing a conversation.
    """
    client: genai.Client = request.app.state.genai_client
    try:
        model = "gemini-1.5-flash-latest"

        history = []
        for msg in interaction_request.messages:
            # The 'assistant' role from the API maps to the 'model' role in the genai library
            role = "user" if msg.type == "user" else "model"
            history.append(types.Content(role=role, parts=[types.Part(text=msg.message)]))

        response = await client.aio.models.generate_content(
            model=model, contents=history
        )

        response_messages = [
            InteractionMessage(
                type=msg.type,
                message=msg.message,
            )
            for msg in interaction_request.messages
        ]

        if response.text:
            response_messages.append(
                InteractionMessage(
                    type="assistant",
                    message=response.text,
                )
            )

        return InteractionResponse(
            sessionID=interaction_request.sessionID, messages=response_messages
        )
    except errors.APIError as e:
        logger.error(f"Gemini API Error: {e}")
        raise HTTPException(status_code=500, detail=f"Gemini API Error: {e!s}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Check server logs and environment variables.",
        )
