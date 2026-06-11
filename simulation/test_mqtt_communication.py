#!/usr/bin/env python3
"""Tests de communication MQTT pour la simulation de surveillance pollution Dakar.

Vérifie la connectivité au broker et la publication/souscription sur les
5 topics requis par la spec :

  - dakar/sensors/{id}/data       (QoS 1)
  - dakar/sensors/{id}/status     (QoS 1, retain)
  - dakar/sensors/{id}/alert      (QoS 2)
  - dakar/gateway/{id}/heartbeat  (QoS 0)
  - dakar/system/broadcast        (QoS 1)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
TEST_SENSOR_ID = "ESP32-DK-TEST-001"
TEST_GATEWAY_ID = "GW-DK-TEST-001"
TIMEOUT = 5  # secondes d'attente max pour la réception d'un message

_received: dict[str, str | None] = {}


def _on_message(client, userdata, msg):
    _received[msg.topic] = msg.payload.decode()


def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[OK] Connecté au broker MQTT {BROKER}:{PORT}")
    else:
        print(f"[FAIL] Échec connexion MQTT, rc={rc}")


def test_broker_connectivity() -> bool:
    """Tente une connexion au broker MQTT et retourne True si réussie."""
    client = mqtt.Client(client_id="mqtt_test_connectivity", clean_session=True)
    client.on_connect = _on_connect

    connected = False

    def _flag_connect(client, userdata, flags, rc):
        nonlocal connected
        connected = (rc == 0)

    client.on_connect = _flag_connect
    try:
        client.connect(BROKER, PORT, keepalive=10)
        client.loop_start()
        t0 = time.monotonic()
        while not connected and (time.monotonic() - t0) < TIMEOUT:
            time.sleep(0.1)
        client.loop_stop()
        client.disconnect()
    except Exception as exc:
        print(f"[FAIL] Exception connexion : {exc}")
        return False

    if connected:
        print("[OK] Connectivité broker MQTT vérifiée")
    else:
        print("[FAIL] Impossible de se connecter au broker MQTT")
    return connected


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def test_topic_publish_subscribe() -> bool:
    """Publie un message de test sur chacun des 5 topics et vérifie la réception."""
    _received.clear()
    client = mqtt.Client(client_id="mqtt_test_topics", clean_session=True)
    client.on_message = _on_message

    try:
        client.connect(BROKER, PORT, keepalive=10)
    except Exception as exc:
        print(f"[FAIL] Connexion échouée : {exc}")
        return False

    now = _iso(datetime.now(timezone.utc))

    topics = [
        ("dakar/sensors/{id}/data",       f"dakar/sensors/{TEST_SENSOR_ID}/data",       1,
         json.dumps({"sensor_id": TEST_SENSOR_ID, "test": True, "time": now, "sim": True})),
        ("dakar/sensors/{id}/status",     f"dakar/sensors/{TEST_SENSOR_ID}/status",     1,
         json.dumps({"status": "online", "sim": True, "timestamp": now})),
        ("dakar/sensors/{id}/alert",      f"dakar/sensors/{TEST_SENSOR_ID}/alert",      2,
         json.dumps({"sensor_id": TEST_SENSOR_ID, "type": "TEST", "time": now, "sim": True})),
        ("dakar/gateway/{id}/heartbeat",  f"dakar/gateway/{TEST_GATEWAY_ID}/heartbeat", 0,
         json.dumps({"gateway_id": TEST_GATEWAY_ID, "time": now, "status": "online", "sim": True})),
        ("dakar/system/broadcast",        "dakar/system/broadcast",                      1,
         json.dumps({"time": now, "run_id": "test", "n_sensors": 1, "anomalies_active": 0})),
    ]

    for topic_tpl, topic, qos, payload in topics:
        _received.pop(topic, None)
        client.subscribe(topic, qos=qos)

    client.loop_start()
    time.sleep(0.3)

    for topic_tpl, topic, qos, payload in topics:
        info = client.publish(topic, payload, qos=qos)
        print(f"  → Publié sur {topic_tpl:<38} (QoS {qos}): rc={info.rc}")

    time.sleep(1.0)
    client.loop_stop()
    client.disconnect()

    all_ok = True
    print()
    for topic_tpl, topic, qos, payload in topics:
        received = _received.get(topic)
        if received is not None:
            try:
                data = json.loads(received)
            except json.JSONDecodeError:
                data = received
            print(f"[OK]  Reçu  sur {topic_tpl:<38} : {json.dumps(data)[:80]}")
        else:
            print(f"[FAIL] Rien reçu sur {topic_tpl}")
            all_ok = False

    return all_ok


def main() -> int:
    print("=== Test connectivité broker MQTT ===")
    if not test_broker_connectivity():
        print("\nLe broker MQTT n'est pas accessible. Abandon des tests.")
        return 1

    print("\n=== Test publication/souscription sur les 5 topics ===")
    if not test_topic_publish_subscribe():
        print("\nCertains topics n'ont pas été reçus correctement.")
        return 1

    print("\nTous les tests MQTT sont passés avec succès.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
