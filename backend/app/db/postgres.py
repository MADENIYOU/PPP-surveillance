"""Pool PostgreSQL du backend — même pattern que pipeline/db/postgres_client.py
(ThreadedConnectionPool + context manager cursor avec commit/rollback)."""
from __future__ import annotations

import threading
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

from app.config import get_settings

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_lock = threading.Lock()


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                s = get_settings()
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 10,
                    host=s.postgres_host, port=s.postgres_port, dbname=s.postgres_db,
                    user=s.postgres_user, password=s.postgres_password,
                )
    return _pool


class cursor:
    """`with cursor() as cur:` — emprunte une connexion au pool, commit si OK,
    rollback sinon, restitue toujours la connexion."""

    def __enter__(self) -> "psycopg2.extensions.cursor":
        self._conn = _get_pool().getconn()
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            _get_pool().putconn(self._conn)
        return False


def zone_id_from_slug(slug: str) -> Optional[int]:
    with cursor() as cur:
        cur.execute("SELECT id FROM zones WHERE path ~ %s ORDER BY niveau DESC LIMIT 1",
                    (f"*.{slug}",))
        row = cur.fetchone()
        return int(row["id"]) if row else None


def list_zones() -> list[dict]:
    """Zones de niveau quartier avec slug, nom et centroïde."""
    with cursor() as cur:
        cur.execute("""
            SELECT id, nom, split_part(path::text, '.', -1) AS slug,
                   ST_Y(ST_Centroid(geom)) AS lat_center,
                   ST_X(ST_Centroid(geom)) AS lon_center
            FROM zones WHERE niveau = 3 ORDER BY nom
        """)
        return [dict(r) for r in cur.fetchall()]
