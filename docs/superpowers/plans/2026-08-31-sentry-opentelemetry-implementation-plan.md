# Sentry and OpenTelemetry Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in, privacy-safe Sentry and OpenTelemetry traces and metrics to the FastAPI application, ingestion pipeline, discovery scheduler, vector operations, and vault writes without changing product behavior.

**Architecture:** `core/observability.py` owns one idempotent OpenTelemetry runtime. It builds one shared `TracerProvider`, adds Sentry's `OTLPIntegration` and an optional external OTLP exporter to that provider, and exposes bounded operation/error/metric helpers. FastAPI lifespan and direct `run_pipeline()` execution call the same bootstrap; all exported spans pass through centralized redaction before either backend receives them.

**Tech Stack:** Python 3.13, FastAPI, Sentry Python SDK 2.68.1, OpenTelemetry API/SDK/exporter 1.44.0, OpenTelemetry contrib instrumentation 0.65b0, pytest, pytest-asyncio, in-memory OTel exporters/readers, Ruff.

---

## Current Constraints and File Map

The checkout has substantial pre-existing migration, CI, and security changes. Work only in `/Users/vladbrincoveanu/Desktop/Startup/personalWiki/.worktrees/sentry-otel`, stage only files belonging to the current task, and do not reset or overwrite unrelated changes.

Files to create or modify:

- Create `core/observability.py` for settings consumption, provider construction, Sentry setup, OTel instrumentation, redaction, operation spans, metrics, and shutdown.
- Modify `config.py` with a dynamic telemetry settings object so tests can change environment variables without reloading the module.
- Modify `requirements.txt` with the pinned Sentry/OpenTelemetry runtime packages.
- Create `tests/test_observability.py` for configuration, provider wiring, sampler, redaction, idempotence, and lifecycle tests.
- Create `tests/test_observability_operations.py` for embedding, vector, and vault operation boundaries.
- Modify `tests/conftest.py` only if a shared in-memory telemetry fixture is needed; keep the existing vector-store and scheduler cleanup fixtures unchanged.
- Modify `app.py` only to call the shared bootstrap at lifespan entry and bounded shutdown at lifespan exit.
- Modify `pipeline.py` only to add root/stage spans and pipeline metrics around existing behavior.
- Modify `core/discovery_scheduler.py` only to add cycle/search/queue/ingestion spans and discovery metrics; preserve existing logger records and provider-specific search behavior.
- Modify `core/embeddings.py`, `core/vector_store.py`, and `vault/writer.py` only at public operation boundaries.
- Modify `.env.example`, `README.md`, and the CI environment in `.github/workflows/ci.yml` with safe empty telemetry defaults and documentation.
- Do not modify `core/minimax_client.py`, the durable discovery logger implementation, any UI template, or add a Prometheus endpoint.

The existing `docker-compose.yml` passes `.env` through its optional `env_file`; do not duplicate telemetry variables in the `environment` mapping, because that would risk overriding `.env` values. Verify Compose configuration instead of changing it. The existing `Dockerfile` installs `requirements.txt`, so no Dockerfile change is required.

## Task 1: Add Dynamic Telemetry Settings and Dependencies

**Files:**
- Modify: `config.py`
- Modify: `requirements.txt`
- Test: `tests/test_observability.py`

- [ ] **Step 1: Write the failing settings tests**

Add these tests before adding the implementation. They intentionally import a function that does not exist yet.

```python
def test_telemetry_settings_default_to_disabled(monkeypatch):
    for name in (
        "SENTRY_DSN",
        "SENTRY_ENVIRONMENT",
        "SENTRY_RELEASE",
        "OTEL_SERVICE_NAME",
        "OTEL_SERVICE_VERSION",
        "OTEL_RESOURCE_ATTRIBUTES",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_TRACES_SAMPLER",
        "OTEL_TRACES_SAMPLER_ARG",
        "OTEL_SDK_DISABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    from config import get_telemetry_settings

    settings = get_telemetry_settings()

    assert settings.sentry_dsn == ""
    assert settings.sentry_environment is None
    assert settings.sentry_release is None
    assert settings.service_name == "personalwiki"
    assert settings.service_version is None
    assert settings.resource_attributes == ""
    assert settings.otlp_endpoint == ""
    assert settings.otlp_headers == ""
    assert settings.traces_sampler == "parentbased_traceidratio"
    assert settings.traces_sampler_arg == "0.1"
    assert settings.sdk_disabled is False


def test_telemetry_settings_read_environment_at_call_time(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTRY_RELEASE", "build-42")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "personalwiki-worker")
    monkeypatch.setenv("OTEL_SERVICE_VERSION", "1.2.3")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=staging")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=Bearer test-only")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from config import get_telemetry_settings

    settings = get_telemetry_settings()

    assert settings.sentry_dsn.endswith("/1")
    assert settings.sentry_environment == "test"
    assert settings.sentry_release == "build-42"
    assert settings.service_name == "personalwiki-worker"
    assert settings.service_version == "1.2.3"
    assert settings.resource_attributes == "deployment.environment=staging"
    assert settings.otlp_endpoint == "http://collector:4318/"
    assert settings.otlp_headers == "authorization=Bearer test-only"
    assert settings.traces_sampler == "always_on"
    assert settings.sdk_disabled is True
```

- [ ] **Step 2: Run the settings tests and verify the correct failure**

Run:

```bash
python -m pytest tests/test_observability.py::test_telemetry_settings_default_to_disabled tests/test_observability.py::test_telemetry_settings_read_environment_at_call_time -q
```

Expected: FAIL during import with `ImportError` because `get_telemetry_settings` is not defined. Do not make a production change before observing this failure.

- [ ] **Step 3: Implement the dynamic settings object**

Add the following to `config.py` after the existing environment-backed settings. Keep `load_dotenv()` behavior unchanged. The settings object must read `os.environ` every time `get_telemetry_settings()` is called so lifespan tests and subprocesses can control configuration without reloading `config.py`.

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class TelemetrySettings:
    sentry_dsn: str
    sentry_environment: str | None
    sentry_release: str | None
    service_name: str
    service_version: str | None
    resource_attributes: str
    otlp_endpoint: str
    otlp_headers: str
    traces_sampler: str
    traces_sampler_arg: str
    sdk_disabled: bool


def get_telemetry_settings() -> TelemetrySettings:
    def optional(name: str) -> str | None:
        value = os.getenv(name, "").strip()
        return value or None

    return TelemetrySettings(
        sentry_dsn=os.getenv("SENTRY_DSN", "").strip(),
        sentry_environment=optional("SENTRY_ENVIRONMENT"),
        sentry_release=optional("SENTRY_RELEASE"),
        service_name=os.getenv("OTEL_SERVICE_NAME", "personalwiki").strip() or "personalwiki",
        service_version=optional("OTEL_SERVICE_VERSION"),
        resource_attributes=os.getenv("OTEL_RESOURCE_ATTRIBUTES", "").strip(),
        otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip(),
        otlp_headers=os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").strip(),
        traces_sampler=os.getenv(
            "OTEL_TRACES_SAMPLER", "parentbased_traceidratio"
        ).strip().lower(),
        traces_sampler_arg=os.getenv("OTEL_TRACES_SAMPLER_ARG", "0.1").strip() or "0.1",
        sdk_disabled=os.getenv("OTEL_SDK_DISABLED", "false").strip().lower() == "true",
    )
```

- [ ] **Step 4: Run the settings tests and verify they pass**

Run:

```bash
python -m pytest tests/test_observability.py::test_telemetry_settings_default_to_disabled tests/test_observability.py::test_telemetry_settings_read_environment_at_call_time -q
```

Expected: PASS.

- [ ] **Step 5: Add pinned runtime dependencies**

Append these lines to `requirements.txt`, keeping the existing alphabetical-by-subsystem style and exact pins. `sentry-sdk[opentelemetry-otlp]` is required because Sentry's OTLP integration owns its Sentry trace exporter; the direct OTel pins keep API, SDK, exporter, and contrib instrumentation on one compatible release set.

```text
sentry-sdk[opentelemetry-otlp]==2.68.1
opentelemetry-api==1.44.0
opentelemetry-sdk==1.44.0
opentelemetry-exporter-otlp-proto-http==1.44.0
opentelemetry-instrumentation-fastapi==0.65b0
opentelemetry-instrumentation-requests==0.65b0
opentelemetry-instrumentation-urllib==0.65b0
```

- [ ] **Step 6: Install the dependency set and verify importability**

Run:

```bash
python -m pip install --requirement requirements-dev.txt
python -c "import sentry_sdk, opentelemetry, opentelemetry.sdk; from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor; from opentelemetry.instrumentation.requests import RequestsInstrumentor; from opentelemetry.instrumentation.urllib import URLLibInstrumentor; print('telemetry imports ok')"
```

Expected: dependency installation succeeds and the final command prints `telemetry imports ok`.

- [ ] **Step 7: Commit the settings slice**

```bash
git add config.py requirements.txt tests/test_observability.py
git commit -m "feat: add telemetry settings and dependencies"
```

## Task 2: Build the Shared Runtime, Export Fan-Out, and Redaction

**Files:**
- Create: `core/observability.py`
- Modify: `tests/test_observability.py`

- [ ] **Step 1: Write failing provider and privacy tests**

Add tests that use `_build_runtime()` with `register_globals=False` and in-memory processors. The production bootstrap may register globals only in the idempotence/lifecycle test; avoid contaminating all tests with multiple global provider registrations.

```python
from unittest.mock import Mock, patch


def test_no_backends_builds_no_exporters(monkeypatch):
    from config import get_telemetry_settings
    from core.observability import _build_runtime

    for name in ("SENTRY_DSN", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)

    runtime = _build_runtime(get_telemetry_settings(), register_globals=False)

    assert runtime.exporters == ()
    assert runtime.metric_readers == ()
    assert runtime.sentry_initialized is False


def test_sentry_only_uses_otlp_integration_on_the_shared_provider(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from config import get_telemetry_settings
    from core.observability import OTLPIntegration, _build_runtime

    sentry_init = Mock()
    runtime = _build_runtime(
        get_telemetry_settings(),
        sentry_init=sentry_init,
        register_globals=False,
    )

    sentry_init.assert_called_once()
    kwargs = sentry_init.call_args.kwargs
    assert kwargs["dsn"] == "https://public@example.invalid/1"
    assert kwargs["instrumenter"] == "otel"
    assert kwargs["send_default_pii"] is False
    assert kwargs["max_request_body_size"] == "never"
    assert kwargs["include_local_variables"] is False
    assert kwargs["enable_logs"] is False
    assert "traces_sample_rate" not in kwargs
    assert any(isinstance(item, OTLPIntegration) for item in kwargs["integrations"])
    assert runtime.sentry_initialized is True


def test_external_otlp_adds_trace_and_metric_exporters(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")

    from config import get_telemetry_settings
    from core.observability import _build_runtime

    trace_factory = Mock(return_value=Mock(name="trace-exporter"))
    metric_factory = Mock(return_value=Mock(name="metric-exporter"))
    runtime = _build_runtime(
        get_telemetry_settings(),
        trace_exporter_factory=trace_factory,
        metric_exporter_factory=metric_factory,
        register_globals=False,
    )

    trace_factory.assert_called_once_with(endpoint="http://collector:4318/v1/traces")
    metric_factory.assert_called_once_with(endpoint="http://collector:4318/v1/metrics")
    assert len(runtime.exporters) == 1
    assert len(runtime.metric_readers) == 1


def test_sentry_setup_follows_global_provider_registration(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from config import get_telemetry_settings
    from core.observability import _build_runtime

    calls = []

    def capture_provider(provider):
        calls.append(("provider", provider))

    def capture_sentry(**kwargs):
        calls.append(("sentry", kwargs))

    with patch("core.observability.trace.set_tracer_provider", side_effect=capture_provider):
        runtime = _build_runtime(
            get_telemetry_settings(),
            sentry_init=capture_sentry,
            register_globals=True,
        )

    assert calls[0] == ("provider", runtime.tracer_provider)
    assert calls[1][0] == "sentry"


def test_both_backends_share_one_provider_and_do_not_duplicate_instrumentation(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")

    from config import get_telemetry_settings
    from core.observability import FastAPIInstrumentor, RequestsInstrumentor, URLLibInstrumentor, _build_runtime

    sentry_init = Mock()
    runtime = _build_runtime(get_telemetry_settings(), sentry_init=sentry_init, register_globals=False)
    test_app = object()
    with (
        patch.object(FastAPIInstrumentor, "instrument_app") as instrument_app,
        patch.object(RequestsInstrumentor, "instrument") as instrument_requests,
        patch.object(URLLibInstrumentor, "instrument") as instrument_urllib,
    ):
        runtime.instrument_app(test_app)
        runtime.instrument_app(test_app)

    assert len(runtime.exporters) == 1
    assert sentry_init.call_count == 1
    instrument_app.assert_called_once_with(test_app, tracer_provider=runtime.tracer_provider)
    assert instrument_requests.call_count == 1
    assert instrument_urllib.call_count == 1


def test_sampler_defaults_to_parent_based_ten_percent_and_honors_override(monkeypatch):
    from config import get_telemetry_settings
    from core.observability import _build_runtime
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    monkeypatch.delenv("OTEL_TRACES_SAMPLER", raising=False)
    monkeypatch.delenv("OTEL_TRACES_SAMPLER_ARG", raising=False)
    default_runtime = _build_runtime(get_telemetry_settings(), register_globals=False)
    assert isinstance(default_runtime.tracer_provider.sampler, ParentBased)
    assert default_runtime.tracer_provider.sampler._root.__class__ is TraceIdRatioBased
    assert default_runtime.tracer_provider.sampler._root.rate == 0.1

    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    override_runtime = _build_runtime(get_telemetry_settings(), register_globals=False)
    assert override_runtime.tracer_provider.sampler.description == "AlwaysOnSampler"


def test_resource_attributes_keep_identity_and_drop_secrets(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_VERSION", "1.2.3")
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES",
        "deployment.environment=staging,api.key=should-not-appear,service.name=wrong",
    )

    from config import get_telemetry_settings
    from core.observability import _build_runtime

    runtime = _build_runtime(get_telemetry_settings(), register_globals=False)
    attributes = dict(runtime.tracer_provider.resource.attributes)

    assert attributes["service.name"] == "personalwiki"
    assert attributes["service.version"] == "1.2.3"
    assert attributes["deployment.environment"] == "staging"
    assert "api.key" not in attributes
    assert attributes["service.name"] != "wrong"


def test_redaction_removes_http_payloads_and_exception_messages():
    from config import get_telemetry_settings
    from core.observability import _build_runtime
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    runtime = _build_runtime(
        settings=get_telemetry_settings(),
        extra_span_processors=(SimpleSpanProcessor(exporter),),
        register_globals=False,
    )

    with runtime.tracer.start_as_current_span(
        "personalwiki.test",
        attributes={
            "http.route": "/items/{item_id}",
            "http.request.method": "POST",
            "http.response.status_code": 500,
            "http.url": "https://private.example/items/42?token=secret",
            "http.request.header.authorization": "Bearer secret",
            "request.body": "raw document text",
        },
    ) as span:
        span.record_exception(ValueError("raw exception secret"))

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    attributes = dict(finished[0].attributes)
    assert attributes["http.route"] == "/items/{item_id}"
    assert attributes["http.request.method"] == "POST"
    assert attributes["http.response.status_code"] == 500
    assert "http.url" not in attributes
    assert "http.request.header.authorization" not in attributes
    assert "request.body" not in attributes
    assert all(
        "raw exception secret" not in str(event.attributes)
        for event in finished[0].events
    )


def test_sentry_event_redaction_drops_request_and_exception_values():
    from core.observability import redact_sentry_event

    event = {
        "request": {
            "url": "https://private.example/items?token=secret",
            "method": "POST",
            "headers": {"Authorization": "Bearer secret"},
            "query_string": "token=secret",
            "data": {"body": "raw document"},
        },
        "user": {"id": "private-user"},
        "breadcrumbs": [{"message": "raw breadcrumb"}],
        "extra": {"secret": "raw exception secret"},
        "exception": {
            "values": [{
                "type": "ValueError",
                "value": "raw exception secret",
                "stacktrace": {"frames": [{"vars": {"secret": "raw"}}]},
            }]
        },
    }

    redacted = redact_sentry_event(event, {})

    assert redacted["request"] == {"method": "POST"}
    assert "user" not in redacted
    assert "breadcrumbs" not in redacted
    assert "extra" not in redacted
    exception_value = redacted["exception"]["values"][0]
    assert exception_value == {"type": "ValueError"}
    assert "raw exception secret" not in str(redacted)


def test_shutdown_swallows_exporter_failures_and_is_idempotent():
    from core.observability import _build_runtime
    from config import get_telemetry_settings

    runtime = _build_runtime(get_telemetry_settings(), register_globals=False)
    with (
        patch.object(runtime.tracer_provider, "force_flush", side_effect=RuntimeError("flush secret")) as trace_flush,
        patch.object(runtime.tracer_provider, "shutdown", side_effect=RuntimeError("shutdown secret")),
        patch.object(runtime.meter_provider, "force_flush", side_effect=RuntimeError("metric secret")) as metric_flush,
        patch.object(runtime.meter_provider, "shutdown", side_effect=RuntimeError("metric shutdown secret")),
        patch("core.observability.sentry_sdk.flush", side_effect=RuntimeError("sentry secret")),
    ):
        runtime.shutdown(timeout_seconds=0.01)
        runtime.shutdown(timeout_seconds=0.01)

    trace_flush.assert_called_once()
    metric_flush.assert_called_once()
```

The `test_both_backends_share_one_provider_and_do_not_duplicate_instrumentation` test uses a small fake app object accepted by the runtime's instrumentation seam rather than assuming a real FastAPI app. The observable requirement is one instrumentation call per app and one Sentry initialization.

- [ ] **Step 2: Run the new provider tests and verify they fail for missing runtime symbols**

Run:

```bash
python -m pytest tests/test_observability.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing-symbol errors for `core.observability`. The settings tests from Task 1 must remain passing.

- [ ] **Step 3: Implement `core/observability.py` with one provider graph**

Implement the following concrete interfaces and invariants. Keep all imports of Sentry and OTel in this module so application modules do not own provider setup.

```python
from __future__ import annotations

import copy
import hashlib
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

import sentry_sdk
from sentry_sdk.integrations.otlp import OTLPIntegration
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import DEPLOYMENT_ENVIRONMENT, SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import Span, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanProcessor
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    Sampler,
    TraceIdRatioBased,
)
from opentelemetry.trace import Status, StatusCode

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
_VECTOR_OPERATIONS = {"embed", "search", "hybrid_search", "upsert", "entity_search", "entity_upsert"}


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
            for key in list(attributes):
                if key not in _SAFE_SPAN_KEYS:
                    attributes.pop(key, None)
                elif key in {"server.address", "net.peer.name"}:
                    attributes[key] = _normalise_host(attributes[key])
                elif isinstance(attributes[key], str):
                    attributes[key] = _bounded(attributes[key])

        for event in getattr(span, "_events", ()):
            if event.name != "exception":
                continue
            event_attributes = getattr(event, "_attributes", None)
            if event_attributes is None:
                continue
            exception_type = event_attributes.get("exception.type")
            event_attributes.clear()
            if exception_type:
                event_attributes["exception.type"] = _bounded(exception_type)


def redact_sentry_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(event)
    request = redacted.get("request")
    if isinstance(request, dict):
        method = request.get("method")
        redacted["request"] = {"method": method} if method else {}
    for key in ("user", "breadcrumbs", "extra", "contexts.runtime", "modules"):
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
        _logger.warning("Invalid OTEL_TRACES_SAMPLER=%s; using parentbased_traceidratio", name)
        return ParentBased(TraceIdRatioBased(_DEFAULT_SAMPLE_RATIO))
    return selected


def _signal_endpoint(base: str, signal: str) -> str:
    endpoint = base.rstrip("/")
    suffix = f"/v1/{signal}"
    return endpoint if endpoint.endswith(suffix) else endpoint + suffix
```

Continue the same module with an `ObservabilityRuntime` dataclass containing `tracer_provider`, `meter_provider`, `tracer`, `meter`, `exporters`, `metric_readers`, `sentry_initialized`, `instrumented_apps`, and a private `_closed` flag. Its `instrument_app(app)` method must call `FastAPIInstrumentor.instrument_app(app, tracer_provider=self.tracer_provider)` at most once per app, and must call `RequestsInstrumentor().instrument(tracer_provider=self.tracer_provider)` and `URLLibInstrumentor().instrument(tracer_provider=self.tracer_provider)` at most once per process. Record the app object in `instrumented_apps` for test visibility. Never instrument during module import.

Implement `_build_runtime(settings, *, trace_exporter_factory=OTLPSpanExporter, metric_exporter_factory=OTLPMetricExporter, extra_span_processors=(), extra_metric_readers=(), sentry_init=sentry_sdk.init, register_globals=False)` as follows:

- If `settings.sdk_disabled` is true, construct no-op providers and return without Sentry, exporters, instrumentors, or network work.
- Create one `Resource` with `service.name` from `settings.service_name`, optional `service.version`, optional `deployment.environment` from `SENTRY_ENVIRONMENT`, and only the allowlisted `OTEL_RESOURCE_ATTRIBUTES` keys. Explicit service identity values win over environment-string duplicates.
- Create one `TracerProvider(resource=resource, sampler=_sampler(settings))` and add `RedactingSpanProcessor()` before every exporter or test processor.
- If `settings.otlp_endpoint` is non-empty, construct one `BatchSpanProcessor(trace_exporter_factory(endpoint=_signal_endpoint(settings.otlp_endpoint, "traces")))` and append that exporter to `runtime.exporters`.
- Register the tracer provider globally before Sentry when `register_globals` is true.
- If `settings.sentry_dsn` is non-empty, call `sentry_init` once with `OTLPIntegration(capture_exceptions=True)`, `instrumenter="otel"`, `send_default_pii=False`, `max_request_body_size="never"`, `include_local_variables=False`, `enable_logs=False`, `before_send=redact_sentry_event`, and `before_send_transaction=redact_sentry_transaction`; include `environment` and `release` only when configured. Do not pass `traces_sample_rate` or `traces_sampler`. Catch configuration errors, log a warning without the DSN, and leave the application usable.
- Construct a `MeterProvider(resource=resource)` with no reader by default. If `settings.otlp_endpoint` is non-empty, add exactly one `PeriodicExportingMetricReader(metric_exporter_factory(endpoint=_signal_endpoint(settings.otlp_endpoint, "metrics")))`; append test readers after the production reader. Never create a metrics reader for Sentry-only mode.
- Register the meter provider globally after provider construction when `register_globals` is true.
- Create all eight instruments once from `meter = meter_provider.get_meter("personalwiki")`: pipeline run counter, pipeline duration histogram, pipeline stage duration histogram, discovery cycle counter, discovery candidate counter, discovery queue observable gauge, vault write counter, and vector operation counter. Use the exact names and units in the spec and only the specified low-cardinality label keys.
- Catch exporter construction errors individually, log only the exception class and signal, and continue with the provider and no-op export for that signal.

Implement the global API with a `threading.RLock`:

```python
_runtime: ObservabilityRuntime | None = None
_runtime_lock = threading.RLock()


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
```

`ObservabilityRuntime.shutdown()` must call provider flush/shutdown and `sentry_sdk.flush(timeout=timeout_seconds)` inside independent `try/except` blocks, never raise an exporter error during application shutdown, and be idempotent. Use a bounded timeout for every provider operation. Add `observed_span(name, attributes=None)` as a context manager that applies `_safe_span_attributes`, records `error.type` and `StatusCode.ERROR` plus a sanitized `record_exception()` on raised exceptions, and otherwise leaves status unset. Add `record_handled_error(span, error)` for existing catch-and-yield paths; it must set only `error.type`, record the exception for the redaction processor, and set `StatusCode.ERROR` without re-raising.

Add these helper signatures for application modules. Each helper must normalize values to finite allowlists (`article`, `paper`, `video`, `other`; `manual`, `discovery`; `success`, `error`, `skipped`; approved discovery sources plus `other`) before recording:

```python
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
            {"outcome": _normalise_outcome(outcome), "discovery": "true" if discovery else "false"},
        )


def record_vector_operation(operation: str, outcome: str) -> None:
    if _runtime is not None:
        _runtime.vector_operations.add(
            1,
            {"operation": _normalise_vector_operation(operation), "outcome": _normalise_outcome(outcome)},
        )
```

Define `_normalise_category`, `_normalise_outcome`, `_normalise_discovery_source`, and `_normalise_vector_operation` immediately before these helpers. Each returns the original value only when it is in its explicit finite allowlist and returns `"other"` otherwise. The observable gauge callback must read `runtime.queue_depth` and emit one `Observation(runtime.queue_depth)` with no attributes. The plan intentionally gives the exact API names so all later tasks use the same seam.

- [ ] **Step 4: Run provider, sampler, and redaction tests**

Run:

```bash
python -m pytest tests/test_observability.py -q
```

Expected: all settings, provider wiring, sampler, resource, and redaction tests PASS. If an exporter or Sentry setup fails, the test must identify the specific API mismatch; do not weaken privacy assertions.

- [ ] **Step 5: Commit the runtime slice**

```bash
git add core/observability.py tests/test_observability.py
git commit -m "feat: add shared Sentry OTel runtime"
```

## Task 3: Wire FastAPI Lifespan and Automatic HTTP Traces

**Files:**
- Modify: `app.py`
- Modify: `tests/test_observability.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write failing lifecycle and HTTP assertions**

Add a lifecycle test using a real `TestClient` context. Existing `make_client()` does not enter the lifespan context, so do not use it for this test.

```python
def test_fastapi_lifespan_configures_and_flushes_telemetry():
    import app as app_module
    from fastapi.testclient import TestClient

    runtime = Mock()
    with (
        patch.object(app_module, "configure_observability", return_value=runtime) as configure,
        patch.object(app_module, "shutdown_observability") as shutdown,
        patch.object(app_module, "scan_vault", return_value=0),
    ):
        with TestClient(app_module.app):
            pass

    configure.assert_called_once_with(app_module.app)
    shutdown.assert_called_once_with()


def test_fastapi_http_span_keeps_route_method_status_only():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.observability import _build_runtime
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from config import get_telemetry_settings

    exporter = InMemorySpanExporter()
    runtime = _build_runtime(
        get_telemetry_settings(),
        extra_span_processors=(SimpleSpanProcessor(exporter),),
        register_globals=False,
    )
    test_app = FastAPI()

    @test_app.post("/items/{item_id}")
    async def item(item_id: str):
        return {"item_id": item_id}

    runtime.instrument_app(test_app)
    with TestClient(test_app) as client:
        response = client.post(
            "/items/42?token=query-secret",
            headers={"Authorization": "Bearer header-secret"},
            json={"document": "raw body"},
        )

    assert response.status_code == 200
    server_span = next(
        span for span in exporter.get_finished_spans()
        if span.attributes.get("http.route") == "/items/{item_id}"
    )
    attributes = dict(server_span.attributes)
    assert attributes.get("http.request.method", attributes.get("http.method")) == "POST"
    assert attributes.get("http.response.status_code", attributes.get("http.status_code")) == 200
    assert "http.url" not in attributes
    assert "http.target" not in attributes
    assert all("secret" not in str(value) for value in attributes.values())
    assert "raw body" not in str(server_span.events)
```

- [ ] **Step 2: Run the lifecycle tests and verify they fail**

Run:

```bash
python -m pytest tests/test_observability.py::test_fastapi_lifespan_configures_and_flushes_telemetry tests/test_observability.py::test_fastapi_http_span_keeps_route_method_status_only -q
```

Expected: FAIL because `app.py` has no observability calls and the test app is not instrumented.

- [ ] **Step 3: Add lifespan bootstrap and bounded shutdown**

Import `configure_observability` and `shutdown_observability` in `app.py`. At the first line of `lifespan(app)`, call `configure_observability(app)`. Keep the existing vault scan and `yield` behavior unchanged. In the existing `finally`, stop the doctor scheduler as today, then call `shutdown_observability()` in a separate `finally` or independent `try/finally` so telemetry flushing still happens if scheduler cleanup raises. Do not initialize telemetry at module import and do not alter endpoint responses.

The resulting shape must be equivalent to:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_observability(app)
    try:
        try:
            count = await asyncio.to_thread(scan_vault)
            if count:
                print(f"Startup: indexed {count} notes.")
        except Exception as e:
            print(f"Startup: scan_vault failed ({e}), starting without vault index.")
        yield
    finally:
        try:
            if _doctor_scheduler:
                _doctor_scheduler.stop()
        finally:
            shutdown_observability()
```

- [ ] **Step 4: Verify HTTP instrumentation and idempotence**

Run:

```bash
python -m pytest tests/test_observability.py::test_fastapi_lifespan_configures_and_flushes_telemetry tests/test_observability.py::test_fastapi_http_span_keeps_route_method_status_only tests/test_app.py -q
```

Expected: PASS, including all existing API behavior tests. Add one focused assertion that calling `runtime.instrument_app(test_app)` twice does not call `FastAPIInstrumentor.instrument_app` twice and that requests/urllib instrumentors are installed once.

- [ ] **Step 5: Commit the HTTP slice**

```bash
git add app.py tests/test_observability.py tests/test_app.py
git commit -m "feat: instrument FastAPI lifecycle and HTTP"
```

## Task 4: Instrument Direct Pipeline Runs and Pipeline Outcomes

**Files:**
- Modify: `pipeline.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_observability.py`

- [ ] **Step 1: Write the failing direct-bootstrap and span tests**

Add this isolated fixture to `tests/conftest.py`. It keeps the module-level observability runtime out of the global SDK and gives pipeline/discovery/operation tests both finished spans and collected metrics.

```python
from types import SimpleNamespace


@pytest.fixture
def telemetry_runtime(monkeypatch):
    from config import get_telemetry_settings
    from core import observability
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    for name in ("SENTRY_DSN", "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SDK_DISABLED"):
        monkeypatch.delenv(name, raising=False)

    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    runtime = observability._build_runtime(
        get_telemetry_settings(),
        extra_span_processors=(SimpleSpanProcessor(span_exporter),),
        extra_metric_readers=(metric_reader,),
        register_globals=False,
    )
    monkeypatch.setattr(observability, "_runtime", runtime)
    return SimpleNamespace(
        runtime=runtime,
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )
```

Then add a duplicate-path test proving `run_pipeline()` configures telemetry before it touches the store, followed by a success-path assertion for the exact root and child span names. Use concrete local mocks so no extractor, model, embedding model, network call, or vault write runs.

```python
@pytest.mark.asyncio
async def test_direct_pipeline_execution_bootstraps_observability():
    import pipeline

    store = MagicMock()
    store.exists.return_value = True
    with (
        patch.object(pipeline, "get_store", return_value=store),
        patch.object(pipeline, "configure_observability") as configure,
    ):
        messages = [message async for message in pipeline.run_pipeline(url="https://example.com")]

    configure.assert_called_once_with()
    assert any("already exists" in message.lower() for message in messages)


@pytest.mark.asyncio
async def test_pipeline_emits_root_and_stage_spans_without_source_content(telemetry_runtime):
    from pipeline import run_pipeline

    store = MagicMock()
    store.exists.return_value = False
    store.search.return_value = []
    document = MagicMock(
        raw_text="meaningful extracted article text " * 100,
        content_type="article",
        images=[],
    )
    note = {
        "title": "private title",
        "type": "article",
        "summary": "meaningful summary " * 40,
        "key_facts": ["meaningful fact " * 20],
        "cross_links": [],
        "entities": [],
    }
    with (
        patch("pipeline.get_store", return_value=store),
        patch("pipeline.extract", new_callable=AsyncMock, return_value=document),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.enrich", return_value=note),
        patch("pipeline.extract_entities", return_value=[]),
        patch("pipeline.fetch_entity_status", return_value=[]),
        patch("pipeline.detect_gaps", return_value=[]),
        patch("pipeline.write_note", return_value="/vault/notes/private-title.md"),
    ):
        async for _ in run_pipeline(url="https://private.example/articles/secret?token=abc"):
            pass

    names = {span.name for span in telemetry_runtime.span_exporter.get_finished_spans()}
    assert "personalwiki.pipeline.run" in names
    assert {
        "personalwiki.pipeline.extract",
        "personalwiki.pipeline.quality_gate",
        "personalwiki.pipeline.embed",
        "personalwiki.pipeline.vector_search",
        "personalwiki.pipeline.enrich",
        "personalwiki.pipeline.entity_status",
        "personalwiki.pipeline.gap_detection",
        "personalwiki.pipeline.vault_write",
        "personalwiki.pipeline.vector_upsert",
    } <= names
    assert all(
        "private.example" not in str(span.attributes)
        and "token=abc" not in str(span.attributes)
        for span in telemetry_runtime.span_exporter.get_finished_spans()
    )


@pytest.mark.asyncio
async def test_pipeline_duplicate_and_quality_gate_paths_record_skipped_outcome(telemetry_runtime):
    from pipeline import run_pipeline

    store = MagicMock()
    store.exists.return_value = True
    with patch("pipeline.get_store", return_value=store):
        async for _ in run_pipeline(url="https://example.com"):
            pass

    root = next(
        span for span in telemetry_runtime.span_exporter.get_finished_spans()
        if span.name == "personalwiki.pipeline.run"
    )
    assert root.attributes["pipeline.outcome"] == "skipped"
```

Keep the fixture's `monkeypatch` restoration behavior; never use a real DSN, external endpoint, or global provider in these tests.

- [ ] **Step 2: Run the pipeline tests and verify the new assertions fail**

Run:

```bash
python -m pytest tests/test_pipeline.py tests/test_observability.py::test_direct_pipeline_execution_bootstraps_observability -q
```

Expected: existing tests pass or expose only the new failures; new telemetry assertions fail because no observability spans or bootstrap call exist.

- [ ] **Step 3: Add the pipeline root span and outcome accounting**

Import `configure_observability`, `observed_span`, `record_pipeline_run`, `record_pipeline_stage`, and `stable_source_hash` from `core.observability`. Call `configure_observability()` as the first statement inside `run_pipeline()`, before `get_store()`.

    Wrap the entire async-generator body in an `observed_span` whose name is `personalwiki.pipeline.run`. The root attributes may contain only:

```python
{
    "pipeline.source_type": "url" or the finite file type,
    "pipeline.trigger": "discovery" if is_discovery else "manual",
    "source_hash": stable_source_hash(source) if source else None,
}
```

    Never attach `source`, a URL, a local path, `source_keyword`, a title, or a keyword. Track `outcome` locally as `success`, `skipped`, or `error`; set `pipeline.outcome` before the root span closes and call `record_pipeline_run` exactly once in a `finally` block with elapsed seconds.

- [ ] **Step 4: Add exact child stage spans without changing generator messages**

Use `observed_span()` around the existing code blocks and `record_pipeline_stage()` with the same finite `source_type` and final outcome. Keep all current `yield` strings and catch/return behavior. The required names and boundaries are:

```text
personalwiki.pipeline.extract
personalwiki.pipeline.quality_gate
personalwiki.pipeline.embed
personalwiki.pipeline.vector_search
personalwiki.pipeline.enrich
personalwiki.pipeline.entity_status
personalwiki.pipeline.gap_detection
personalwiki.pipeline.vault_write
personalwiki.pipeline.vector_upsert
```

For extraction and quality-gate exceptions that are caught to yield an existing error/skip message, call `record_handled_error(span, error)`, set the root outcome, and return as before. For an exception that currently propagates, let `observed_span()` record and re-raise it. The enrichment span must be named generically and must not mention MiniMax or provider-specific fields.

- [ ] **Step 5: Run focused pipeline verification**

Run:

```bash
python -m pytest tests/test_pipeline.py tests/test_quality_gate_integration.py -q
```

Expected: PASS with unchanged progress messages, duplicate/skip/error behavior, and the new span/metric assertions.

- [ ] **Step 6: Commit the pipeline slice**

```bash
git add pipeline.py tests/test_pipeline.py tests/test_observability.py tests/conftest.py
git commit -m "feat: trace pipeline runs and stages"
```

## Task 5: Instrument Discovery Cycles, Searches, Queueing, and Ingestion

**Files:**
- Modify: `core/discovery_scheduler.py`
- Modify: `tests/test_discovery_scheduler.py`
- Modify: `tests/test_observability.py`

- [ ] **Step 1: Write failing discovery telemetry tests**

Add tests that patch all network/search/pipeline operations. The test data must include a URL, title, keyword, and provider-like source so the assertions prove those values do not enter telemetry.

```python
@pytest.mark.asyncio
async def test_discovery_cycle_emits_sanitized_cycle_search_and_ingest_spans(telemetry_runtime):
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()
    scheduler._keywords = ["private keyword"]
    scheduler._run_pipeline = AsyncMock()
    with (
        patch.object(
            scheduler,
            "_search_keyword",
            new_callable=AsyncMock,
            return_value=[{
                "url": "https://private.example/article?token=secret",
                "title": "private title",
                "snippet": "private snippet",
                "source": "minimax",
            }],
        ),
        patch("core.vector_store.get_store", return_value=MagicMock(exists=MagicMock(return_value=False))),
        patch.object(scheduler, "_fetch_html", new_callable=AsyncMock, return_value=""),
        patch("core.discovery_scheduler.cleanup_junk", return_value=[]),
        patch("core.discovery_scheduler.get_discovery_logger") as logger_factory,
    ):
        logger_factory.return_value.record = MagicMock()
        logger_factory.return_value.today.return_value = []
        await scheduler._run_discovery_cycle()

    spans = telemetry_runtime.span_exporter.get_finished_spans()
    names = {span.name for span in spans}
    assert "personalwiki.discovery.cycle" in names
    assert "personalwiki.discovery.ingest" in names
    assert all("private.example" not in str(span.attributes) for span in spans)
    assert all("private keyword" not in str(span.attributes) for span in spans)
    assert all("private title" not in str(span.attributes) for span in spans)
    assert all("minimax" not in str(span.attributes).lower() for span in spans)


@pytest.mark.asyncio
async def test_discovery_failure_marks_ingestion_error_without_changing_logger_behavior(telemetry_runtime):
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()
    with patch("pipeline.run_pipeline", side_effect=RuntimeError("raw secret")):
        await scheduler._run_pipeline("https://private.example/secret", keyword="private keyword")

    span = next(
        span for span in telemetry_runtime.span_exporter.get_finished_spans()
        if span.name == "personalwiki.discovery.ingest"
    )
    assert span.attributes["discovery.outcome"] == "error"
    assert span.attributes["error.type"] == "RuntimeError"
    assert "raw secret" not in str(span.events)
    assert "private.example" not in str(span.attributes)
```

Add a queue-depth metric assertion using the in-memory metric reader after `_enqueue_interest_domain()` and after queue draining. Reuse the existing scheduler tests for rate limits, queue draining, source-keyword forwarding, and logger persistence as regression coverage.

- [ ] **Step 2: Run the discovery telemetry tests and verify they fail**

Run:

```bash
python -m pytest tests/test_observability.py -k discovery tests/test_discovery_scheduler.py -q
```

Expected: new span/metric assertions fail while existing scheduler behavior remains the baseline.

- [ ] **Step 3: Add the discovery cycle root and child spans**

Wrap `_run_discovery_cycle()` in `observed_span("personalwiki.discovery.cycle")` and set `discovery.outcome` to `success`, `error`, or `skipped` before closing. Record one discovery-cycle counter in `finally`.

Use generic child spans for search, queue drain, and ingestion. Search spans may include only a normalized finite `discovery.source`; they must never include the keyword, URL, title, snippet, or provider name. Do not add a span around `_search_minimax()` and do not modify its request/payload behavior. If a result's source is `minimax` or any unknown value, map it to `other` for metrics or omit the source attribute.

Preserve every existing `_logger` and `get_discovery_logger()` call. OTel spans supplement the durable activity feed and must not write duplicate activity events.

- [ ] **Step 4: Add candidate, queue-depth, and ingestion metrics**

Record `personalwiki.discovery.candidates` for accepted, skipped, and failed candidates with normalized `source` and finite `outcome` labels. Call `record_discovery_queue_depth(self._sitemap_queue.qsize())` after every enqueue and dequeue/drain operation. Wrap `_run_pipeline()` with `observed_span("personalwiki.discovery.ingest", {"discovery": "true"})`; on the existing swallowed exception path call `record_handled_error()`, set `discovery.outcome="error"`, and retain the current logger update/error behavior.

Do not attach `keyword`, `url`, `title`, `snippet`, or exception text to spans or metric attributes.

- [ ] **Step 5: Run scheduler and discovery verification**

Run:

```bash
python -m pytest tests/test_discovery_scheduler.py tests/test_discovery_integration.py tests/test_discovery_logger.py -q
```

Expected: PASS, including existing source-keyword forwarding, queue-rate limiting, cleanup, start/stop, and logger tests.

- [ ] **Step 6: Commit the discovery slice**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py tests/test_observability.py
git commit -m "feat: trace discovery cycles"
```

## Task 6: Instrument Embeddings, Vector Operations, and Vault Writes

**Files:**
- Modify: `core/embeddings.py`
- Modify: `core/vector_store.py`
- Modify: `vault/writer.py`
- Create: `tests/test_observability_operations.py`
- Modify: `tests/test_vector_store.py`
- Modify: `tests/test_writer.py`

- [ ] **Step 1: Write failing operation-boundary tests**

Use fake model/table objects and temporary directories so the tests never download a model, open a real LanceDB store, or write outside `tmp_path`.

```python
def test_embedding_span_contains_no_input_text(telemetry_runtime, monkeypatch):
    from core import embeddings

    class FakeVector:
        def tolist(self):
            return [0.1] * 384

    class FakeModel:
        def embed(self, values):
            assert values == ["secret document content"]
            return iter([FakeVector()])

    monkeypatch.setattr(embeddings, "_get_model", lambda: FakeModel())
    assert embeddings.embed("secret document content") == [0.1] * 384

    span = next(
        span for span in telemetry_runtime.span_exporter.get_finished_spans()
        if span.name == "personalwiki.vector.embed"
    )
    assert "secret document content" not in str(span.attributes)


def test_write_note_records_safe_success_attributes(telemetry_runtime, tmp_path, monkeypatch):
    from vault import writer

    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    monkeypatch.setattr(writer, "NOTES_DIR", notes_dir)
    monkeypatch.setattr(writer, "VAULT_PATH", tmp_path)
    writer.write_note(
        {
            "title": "private title",
            "type": "article",
            "summary": "raw document summary",
            "key_facts": [],
            "raw_text": "raw document body",
        },
        source="https://private.example/article?token=secret",
        is_discovery=True,
    )

    span = next(
        span for span in telemetry_runtime.span_exporter.get_finished_spans()
        if span.name == "personalwiki.vault.write"
    )
    assert span.attributes["discovery"] == "true"
    assert span.attributes["vault.outcome"] == "success"
    assert "private title" not in str(span.attributes)
    assert "raw document" not in str(span.attributes)
    assert "private.example" not in str(span.attributes)
```

Add vector-store tests asserting `search`, `upsert`, and `hybrid_search` record `personalwiki.vector.*` spans and `personalwiki.vector.operations` with only `operation` and `outcome` labels. Add a writer failure test that raises from `_build_body` and asserts `StatusCode.ERROR`, `error.type`, and no exception message/source/path in the finished span.

- [ ] **Step 2: Run the operation tests and verify they fail**

Run:

```bash
python -m pytest tests/test_observability_operations.py tests/test_vector_store.py tests/test_writer.py -q
```

Expected: new telemetry assertions fail because the operation modules are not instrumented.

- [ ] **Step 3: Add embedding and vector operation boundaries**

In `core/embeddings.py`, wrap the model call in `observed_span("personalwiki.vector.embed", {"operation": "embed"})` and record `record_vector_operation("embed", "success")` or `"error"`. Never pass the input text as an attribute.

In `core/vector_store.py`, wrap each public operation boundary with a generic operation span and safe operation label. At minimum instrument `search`, `upsert`, `hybrid_search`, `upsert_entity`, and `search_entities`; preserve all SQL, path, metadata, and return behavior. Record only finite operation names and `success`/`error`; do not attach paths, queries, metadata, vectors, links, SQL, or exception text.

- [ ] **Step 4: Add vault write boundary**

Wrap the body of `write_note()` in `observed_span("personalwiki.vault.write", {"discovery": "true" if is_discovery else "false"})`. On success set `vault.outcome="success"` and record `record_vault_write("success", is_discovery)`; on failure use `record_handled_error()` or let the context manager re-raise according to the existing behavior, set the error outcome, and record the error metric. Do not add source, filepath, title, note body, image bytes, keywords, or entity values to telemetry.

- [ ] **Step 5: Run operation and regression verification**

Run:

```bash
python -m pytest tests/test_observability_operations.py tests/test_vector_store.py tests/test_writer.py -q
```

Expected: PASS with all pre-existing vector and writer behavior intact.

- [ ] **Step 6: Commit the operation slice**

```bash
git add core/embeddings.py core/vector_store.py vault/writer.py tests/test_observability_operations.py tests/test_vector_store.py tests/test_writer.py
git commit -m "feat: trace storage and vault operations"
```

## Task 7: Document Configuration and Keep CI/Compose Opt-In

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Write a configuration documentation check**

Add a small test in `tests/test_observability.py` that reads `.env.example` and asserts every supported variable appears with an empty/default value, without asserting or printing any secret:

```python
def test_env_example_documents_opt_in_telemetry_defaults():
    from pathlib import Path

    text = Path(".env.example").read_text(encoding="utf-8")
    assert "SENTRY_DSN=" in text
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=" in text
    assert "OTEL_TRACES_SAMPLER=parentbased_traceidratio" in text
    assert "OTEL_TRACES_SAMPLER_ARG=0.1" in text
    assert "OTEL_SDK_DISABLED=false" in text
    assert "OTEL_EXPORTER_OTLP_HEADERS=" in text
```

- [ ] **Step 2: Run the documentation test and verify it fails**

Run:

```bash
python -m pytest tests/test_observability.py::test_env_example_documents_opt_in_telemetry_defaults -q
```

Expected: FAIL because `.env.example` does not yet contain the telemetry block.

- [ ] **Step 3: Add safe `.env.example` values**

Append this block with no DSN, endpoint, token, or header value:

```text

# Optional observability; empty values keep telemetry disabled.
SENTRY_DSN=
SENTRY_ENVIRONMENT=
SENTRY_RELEASE=
OTEL_SERVICE_NAME=personalwiki
OTEL_SERVICE_VERSION=
OTEL_RESOURCE_ATTRIBUTES=
OTEL_EXPORTER_OTLP_ENDPOINT=
OTEL_EXPORTER_OTLP_HEADERS=
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1
OTEL_SDK_DISABLED=false
```

- [ ] **Step 4: Document the two backend modes in `README.md`**

Add an `Observability` subsection after the existing configuration table. State exactly:

- `SENTRY_DSN` enables Sentry error monitoring and Sentry's OTLP trace export.
- `OTEL_EXPORTER_OTLP_ENDPOINT` enables external OTLP HTTP/protobuf traces and metrics.
- Either variable may be set alone; both use one correlated OTel provider.
- Telemetry is disabled and produces no exporter network traffic when both are empty.
- Sampling defaults to parent-based 10% traces; metrics are not sampled.
- Request bodies, headers, query values, raw URLs, vault content, credentials, and exception messages are intentionally excluded.
- `OTEL_EXPORTER_OTLP_HEADERS` belongs in the deployment environment and must never be committed.
- There is no Prometheus endpoint and no OTel log export.

Update the setup command to install `requirements-dev.txt` only where development tooling is intended; keep the runtime setup on `requirements.txt`. Update the configuration table with the exact variables and defaults from the spec.

- [ ] **Step 5: Make CI defaults explicit and preserve Compose pass-through**

Add empty `SENTRY_DSN`, empty `OTEL_EXPORTER_OTLP_ENDPOINT`, and `OTEL_SDK_DISABLED=false` to the top-level `env:` block in `.github/workflows/ci.yml`, next to the existing isolated vault/index values. Do not add a secret or endpoint. Do not add telemetry variables to `docker-compose.yml` or `Dockerfile`; the existing optional `.env` file is the deployment injection point.

- [ ] **Step 6: Run documentation, Compose, and CI-shape verification**

Run:

```bash
python -m pytest tests/test_observability.py::test_env_example_documents_opt_in_telemetry_defaults -q
docker compose config --quiet
```

Expected: both commands succeed. Inspect `docker compose config` when necessary to verify `.env` remains the source of runtime telemetry values and no committed default contains a credential.

- [ ] **Step 7: Commit the configuration slice**

```bash
git add .env.example README.md .github/workflows/ci.yml tests/test_observability.py
git commit -m "docs: document opt-in telemetry configuration"
```

## Task 8: Full Verification, Privacy Audit, and Delivery Checkpoint

**Files:**
- No new production files; inspect all task files and the approved spec.

- [ ] **Step 1: Run focused observability tests**

```bash
python -m pytest tests/test_observability.py tests/test_observability_operations.py -q
```

Expected: PASS with no network calls and no real Sentry DSN usage.

- [ ] **Step 2: Run the deterministic repository suite**

```bash
python -m pytest -q --disable-warnings -m "not integration and not slow"
```

Expected: all deterministic tests pass, including the existing baseline of 300 tests plus the new observability coverage. If the suite exceeds the shell timeout, rerun the same command with a longer timeout and report the measured result; do not substitute the integration suite.

- [ ] **Step 3: Run compile, lint, dependency, and Compose checks**

```bash
python -m compileall -q app.py pipeline.py config.py core ingesters vault scripts
python -m ruff check app.py pipeline.py config.py core ingesters vault
python -m pip check
docker compose config --quiet
```

Expected: all commands exit 0.

- [ ] **Step 4: Inspect complete in-memory payloads and configuration diff**

Run the focused privacy tests again with verbose output if any assertion fails. Confirm the tests inspect finished span attributes/events and complete Sentry event dictionaries, not only custom attributes. Review the diff for:

- one provider and no duplicate FastAPI/requests/urllib instrumentation;
- Sentry-only traces with no external metrics reader;
- external-only traces and metrics without Sentry initialization;
- no-backend mode with no exporters or network constructors;
- `StatusCode.ERROR` and `error.type` on handled failures, with exception messages removed;
- success, skipped, and failure metrics for pipeline/discovery;
- bounded shutdown that cannot mask application shutdown;
- no modifications to `core/minimax_client.py` or durable discovery logging;
- no committed DSN, OTLP header, API key, raw URL, request body, or vault content in telemetry tests, docs, or config.

- [ ] **Step 5: Run a final status/diff review without staging unrelated work**

```bash
git status --short
git diff --check
git log --oneline --decorate -12
git diff --stat HEAD~6..HEAD
```

Expected: only the observability commits and intended files are present in the task branch; pre-existing unrelated changes remain unstaged and untouched. If the number of commits differs because a task was combined, inspect the full diff rather than relying on `HEAD~8`.

- [ ] **Step 6: Create the delivery checkpoint**

```bash
git log --oneline --decorate -10
git status --short --branch
```

Record the exact verification outputs, remaining integration/slow-suite limitations, and the final commit range before handing the branch back for merge/review.

## Spec Coverage Self-Review

- Shared OTel provider, Sentry OTLP integration, optional external OTLP trace exporter, metrics-only external reader, default-disabled behavior, and 10% parent-based sampling are covered by Tasks 1-2.
- FastAPI lifespan, direct pipeline bootstrap, idempotence, and automatic HTTP spans are covered by Task 3.
- Pipeline root/stage traces, skip/error semantics, and metrics are covered by Task 4.
- Discovery cycle/search/queue/ingestion spans, source normalization, candidate metrics, queue gauge, and durable logger preservation are covered by Task 5.
- Embedding, vector, vault-write boundaries and operation metrics are covered by Task 6.
- Environment placeholders, README guidance, CI empty defaults, and Compose pass-through are covered by Task 7.
- Complete redaction payload checks, bounded shutdown, no-network tests, lint, compile, dependency, deterministic tests, and diff review are covered by Task 8.
- No task changes MiniMax, provider-specific model instrumentation, OTel logs, Prometheus, UI, dashboards, alerts, releases, or deployment automation.

Before execution, scan this plan for incomplete markers and placeholder syntax inside implementation instructions. Every implementation block above must be complete before production code is committed.
