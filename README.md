# Whatsapp-chatbot-api

This project is the backend API for a WhatsApp chatbot. It's responsible for processing incoming messages from users on WhatsApp and generating intelligent responses using Google's Gemini models.

## Overview

The main purpose of this API is to serve as the brain for a WhatsApp chatbot. It handles the conversational logic, state management for each user, and integration with external services like Google Sheets.

When a user sends a message to the chatbot's WhatsApp number, the message is forwarded to this API. The API then processes the message, maintains the context of the conversation, and uses Google Gemini to understand the user's intent and formulate a relevant reply. The response is then sent back to the user through WhatsApp.

## Core Functionality

- **Message Processing:** Receives messages from WhatsApp users via webhooks.
- **Conversational AI:** Integrates with Google Gemini to understand natural language and generate human-like responses.
- **State Management:** Keeps track of each conversation's state to provide contextual replies.
- **External Integrations:** Connects to other services, such as Google Sheets, to store or retrieve information as needed during a conversation.
