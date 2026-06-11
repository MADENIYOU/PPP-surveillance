"""Application FastAPI — Surveillance Citoyenne de la Pollution à Dakar (DIC2).

Référence : backend/API_SPEC.md (PPP-md). Stack middleware §1.1 :
CORS → rate limit (slowapi) → security headers → request ID → audit logging,
puis JWT/RBAC par dépendance sur les routes protégées.

Démarrage local :
  uvicorn app.main:app --reload --port 8000
Docs interactives : /docs (Swagger), /redoc.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.middleware.audit_logging import AuditLoggingMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import admin, alerts, aqi, auth, export, map as map_router, pipeline, predictions, reports, sensors
from app.security.rate_limit import limiter

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db.seed import seed_demo_users
    try:
        seed_demo_users()
    except Exception as exc:  # noqa: BLE001 — le seed ne doit pas bloquer le démarrage
        logger.warning("seed démo ignoré : %s", exc)
    yield


app = FastAPI(
    title="API Surveillance Pollution Dakar",
    version="1.0.0",
    description="API REST du projet DIC2 — IQA, capteurs, prédictions, signalements.",
    lifespan=lifespan,
)

settings = get_settings()
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

# Ordre : le dernier middleware ajouté s'exécute en premier (CORS en tête).
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,   # jamais "*" (API_SPEC §1.2)
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


# ── Format d'erreur standardisé (API_SPEC §8) ────────────────────────────────
def _error_body(request: Request, code: str, message: str, details=None) -> dict:
    return {"error": {
        "code": code, "message": message, "details": details,
        "request_id": getattr(request.state, "request_id", None),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        body = _error_body(request, exc.detail["code"], exc.detail.get("message", ""),
                           exc.detail.get("details"))
    else:
        body = _error_body(request, "NOT_FOUND" if exc.status_code == 404 else "INTERNAL_ERROR",
                           str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content=_error_body(
        request, "VALIDATION_ERROR", "Validation des paramètres échouée.", exc.errors()))


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    retry_after = int(getattr(exc, "retry_after", 60) or 60)
    body = _error_body(request, "RATE_LIMIT_EXCEEDED",
                       f"Trop de requêtes. Réessayez dans {retry_after} secondes.")
    body["error"]["retry_after_s"] = retry_after
    return JSONResponse(status_code=429, content=body,
                        headers={"Retry-After": str(retry_after)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Jamais de stack trace dans la réponse (API_SPEC §8) — log serveur seulement.
    logger.exception("unhandled error path=%s", request.url.path)
    return JSONResponse(status_code=500, content=_error_body(
        request, "INTERNAL_ERROR", "Erreur interne du serveur."))


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


for r in (auth.router, aqi.router, sensors.router, reports.router,
          predictions.router, map_router.router, alerts.router,
          export.router, admin.router, pipeline.router):
    app.include_router(r)
