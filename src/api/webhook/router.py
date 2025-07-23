import logging
import json
import uuid
import asyncio
from typing import Optional

from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from pydantic import ValidationError
import google.genai as genai
import httpx
from sqlalchemy.orm.attributes import flag_modified

from src.config import settings
from src.api.chat_router.router import _chat_router_logic
from src.database.db import AsyncSessionFactory
from src.database import models
from src.shared.enums import InteractionType
from src.shared.schemas import InteractionMessage, InteractionRequest
from src.shared.messages import MESSAGE_NON_TEXT_MESSAGES_NOT_ACCEPTED
from src.services.google_sheets import GoogleSheetsService
from src.shared.messages import (
    SPECIAL_LIST_TITLE,
    SPECIAL_LIST_DESCRIPTION,
    SPECIAL_LIST_FIRST_OPTION,
    SPECIAL_LIST_SECOND_OPTION,
    SPECIAL_LIST_THIRD_OPTION,
    SPECIAL_LIST_FOURTH_OPTION,
    SPECIAL_LIST_FIFTH_OPTION,
    SPECIAL_LIST_SIXTH_OPTION,
    WHATSAPP_WEB_INSTRUCTIONS_MESSAGE,
)

from .schemas import WebhookEvent, WebhookMessage


router = APIRouter()
logger = logging.getLogger(__name__)


TEXT_LIST_OPTIONS = {
    "1": SPECIAL_LIST_FIRST_OPTION,
    "2": SPECIAL_LIST_SECOND_OPTION,
    "3": SPECIAL_LIST_THIRD_OPTION,
    "4": SPECIAL_LIST_FOURTH_OPTION,
    "5": SPECIAL_LIST_FIFTH_OPTION,
    "6": SPECIAL_LIST_SIXTH_OPTION,
    "1️⃣": SPECIAL_LIST_FIRST_OPTION,
    "2️⃣": SPECIAL_LIST_SECOND_OPTION,
    "3️⃣": SPECIAL_LIST_THIRD_OPTION,
    "4️⃣": SPECIAL_LIST_FOURTH_OPTION,
    "5️⃣": SPECIAL_LIST_FIFTH_OPTION,
    "6️⃣": SPECIAL_LIST_SIXTH_OPTION,
}


def detect_non_text_message(message: Optional[WebhookMessage]) -> bool:
    """
    Detects if the message is a non-text message (e.g., audio, image, video).
    A message is considered non-text if it exists but does not contain
    a 'conversation' or 'listResponseMessage' field, which are used for text.
    """
    if not message:
        # No message object, so not a non-text message we're concerned with.
        return False

    is_text_based = (
        message.conversation is not None or message.listResponseMessage is not None
    )
    return not is_text_based


async def send_composing_presence(phone_number: str, message: str):
    """
    Sends a 'composing' presence to a phone number and waits for a calculated delay.
    """
    if not all(
        [
            settings.WHATSAPP_SERVER_URL,
            settings.WHATSAPP_SERVER_API_KEY,
            settings.WHATSAPP_SERVER_INSTANCE_NAME,
        ]
    ):
        logger.warning(
            "WhatsApp server settings are not configured. Skipping composing presence."
        )
        return

    typing_delay_seconds = min(max(len(message) / 10, 0.5), 3)

    # The presence duration in the API call should be slightly longer than our wait time
    # to ensure it's visible until the message is sent.
    presence_duration_ms = int(typing_delay_seconds * 1000)

    url = f"{settings.WHATSAPP_SERVER_URL}/chat/sendPresence/{settings.WHATSAPP_SERVER_INSTANCE_NAME}"
    headers = {"apikey": settings.WHATSAPP_SERVER_API_KEY}
    payload = {
        "presence": "composing",
        "delay": presence_duration_ms,
        "number": phone_number,
    }

    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, headers=headers, json=payload)
            logger.debug(
                f"Sent 'composing' presence to {phone_number} for {typing_delay_seconds}s."
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Failed to send 'composing' presence to {phone_number}. Status: {e.response.status_code}, Response: {e.response.text}"
            )
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while sending 'composing' presence to {phone_number}: {e}",
                exc_info=True,
            )

    await asyncio.sleep(    typing_delay_seconds)


async def send_whatsapp_message(phone_number: str, message: str):
    """
    Sends a message to a phone number using the WhatsApp API.
    """
    if not all(
        [
            settings.WHATSAPP_SERVER_URL,
            settings.WHATSAPP_SERVER_API_KEY,
            settings.WHATSAPP_SERVER_INSTANCE_NAME,
        ]
    ):
        logger.warning(
            "WhatsApp server settings are not configured. Skipping message sending."
        )
        return

    await send_composing_presence(phone_number, message)

    url = f"{settings.WHATSAPP_SERVER_URL}/message/sendText/{settings.WHATSAPP_SERVER_INSTANCE_NAME}"
    headers = {"apikey": settings.WHATSAPP_SERVER_API_KEY}
    payload = {"number": phone_number, "text": message}

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, headers=headers, json=payload)
            res.raise_for_status()
            try:
                response_data = res.json()
                log_message = response_data.get("message", {}).get(
                    "conversation", res.text
                )
            except json.JSONDecodeError:
                log_message = res.text
            logger.debug(
                f"Successfully sent WhatsApp message to {phone_number}. Response: {log_message}"
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Failed to send WhatsApp message to {phone_number}. Status: {e.response.status_code}, Response: {e.response.text}"
            )
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while sending WhatsApp message to {phone_number}: {e}",
                exc_info=True,
            )


async def send_whatsapp_text_list_message(phone_number: str):
    """
    Sends a text-based list message for WhatsApp Web users.
    """
    if not all(
        [
            settings.WHATSAPP_SERVER_URL,
            settings.WHATSAPP_SERVER_API_KEY,
            settings.WHATSAPP_SERVER_INSTANCE_NAME,
        ]
    ):
        logger.warning(
            "WhatsApp server settings are not configured. Skipping message sending."
        )
        return

    message = (
        f"{SPECIAL_LIST_TITLE}\n"
        f"{SPECIAL_LIST_DESCRIPTION}\n\n"
        f"1️⃣. {SPECIAL_LIST_FIRST_OPTION}\n"
        f"2️⃣. {SPECIAL_LIST_SECOND_OPTION}\n"
        f"3️⃣. {SPECIAL_LIST_THIRD_OPTION}\n"
        f"4️⃣. {SPECIAL_LIST_FOURTH_OPTION}\n"
        f"5️⃣. {SPECIAL_LIST_FIFTH_OPTION}\n"
        f"6️⃣. {SPECIAL_LIST_SIXTH_OPTION}\n"
        f"\n{WHATSAPP_WEB_INSTRUCTIONS_MESSAGE}"
    )
    await send_whatsapp_message(phone_number, message)
    logger.debug(f"Successfully sent WhatsApp text list message to {phone_number}.")


async def send_whatsapp_list_message(phone_number: str):
    """
    Sends a list message to a phone number using the WhatsApp API.
    """
    if not all(
        [
            settings.WHATSAPP_SERVER_URL,
            settings.WHATSAPP_SERVER_API_KEY,
            settings.WHATSAPP_SERVER_INSTANCE_NAME,
        ]
    ):
        logger.warning(
            "WhatsApp server settings are not configured. Skipping message sending."
        )
        return

    # Create a representative text for delay calculation
    representative_text = (
        f"{SPECIAL_LIST_TITLE}\n"
        f"{SPECIAL_LIST_DESCRIPTION}\n"
        f"{SPECIAL_LIST_FIRST_OPTION}\n"
        f"{SPECIAL_LIST_SECOND_OPTION}\n"
        f"{SPECIAL_LIST_THIRD_OPTION}\n"
        f"{SPECIAL_LIST_FOURTH_OPTION}\n"
        f"{SPECIAL_LIST_FIFTH_OPTION}\n"
        f"{SPECIAL_LIST_SIXTH_OPTION}"
    )
    await send_composing_presence(phone_number, representative_text)

    url = f"{settings.WHATSAPP_SERVER_URL}/message/sendList/{settings.WHATSAPP_SERVER_INSTANCE_NAME}"
    headers = {"apikey": settings.WHATSAPP_SERVER_API_KEY}
    payload = {
        "number": phone_number,
        "title": f"{SPECIAL_LIST_TITLE}",
        "description": f"{SPECIAL_LIST_DESCRIPTION}",
        "buttonText": "Haz click aquí",
        "footerText": "",
        "sections": [
            {
                "title": "",
                "rows": [
                    {"title": f"{SPECIAL_LIST_FIRST_OPTION}", "rowId": "rowId 001"},
                    {
                        "title": f"{SPECIAL_LIST_SECOND_OPTION}",
                        "rowId": "rowId 002",
                    },
                    {
                        "title": f"{SPECIAL_LIST_THIRD_OPTION}",
                        "rowId": "rowId 003",
                    },
                    {
                        "title": f"{SPECIAL_LIST_FOURTH_OPTION}",
                        "rowId": "rowId 004",
                    },
                    {
                        "title": f"{SPECIAL_LIST_FIFTH_OPTION}",
                        "rowId": "rowId 005",
                    },
                    {
                        "title": f"{SPECIAL_LIST_SIXTH_OPTION}",
                        "rowId": "rowId 006",
                    },
                ],
            }
        ],
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, headers=headers, json=payload)
            res.raise_for_status()
            logger.debug(
                f"Successfully sent WhatsApp list message to {phone_number}."
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Failed to send WhatsApp list message to {phone_number}. Status: {e.response.status_code}, Response: {e.response.text}"
            )
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while sending WhatsApp list message to {phone_number}: {e}",
                exc_info=True,
            )


async def process_webhook_event(
    event: WebhookEvent, client: genai.Client, sheets_service: GoogleSheetsService
):
    """
    Processes a single webhook event in the background.
    """
    session_id = None
    if event.data.key and event.data.key.remoteJid:
        session_id = event.data.key.remoteJid.split("@")[0]

    from_me = event.data.key.fromMe
    event_type = event.event

    # Basic filtering for events to process
    if not (event_type == "messages.upsert" and not from_me and session_id):
        has_message = bool(event.data.message)
        logger.debug(
            f"Skipping webhook event processing. Details: event_type='{event_type}', from_me={from_me}, has_session_id={bool(session_id)}, has_message={has_message}"
        )
        return

    phone_number = session_id

    # Handle non-text messages
    if detect_non_text_message(event.data.message):
        logger.debug(
            f"Detected non-text message for session_id: {session_id}. Sending reply and stopping."
        )
        if phone_number:
            await send_whatsapp_message(phone_number, MESSAGE_NON_TEXT_MESSAGES_NOT_ACCEPTED)
        return

    # Extract text from message
    message_text = None
    if event.data.message:
        if event.data.message.conversation:
            message_text = event.data.message.conversation
        elif (
            event.data.message.listResponseMessage
            and event.data.message.listResponseMessage.title
        ):
            message_text = event.data.message.listResponseMessage.title

    if not message_text:
        logger.debug(
            f"Skipping webhook event with no text content for session_id: {session_id}"
        )
        return

    async with AsyncSessionFactory() as db:
        interaction = await db.get(models.Interaction, session_id)

        # Handle numeric input if a text list was previously sent to a web client
        if interaction and interaction.interaction_data and interaction.interaction_data.get("text_list_sent_to_web"):
            if message_text.strip() in TEXT_LIST_OPTIONS:
                logger.debug(f"Mapping numeric input '{message_text.strip()}' for session {session_id}")
                message_text = TEXT_LIST_OPTIONS[message_text.strip()]
                interaction.interaction_data["text_list_sent_to_web"] = False
                flag_modified(interaction, "interaction_data")
                await db.commit()

        # Process text messages
        logger.debug(f"Processing webhook for session_id: {session_id}")

        if message_text.strip().upper() == "RESET":
            logger.debug(f"Received RESET command for session_id: {session_id}")
            if interaction:
                # Generate new session_id for the deleted conversation
                random_uuid = str(uuid.uuid4())[:8]
                new_session_id = f"DELETED-{session_id}-{random_uuid}"

                # Update the session_id and mark as deleted
                interaction.session_id = new_session_id
                interaction.is_deleted = True
                await db.commit()
                logger.debug(
                    f"Soft deleted interaction for session_id: {session_id}, new session_id: {new_session_id}"
                )
            else:
                logger.debug(
                    f"No interaction found for session_id: {session_id}, nothing to reset."
                )
            if phone_number:
                await send_whatsapp_message(phone_number, "El chat ha sido reiniciado")
            return

        user_data = {}
        if phone_number:
            user_data["phoneNumber"] = phone_number
        if event.data.pushName:
            user_data["tagName"] = event.data.pushName

        interaction_message = InteractionMessage(
            role=InteractionType.USER, message=message_text
        )
        interaction_request = InteractionRequest(
            sessionId=session_id, message=interaction_message, userData=user_data
        )
        try:
            # We use the existing 'db' session for the logic call
            response = await _chat_router_logic(
                interaction_request, client, sheets_service, db
            )
            if phone_number:
                if response.toolCall == "send_special_list_message":
                    if event.data.source == "web":
                        await send_whatsapp_text_list_message(phone_number)
                        # The interaction is updated inside _chat_router_logic, so we fetch it again
                        interaction_after_logic = await db.get(models.Interaction, session_id)
                        if interaction_after_logic:
                            if interaction_after_logic.interaction_data is None:
                                interaction_after_logic.interaction_data = {}
                            interaction_after_logic.interaction_data["text_list_sent_to_web"] = True
                            flag_modified(interaction_after_logic, "interaction_data")
                            await db.commit()
                            logger.debug(f"Set text_list_sent_to_web flag for session {session_id}")
                    else:
                        await send_whatsapp_list_message(phone_number)
                elif response.messages:
                    for msg in response.messages:
                        await send_whatsapp_message(phone_number, msg.message)
        except Exception as e:
            logger.error(
                f"Error processing webhook event for session {session_id}: {e}",
                exc_info=True,
            )


@router.post(f"/webhook/{settings.WEBHOOK_PATH}", status_code=200)
async def handle_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Handles incoming webhooks from the Evolution API.
    """
    logger.debug(f"Received webhook on path: /webhook/{settings.WEBHOOK_PATH}")
    client: genai.Client = request.app.state.genai_client
    sheets_service: GoogleSheetsService = request.app.state.sheets_service

    payload_json = None
    try:
        payload_json = await request.json()
        logger.debug(f"Webhook payload: {json.dumps(payload_json, indent=2)}")

        # Handle both single object and list of objects
        events_to_process = (
            payload_json if isinstance(payload_json, list) else [payload_json]
        )

        # Manually validate the payload.
        payload = [WebhookEvent.model_validate(p) for p in events_to_process]

    except json.JSONDecodeError:
        raw_body = await request.body()
        logger.error(
            f"Failed to decode webhook JSON. Raw body: {raw_body.decode('utf-8', errors='ignore')}"
        )
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except ValidationError as e:
        logger.error(f"Webhook payload validation failed: {e}")
        if payload_json:
            logger.error(f"Offending payload: {json.dumps(payload_json, indent=2)}")
        raise HTTPException(status_code=422, detail=e.errors())
    except Exception as e:
        logger.error(
            f"An unexpected error occurred during webhook processing: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    for event in payload:
        background_tasks.add_task(process_webhook_event, event, client, sheets_service)

    return {"status": "ok"}
