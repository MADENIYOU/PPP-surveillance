"""Seed des comptes de démonstration (BACKEND_SEED_DEMO_USERS=true).

Les hash bcrypt sont calculés à l'exécution depuis les mots de passe d'env
(DEMO_PASSWORD_*) — jamais de hash en dur dans un fichier versionné."""
from __future__ import annotations

import logging

import bcrypt

from app.config import get_settings
from app.db import postgres

logger = logging.getLogger(__name__)

DEMO_USERS = [
    ("citizen@demo.dakar-pollution.sn", "citizen", "demo_password_citizen"),
    ("researcher@demo.dakar-pollution.sn", "researcher", "demo_password_researcher"),
    ("admin@demo.dakar-pollution.sn", "admin", "demo_password_admin"),
]


def seed_demo_users() -> int:
    s = get_settings()
    if not s.backend_seed_demo_users:
        return 0
    n = 0
    with postgres.cursor() as cur:
        cur.execute("""
            INSERT INTO citizens (pseudonyme) VALUES ('demo_citizen')
            ON CONFLICT (pseudonyme) DO NOTHING
        """)
        for email, role, pwd_attr in DEMO_USERS:
            pwd_hash = bcrypt.hashpw(getattr(s, pwd_attr).encode(), bcrypt.gensalt()).decode()
            cur.execute("""
                INSERT INTO users (email, password_hash, role, zone_id, citizen_id)
                VALUES (%s, %s, %s::user_role,
                        (SELECT id FROM zones WHERE path = 'dakar.medina'::ltree),
                        (SELECT id FROM citizens WHERE pseudonyme = 'demo_citizen'))
                ON CONFLICT (email) DO NOTHING
            """, (email, pwd_hash, role))
            n += cur.rowcount
    if n:
        logger.info("seed: %d compte(s) démo créé(s)", n)
    return n
