"""Redis — cache court (réponses publiques) + blacklist de jti JWT révoqués.

Dégradation gracieuse : si Redis est indisponible, le cache devient un no-op
et la blacklist considère tous les tokens valides (logué en warning) — l'API
publique reste servie, conformément au principe de résilience du projet."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)
_client: Optional[redis.Redis] = None


def client() -> Optional[redis.Redis]:
    global _client
    if _client is None:
        try:
            _client = redis.Redis.from_url(get_settings().redis_url,
                                           socket_timeout=1, socket_connect_timeout=1)
            _client.ping()
        except Exception as exc:  # noqa: BLE001 — toute panne Redis = mode dégradé
            logger.warning("redis indisponible (%s) — cache/blacklist désactivés", exc)
            _client = None
            return None
    return _client


def cache_get(key: str) -> Optional[Any]:
    c = client()
    if c is None:
        return None
    try:
        raw = c.get(f"cache:{key}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl_s: int = 15) -> None:
    c = client()
    if c is None:
        return
    try:
        c.setex(f"cache:{key}", ttl_s, json.dumps(value, default=str))
    except Exception:
        pass


def blacklist_jti(jti: str, ttl_s: int) -> None:
    c = client()
    if c is not None:
        try:
            c.setex(f"jwt:blacklist:{jti}", ttl_s, "1")
        except Exception:
            pass


def is_jti_blacklisted(jti: str) -> bool:
    c = client()
    if c is None:
        return False
    try:
        return bool(c.exists(f"jwt:blacklist:{jti}"))
    except Exception:
        return False
