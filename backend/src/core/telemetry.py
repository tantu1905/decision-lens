"""Correlation ids, telemetry events and timings. Every event is one log line on ApplicationLogger and, when a
span is recording, attributes on it (Application Insights in logging_mode=azure)."""
import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Iterator, Mapping
from uuid import uuid4

from opentelemetry import trace

from src.core.utils import (
    APPLICATION_LOGGER_NAME,
    build_log_extra,
    format_log_attributes,
    sanitize_log_attributes,
)

logger = logging.getLogger(APPLICATION_LOGGER_NAME)
CORRELATION_ID_HEADER = "X-Correlation-Id"
_correlation_id_context: ContextVar[str | None] = ContextVar("workflow_correlation_id", default=None)


def get_correlation_id() -> str | None:
    return _correlation_id_context.get()


def ensure_correlation_id(correlation_id: str | None = None) -> str:
    value = (correlation_id or "").strip()
    if value:
        return value
    return get_correlation_id() or str(uuid4())


def set_correlation_id(correlation_id: str) -> Token[str | None]:
    return _correlation_id_context.set(correlation_id)


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id_context.reset(token)


def get_current_trace_metadata() -> dict[str, str]:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {}
    return {"trace_id": f"{span_context.trace_id:032x}", "span_id": f"{span_context.span_id:016x}"}


def emit_telemetry_event(event_name: str, *, level: int = logging.INFO, **properties: object) -> None:
    sanitized = sanitize_log_attributes(properties, {"correlation_id": ensure_correlation_id(get_correlation_id()),
                                                     **get_current_trace_metadata()})
    logger.log(level, "workflow_event=%s %s", event_name, format_log_attributes(sanitized),
               extra=build_log_extra(event_name, sanitized))
    _apply_span_attributes(event_name, sanitized)


def emit_telemetry_exception(event_name: str, error: Exception, **properties: object) -> None:
    sanitized = sanitize_log_attributes(properties, {"correlation_id": ensure_correlation_id(get_correlation_id()),
                                                     **get_current_trace_metadata()})
    logger.error("workflow_event=%s %s exception_type=%s", event_name, format_log_attributes(sanitized),
                 type(error).__name__, extra=build_log_extra(event_name, sanitized))
    _apply_span_attributes(event_name, {**sanitized, "exception_type": type(error).__name__})
    current_span = trace.get_current_span()
    if current_span.is_recording():
        current_span.set_attribute("error.type", type(error).__name__)


@contextmanager
def latency_tracker(operation: str, **properties: object) -> Iterator[None]:
    started_at = perf_counter()
    try:
        yield
    except Exception as exc:
        emit_telemetry_event("workflow.latency", operation=operation, duration_ms=_duration_ms(started_at),
                             outcome="error", exception_type=type(exc).__name__, **properties)
        raise
    emit_telemetry_event("workflow.latency", operation=operation, duration_ms=_duration_ms(started_at),
                         outcome="success", **properties)


def _duration_ms(started_at: float) -> int:
    return int(round((perf_counter() - started_at) * 1000))


def _apply_span_attributes(event_name: str, properties: Mapping[str, object]) -> None:
    current_span = trace.get_current_span()
    if not current_span.is_recording():
        return
    current_span.set_attribute("workflow.event", event_name)
    for key, value in properties.items():
        current_span.set_attribute(f"workflow.{key}", value if isinstance(value, (bool, int, float, str)) else str(value))
