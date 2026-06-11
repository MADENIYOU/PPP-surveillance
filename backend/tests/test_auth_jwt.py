"""Tests unitaires — création/vérification JWT (sans services externes)."""
import pytest
from fastapi import HTTPException

from app.security.jwt import create_token, decode_token


def test_token_roundtrip():
    token = create_token("user-1", "citizen", "medina")
    payload = decode_token(token)
    assert payload["sub"] == "user-1"
    assert payload["role"] == "citizen"
    assert payload["zone_id"] == "medina"
    assert payload["jti"]


def test_refresh_token_rejected_as_access():
    token = create_token("user-1", "citizen", None, token_type="refresh")
    with pytest.raises(HTTPException) as exc:
        decode_token(token, expected_type="access")
    assert exc.value.status_code == 401


def test_garbage_token_rejected():
    with pytest.raises(HTTPException):
        decode_token("not-a-jwt")
