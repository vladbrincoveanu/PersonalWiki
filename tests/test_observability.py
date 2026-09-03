import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch


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
    assert runtime.metric_readers == ()


def test_sentry_trace_exporter_uses_the_shared_redaction_processor(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")

    from config import get_telemetry_settings
    from core.observability import _build_runtime
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import Link, SpanContext, Status, StatusCode, TraceFlags, TraceState

    exporter = InMemorySpanExporter()
    sentry_init = Mock()
    runtime = _build_runtime(
        get_telemetry_settings(),
        sentry_trace_exporter_factory=Mock(return_value=exporter),
        sentry_init=sentry_init,
        register_globals=False,
    )

    with runtime.tracer.start_as_current_span(
        "personalwiki.test",
        attributes={
            "http.route": "/items/{item_id}",
            "http.url": "https://private.example/items/42?token=secret",
        },
        links=(
            Link(
                SpanContext(
                    1,
                    2,
                    TraceFlags(1),
                    False,
                    TraceState(),
                ),
                {"secret.link": "raw link secret"},
            ),
        ),
    ) as span:
        span.set_status(Status(StatusCode.ERROR, "raw status secret"))

    runtime.tracer_provider.force_flush()

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    assert dict(finished[0].attributes) == {"http.route": "/items/{item_id}"}
    assert finished[0].status.description is None
    assert not finished[0].links[0].attributes

    integration = sentry_init.call_args.kwargs["integrations"][0]
    assert integration.setup_otlp_traces_exporter is False


def test_sentry_redaction_removes_transaction_and_log_payloads():
    from core.observability import redact_sentry_event, redact_sentry_transaction

    event = {
        "transaction": "https://private.example/items/42?token=secret",
        "spans": [{
            "description": "GET https://private.example/items/42",
            "data": {"url": "https://private.example/items/42?token=secret"},
        }],
        "logentry": {"message": "raw log secret"},
        "tags": {"source": "raw tag secret"},
    }

    for redactor in (redact_sentry_event, redact_sentry_transaction):
        redacted = redactor(event, {})
        assert "transaction" not in redacted
        assert "spans" not in redacted
        assert "logentry" not in redacted
        assert "tags" not in redacted
        assert "raw" not in str(redacted)


def test_external_otlp_adds_trace_and_metric_exporters(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")

    from config import get_telemetry_settings
    from core.observability import _build_runtime

    trace_factory = Mock(return_value=Mock(name="trace-exporter"))
    metric_exporter = Mock(name="metric-exporter")
    metric_exporter._preferred_temporality = {}
    metric_exporter._preferred_aggregation = {}
    metric_factory = Mock(return_value=metric_exporter)
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
    from core.observability import (
        FastAPIInstrumentor,
        RequestsInstrumentor,
        URLLibInstrumentor,
        _build_runtime,
    )

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

    assert len(runtime.exporters) == 2
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
    assert override_runtime.tracer_provider.sampler.get_description() == "AlwaysOnSampler"


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


def test_redaction_removes_http_payloads_and_exception_messages(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    from config import get_telemetry_settings
    from core.observability import _build_runtime
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
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


def test_redacting_processor_forwards_a_public_sanitized_span_copy():
    from core.observability import RedactingSpanProcessor
    from opentelemetry.sdk.trace import Event, ReadableSpan
    from opentelemetry.sdk.trace.export import SpanProcessor

    class CapturingProcessor(SpanProcessor):
        def __init__(self):
            self.spans = []

        def on_end(self, span):
            self.spans.append(span)

    original = ReadableSpan(
        name="personalwiki.test",
        attributes={
            "http.route": "/items/{item_id}",
            "request.body": "raw document text",
        },
        events=(
            Event(
                "exception",
                {
                    "exception.type": "ValueError",
                    "exception.message": "raw exception secret",
                },
            ),
            Event("custom", {"message": "raw event secret"}),
        ),
    )
    delegate = CapturingProcessor()

    RedactingSpanProcessor(delegate).on_end(original)

    assert len(delegate.spans) == 1
    sanitized = delegate.spans[0]
    assert isinstance(sanitized, ReadableSpan)
    assert sanitized is not original
    assert dict(sanitized.attributes) == {"http.route": "/items/{item_id}"}
    assert len(sanitized.events) == 1
    assert dict(sanitized.events[0].attributes) == {"exception.type": "ValueError"}
    assert dict(original.attributes)["request.body"] == "raw document text"
    assert dict(original.events[0].attributes)["exception.message"] == "raw exception secret"


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
        "message": "raw top-level exception secret",
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
    assert "message" not in redacted
    exception_value = redacted["exception"]["values"][0]
    assert exception_value == {"type": "ValueError"}
    assert "raw exception secret" not in str(redacted)


def test_shutdown_swallows_exporter_failures_and_is_idempotent():
    from config import get_telemetry_settings
    from core.observability import _build_runtime

    runtime = _build_runtime(get_telemetry_settings(), register_globals=False)
    with (
        patch.object(
            runtime.tracer_provider,
            "force_flush",
            side_effect=RuntimeError("flush secret"),
        ) as trace_flush,
        patch.object(
            runtime.tracer_provider,
            "shutdown",
            side_effect=RuntimeError("shutdown secret"),
        ),
        patch.object(
            runtime.meter_provider,
            "force_flush",
            side_effect=RuntimeError("metric secret"),
        ) as metric_flush,
        patch.object(
            runtime.meter_provider,
            "shutdown",
            side_effect=RuntimeError("metric shutdown secret"),
        ),
        patch("core.observability.sentry_sdk.flush", side_effect=RuntimeError("sentry secret")),
    ):
        runtime.shutdown(timeout_seconds=0.01)
        runtime.shutdown(timeout_seconds=0.01)

    trace_flush.assert_called_once()
    metric_flush.assert_called_once()


def test_fastapi_lifespan_configures_and_flushes_telemetry():
    import app as app_module
    from fastapi.testclient import TestClient

    runtime = Mock()
    with (
        patch.object(
            app_module,
            "configure_observability",
            return_value=runtime,
            create=True,
        ) as configure,
        patch.object(app_module, "shutdown_observability", create=True) as shutdown,
        patch.object(app_module, "scan_vault", return_value=0),
    ):
        with TestClient(app_module.app):
            pass

    configure.assert_called_once_with(app_module.app)
    shutdown.assert_called_once_with()


def test_fastapi_http_span_keeps_route_method_status_only(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    from config import get_telemetry_settings
    from core.observability import _build_runtime
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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
        span
        for span in exporter.get_finished_spans()
        if span.attributes.get("http.route") == "/items/{item_id}"
    )
    attributes = dict(server_span.attributes)
    assert attributes.get("http.request.method", attributes.get("http.method")) == "POST"
    assert attributes.get("http.response.status_code", attributes.get("http.status_code")) == 200
    assert "http.url" not in attributes
    assert "http.target" not in attributes
    assert all("secret" not in str(value) for value in attributes.values())
    assert "raw body" not in str(server_span.events)


@pytest.mark.asyncio
async def test_direct_pipeline_execution_bootstraps_observability():
    import pipeline

    store = MagicMock()
    store.exists.return_value = True
    with (
        patch.object(pipeline, "get_store", return_value=store),
        patch.object(pipeline, "configure_observability", create=True) as configure,
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
        patch("pipeline._merge_entities", return_value=[]),
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
        span
        for span in telemetry_runtime.span_exporter.get_finished_spans()
        if span.name == "personalwiki.pipeline.run"
    )
    assert root.attributes["pipeline.outcome"] == "skipped"


@pytest.mark.asyncio
async def test_discovery_cycle_emits_sanitized_cycle_search_and_ingest_spans(telemetry_runtime):
    from core.discovery_scheduler import DiscoveryScheduler

    async def fake_pipeline(**kwargs):
        yield "done"

    with patch.object(DiscoveryScheduler, "_blocking_refresh"):
        scheduler = DiscoveryScheduler()
    scheduler._keywords = ["private keyword"]
    scheduler._seen_urls.clear()
    scheduler._pipeline_func = object()
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
        patch(
            "core.vector_store.get_store",
            return_value=MagicMock(exists=MagicMock(return_value=False)),
        ),
        patch.object(scheduler, "_fetch_html", new_callable=AsyncMock, return_value=""),
        patch("pipeline.run_pipeline", fake_pipeline),
        patch("core.discovery_scheduler.cleanup_junk", return_value=[]),
        patch("core.discovery_scheduler.get_discovery_logger") as logger_factory,
    ):
        logger_factory.return_value.record = MagicMock()
        logger_factory.return_value.today.return_value = []
        await scheduler._run_discovery_cycle()
    scheduler.stop()

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

    with patch.object(DiscoveryScheduler, "_blocking_refresh"):
        scheduler = DiscoveryScheduler()
    with patch("pipeline.run_pipeline", side_effect=RuntimeError("raw secret")):
        await scheduler._run_pipeline(
            "https://private.example/secret",
            keyword="private keyword",
        )
    scheduler.stop()

    span = next(
        span
        for span in telemetry_runtime.span_exporter.get_finished_spans()
        if span.name == "personalwiki.discovery.ingest"
    )
    assert span.attributes["discovery.outcome"] == "error"
    assert span.attributes["error.type"] == "RuntimeError"
    assert "raw secret" not in str(span.events)
    assert "private.example" not in str(span.attributes)


@pytest.mark.asyncio
async def test_discovery_queue_depth_metric_tracks_enqueue_and_drain(telemetry_runtime):
    from core.discovery_scheduler import DiscoveryScheduler

    def queue_depth():
        data = telemetry_runtime.metric_reader.get_metrics_data()
        metric = next(
            metric
            for resource_metrics in data.resource_metrics
            for scope_metrics in resource_metrics.scope_metrics
            for metric in scope_metrics.metrics
            if metric.name == "personalwiki.discovery.queue.depth"
        )
        return metric.data.data_points[0].value

    with patch.object(DiscoveryScheduler, "_blocking_refresh"):
        scheduler = DiscoveryScheduler()
    scheduler._seen_urls.clear()
    scheduler._keywords = []
    scheduler._run_pipeline = AsyncMock()
    with (
        patch.object(scheduler, "_try_sitemap", return_value=["https://example.com/article"]),
        patch("core.discovery_scheduler.get_discovery_logger") as logger_factory,
        patch("core.vector_store.get_store", return_value=MagicMock(exists=MagicMock(return_value=False))),
        patch.object(scheduler, "_persist_seen_urls"),
        patch("core.discovery_scheduler.cleanup_junk", return_value=[]),
    ):
        logger_factory.return_value.record = MagicMock()
        logger_factory.return_value.today.return_value = []
        scheduler._enqueue_interest_domain("example.com")
        assert queue_depth() == 1
        await scheduler._run_discovery_cycle()
    scheduler.stop()

    assert queue_depth() == 0


def test_env_example_documents_opt_in_telemetry_defaults():
    from pathlib import Path

    text = Path(".env.example").read_text(encoding="utf-8")
    assert "SENTRY_DSN=" in text
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=" in text
    assert "OTEL_TRACES_SAMPLER=parentbased_traceidratio" in text
    assert "OTEL_TRACES_SAMPLER_ARG=0.1" in text
    assert "OTEL_SDK_DISABLED=false" in text
    assert "OTEL_EXPORTER_OTLP_HEADERS=" in text
