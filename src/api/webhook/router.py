import logging
import json
import uuid

from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from pydantic import ValidationError
import google.genai as genai
import httpx

from src.config import settings
from src.api.chat_router.router import _chat_router_logic
from src.database.db import AsyncSessionFactory
from src.database import models
from src.shared.enums import InteractionType
from src.shared.schemas import InteractionMessage, InteractionRequest
from src.services.google_sheets import GoogleSheetsService
from .schemas import WebhookEvent

router = APIRouter()
logger = logging.getLogger(__name__)


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

    url = f"{settings.WHATSAPP_SERVER_URL}/message/sendList/{settings.WHATSAPP_SERVER_INSTANCE_NAME}"
    headers = {"apikey": settings.WHATSAPP_SERVER_API_KEY}
    payload = {
        "number": phone_number,
        "title": "Gracias por comunicarte con Botero Soto",
        "description": "Queremos identificar rápidamente tu solicitud, por favor selecciona entre una de las siguientes opciones👇",
        "buttonText": "Haz click aquí",
        "footerText": "",
        "sections": [
            {
                "title": "",
                "rows": [
                    {"title": "Quiero realizar una cotizacion", "rowId": "rowId 001"},
                    {
                        "title": "Quiero consultar donde está mi vehículo",
                        "rowId": "rowId 002",
                    },
                    {
                        "title": "Quiero saber si están contratando conductores en este momento",
                        "rowId": "rowId 003",
                    },
                    {
                        "title": "Trabajé allí, quiero solicitar un certificado laboral",
                        "rowId": "rowId 004",
                    },
                    {
                        "title": "A quién puedo consultar para ofrecer un producto para la venta?",
                        "rowId": "rowId 005",
                    },
                    {
                        "title": "Quiero averiguar sobre la liquidación de un manifiesto",
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
    if (
        event.data.message
        and event.data.message.messageContextInfo
        and event.data.message.messageContextInfo.deviceListMetadata
        and event.data.message.messageContextInfo.deviceListMetadata.senderKeyHash
    ):
        session_id = (
            event.data.message.messageContextInfo.deviceListMetadata.senderKeyHash
        )

    message_text = None
    if event.data.message:
        if event.data.message.conversation:
            message_text = event.data.message.conversation
        elif (
            event.data.message.listResponseMessage
            and event.data.message.listResponseMessage.title
        ):
            message_text = event.data.message.listResponseMessage.title

    from_me = event.data.key.fromMe
    event_type = event.event

    if (
        event_type == "messages.upsert"
        and not from_me
        and session_id
        and message_text
    ):
        logger.debug(f"Processing webhook for session_id: {session_id}")

        phone_number = None
        if event.data.key.remoteJid:
            phone_number = event.data.key.remoteJid.split("@")[0]

        if message_text.strip().upper() == "RESET":
            logger.debug(f"Received RESET command for session_id: {session_id}")
            async with AsyncSessionFactory() as db:
                interaction = await db.get(models.Interaction, session_id)
                if interaction:
                    # Generate new session_id for the deleted conversation
                    random_uuid = str(uuid.uuid4())[:8]
                    new_session_id = f"DELETED-{session_id}-{random_uuid}"
                    
                    # Update the session_id and mark as deleted
                    interaction.session_id = new_session_id
                    interaction.is_deleted = True
                    await db.commit()
                    logger.debug(f"Soft deleted interaction for session_id: {session_id}, new session_id: {new_session_id}")
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
            # We need a new DB session for the background task
            async with AsyncSessionFactory() as db:
                response = await _chat_router_logic(
                    interaction_request, client, sheets_service, db
                )
                if phone_number:
                    if response.toolCall == "send_special_list_message":
                        await send_whatsapp_list_message(phone_number)
                    elif response.messages:
                        for msg in response.messages:
                            await send_whatsapp_message(phone_number, msg.message)
        except Exception as e:
            logger.error(
                f"Error processing webhook event for session {session_id}: {e}",
                exc_info=True,
            )
    else:
        logger.debug(
            f"Skipping webhook event processing. Details: event_type='{event_type}', from_me={from_me}, has_session_id={bool(session_id)}, has_message_text={bool(message_text)}"
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
