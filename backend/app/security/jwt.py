"""JWT — création/vérification de tokens (API_SPEC.md §2).

Payload : sub (user uuid), role, zone_id, iat, exp, jti (révocation via Redis).
RS256 si paire de clés fournie, repli HS256 en dev (voir config.py)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request

from app.config import get_settings
from app.db.redis_client import blacklist_jti, is_jti_blacklisted


def create_token(user_id: str, role: str, zone_id: Optional[str],
                 token_type: str = "access") -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    if token_type == "access":
        ttl = s.jwt_access_ttl_s
    elif token_type == "mfa_temp":
        ttl = s.jwt_mfa_temp_ttl_s
    else:
        ttl = s.jwt_refresh_ttl_s
    payload = {
        "sub": user_id,
        "role": role,
        "zone_id": zone_id,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + ttl,
        "jti": str(uuid.uuid4()),
    }
    return pyjwt.encode(payload, s.jwt_signing_key, algorithm=s.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict:
    """Vérifie signature, expiration, type et blacklist. Lève HTTPException
    au format d'erreur standard (géré par le handler global)."""
    s = get_settings()
    try:
        payload = pyjwt.decode(token, s.jwt_verify_key, algorithms=[s.jwt_algorithm])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, detail={"code": "TOKEN_EXPIRED", "message": "Token JWT expiré."})
    except pyjwt.InvalidTokenError:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Token JWT invalide."})
    if payload.get("type") != expected_type:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Type de token invalide."})
    if is_jti_blacklisted(payload.get("jti", "")):
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Token révoqué."})
    return payload


def revoke_token(payload: dict) -> None:
    ttl = max(1, payload["exp"] - int(datetime.now(timezone.utc).timestamp()))
    blacklist_jti(payload["jti"], ttl)


def _extract_bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def get_current_user(request: Request) -> dict:
    """Dépendance FastAPI — utilisateur authentifié requis."""
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Token JWT absent."})
    return decode_token(token)


def get_optional_user(request: Request) -> Optional[dict]:
    """Dépendance — utilisateur si token présent, None sinon (routes publiques)."""
    token = _extract_bearer(request)
    return decode_token(token) if token else None


CurrentUser = Annotated[dict, Depends(get_current_user)]
