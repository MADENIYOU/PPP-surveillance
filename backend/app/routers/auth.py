"""Router /auth — login + refresh (API_SPEC.md §2)."""
from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import get_settings
from app.db import postgres
from app.models.auth import (
    LoginRequest, RefreshRequest, RefreshResponse, TokenResponse, UserInfo,
    MfaEnableResponse, MfaVerifyRequest, MfaDisableRequest,
    ErasureResponse, ConsentRequest,
)
from app.security.jwt import create_token, decode_token, get_current_user, revoke_token
from app.security.rate_limit import limiter
from app.utils.audit import log_sensitive_access
from app.utils.encryption import decrypt_deterministic, make_email_lookup

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
@limiter.limit("5/minute")  # anti brute-force (API_SPEC §3)
def login(request: Request, body: LoginRequest):
    email_input = body.email.lower()
    email_lookup = make_email_lookup(email_input)
    use_like = email_lookup != email_input  # True when encryption is enabled
    operator = "LIKE" if use_like else "="
    with postgres.cursor() as cur:
        cur.execute(f"""
            SELECT u.id, u.password_hash, u.role, u.is_active,
                   u.mfa_enabled, u.mfa_secret,
                   split_part(z.path::text, '.', -1) AS zone_slug
            FROM users u LEFT JOIN zones z ON z.id = u.zone_id
            WHERE u.email {operator} %s
        """, (email_lookup,))
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

    # Check if MFA is enabled for this user
    mfa_enabled = row["mfa_enabled"] if "mfa_enabled" in row else False

    if mfa_enabled:
        # Return a temporary token valid for 5 minutes
        temp_token = create_token(user_id, role, zone, "mfa_temp")
        return {
            "mfa_required": True,
            "temp_token": temp_token,
            "message": "MFA requis. Utilisez /auth/mfa/verify avec votre code TOTP."
        }

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


@router.delete("/me", response_model=ErasureResponse)
@limiter.limit("3/hour")
def delete_my_account(request: Request, user: dict = Depends(get_current_user)):
    """Droit à l'effacement RGPD — l'utilisateur supprime son propre compte."""
    with postgres.cursor() as cur:
        cur.execute("SELECT * FROM gdpr_erase_user(%s::uuid)", (user["sub"],))
        cur.fetchall()

    revoke_token(user)

    log_sensitive_access("DELETE", "users", user["sub"],
                         request.client.host if request.client else None,
                         {"gdpr_erasure": True, "self_service": True})

    return ErasureResponse(
        message="Toutes vos données personnelles ont été anonymisées. Votre compte est désactivé."
    )


@router.post("/consent")
@limiter.limit("10/minute")
def update_consent(request: Request, body: ConsentRequest, user: dict = Depends(get_current_user)):
    with postgres.cursor() as cur:
        cur.execute("""
            UPDATE users SET data_consent = %s, data_retention_days = %s,
                   consent_date = CASE WHEN %s THEN now() ELSE consent_date END
            WHERE id = %s
        """, (body.data_consent, body.data_retention_days, body.data_consent, user["sub"]))

        cur.execute("""
            UPDATE citizens c SET data_consent = %s
            FROM users u WHERE u.id = %s AND c.id = u.citizen_id
        """, (body.data_consent, user["sub"]))

    if not body.data_consent:
        log_sensitive_access("UPDATE", "users", user["sub"],
                             request.client.host if request.client else None,
                             {"consent_withdrawn": True, "retention_days": body.data_retention_days})

    return {"status": "updated", "data_consent": body.data_consent}


@router.get("/consent")
def get_consent(user: dict = Depends(get_current_user)):
    with postgres.cursor() as cur:
        cur.execute("""
            SELECT data_consent, consent_date, data_retention_days, erasure_requested_at
            FROM users WHERE id = %s
        """, (user["sub"],))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Utilisateur introuvable."})
        return dict(row)


@router.post("/mfa/enable", response_model=MfaEnableResponse)
@limiter.limit("5/minute")
def mfa_enable(request: Request, user: dict = Depends(get_current_user)):
    import pyotp
    secret = pyotp.random_base32()
    s = get_settings()
    issuer = s.totp_issuer
    with postgres.cursor() as cur:
        cur.execute("SELECT email FROM users WHERE id = %s", (user["sub"],))
        email_row = cur.fetchone()
        if not email_row:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Utilisateur introuvable."})
        email = decrypt_deterministic(email_row["email"])
        cur.execute("UPDATE users SET mfa_secret = %s, mfa_enabled = true WHERE id = %s", (secret, user["sub"]))
    qr_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)
    return MfaEnableResponse(secret=secret, qr_code_uri=qr_uri)


@router.post("/mfa/verify", response_model=TokenResponse)
@limiter.limit("5/minute")
def mfa_verify(request: Request, body: MfaVerifyRequest):
    import pyotp
    # Decode the temporary token
    payload = decode_token(body.temp_token, expected_type="mfa_temp")
    user_id = payload["sub"]
    role = payload["role"]
    zone = payload.get("zone_id")

    with postgres.cursor() as cur:
        cur.execute("SELECT mfa_secret, mfa_enabled FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if not row or not row["mfa_enabled"] or not row["mfa_secret"]:
            raise HTTPException(400, detail={"code": "MFA_NOT_ENABLED", "message": "MFA non configuré pour cet utilisateur."})

        totp = pyotp.TOTP(row["mfa_secret"])
        if not totp.verify(body.totp_code, valid_window=1):
            raise HTTPException(401, detail={"code": "MFA_INVALID", "message": "Code TOTP invalide."})

        # Prevent code replay
        cur.execute("UPDATE users SET mfa_last_used = now() WHERE id = %s", (user_id,))

    s = get_settings()
    log_sensitive_access("LOGIN", "users", user_id,
                         request.client.host if request.client else None, {"mfa_verified": True})
    return TokenResponse(
        access_token=create_token(user_id, role, zone, "access"),
        refresh_token=create_token(user_id, role, zone, "refresh"),
        expires_in=s.jwt_access_ttl_s,
        user=UserInfo(id=user_id, role=role, zone_id=zone),
    )


@router.post("/mfa/disable")
@limiter.limit("5/minute")
def mfa_disable(request: Request, body: MfaDisableRequest, user: dict = Depends(get_current_user)):
    import pyotp
    with postgres.cursor() as cur:
        cur.execute("SELECT mfa_secret, mfa_enabled FROM users WHERE id = %s", (user["sub"],))
        row = cur.fetchone()
        if not row or not row["mfa_enabled"]:
            raise HTTPException(400, detail={"code": "MFA_NOT_ENABLED", "message": "MFA déjà désactivé."})
        totp = pyotp.TOTP(row["mfa_secret"])
        if not totp.verify(body.totp_code, valid_window=1):
            raise HTTPException(401, detail={"code": "MFA_INVALID", "message": "Code TOTP invalide."})
        cur.execute("UPDATE users SET mfa_enabled = false, mfa_secret = NULL WHERE id = %s", (user["sub"],))
    return {"status": "disabled", "message": "MFA désactivé avec succès."}


@router.get("/mfa/status")
def mfa_status(user: dict = Depends(get_current_user)):
    with postgres.cursor() as cur:
        cur.execute("SELECT mfa_enabled FROM users WHERE id = %s", (user["sub"],))
        row = cur.fetchone()
        return {"mfa_enabled": bool(row["mfa_enabled"]) if row else False}
