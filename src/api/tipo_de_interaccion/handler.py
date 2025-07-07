import logging
from typing import Optional, Tuple

import google.genai as genai

from src.shared.schemas import Clasificacion, InteractionMessage
from .workflows import workflow_tipo_de_interaccion


logger = logging.getLogger(__name__)


async def handle_tipo_de_interaccion(
    history_messages: list[InteractionMessage],
    client: genai.Client,
) -> Tuple[list[InteractionMessage], Optional[Clasificacion], Optional[str]]:
    return await workflow_tipo_de_interaccion(history_messages, client)
