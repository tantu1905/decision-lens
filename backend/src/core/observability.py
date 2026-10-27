"""Logging and tracing set-up. logging_mode=console: log lines on the console. logging_mode=azure: logs and
traces go to Application Insights (Azure Monitor OpenTelemetry), with the Microsoft Agent Framework's own
agent and model spans; agent_telemetry_mode=verbose also records prompts and answers (synthetic data only)."""
import logging
from threading import Lock
from typing import Any

from agent_framework.observability import enable_instrumentation
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk.resources import Resource

from src.core.settings import Settings, settings
from src.core.telemetry import get_correlation_id, get_current_trace_metadata
from src.core.utils import APPLICATION_LOGGER_NAME

SERVICE_NAME = "decision-lens-backend"
_SETUP_LOCK = Lock()
_is_configured = False


class TelemetryContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        correlation_id = get_correlation_id()
        if correlation_id and getattr(record, "correlation_id", None) is None:
            record.correlation_id = correlation_id
        for key, value in get_current_trace_metadata().items():
            if getattr(record, key, None) is None:
                setattr(record, key, value)
        return True


def setup_observability(config: Settings = settings) -> None:
    global _is_configured
    with _SETUP_LOCK:
        if _is_configured:
            return
        _configure_python_logging(config.logging_mode, config.agent_telemetry_mode)
        if config.logging_mode == "azure":
            _configure_azure_monitor(config)
            enable_instrumentation(enable_sensitive_data=config.agent_telemetry_mode == "verbose")
        _is_configured = True
        logging.getLogger(APPLICATION_LOGGER_NAME).info(
            "observability_configured mode=%s agent_telemetry_mode=%s service=%s environment=%s",
            config.logging_mode, config.agent_telemetry_mode, SERVICE_NAME, config.deployment_environment)


def shutdown_observability() -> None:
    tracer_provider = trace.get_tracer_provider()
    _call_provider_method(tracer_provider, "force_flush")
    _call_provider_method(get_logger_provider(), "force_flush")
    _call_provider_method(get_logger_provider(), "shutdown")
    _call_provider_method(tracer_provider, "shutdown")


def _configure_python_logging(mode: str, agent_telemetry_mode: str) -> None:
    app_logger = logging.getLogger(APPLICATION_LOGGER_NAME)
    app_logger.setLevel(logging.DEBUG if mode == "console" or agent_telemetry_mode == "verbose" else logging.INFO)
    app_logger.addFilter(TelemetryContextFilter())
    if mode == "console" and not any(getattr(h, "_decision_lens_console_handler", False) for h in app_logger.handlers):
        handler = logging.StreamHandler()
        handler._decision_lens_console_handler = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        app_logger.addHandler(handler)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("azure.monitor.opentelemetry.exporter.export").setLevel(logging.WARNING)


def _configure_azure_monitor(config: Settings) -> None:
    if not config.app_insights_connection_string:
        raise RuntimeError("APPLICATIONINSIGHTS_CONNECTION_STRING is required when logging_mode=azure.")
    resource = Resource.create({"service.name": SERVICE_NAME, "service.version": config.service_version,
                                "deployment.environment.name": config.deployment_environment})
    configure_azure_monitor(connection_string=config.app_insights_connection_string, resource=resource,
                            sampling_ratio=config.telemetry_sampling_ratio, logger_name=APPLICATION_LOGGER_NAME,
                            enable_live_metrics=False)


def _call_provider_method(provider: Any, method_name: str) -> None:
    method = getattr(provider, method_name, None)
    if callable(method):
        try:
            method()
        except Exception:
            logging.getLogger(APPLICATION_LOGGER_NAME).exception(
                "telemetry_provider_%s_failed provider=%s", method_name, type(provider).__name__)
