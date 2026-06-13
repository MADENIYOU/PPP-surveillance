#!/usr/bin/env python3
"""Worker d'ingestion MQTT → InfluxDB — Étape 1 du pipeline.

Référence : pipeline/PIPELINE_SPEC.md §2.

Pattern event-driven (callback MQTT `on_message`) : valide chaque message reçu
sur `dakar/sensors/+/data` (JSON → Pydantic), déduplique par `seq`, construit un
point `air_quality_raw` et l'écrit par lot dans InfluxDB (`bucket_raw`). Les
messages invalides partent en dead letter ; `sensors.last_seen` est mis à jour
de façon asynchrone (file + thread dédié, §2.2 point 8) pour ne jamais bloquer
le callback MQTT sur une requête PostgreSQL.

Conçu sur le même principe d'injection de dépendances que les modules de
`simulation/` (`clock_fn`, etc.) pour rester testable sans broker/DB réels.
"""
from __future__ import annotations

import functools
import json
import os
import queue
import random
import signal
import structlog
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import paho.mqtt.client as mqtt
from pydantic import ValidationError

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

from circuit_breaker import mqtt_breaker  # noqa: E402

from db.influxdb_client import (  # noqa: E402
    InfluxBatchWriter,
    build_raw_point,
    get_influxdb_client,
)
from db.postgres_client import PostgresPool, ZoneResolver, mark_inactive_sensors, touch_sensor  # noqa: E402
from models.pydantic_schemas import SensorPayload  # noqa: E402

# Prometheus metrics (exposed on port 8001 via a simple HTTP server thread)
try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    HAS_PROMETHEUS = True
    PROM_MESSAGES = Counter("ingestion_messages_total", "Total messages received")
    PROM_DUPLICATES = Counter("ingestion_duplicate_total", "Duplicate messages discarded")
    PROM_VALIDATION_ERRORS = Counter("ingestion_validation_errors_total", "Pydantic validation errors")
    PROM_JSON_PARSE_ERRORS = Counter("ingestion_json_parse_errors_total", "JSON parse errors")
    PROM_DEAD_LETTER = Counter("ingestion_dead_letter_total", "Dead letter records written")
    PROM_POINTS_WRITTEN = Counter("ingestion_points_written_total", "InfluxDB points flushed")
    PROM_BATCHES = Counter("ingestion_batches_total", "InfluxDB batch flushes")
except ImportError:
    HAS_PROMETHEUS = False

LOGGER = structlog.get_logger("ingestion")

MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC = "dakar/sensors/+/data"
MQTT_QOS = 1

BATCH_SIZE = 100      # §2.1 : écriture batch toutes les 100 mesures
BATCH_TIMEOUT_S = 5.0  # … ou toutes les 5 secondes (le premier qui arrive)

WATCHDOG_INTERVAL_S = 5 * 60   # §2.4 : vérification toutes les 5 min
DEAD_LETTER_RATE_WINDOW_S = 5 * 60
DEAD_LETTER_RATE_THRESHOLD = 0.05  # §2.3 : alerte si > 5% de dead letters / 5 min

DEFAULT_DEAD_LETTER_FILE = PIPELINE_ROOT / "dead_letter" / "ingestion_errors.jsonl"

MAX_RETRIES = 10
BASE_DELAY_S = 5
MAX_DELAY_S = 300


# ============================================================================
# Dead Letter Queue — §2.3
# ============================================================================
class DeadLetterWriter:
    """Append-only JSONL, un enregistrement par message rejeté (§2.3 format)."""

    def __init__(self, path: Path):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, raw_payload: bytes | dict, error: str, details: str, mqtt_topic: str,
              now: Optional[datetime] = None) -> None:
        now = now or datetime.now(timezone.utc)
        if isinstance(raw_payload, (bytes, bytearray)):
            try:
                raw_repr = raw_payload.decode("utf-8", errors="replace")
            except Exception:
                raw_repr = repr(raw_payload)
        else:
            raw_repr = json.dumps(raw_payload, ensure_ascii=False)

        record = {
            "timestamp": _iso(now),
            "error": error,
            "details": details,
            "raw_payload": raw_repr,
            "mqtt_topic": mqtt_topic,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


# ============================================================================
# Circuit breaker pour appels externes (MQTT, InfluxDB, PostgreSQL)
# ============================================================================
class CircuitBreaker:
    """Simple circuit breaker — évite les appels répétés à un service défaillant."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout_s: float = 60.0):
        self._failure_threshold = failure_threshold
        self._recovery_timeout_s = recovery_timeout_s
        self._failures = 0
        self._last_failure = 0.0
        self._state = "closed"  # closed → open → half-open → closed

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if self._state == "open":
                if time.monotonic() - self._last_failure > self._recovery_timeout_s:
                    self._state = "half-open"
                else:
                    raise RuntimeError(f"CircuitBreaker open for {func.__name__}")
            try:
                result = func(*args, **kwargs)
                if self._state == "half-open":
                    self._state = "closed"
                    self._failures = 0
                return result
            except Exception:
                self._failures += 1
                self._last_failure = time.monotonic()
                if self._failures >= self._failure_threshold:
                    self._state = "open"
                raise
        return wrapper


# ============================================================================
# Worker — état + callbacks MQTT
# ============================================================================
@dataclass
class IngestionWorker:
    pg_pool: PostgresPool
    zone_resolver: ZoneResolver
    writer: InfluxBatchWriter
    dead_letter: DeadLetterWriter
    broker: str = MQTT_BROKER
    port: int = MQTT_PORT
    batch_size: int = BATCH_SIZE
    batch_timeout_s: float = BATCH_TIMEOUT_S
    watchdog_interval_s: float = WATCHDOG_INTERVAL_S
    clock_fn: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    sleep_fn: Callable[[float], None] = field(default=time.sleep)

    # Compteurs exposés par `/metrics` en théorie (§1.1) — ici simples compteurs
    # en mémoire, journalisés périodiquement (pas de serveur Prometheus dans
    # cette démo, hors-périmètre de la tâche I4.1).
    messages_total: int = field(default=0, init=False)
    duplicate_total: int = field(default=0, init=False)
    validation_error_total: int = field(default=0, init=False)
    json_parse_error_total: int = field(default=0, init=False)
    dead_letter_total: int = field(default=0, init=False)
    points_written_total: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._seq_cache: dict[str, int] = {}
        self._seq_lock = threading.Lock()
        self._sensor_update_queue: "queue.Queue[dict]" = queue.Queue()
        self._stop_event = threading.Event()
        self._dead_letter_window: list[float] = []
        self._dl_window_lock = threading.Lock()
        self._client = mqtt.Client(client_id=f"ingestion-worker-{os.getpid()}")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    # -- MQTT callbacks ---------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(MQTT_TOPIC, qos=MQTT_QOS)
            LOGGER.info("mqtt_connected broker=%s topic=%s", self.broker, MQTT_TOPIC)
        else:
            LOGGER.error("mqtt_connect_failed rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0 and not self._stop_event.is_set():
            LOGGER.warning("mqtt_unexpected_disconnect rc=%s — reconnexion automatique", rc)

    def _on_message(self, client, userdata, msg) -> None:
        t_received = time.time()

        # 1. Parse JSON (§2.2 point 1)
        try:
            raw = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._reject(msg.payload, "json_parse_error", str(exc), msg.topic)
            self.json_parse_error_total += 1
            if HAS_PROMETHEUS:
                PROM_JSON_PARSE_ERRORS.inc()
            return

        # 2. Validation Pydantic (§2.2 point 2)
        try:
            validated = SensorPayload(**raw)
        except ValidationError as exc:
            self._reject(raw, "validation_error", str(exc), msg.topic)
            self.validation_error_total += 1
            if HAS_PROMETHEUS:
                PROM_VALIDATION_ERRORS.inc()
            return

        # 3. Déduplication par seq (§2.2 point 3)
        sensor_id = validated.sensor_id
        seq = validated.seq
        with self._seq_lock:
            last_seq = self._seq_cache.get(sensor_id)
            if last_seq is not None and last_seq >= seq:
                LOGGER.debug("duplicate_seq sensor_id=%s seq=%s", sensor_id, seq)
                self.duplicate_total += 1
                if HAS_PROMETHEUS:
                    PROM_DUPLICATES.inc()
                return
            self._seq_cache[sensor_id] = seq

        # 4-5. Fraîcheur + construction du point (§2.2 points 4-5)
        zone_id = self.zone_resolver.resolve(sensor_id)
        point = build_raw_point(validated, zone_id, now=self.clock_fn())

        # 6-7. Ajout au buffer batch, flush si plein (§2.2 points 6-7)
        size = self.writer.add(point)
        if size >= self.batch_size:
            self._flush()

        # 8. Mise à jour asynchrone sensors.last_seen (§2.2 point 8)
        self._sensor_update_queue.put({
            "sensor_id": sensor_id,
            "last_seen": validated.timestamp,
            "battery_pct": validated.battery.level_pct,
            "rssi": validated.network.rssi_dbm,
        })

        # 9. Métriques (§2.2 point 9)
        latency_ms = (time.time() - t_received) * 1000
        self.messages_total += 1
        inc_counter("dakar_messages_ingested_total", 1)
        if HAS_PROMETHEUS:
            PROM_MESSAGES.inc()
        LOGGER.debug("message_ingested sensor_id=%s seq=%s latency_ms=%.1f", sensor_id, seq, latency_ms)

    def _reject(self, raw_payload, error: str, details: str, topic: str) -> None:
        self.dead_letter.write(raw_payload, error, details, topic, now=self.clock_fn())
        self.dead_letter_total += 1
        if HAS_PROMETHEUS:
            PROM_DEAD_LETTER.inc()
        self._record_dead_letter()

    def _record_dead_letter(self) -> None:
        """Suit le taux de dead letters sur une fenêtre glissante de 5 min et
        journalise une alerte si le seuil de 5% est dépassé (§2.3)."""
        now = time.time()
        with self._dl_window_lock:
            self._dead_letter_window.append(now)
            cutoff = now - DEAD_LETTER_RATE_WINDOW_S
            self._dead_letter_window = [t for t in self._dead_letter_window if t >= cutoff]
            n_dead = len(self._dead_letter_window)
        n_total = max(self.messages_total + n_dead, 1)
        rate = n_dead / n_total
        if rate > DEAD_LETTER_RATE_THRESHOLD and n_dead >= 5:
            LOGGER.warning("dead_letter_rate_alert rate=%.1f%% window_s=%d n_dead=%d",
                           rate * 100, DEAD_LETTER_RATE_WINDOW_S, n_dead)

    def _flush(self) -> None:
        n = self.writer.flush()
        if n:
            self.points_written_total += n
            LOGGER.info("influx_batch_flush n_points=%d total=%d", n, self.points_written_total)

    # -- Threads de fond ---------------------------------------------------
    def _sensor_update_loop(self) -> None:
        """Consomme `sensor_update_queue` (§2.2 point 8) — découple le callback
        MQTT (qui doit rester rapide) de l'écriture PostgreSQL."""
        while not self._stop_event.is_set():
            try:
                update = self._sensor_update_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                touch_sensor(self.pg_pool, update["sensor_id"], update["last_seen"],
                             update["battery_pct"], update["rssi"])
            except Exception:
                LOGGER.exception("sensor_update_failed sensor_id=%s", update["sensor_id"])
            finally:
                self._sensor_update_queue.task_done()

    def _flush_timer_loop(self) -> None:
        """Flush périodique (§2.1 `BATCH_TIMEOUT`) — garantit qu'un buffer
        partiellement rempli n'attend pas indéfiniment le seuil `BATCH_SIZE`."""
        while not self._stop_event.wait(self.batch_timeout_s):
            if len(self.writer):
                self._flush()

    def _watchdog_loop(self) -> None:
        """Watchdog capteurs (§2.4) — toutes les `watchdog_interval_s`."""
        while not self._stop_event.wait(self.watchdog_interval_s):
            try:
                inactive = mark_inactive_sensors(self.pg_pool, now=self.clock_fn())
                for row in inactive:
                    LOGGER.warning("sensor_marked_inactive sensor_id=%s last_seen=%s",
                                   row["serial_number"], row["last_seen"])
            except Exception:
                LOGGER.exception("watchdog_cycle_failed")

    # -- Connexion avec retry/backoff exponentiel (§10.1) -------------------
    def _connect_with_retry(self) -> None:
        for attempt in range(MAX_RETRIES):
            try:
                with mqtt_breaker:
                    self._client.connect(self.broker, self.port, keepalive=60)
                return
            except (ConnectionError, OSError) as exc:
                delay = min(BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY_S)
                LOGGER.warning("connection_retry attempt=%d delay=%.1f error=%s", attempt, delay, exc)
                self.sleep_fn(delay)
        raise RuntimeError(f"Échec de connexion MQTT après {MAX_RETRIES} tentatives")

    # -- Cycle de vie -------------------------------------------------------
    def run(self) -> None:
        self._connect_with_retry()
        self._client.loop_start()

        threads = [
            threading.Thread(target=self._sensor_update_loop, name="sensor-update", daemon=True),
            threading.Thread(target=self._flush_timer_loop, name="flush-timer", daemon=True),
            threading.Thread(target=self._watchdog_loop, name="watchdog", daemon=True),
        ]
        for t in threads:
            t.start()

        # §10.3 graceful shutdown — l'enregistrement échoue si `run()` n'est
        # pas appelé depuis le thread principal (ex. tests, embarquement dans
        # un orchestrateur) : on continue alors sans intercepter les signaux,
        # `stop()` restant utilisable directement par l'appelant.
        try:
            signal.signal(signal.SIGTERM, lambda *_: self.stop())
            signal.signal(signal.SIGINT, lambda *_: self.stop())
        except ValueError:
            LOGGER.debug("signal_handler_not_registered — run() hors thread principal")

        LOGGER.info("ingestion_worker_started broker=%s:%s", self.broker, self.port)
        self._stop_event.wait()

        LOGGER.info("ingestion_worker_stopping — vidage du buffer et fermeture")
        self._client.loop_stop()
        self._client.disconnect()
        self._flush()
        for t in threads:
            t.join(timeout=5.0)

    def stop(self) -> None:
        self._stop_event.set()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_worker(dead_letter_path: Path = DEFAULT_DEAD_LETTER_FILE) -> IngestionWorker:
    pg_pool = PostgresPool()
    zone_resolver = ZoneResolver(pg_pool)
    influx_client = get_influxdb_client()
    writer = InfluxBatchWriter(influx_client)
    dead_letter = DeadLetterWriter(dead_letter_path)
    return IngestionWorker(pg_pool=pg_pool, zone_resolver=zone_resolver, writer=writer, dead_letter=dead_letter)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    from metrics import start_metrics_server
    metrics_server = start_metrics_server()

    worker = build_worker()
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()
