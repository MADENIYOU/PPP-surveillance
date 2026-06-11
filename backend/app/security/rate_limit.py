"""Rate limiting slowapi — limites par endpoint (API_SPEC.md §3)."""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

LIMITS = {
    "auth_login": "5/minute",
    "reports_create": "10/minute",
    "export_data": "5/hour",
    "sensor_data": "60/minute",
    "admin_sensors": "60/minute",
}

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
