"""RBAC — contrôle de rôle par dépendance (API_SPEC.md §2.3).

Hiérarchie : citizen(1) < researcher(2) < analyst(3) < operator(4) < admin(5) < super_admin(6)."""
from __future__ import annotations

from fastapi import Depends, HTTPException

from app.security.jwt import get_current_user

ROLE_LEVELS = {"citizen": 1, "researcher": 2, "analyst": 3, "operator": 4, "admin": 5, "super_admin": 6}


def require_role(min_role: str):
    """`Depends(require_role("researcher"))` → 403 si rôle insuffisant."""
    min_level = ROLE_LEVELS[min_role]

    def _check(user: dict = Depends(get_current_user)) -> dict:
        if ROLE_LEVELS.get(user.get("role", ""), 0) < min_level:
            raise HTTPException(403, detail={
                "code": "FORBIDDEN",
                "message": f"Rôle insuffisant — '{min_role}' requis.",
            })
        return user

    return _check
