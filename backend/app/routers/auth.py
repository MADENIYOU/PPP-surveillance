"""Router /auth — login + refresh (API_SPEC.md §2)."""
from __future__ import annotations

import bcrypt
from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.db import postgres
from app.models.auth import LoginRequest, RefreshRequest, RefreshResponse, TokenResponse, UserInfo
from app.security.jwt import create_token, decode_token
from app.security.rate_limit import limiter
from app.utils.audit import log_sensitive_access

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")  # anti brute-force (API_SPEC §3)
def login(request: Request, body: LoginRequest):
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT u.id, u.password_hash, u.role, u.is_active,
                   split_part(z.path::text, '.', -1) AS zone_slug
            FROM users u LEFT JOIN zones z ON z.id = u.zone_id
            WHERE u.email = %s
        """, (body.email.lower(),))
        row = cur.fetchone()

    # bcrypt.checkpw sur un hash factice si l'utilisateur n'existe pas —
    # réponse en temps constant (pas d'oracle d'énumération d'emails).
    dummy = b"$2b$12$C6UzMDM.H6dfI/f/IKcEeO7ZkW9bT0lHkzQy1xMGsvO8Gm0kqo0r2"
    stored = row["password_hash"].encode() if row else dummy
    valid = bcrypt.checkpw(body.password.encode(), stored) and row is not None

    if not valid or not row["is_active"]:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED",
                                         "message": "Email ou mot de passe incorrect."})

    user_id, role, zone = str(row["id"]), str(row["role"]), row["zone_slug"]
    with postgres.cursor() as cur:
        cur.execute("UPDATE users SET last_login = now() WHERE id = %s", (user_id,))
    log_sensitive_access("LOGIN", "users", user_id,
                         request.client.host if request.client else None, {})

    s = get_settings()
    return TokenResponse(
        access_token=create_token(user_id, role, zone, "access"),
        refresh_token=create_token(user_id, role, zone, "refresh"),
        expires_in=s.jwt_access_ttl_s,
        user=UserInfo(id=user_id, role=role, zone_id=zone),
    )


@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit("10/minute")
def refresh(request: Request, body: RefreshRequest):
    payload = decode_token(body.refresh_token, expected_type="refresh")
    s = get_settings()
    return RefreshResponse(
        access_token=create_token(payload["sub"], payload["role"],
                                  payload.get("zone_id"), "access"),
        expires_in=s.jwt_access_ttl_s,
    )
