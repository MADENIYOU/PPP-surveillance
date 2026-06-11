"""Rate limiting slowapi — limites par endpoint (API_SPEC.md §3)."""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# Limites spécifiques (appliquées par décorateur dans les routers) :
#   POST /reports        : 10/minute par IP
#   POST /auth/login     : 5/minute par IP (anti brute-force)
#   GET  /export/data    : 5/hour
#   GET  /sensors/{id}/data : 60/minute
