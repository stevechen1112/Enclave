"""Phase 8 — OpenTelemetry hooks (optional when OTEL_ENABLED=true)."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_tracer = None
_meter = None


def init_telemetry(service_name: str = "enclave") -> None:
    global _tracer, _meter
    if os.getenv("OTEL_ENABLED", "").lower() != "true":
        return
    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": service_name})
        trace.set_tracer_provider(TracerProvider(resource=resource))
        metrics.set_meter_provider(MeterProvider(resource=resource))
        _tracer = trace.get_tracer(service_name)
        _meter = metrics.get_meter(service_name)
        logger.info("OpenTelemetry initialized for %s", service_name)
    except ImportError:
        logger.warning("OpenTelemetry packages not installed")


@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
        yield span


def record_metric(name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
    if _meter is None:
        return
    counter = _meter.create_counter(name)
    counter.add(value, labels or {})
