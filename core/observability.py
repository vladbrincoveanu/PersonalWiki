from __future__ import annotations

import copy
import hashlib
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

import sentry_sdk
from opentelemetry import metrics, trace
from opentelemetry.metrics import Observation
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import Span, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanProcessor,
)
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    Sampler,
    TraceIdRatioBased,
)
from opentelemetry.trace import Status, StatusCode
from sentry_sdk.integrations.otlp import OTLPIntegration

from config import TelemetrySettings, get_telemetry_settings


_logger = logging.getLogger(__name__)
_TRACER_NAME = "personalwiki"
_METER_NAME = "personalwiki"
_DEFAULT_SAMPLE_RATIO = 0.1
_MAX_ATTRIBUTE_LENGTH = 128
_SAFE_RESOURCE_KEYS = {"deployment.environment", "service.version"}
_SAFE_SPAN_KEYS = {
    "error.type",
    "http.route",
    "http.request.method",
    "http.response.status_code",
    "http.method",
    "http.status_code",
    "server.address",
    "server.port",
    "net.peer.name",
    "pipeline.source_type",
    "pipeline.trigger",
    "pipeline.outcome",
    "discovery.source",
    "discovery.outcome",
    "vault.outcome",
    "job.id",
    "source_hash",
    "stage",
    "operation",
    "discovery",
}
_PIPELINE_STAGES = {
    "extract",
    "quality_gate",
    "embed",
    "vector_search",
    "enrich",
    "entity_status",
    "gap_detection",
    "vault_write",
    "vector_upsert",
}
_DISCOVERY_SOURCES = {"arxiv", "hn", "desprebursa", "sitemap", "other"}
_VECTOR_OPERATIONS = {
    "embed",
    "search",
    "hybrid_search",
    "upsert",
    "entity_search",
    "entity_upsert",
}

_runtime: ObservabilityRuntime | None = None
_runtime_lock = threading.RLock()
_requests_instrumented = False
_urllib_instrumented = False


def _bounded(value: object) -> str:
    return str(value)[:_MAX_ATTRIBUTE_LENGTH]


def stable_source_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _normalise_host(value: object) -> str:
    host = str(value).strip().lower()
    if len(host) > _MAX_ATTRIBUTE_LENGTH:
        return stable_source_hash(host)
    return host


def _safe_span_attributes(attributes: Mapping[str, object] | None) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in (attributes or {}).items():
        if key not in _SAFE_SPAN_KEYS or value is None:
            continue
        if key in {"server.address", "net.peer.name"}:
            safe[key] = _normalise_host(value)
        elif isinstance(value, (bool, int, float)):
            safe[key] = value
        else:
            safe[key] = _bounded(value)
    return safe


class RedactingSpanProcessor(SpanProcessor):
    def on_start(self, span: Span, parent_context: object | None = None) -> None:
        return None

    def on_end(self, span: Any) -> None:
        attributes = getattr(span, "_attributes", None)
        if attributes is not None:
            immutable = getattr(attributes, "_immutable", None)
            attributes._immutable = False
            try:
                for key in list(attributes):
                    if key not in _SAFE_SPAN_KEYS:
                        attributes.pop(key, None)
                    elif key in {"server.address", "net.peer.name"}:
                        attributes[key] = _normalise_host(attributes[key])
                    elif isinstance(attributes[key], str):
                        attributes[key] = _bounded(attributes[key])
            finally:
                if immutable is not None:
                    attributes._immutable = immutable

        for event in getattr(span, "_events", ()):
            if event.name != "exception":
                continue
            event_attributes = getattr(event, "_attributes", None)
            if event_attributes is None:
                continue
            immutable = getattr(event_attributes, "_immutable", None)
            event_attributes._immutable = False
            try:
                exception_type = event_attributes.get("exception.type")
                event_attributes.clear()
                if exception_type:
                    event_attributes["exception.type"] = _bounded(exception_type)
            finally:
                if immutable is not None:
                    event_attributes._immutable = immutable

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def redact_sentry_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(event)
    request = redacted.get("request")
    if isinstance(request, dict):
        method = request.get("method")
        redacted["request"] = {"method": method} if method else {}
    for key in (
        "user",
        "breadcrumbs",
        "extra",
        "contexts",
        "contexts.runtime",
        "modules",
    ):
        redacted.pop(key, None)
    exception = redacted.get("exception")
    if isinstance(exception, dict):
        values = exception.get("values")
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    exception_type = value.get("type")
                    value.clear()
                    if exception_type:
                        value["type"] = _bounded(exception_type)
    return redacted


def redact_sentry_transaction(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    return redact_sentry_event(event, hint)


def _parse_resource_attributes(raw: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in raw.split(","):
        key, separator, value = item.partition("=")
        if separator and key.strip() in _SAFE_RESOURCE_KEYS and value.strip():
            parsed[key.strip()] = _bounded(value.strip())
    return parsed


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in raw.split(","):
        key, separator, value = item.partition("=")
        if separator and key.strip() and value.strip():
            headers[key.strip()] = value.strip()
    return headers


def _sampler(settings: TelemetrySettings) -> Sampler:
    name = settings.traces_sampler or "parentbased_traceidratio"
    try:
        ratio = float(settings.traces_sampler_arg or _DEFAULT_SAMPLE_RATIO)
        if not 0.0 <= ratio <= 1.0:
            raise ValueError("ratio outside [0, 1]")
    except (TypeError, ValueError):
        _logger.warning("Invalid OTEL_TRACES_SAMPLER_ARG; using 0.1")
        ratio = _DEFAULT_SAMPLE_RATIO
    roots: dict[str, Sampler] = {
        "always_on": ALWAYS_ON,
        "always_off": ALWAYS_OFF,
        "traceidratio": TraceIdRatioBased(ratio),
        "parentbased_always_on": ParentBased(ALWAYS_ON),
        "parentbased_always_off": ParentBased(ALWAYS_OFF),
        "parentbased_traceidratio": ParentBased(TraceIdRatioBased(ratio)),
    }
    selected = roots.get(name)
    if selected is None:
        _logger.warning(
            "Invalid OTEL_TRACES_SAMPLER=%s; using parentbased_traceidratio",
            name,
        )
        return ParentBased(TraceIdRatioBased(_DEFAULT_SAMPLE_RATIO))
    return selected


def _signal_endpoint(base: str, signal: str) -> str:
    endpoint = base.rstrip("/")
    suffix = f"/v1/{signal}"
    return endpoint if endpoint.endswith(suffix) else endpoint + suffix


def _resource(settings: TelemetrySettings) -> Resource:
    attributes: dict[str, str] = {
        SERVICE_NAME: _bounded(settings.service_name),
    }
    if settings.service_version:
        attributes[SERVICE_VERSION] = _bounded(settings.service_version)
    if settings.sentry_environment:
        attributes[DEPLOYMENT_ENVIRONMENT] = _bounded(settings.sentry_environment)

    for key, value in _parse_resource_attributes(settings.resource_attributes).items():
        attributes.setdefault(key, value)
    # Resource.create() also reads the process environment, bypassing the
    # allowlist above. Build it directly so ambient attributes cannot leak.
    return Resource(attributes)


def _exporter_kwargs(settings: TelemetrySettings, endpoint: str) -> dict[str, object]:
    kwargs: dict[str, object] = {"endpoint": endpoint}
    if settings.otlp_headers:
        kwargs["headers"] = _parse_headers(settings.otlp_headers)
    return kwargs


@dataclass
class ObservabilityRuntime:
    tracer_provider: Any
    meter_provider: Any
    tracer: Any
    meter: Any
    exporters: tuple[SpanExporter, ...] = ()
    metric_readers: tuple[MetricReader, ...] = ()
    sentry_initialized: bool = False
    instrumented_apps: list[object] = field(default_factory=list)
    queue_depth: int = 0
    pipeline_runs: Any = None
    pipeline_duration: Any = None
    pipeline_stage_duration: Any = None
    discovery_cycles: Any = None
    discovery_candidates: Any = None
    queue_depth_gauge: Any = None
    vault_writes: Any = None
    vector_operations: Any = None
    _closed: bool = False
    _shutdown_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def instrument_app(self, app: object) -> None:
        global _requests_instrumented, _urllib_instrumented

        if app in self.instrumented_apps:
            return
        self.instrumented_apps.append(app)

        if isinstance(self.tracer_provider, trace.NoOpTracerProvider):
            return

        try:
            FastAPIInstrumentor.instrument_app(app, tracer_provider=self.tracer_provider)
        except Exception as error:
            _logger.warning("FastAPI telemetry instrumentation failed: %s", type(error).__name__)

        with _runtime_lock:
            if not _requests_instrumented:
                try:
                    RequestsInstrumentor().instrument(tracer_provider=self.tracer_provider)
                    _requests_instrumented = True
                except Exception as error:
                    _logger.warning(
                        "Requests telemetry instrumentation failed: %s",
                        type(error).__name__,
                    )
            if not _urllib_instrumented:
                try:
                    URLLibInstrumentor().instrument(tracer_provider=self.tracer_provider)
                    _urllib_instrumented = True
                except Exception as error:
                    _logger.warning(
                        "URLlib telemetry instrumentation failed: %s",
                        type(error).__name__,
                    )

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True

        timeout_millis = max(int(timeout_seconds * 1000), 1)
        self._flush_provider(self.tracer_provider, timeout_millis, "traces")
        self._shutdown_provider(self.tracer_provider, "traces")
        self._flush_provider(self.meter_provider, timeout_millis, "metrics")
        self._shutdown_provider(self.meter_provider, "metrics")
        if self.sentry_initialized:
            try:
                sentry_sdk.flush(timeout=timeout_seconds)
            except Exception as error:
                _logger.warning("Sentry telemetry flush failed: %s", type(error).__name__)

    @staticmethod
    def _flush_provider(provider: object, timeout_millis: int, signal: str) -> None:
        flush = getattr(provider, "force_flush", None)
        if flush is None:
            return
        try:
            flush(timeout_millis=timeout_millis)
        except TypeError:
            try:
                flush(timeout_millis)
            except Exception as error:
                _logger.warning("%s telemetry flush failed: %s", signal, type(error).__name__)
        except Exception as error:
            _logger.warning("%s telemetry flush failed: %s", signal, type(error).__name__)

    @staticmethod
    def _shutdown_provider(provider: object, signal: str) -> None:
        shutdown = getattr(provider, "shutdown", None)
        if shutdown is None:
            return
        try:
            shutdown()
        except Exception as error:
            _logger.warning("%s telemetry shutdown failed: %s", signal, type(error).__name__)

    def _create_instruments(self) -> None:
        self.pipeline_runs = self.meter.create_counter(
            "personalwiki.pipeline.runs", unit="{run}"
        )
        self.pipeline_duration = self.meter.create_histogram(
            "personalwiki.pipeline.duration", unit="s"
        )
        self.pipeline_stage_duration = self.meter.create_histogram(
            "personalwiki.pipeline.stage.duration", unit="s"
        )
        self.discovery_cycles = self.meter.create_counter(
            "personalwiki.discovery.cycles", unit="{cycle}"
        )
        self.discovery_candidates = self.meter.create_counter(
            "personalwiki.discovery.candidates", unit="{candidate}"
        )

        def observe_queue(_options: object) -> Sequence[Observation]:
            return [Observation(self.queue_depth)]

        self.queue_depth_gauge = self.meter.create_observable_gauge(
            "personalwiki.discovery.queue.depth",
            callbacks=[observe_queue],
            unit="{item}",
        )
        self.vault_writes = self.meter.create_counter(
            "personalwiki.vault.writes", unit="{write}"
        )
        self.vector_operations = self.meter.create_counter(
            "personalwiki.vector.operations", unit="{operation}"
        )

    def observed_span(
        self,
        name: str,
        attributes: Mapping[str, object] | None = None,
    ) -> Any:
        return self.tracer.start_as_current_span(
            name,
            attributes=_safe_span_attributes(attributes),
        )


def _build_runtime(
    settings: TelemetrySettings,
    *,
    trace_exporter_factory: Any = OTLPSpanExporter,
    metric_exporter_factory: Any = OTLPMetricExporter,
    extra_span_processors: Sequence[SpanProcessor] = (),
    extra_metric_readers: Sequence[MetricReader] = (),
    sentry_init: Any = sentry_sdk.init,
    register_globals: bool = False,
) -> ObservabilityRuntime:
    if settings.sdk_disabled:
        tracer_provider = trace.NoOpTracerProvider()
        meter_provider = metrics.NoOpMeterProvider()
        runtime = ObservabilityRuntime(
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            tracer=tracer_provider.get_tracer(_TRACER_NAME),
            meter=meter_provider.get_meter(_METER_NAME),
        )
        runtime._create_instruments()
        return runtime

    resource = _resource(settings)
    tracer_provider = TracerProvider(resource=resource, sampler=_sampler(settings))
    tracer_provider.add_span_processor(RedactingSpanProcessor())
    exporters: list[SpanExporter] = []

    if settings.otlp_endpoint:
        try:
            exporter = trace_exporter_factory(
                **_exporter_kwargs(
                    settings,
                    _signal_endpoint(settings.otlp_endpoint, "traces"),
                )
            )
            tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
            exporters.append(exporter)
        except Exception as error:
            _logger.warning("OTLP trace exporter setup failed: %s", type(error).__name__)

    for processor in extra_span_processors:
        tracer_provider.add_span_processor(processor)

    if register_globals:
        trace.set_tracer_provider(tracer_provider)

    sentry_initialized = False
    if settings.sentry_dsn:
        sentry_kwargs: dict[str, object] = {
            "dsn": settings.sentry_dsn,
            "integrations": [OTLPIntegration(capture_exceptions=True)],
            "instrumenter": "otel",
            "send_default_pii": False,
            "max_request_body_size": "never",
            "include_local_variables": False,
            "enable_logs": False,
            "before_send": redact_sentry_event,
            "before_send_transaction": redact_sentry_transaction,
        }
        if settings.sentry_environment:
            sentry_kwargs["environment"] = settings.sentry_environment
        if settings.sentry_release:
            sentry_kwargs["release"] = settings.sentry_release
        try:
            sentry_init(**sentry_kwargs)
            sentry_initialized = True
        except Exception as error:
            _logger.warning("Sentry telemetry setup failed: %s", type(error).__name__)

    readers: list[MetricReader] = []
    if settings.otlp_endpoint:
        try:
            metric_exporter = metric_exporter_factory(
                **_exporter_kwargs(
                    settings,
                    _signal_endpoint(settings.otlp_endpoint, "metrics"),
                )
            )
            production_reader = PeriodicExportingMetricReader(metric_exporter)
            readers.append(production_reader)
        except Exception as error:
            _logger.warning("OTLP metric exporter setup failed: %s", type(error).__name__)
    readers.extend(extra_metric_readers)
    meter_provider = MeterProvider(metric_readers=readers, resource=resource)
    if register_globals:
        metrics.set_meter_provider(meter_provider)

    runtime = ObservabilityRuntime(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        tracer=tracer_provider.get_tracer(_TRACER_NAME),
        meter=meter_provider.get_meter(_METER_NAME),
        exporters=tuple(exporters),
        metric_readers=tuple(readers),
        sentry_initialized=sentry_initialized,
    )
    runtime._create_instruments()
    return runtime


def configure_observability(app: object | None = None) -> ObservabilityRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = _build_runtime(
                get_telemetry_settings(),
                register_globals=True,
            )
        if app is not None:
            _runtime.instrument_app(app)
        return _runtime


def shutdown_observability(timeout_seconds: float = 5.0) -> None:
    with _runtime_lock:
        runtime = _runtime
    if runtime is None:
        return
    runtime.shutdown(timeout_seconds=timeout_seconds)


@contextmanager
def observed_span(
    name: str,
    attributes: Mapping[str, object] | None = None,
) -> Iterator[Any]:
    runtime = _runtime
    if runtime is None:
        yield None
        return

    with runtime.observed_span(name, attributes) as span:
        try:
            yield span
        except Exception as error:
            record_handled_error(span, error)
            raise


def record_handled_error(span: Any, error: BaseException) -> None:
    if span is None:
        return
    span.set_attribute("error.type", type(error).__name__)
    span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR))


def _normalise_category(value: str, allowed: set[str]) -> str:
    return value if value in allowed else "other"


def _normalise_outcome(value: str) -> str:
    return value if value in {"success", "error", "skipped"} else "other"


def _normalise_discovery_source(value: str) -> str:
    return value if value in _DISCOVERY_SOURCES else "other"


def _normalise_vector_operation(value: str) -> str:
    return value if value in _VECTOR_OPERATIONS else "other"


def record_pipeline_run(source_type: str, trigger: str, outcome: str, duration: float) -> None:
    runtime = _runtime
    if runtime is None:
        return
    labels = {
        "source_type": _normalise_category(source_type, {"article", "paper", "video"}),
        "trigger": _normalise_category(trigger, {"manual", "discovery"}),
        "outcome": _normalise_outcome(outcome),
    }
    runtime.pipeline_runs.add(1, labels)
    runtime.pipeline_duration.record(max(duration, 0.0), labels)


def record_pipeline_stage(stage: str, source_type: str, outcome: str, duration: float) -> None:
    runtime = _runtime
    if runtime is None:
        return
    labels = {
        "stage": _normalise_category(stage, _PIPELINE_STAGES),
        "source_type": _normalise_category(source_type, {"article", "paper", "video"}),
        "outcome": _normalise_outcome(outcome),
    }
    runtime.pipeline_stage_duration.record(max(duration, 0.0), labels)


def record_discovery_cycle(outcome: str) -> None:
    if _runtime is not None:
        _runtime.discovery_cycles.add(1, {"outcome": _normalise_outcome(outcome)})


def record_discovery_candidate(source: str, outcome: str) -> None:
    if _runtime is not None:
        labels = {
            "source": _normalise_discovery_source(source),
            "outcome": _normalise_outcome(outcome),
        }
        _runtime.discovery_candidates.add(1, labels)


def record_discovery_queue_depth(depth: int) -> None:
    if _runtime is not None:
        _runtime.queue_depth = max(int(depth), 0)


def record_vault_write(outcome: str, discovery: bool) -> None:
    if _runtime is not None:
        _runtime.vault_writes.add(
            1,
            {
                "outcome": _normalise_outcome(outcome),
                "discovery": "true" if discovery else "false",
            },
        )


def record_vector_operation(operation: str, outcome: str) -> None:
    if _runtime is not None:
        _runtime.vector_operations.add(
            1,
            {
                "operation": _normalise_vector_operation(operation),
                "outcome": _normalise_outcome(outcome),
            },
        )
