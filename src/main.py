import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
import google.genai as genai

from src.api.chat_router import router as chat_router
from src.api.interaction import router as interaction
from src.api.cliente_potencial import router as cliente_potencial
from src.api.tipo_de_interaccion import router as tipo_de_interaccion
from src.api.cliente_activo import router as cliente_activo
from src.api.proveedor_potencial import router as proveedor_potencial
from src.api.usuario_administrativo import router as usuario_administrativo
from src.api.candidato_a_empleo import router as candidato_a_empleo
from src.api.transportista import router as transportista
from src.api.webhook import router as webhook_router
from src.config import settings
from src.database.db import engine, test_db_connection
from src.services.google_sheets import GoogleSheetsService
from src.shared.schemas import HealthResponse

log_level = settings.LOG_LEVEL.upper()
logging.basicConfig(
    level=log_level,
    format="%(levelname)s:%(name)s: [%(funcName)s] - %(message)s",
)

# httpx logs at INFO level for requests, which is noisy for production.
# We set it to WARNING to silence it, unless we are in DEBUG mode.
if log_level != "DEBUG":
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

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

    try:
        app.state.sheets_service = GoogleSheetsService()
        logger.info("Google Sheets Service initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets Service: {e}")
        app.state.sheets_service = None

    yield
    # Shutdown
    logger.info("Shutting down application...")
    await engine.dispose()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.mount(f"/{settings.SECRET_PATH}/videos", StaticFiles(directory="src/media"), name="videos")

app.include_router(chat_router.router, prefix="/api/v1", tags=["Chat Router"])
app.include_router(webhook_router.router, prefix="/api/v1", tags=["Webhook"])
app.include_router(interaction.router, prefix="/api/v1", tags=["Interaction"])
app.include_router(tipo_de_interaccion.router, prefix="/api/v1", tags=["Tipo de Interacción"])
app.include_router(cliente_potencial.router, prefix="/api/v1", tags=["Cliente Potencial"])
app.include_router(cliente_activo.router, prefix="/api/v1", tags=["Cliente Activo"])
app.include_router(proveedor_potencial.router, prefix="/api/v1", tags=["Proveedor Potencial"])
app.include_router(usuario_administrativo.router, prefix="/api/v1", tags=["Usuario Administrativo"])
app.include_router(candidato_a_empleo.router, prefix="/api/v1", tags=["Candidato a Empleo"])
app.include_router(transportista.router, prefix="/api/v1", tags=["Transportista"])


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(request: Request):
    """
    Checks the health of the application and its database connection.
    """
    db_ok = await test_db_connection()
    sheets_ok = request.app.state.sheets_service is not None
    return HealthResponse(
        status="ok",
        db_connection="ok" if db_ok else "failed",
        sheets_connection="ok" if sheets_ok else "failed",
    )
