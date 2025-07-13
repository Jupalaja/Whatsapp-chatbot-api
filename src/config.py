from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any, Optional
from pydantic import PostgresDsn, field_validator


class Settings(BaseSettings):
    PROJECT_NAME: str = "Gemini FastAPI"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: PostgresDsn

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
        "1ulDgCbARxwiNIwz2wddZWRcUFDvWPwfunpxdbxzttrY"
    )
    GOOGLE_SHEET_ID_EXPORT: Optional[str] = (
        "1Ya_hzfVc5zRFBKc8581eKagvVwlLyaaRH7dzYRTBR3g"
    )

    # Google GenAI
    GOOGLE_GENAI_USE_VERTEXAI: bool = False
    GOOGLE_CLOUD_PROJECT: Optional[str] = None
    GOOGLE_CLOUD_LOCATION: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

    # WhatsApp API
    WEBHOOK_PATH: str
    WHATSAPP_SERVER_URL: Optional[str] = None
    WHATSAPP_SERVER_API_KEY: Optional[str] = None
    WHATSAPP_SERVER_INSTANCE_NAME: Optional[str] = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def strip_quotes_from_db_url(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip('"')
        return v

    @field_validator("GOOGLE_SA_PRIVATE_KEY", mode="before")
    @classmethod
    def strip_quotes_from_private_key(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip('"')
        return v

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
