"""Supabase singleton."""
from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache
def get_supabase() -> Client:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY ausentes no .env — "
            "configure antes de subir o servidor ou rodar os seeders."
        )
    return create_client(settings.supabase_url, settings.supabase_service_key)
