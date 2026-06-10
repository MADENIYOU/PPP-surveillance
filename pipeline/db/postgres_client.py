"""Pool de connexions PostgreSQL et helpers communs aux workers.

Référence : pipeline/PIPELINE_SPEC.md §1.1 ("pool de connexions pour PostgreSQL
— `psycopg2.pool`") et §2.2 (`get_zone_for_sensor`, mise à jour `sensors.last_seen`).

`PostgresPool` est un wrapper mince autour de `psycopg2.pool.ThreadedConnectionPool`
(les workers tournent dans des threads — boucle MQTT + watchdog + flush périodique).
Les fonctions `get_zone_for_sensor`/`touch_sensor`/`mark_stale_sensors` sont
partagées par plusieurs étapes (ingestion §2, calibration §3, détection §4,
watchdog §2.4) — d'où leur place ici plutôt que dans `workers/ingestion.py`.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_DB", "dakar_pollution")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "dakar_admin")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

WATCHDOG_INACTIVE_AFTER_S = 10 * 60   # §2.4 : > 10 min → status = 'inactive'
WATCHDOG_DROPOUT_AFTER_S = 30 * 60    # §2.4 : > 30 min → point data_quality sensor_dropout


class PostgresPool:
    """Pool de connexions threadsafe (`ThreadedConnectionPool`).

    `cursor()` est un context manager qui emprunte une connexion au pool, la
    restitue à la sortie (commit implicite si pas d'exception, rollback sinon)
    — pattern standard pour éviter les fuites de connexions dans une boucle
    MQTT longue durée."""

    def __init__(self, minconn: int = 1, maxconn: int = 10):
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn, maxconn,
            host=POSTGRES_HOST, port=POSTGRES_PORT, dbname=POSTGRES_DB,
            user=POSTGRES_USER, password=POSTGRES_PASSWORD,
        )

    class _CursorCtx:
        def __init__(self, pool: "psycopg2.pool.ThreadedConnectionPool"):
            self._pool = pool
            self._conn = None

        def __enter__(self) -> "psycopg2.extensions.cursor":
            self._conn = self._pool.getconn()
            return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        def __exit__(self, exc_type, exc, tb):
            assert self._conn is not None
            try:
                if exc_type is None:
                    self._conn.commit()
                else:
                    self._conn.rollback()
            finally:
                self._pool.putconn(self._conn)
            return False

    def cursor(self) -> "PostgresPool._CursorCtx":
        return PostgresPool._CursorCtx(self._pool)

    def closeall(self) -> None:
        self._pool.closeall()


# ============================================================================
# Résolution zone — cache en mémoire (rafraîchi à la demande, TTL implicite
# via `invalidate`). Évite une requête PostgreSQL par message MQTT (~1/30s/
# capteur × N capteurs : volume trop faible pour justifier un cache distribué,
# mais une requête par message reste un gaspillage évitable).
# ============================================================================
class ZoneResolver:
    """Résout `sensor_id` (matériel, ex. `ESP32-DK-MEDINA-001`) → identifiant
    de zone à utiliser comme tag InfluxDB.

    Choix documenté : on retient le dernier label du `path` ltree de la zone
    (ex. `dakar.plateau.fann` → `fann`) comme slug — cohérent avec les
    `zone_id` courts (`medina`, `plateau`…) utilisés par `simulation/config/
    sensors.yaml`. Si le capteur est inconnu en base (pas encore enregistré —
    cf. tâche #8 seed des données), on retombe sur le `zone_id` brut du
    payload simulé (`sim_metadata` n'étant pas garanti, on utilise un slug
    dérivé du `sensor_id` matériel) plutôt que d'échouer l'ingestion."""

    def __init__(self, pool: PostgresPool):
        self._pool = pool
        self._lock = threading.Lock()
        self._cache: dict[str, str] = {}

    def resolve(self, sensor_id: str) -> str:
        with self._lock:
            cached = self._cache.get(sensor_id)
        if cached is not None:
            return cached

        slug = self._lookup(sensor_id) or _fallback_zone_slug(sensor_id)
        with self._lock:
            self._cache[sensor_id] = slug
        return slug

    def invalidate(self, sensor_id: Optional[str] = None) -> None:
        with self._lock:
            if sensor_id is None:
                self._cache.clear()
            else:
                self._cache.pop(sensor_id, None)

    def _lookup(self, sensor_id: str) -> Optional[str]:
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT z.path
                FROM sensors s
                JOIN zones z ON z.id = s.zone_id
                WHERE s.serial_number = %s
                """,
                (sensor_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        path = str(row["path"])
        return path.split(".")[-1]


def _fallback_zone_slug(sensor_id: str) -> str:
    """`ESP32-DK-MEDINA-001` → `medina` (cohérent avec `simulation/config/
    sensors.yaml`, utilisé tant que le capteur n'est pas encore en base)."""
    parts = sensor_id.split("-")
    if len(parts) >= 4:
        return parts[2].lower()
    return "unknown"


# ============================================================================
# sensors.last_seen / status — §2.2 point 8, §2.4 watchdog
# ============================================================================
def touch_sensor(pool: PostgresPool, sensor_id: str, last_seen: datetime,
                 battery_pct: Optional[int], rssi_dbm: Optional[int]) -> None:
    """`UPDATE sensors SET last_seen=…, status='active', metadata ← battery/rssi`
    (§2.2 point 8 — `sensor_update_queue`). Réactive un capteur marqué `inactive`
    dès qu'il republie (le watchdog l'avait potentiellement désactivé)."""
    with pool.cursor() as cur:
        cur.execute(
            """
            UPDATE sensors
            SET last_seen = %(last_seen)s,
                status = 'active',
                metadata = metadata || %(extra)s::jsonb,
                updated_at = now()
            WHERE serial_number = %(sensor_id)s
            """,
            {
                "last_seen": last_seen,
                "sensor_id": sensor_id,
                "extra": psycopg2.extras.Json({"battery_pct": battery_pct, "rssi_dbm": rssi_dbm}),
            },
        )


def mark_inactive_sensors(pool: PostgresPool, now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Watchdog §2.4 — `now() - last_seen > 10 min` → `status = 'inactive'`.

    Retourne les capteurs fraîchement marqués inactifs (pour journalisation/
    métriques côté worker)."""
    with pool.cursor() as cur:
        cur.execute(
            """
            UPDATE sensors
            SET status = 'inactive', updated_at = now()
            WHERE status = 'active'
              AND last_seen IS NOT NULL
              AND now() - last_seen > (%s * interval '1 second')
            RETURNING id, serial_number, zone_id, last_seen
            """,
            (WATCHDOG_INACTIVE_AFTER_S,),
        )
        return list(cur.fetchall())


def get_dropout_sensors(pool: PostgresPool) -> list[dict[str, Any]]:
    """Watchdog §2.4 — capteurs muets depuis > 30 min (déclenche un point
    `data_quality` `type=sensor_dropout` côté InfluxDB, écrit par l'appelant)."""
    with pool.cursor() as cur:
        cur.execute(
            """
            SELECT id, serial_number, zone_id, last_seen
            FROM sensors
            WHERE last_seen IS NOT NULL
              AND now() - last_seen > (%s * interval '1 second')
            """,
            (WATCHDOG_DROPOUT_AFTER_S,),
        )
        return list(cur.fetchall())
