import logging
from typing import List

from fastapi import APIRouter, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
import google.genai as genai

from src.api.chat_router.router import _chat_router_logic
from src.database.db import AsyncSessionFactory
from src.shared.enums import InteractionType
from src.shared.schemas import InteractionMessage, InteractionRequest
from src.services.google_sheets import GoogleSheetsService
from .schemas import WebhookPayload, WebhookEvent

router = APIRouter()
logger = logging.getLogger(__name__)

# This is the "safe UUID path" from the example payload destination.
WEBHOOK_PATH = "8dc6d878-da30-4102-b6b0-4faed52ba983"


async def process_webhook_event(
    event: WebhookEvent, client: genai.Client, sheets_service: GoogleSheetsService
):
    """
    Processes a single webhook event in the background.
    """
    session_id = None
    if (
        event.body.data.message
        and event.body.data.message.messageContextInfo
        and event.body.data.message.messageContextInfo.senderKeyHash
    ):
        session_id = event.body.data.message.messageContextInfo.senderKeyHash

    message_text = None
    if event.body.data.message and event.body.data.message.conversation:
        message_text = event.body.data.message.conversation

    from_me = event.body.data.key.fromMe
    event_type = event.body.event

    if (
        event_type == "messages.upsert"
        and not from_me
        and session_id
        and message_text
    ):
        logger.info(f"Processing webhook for session_id: {session_id}")
        interaction_message = InteractionMessage(
            role=InteractionType.USER, message=message_text
        )
        interaction_request = InteractionRequest(
            sessionId=session_id, message=interaction_message
        )
        try:
            # We need a new DB session for the background task
            async with AsyncSessionFactory() as db:
                await _chat_router_logic(interaction_request, client, sheets_service, db)
        except Exception as e:
            logger.error(
                f"Error processing webhook event for session {session_id}: {e}",
                exc_info=True,
            )


@router.post(f"/webhook/{WEBHOOK_PATH}", status_code=200)
async def handle_webhook(
    payload: WebhookPayload,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Handles incoming webhooks from the Evolution API.
    """
    logger.info(f"Received webhook on path: /webhook/{WEBHOOK_PATH}")
    client: genai.Client = request.app.state.genai_client
    sheets_service: GoogleSheetsService = request.app.state.sheets_service

    for event in payload:
        background_tasks.add_task(process_webhook_event, event, client, sheets_service)

    return {"status": "ok"}
