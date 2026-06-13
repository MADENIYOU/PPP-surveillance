#!/usr/bin/env python3
"""Prometheus metrics endpoint for pipeline workers.
Exposes gauges and counters via HTTP GET /metrics on port 9090.
"""
from __future__ import annotations

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

_metrics = {}
_lock = threading.Lock()


def set_gauge(name: str, value: float, labels: dict = None):
    with _lock:
        key = name if not labels else f"{name}{json.dumps(labels, sort_keys=True)}"
        _metrics[key] = (name, float(value), labels or {})


def inc_counter(name: str, amount: float = 1, labels: dict = None):
    with _lock:
        key = name if not labels else f"{name}{json.dumps(labels, sort_keys=True)}"
        if key in _metrics:
            _, old_val, old_labels = _metrics[key]
            _metrics[key] = (name, old_val + amount, old_labels)
        else:
            _metrics[key] = (name, float(amount), labels or {})


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            with _lock:
                for name, value, labels in _metrics.values():
                    label_str = ""
                    if labels:
                        label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
                    self.wfile.write(f"{name}{label_str} {value}\n".encode())
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()


def start_metrics_server(port: int = 9090):
    """Démarre le serveur de métriques. Si le port est déjà pris (autre worker),
       loggue un avertissement et continue sans planter."""
    import logging
    logger = logging.getLogger(__name__)
    try:
        server = HTTPServer(("0.0.0.0", port), MetricsHandler)
    except OSError:
        logger.warning("Metrics server port %d already in use — skipping (another worker handles it)", port)
        return None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
