from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Gemini FastAPI"

    # Database
    DATABASE_URL: str

    # Google
    GOOGLE_SECRETS_JSON_PATH: str = "secrets.json"
    GOOGLE_SHEET_ID_CLIENTES_POTENCIALES: str | None = "16G1_hvPfn6rVhwVN5inWef1_XRnI4Ge-5hZhFK1SU4E"
    GOOGLE_SHEET_ID_CLIENTES_POTENCIALES_EXPORT: str | None = "1Ya_hzfVc5zRFBKc8581eKagvVwlLyaaRH7dzYRTBR3g"

    # Google GenAI
    GOOGLE_GENAI_USE_VERTEXAI: bool = False
    GOOGLE_CLOUD_PROJECT: str | None = None
    GOOGLE_CLOUD_LOCATION: str | None = None
    GOOGLE_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

settings = Settings()
