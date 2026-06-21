from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SERVICE_KEY nunca vai para o frontend
    supabase_url: str = ""
    supabase_service_key: str = ""

    cloudinary_cloud_name: str = ""

    # usadas só pelos seeders
    tmdb_api_key: str = ""
    rawg_api_key: str = ""
    freesound_api_key: str = ""
    gemini_api_key: str = ""
    restcountries_api_key: str = ""

    cors_origins: str = "http://localhost:5173"

    default_round_duration: float = 20.0
    default_total_rounds: int = 10

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
