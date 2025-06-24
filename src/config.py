from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    PROJECT_NAME: str = "Gemini FastAPI"

    # Database
    DATABASE_URL: str

    # Google Service Account Credentials
    GOOGLE_SA_TYPE: str = "service_account"
    GOOGLE_SA_PROJECT_ID: str
    GOOGLE_SA_PRIVATE_KEY_ID: str
    GOOGLE_SA_PRIVATE_KEY: str
    GOOGLE_SA_CLIENT_EMAIL: str
    GOOGLE_SA_CLIENT_ID: str
    GOOGLE_SA_AUTH_URI: str
    GOOGLE_SA_TOKEN_URI: str
    GOOGLE_SA_AUTH_PROVIDER_X509_CERT_URL: str
    GOOGLE_SA_CLIENT_X509_CERT_URL: str

    # Google Sheets
    GOOGLE_SHEET_ID_CLIENTES_POTENCIALES: Optional[str] = (
        "16G1_hvPfn6rVhwVN5inWef1_XRnI4Ge-5hZhFK1SU4E"
    )
    GOOGLE_SHEET_ID_CLIENTES_POTENCIALES_EXPORT: Optional[str] = (
        "1Ya_hzfVc5zRFBKc8581eKagvVwlLyaaRH7dzYRTBR3g"
    )

    # Google GenAI
    GOOGLE_GENAI_USE_VERTEXAI: bool = False
    GOOGLE_CLOUD_PROJECT: Optional[str] = None
    GOOGLE_CLOUD_LOCATION: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

settings = Settings()
