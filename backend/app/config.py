"""Configuration du backend FastAPI — API_SPEC.md §1/§9.

Tout vient de l'environnement (.env via docker compose) — aucun secret en dur.
JWT : RS256 si une paire de clés est fournie (JWT_PRIVATE_KEY_PATH /
JWT_PUBLIC_KEY_PATH, conformément aux specs non fonctionnelles), sinon repli
HS256 avec JWT_SECRET (dev local uniquement).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "dakar_pollution"
    postgres_user: str = "dakar_admin"
    postgres_password: str = ""

    # InfluxDB
    influxdb_url: str = "http://localhost:8086"
    influxdb_token: str = ""
    influxdb_org: str = "dakar_pollution"
    influxdb_bucket_raw: str = "bucket_raw"
    influxdb_bucket_cleansed: str = "bucket_cleansed"
    influxdb_bucket_downsampled: str = "bucket_downsampled"

    # Redis (cache + blacklist JWT) — l'API reste fonctionnelle sans Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret: str = "dev-only-change-me"
    jwt_private_key_path: str = ""
    jwt_public_key_path: str = ""
    jwt_access_ttl_s: int = 3600
    jwt_refresh_ttl_s: int = 30 * 24 * 3600

    # CORS — origines explicites, jamais "*" (API_SPEC §1.2)
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Seed des comptes démo au démarrage (Phase 4 uniquement)
    backend_seed_demo_users: bool = False
    demo_password_citizen: str = "citizen-demo-2026"
    demo_password_researcher: str = "researcher-demo-2026"
    demo_password_admin: str = "admin-demo-2026"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def jwt_algorithm(self) -> str:
        return "RS256" if self.jwt_private_key_path else "HS256"

    @property
    def jwt_signing_key(self) -> str:
        if self.jwt_private_key_path:
            return Path(self.jwt_private_key_path).read_text()
        return self.jwt_secret

    @property
    def jwt_verify_key(self) -> str:
        if self.jwt_public_key_path:
            return Path(self.jwt_public_key_path).read_text()
        return self.jwt_secret

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
