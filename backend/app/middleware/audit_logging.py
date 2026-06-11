"""Audit logging — log structuré de chaque requête (API_SPEC.md §1.1 [6]).

Log applicatif JSON sur stdout (collecté par Docker). Les accès sensibles
(export, admin) sont en plus journalisés en base via app.utils.audit."""
from __future__ import annotations

import json
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("api.audit")


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(json.dumps({
            "request_id": getattr(request.state, "request_id", None),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 1),
            "client_ip": request.client.host if request.client else None,
        }))
        return response
