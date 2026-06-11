#!/usr/bin/env python3
"""Circuit breaker pattern for external API calls (PIPELINE_SPEC.md §10.2).

Usage:
    cb = CircuitBreaker("weather_api", failure_threshold=5, recovery_timeout=60)
    
    @cb
    def call_weather_api():
        ...
    
    with cb:
        result = call_external_service()
"""
from __future__ import annotations

import functools
import logging
import threading
import time
from enum import Enum

LOGGER = logging.getLogger("circuit_breaker")

class CircuitState(Enum):
    CLOSED = "closed"              # Normal operation
    OPEN = "open"                  # Failing, reject immediately
    HALF_OPEN = "half_open"        # Testing recovery

class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._success_count = 0

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    LOGGER.info("circuit_breaker_half_open name=%s", self.name)
            return self._state

    def _on_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= 2:
                    self._state = CircuitState.CLOSED
                    LOGGER.info("circuit_breaker_closed name=%s", self.name)

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                LOGGER.warning("circuit_breaker_opened name=%s failures=%d", self.name, self._failure_count)

    def __enter__(self) -> CircuitBreaker:
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(f"Circuit {self.name} is OPEN")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._on_success()
        else:
            self._on_failure()
        return False  # Don't suppress the exception

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)
        return wrapper

class CircuitBreakerOpenError(Exception):
    pass

# Pre-configured breakers for known external dependencies
weather_breaker = CircuitBreaker("external_weather", failure_threshold=5, recovery_timeout=60)
nlp_breaker = CircuitBreaker("nlp_spacy", failure_threshold=3, recovery_timeout=120)
mqtt_breaker = CircuitBreaker("mqtt_broker", failure_threshold=5, recovery_timeout=30)
