"""Audit en base des accès sensibles (export, admin) — table audit_logs."""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.db import postgres

logger = logging.getLogger(__name__)


def log_sensitive_access(action: str, resource: str, user_id: Optional[str],
                         ip: Optional[str], details: dict) -> None:
    """`action` ∈ enum audit_action (EXPORT, LOGIN, LOGOUT, READ_REPORT…).
    Ne doit jamais faire échouer la requête métier — erreurs loguées seulement."""
    try:
        with postgres.cursor() as cur:
            cur.execute("""
                INSERT INTO audit_logs (action, resource, details, ip_address, status)
                VALUES (%s::audit_action, %s, %s::jsonb, %s, 'success')
            """, (action, resource,
                  json.dumps({**details, "user_id": user_id}, default=str), ip))
    except Exception as exc:  # noqa: BLE001
        logger.error("audit_log_failed action=%s err=%s", action, exc)
