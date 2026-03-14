# -*- coding: utf-8 -*-
"""
ArcMind — OpenTelemetry Tracing Layer

P2-2: 輕量追蹤模組，在關鍵路徑加入 trace/span。
- 環境變數 `OTEL_ENABLED=true` 啟用
- 預設關閉（no-op fallback）
- 未安裝 opentelemetry 時自動降級

Usage:
    from runtime.tracing import get_tracer
    tracer = get_tracer("arcmind.main_loop")
    with tracer.start_as_current_span("process_request") as span:
        span.set_attribute("command", command[:100])
        ...
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("arcmind.tracing")

_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() in ("true", "1", "yes")
_initialized = False
_tracer_provider = None


class _NoOpSpan:
    """No-op span for when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *args, **kwargs) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: dict = None) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTracer:
    """No-op tracer for when tracing is disabled."""

    def start_as_current_span(self, name: str, **kwargs):
        return _NoOpSpan()

    @contextmanager
    def start_span(self, name: str, **kwargs):
        yield _NoOpSpan()


_noop_tracer = _NoOpTracer()


def init_tracing() -> bool:
    """
    Initialize OpenTelemetry tracing if enabled.
    Returns True if tracing was successfully initialized.
    """
    global _initialized, _tracer_provider

    if _initialized:
        return _tracer_provider is not None

    _initialized = True

    if not _ENABLED:
        logger.debug("[Tracing] Disabled (set OTEL_ENABLED=true to enable)")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource

        # Try OTLP exporter first, fall back to console
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(
                endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
            )
            logger.info("[Tracing] Using OTLP exporter")
        except ImportError:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            exporter = ConsoleSpanExporter()
            logger.info("[Tracing] Using Console exporter (install opentelemetry-exporter-otlp for OTLP)")

        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({
            "service.name": "arcmind",
            "service.version": os.getenv("ARCMIND_VERSION", "0.9.4"),
        })

        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer_provider = provider

        logger.info("[Tracing] OpenTelemetry initialized successfully")
        return True

    except ImportError:
        logger.info("[Tracing] opentelemetry not installed — using no-op tracer")
        return False
    except Exception as e:
        logger.warning("[Tracing] Initialization failed: %s — using no-op tracer", e)
        return False


def get_tracer(name: str = "arcmind") -> Any:
    """
    Get a tracer instance.
    Returns OpenTelemetry tracer if available, otherwise no-op tracer.
    """
    if not _initialized:
        init_tracing()

    if _tracer_provider is not None:
        try:
            from opentelemetry import trace
            return trace.get_tracer(name)
        except Exception:
            pass

    return _noop_tracer


def trace_function(span_name: str = None):
    """
    Decorator to add tracing to a function.

    Usage:
        @trace_function("my_operation")
        def do_something():
            ...
    """
    def decorator(func):
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = span_name or f"{func.__module__}.{func.__qualname__}"
            tracer = get_tracer(func.__module__ or "arcmind")
            with tracer.start_as_current_span(name) as span:
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    raise

        return wrapper
    return decorator
