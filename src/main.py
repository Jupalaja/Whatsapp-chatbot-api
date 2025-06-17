import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
import google.genai as genai

from src.api.chat import router as chat
from src.api.interaction import router as interaction
from src.api.cliente_potencial import router as cliente_potencial
from src.api.tipo_de_interaccion import router as tipo_de_interaccion
from src.config import settings
from src.database.db import engine, test_db_connection
from src.shared.schemas import HealthResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up application...")
    if not await test_db_connection():
        logger.warning(
            "Database connection could not be established on startup."
        )
    else:
        logger.info("Database connection successful.")

    app.state.genai_client = genai.Client(
        vertexai=settings.GOOGLE_GENAI_USE_VERTEXAI,
        api_key=settings.GOOGLE_API_KEY,
        project=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.GOOGLE_CLOUD_LOCATION,
    )
    logger.info("Google GenAI Client initialized.")

    yield
    # Shutdown
    logger.info("Shutting down application...")
    await engine.dispose()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
app.include_router(interaction.router, prefix="/api/v1", tags=["Interaction"])
app.include_router(tipo_de_interaccion.router, prefix="/api/v1", tags=["Tipo de Interacción"])
app.include_router(cliente_potencial.router, prefix="/api/v1", tags=["Cliente Potencial"])


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Checks the health of the application and its database connection.
    """
    db_ok = await test_db_connection()
    return HealthResponse(
        status="ok", db_connection="ok" if db_ok else "failed"
    )
