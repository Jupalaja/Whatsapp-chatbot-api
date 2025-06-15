from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Gemini FastAPI"

    # Database
    DATABASE_URL: str

    # Google GenAI
    GOOGLE_GENAI_USE_VERTEXAI: bool = False
    GOOGLE_CLOUD_PROJECT: str | None = None
    GOOGLE_CLOUD_LOCATION: str | None = None
    GOOGLE_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

settings = Settings()