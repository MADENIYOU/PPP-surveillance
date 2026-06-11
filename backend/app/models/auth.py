"""Modèles Pydantic — /auth/* (API_SPEC.md §2)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserInfo(BaseModel):
    id: str
    role: str
    zone_id: Optional[str] = None
    mfa_enabled: bool = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int


class MfaEnableResponse(BaseModel):
    secret: str
    qr_code_uri: str  # otpauth://totp/...
    message: str = "Scannez ce QR code avec votre application d'authentification."


class MfaVerifyRequest(BaseModel):
    temp_token: str  # token returned by login when MFA is required
    totp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MfaDisableRequest(BaseModel):
    totp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ErasureResponse(BaseModel):
    status: str = "erased"
    message: str = "Vos données personnelles ont été effacées conformément au RGPD."


class AdminErasureRequest(BaseModel):
    user_id: str
    reason: str = Field(min_length=10, max_length=500)


class ConsentRequest(BaseModel):
    data_consent: bool
    data_retention_days: int = Field(default=365, ge=30, le=3650)
