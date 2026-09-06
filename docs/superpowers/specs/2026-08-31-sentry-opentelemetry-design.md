# Sentry and OpenTelemetry Observability - Design Spec

## Status

The direction was approved in conversation. This written spec is the reviewable
design artifact before implementation begins.

## Goal

Add useful, vendor-neutral observability to the Python FastAPI personalWiki
service. Sentry will receive errors and OpenTelemetry traces. An external OTLP
collector or backend may receive the same traces and all OpenTelemetry
metrics. The application must remain unchanged when neither telemetry backend
is configured.

## Context

The active product is a Python 3.13 FastAPI application with an asynchronous
ingestion pipeline, background discovery, LanceDB search, vault writes, and
outbound HTTP calls. The repository already has standard-library logging and a
discovery activity logger, but no Sentry or OpenTelemetry dependency or shared
telemetry bootstrap.

The checkout contains substantial pre-existing uncommitted Python migration,
CI, and security changes. This work must preserve them and must not modify
MiniMax code or add provider-specific model instrumentation. Existing
discovery observer behavior is also out of scope.

## Decisions

- Use one OpenTelemetry instrumentation layer for application traces and
  metrics.
- Use Sentry's current `OTLPIntegration` to export OpenTelemetry traces to
  Sentry and link Sentry errors to active OpenTelemetry traces.
- Add a second OTLP trace exporter only when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is configured.
- Export OpenTelemetry metrics only to the configured external OTLP endpoint.
  Metrics are no-op when that endpoint is absent. Do not duplicate them with
  Sentry-native metrics.
- Disable telemetry by default. `SENTRY_DSN` enables Sentry; an OTLP endpoint
  enables external OpenTelemetry export.
- Use configurable parent-based trace-ID ratio sampling, defaulting to 10%.
  Metrics are not sampled by this application.
- Use OTLP push only. Do not add a Prometheus endpoint.
- Apply strict redaction. Telemetry contains IDs, finite types, sizes,
  durations, status, and error classes, never raw document text, uploads,
  request bodies, authentication headers, API keys, or raw source URLs.
- Use one shared idempotent initializer for FastAPI startup and direct pipeline
  execution.
- Verify with in-memory exporters and mocked Sentry configuration. Tests never
  contact Sentry or an OTLP endpoint.

## Selected Architecture

### Shared bootstrap

Create `core/observability.py` as the only module that owns telemetry setup.
It exposes an idempotent `configure_observability()` function, an application
instrumentation function, and a bounded shutdown/flush function. The module
keeps provider references so shutdown is deterministic and repeated setup does
not install duplicate processors or instrumentors.

Bootstrap sequence:

1. Build one OpenTelemetry `Resource` with `service.name=personalwiki` and
   optional standard service version and deployment environment attributes.
2. Build one OpenTelemetry `TracerProvider` with the configured
   parent-based ratio sampler. When the standard sampler variables are absent,
   supply `parentbased_traceidratio` with a `0.1` argument; honor explicit
   OpenTelemetry sampler variables.
3. Add an OTLP trace `BatchSpanProcessor` when
   `OTEL_EXPORTER_OTLP_ENDPOINT` is present.
4. Register the provider globally before initializing Sentry. If
   `SENTRY_DSN` is present, initialize Sentry with
   `OTLPIntegration(capture_exceptions=True)`, using the existing provider so
   Sentry adds its trace exporter to the same span graph.
5. Configure an OTLP `PeriodicExportingMetricReader` only when the external
   OTLP endpoint is present, then register the `MeterProvider` globally.
6. Install OpenTelemetry FastAPI, `requests`, and `urllib` instrumentation
   once. Initialize Sentry with `instrumenter="otel"` so Sentry tracing
   instrumentation is disabled in favor of OpenTelemetry and duplicate spans
   cannot be created.

The Sentry initialization uses `send_default_pii=False`, disables request body
capture and local-variable capture, keeps Sentry log capture off, and enables
the OTLP integration's handled-exception bridge. Sentry's
`traces_sample_rate` is intentionally omitted because OpenTelemetry owns the
sampling decision in OTLP mode.

FastAPI calls the shared bootstrap from its lifespan before startup work and
flushes it during lifespan shutdown. `run_pipeline()` calls the same bootstrap
at entry so direct async pipeline execution also creates telemetry. Both paths
are safe when the other path already initialized telemetry.

### Trace fan-out

When both backends are configured, one sampled OTel span is sent through two
processors: Sentry's exporter and the external OTLP exporter. This preserves a
single trace identity and avoids separate Sentry and OTel instrumentation
trees. When only one backend is configured, only its processor is installed.
When neither is configured, the application uses OpenTelemetry no-op behavior
and performs no telemetry network I/O.

The default propagation format remains W3C Trace Context and W3C Baggage.
Outgoing requests may continue distributed traces, but propagation targets and
headers are never recorded as telemetry attributes.

## Signal Model

### Automatic HTTP traces

OpenTelemetry FastAPI instrumentation creates inbound server spans for the
application routes. Span names and `http.route` use low-cardinality route
templates. Request bodies, form values, headers, query values, and user data
are not captured.

OpenTelemetry `requests` and `urllib` instrumentation creates outbound client
spans for supported HTTP calls. Only allowlisted low-cardinality metadata is
retained: method, sanitized host where needed, status code, duration, and
error type. Full URLs, query strings, headers, and response content are
removed before export.

### Pipeline traces

Each pipeline run creates one root span named `personalwiki.pipeline.run`.
Safe attributes are `pipeline.source_type`, `pipeline.trigger`,
`pipeline.outcome`, and an optional truncated stable `job.id` or
`source_hash`. Raw URL/path values are never attached.

Child spans cover these deterministic boundaries:

- `personalwiki.pipeline.extract`
- `personalwiki.pipeline.quality_gate`
- `personalwiki.pipeline.embed`
- `personalwiki.pipeline.vector_search`
- `personalwiki.pipeline.enrich`
- `personalwiki.pipeline.entity_status`
- `personalwiki.pipeline.gap_detection`
- `personalwiki.pipeline.vault_write`
- `personalwiki.pipeline.vector_upsert`

The spans are provider-agnostic. They do not name, inspect, or change MiniMax
or any other model implementation.

### Discovery traces

Each discovery cycle creates `personalwiki.discovery.cycle`. Search source,
queue draining, and individual ingestion receive child spans. Attributes are
limited to finite source names, counts, outcomes, and durations. Keywords,
URLs, titles, and source content are not span attributes.

Provider-specific model search paths are not instrumented. Any existing source
label that reaches a shared discovery metric must be normalized to an
allowlisted non-provider source or omitted; it must never create a model-name
label or span.

The existing `core.discovery_logger.py` remains the durable activity feed. OTel
spans provide operational timing and failure correlation; they do not replace
or duplicate its event persistence.

### Application metrics

Create instruments once from a meter named `personalwiki`:

| Instrument | Type | Unit | Low-cardinality attributes |
| --- | --- | --- | --- |
| `personalwiki.pipeline.runs` | Counter | `{run}` | `source_type`, `trigger`, `outcome` |
| `personalwiki.pipeline.duration` | Histogram | `s` | `source_type`, `trigger`, `outcome` |
| `personalwiki.pipeline.stage.duration` | Histogram | `s` | `stage`, `source_type`, `outcome` |
| `personalwiki.discovery.cycles` | Counter | `{cycle}` | `outcome` |
| `personalwiki.discovery.candidates` | Counter | `{candidate}` | `source`, `outcome` |
| `personalwiki.discovery.queue.depth` | Observable gauge | `{item}` | none |
| `personalwiki.vault.writes` | Counter | `{write}` | `outcome`, `discovery` |
| `personalwiki.vector.operations` | Counter | `{operation}` | `operation`, `outcome` |

Metrics have no document, URL, keyword, title, exception message, or user
attributes. Metrics are exported with the same service resource as traces.

## Error Semantics

Every custom stage span uses the OpenTelemetry error conventions:

- success leaves span status unset;
- handled failure sets `StatusCode.ERROR` and low-cardinality `error.type`;
- the existing generator/API behavior remains unchanged;
- failed pipeline and discovery metrics record `outcome=error` or
  `outcome=skipped` as appropriate.

Handled exceptions are recorded through one telemetry helper. The helper
records a sanitized exception representation and error type, never the raw
exception value. Sentry's OTLP integration receives that sanitized handled
failure without an additional direct `capture_exception()` call, preventing
duplicate issues. Unhandled exceptions continue to be captured automatically
by Sentry when a DSN is configured.

Telemetry export failures are non-fatal. An unavailable Sentry or OTLP backend
must not fail ingestion, discovery, vault writes, or application startup.

## Privacy Controls

Redaction is centralized and enforced at both backend boundaries:

- OpenTelemetry span export removes full URL, path, query, request/response
  headers, request/response bodies, database statements, exception messages,
  exception local variables, and every attribute outside the explicit safe
  allowlist.
- Sentry `before_send` and transaction filtering remove request payloads,
  query values, cookies, headers, local variables, exception values, and
  breadcrumbs that contain unapproved data.
- `send_default_pii=False`, `max_request_body_size="never"`,
  `include_local_variables=False`, and disabled log capture are explicit rather
  than relying only on SDK defaults.
- Correlation uses bounded identifiers or a truncated SHA-256 source hash when
  needed. Hashing is not used as a reason to export source content.
- No telemetry code reads `.env` contents or writes credentials to logs,
  traces, metrics, test output, or artifacts.

The redaction tests inspect complete in-memory span and Sentry event payloads,
not only the attributes added by custom instrumentation.

## Configuration

Add safe placeholders to `.env.example` and document them in `README.md`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `SENTRY_DSN` | empty | Enables Sentry error monitoring and OTel trace export to Sentry |
| `SENTRY_ENVIRONMENT` | SDK default | Sentry deployment environment |
| `SENTRY_RELEASE` | SDK default | Sentry release identifier |
| `OTEL_SERVICE_NAME` | `personalwiki` | OpenTelemetry service name |
| `OTEL_SERVICE_VERSION` | empty | Optional OpenTelemetry service version |
| `OTEL_RESOURCE_ATTRIBUTES` | empty | Optional standard resource attributes, excluding secrets |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | Base OTLP HTTP/protobuf endpoint for external traces and metrics |
| `OTEL_EXPORTER_OTLP_HEADERS` | empty | Optional collector authentication headers; supplied outside source control |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio` | OpenTelemetry trace sampler |
| `OTEL_TRACES_SAMPLER_ARG` | `0.1` | Default 10% trace ratio |
| `OTEL_SDK_DISABLED` | `false` | Standard emergency opt-out |

`SENTRY_DSN` and `OTEL_EXPORTER_OTLP_ENDPOINT` remain empty in local and CI
defaults. Compose passes deployment environment values through its existing
`.env` mechanism; no secret is added to Dockerfiles or committed files.

## Lifecycle and Resilience

- Initialization is idempotent and safe under repeated FastAPI imports and
  test clients.
- Instrumentors are not installed twice.
- Batch span and metric processors are used for production-safe asynchronous
  export.
- Shutdown calls bounded provider flush/shutdown and Sentry flush. Shutdown
  errors are logged locally and do not mask application shutdown.
- No exporter performs a blocking network call during module import when the
  relevant backend is disabled.
- Invalid telemetry configuration degrades to local logging and no-op export;
  it never prevents the application from serving requests.

## Testing Strategy

Implementation follows test-driven development in vertical slices. Each slice
starts with a failing test, then the smallest implementation, then the focused
test and deterministic suite.

Required tests:

- no configured backends produce no exporters and no network calls;
- Sentry-only setup adds Sentry's OTLP trace processor to the shared provider;
- external OTLP setup adds trace and metric exporters;
- both backends share one provider and do not duplicate instrumentation;
- initialization and instrumentation are idempotent;
- standard sampler defaults to 10% and honors environment overrides;
- resource attributes contain service identity but no secrets;
- redaction removes forbidden span/event fields, including automatic HTTP
  fields and handled exception messages;
- FastAPI request traces contain route/method/status without bodies or headers;
- pipeline success, skip, and failure produce expected spans and metrics;
- discovery cycle and ingestion failures produce expected spans and metrics;
- shutdown flushes providers without raising when exporters fail;
- existing discovery logger/API behavior remains unchanged.

Tests use `InMemorySpanExporter`, an in-memory metric reader, isolated provider
factories, and mocked Sentry initialization. No test sets a real DSN or sends
data to a remote endpoint. Existing deterministic CI tests must continue to
pass with `SENTRY_DSN` and `OTEL_EXPORTER_OTLP_ENDPOINT` unset.

## Delivery Surface

Expected implementation files:

- Create `core/observability.py` for provider setup, instrumentation, metrics,
  redaction, and lifecycle.
- Modify `app.py` to initialize/instrument FastAPI and flush on lifespan exit.
- Modify `pipeline.py` to create root/stage spans and record pipeline metrics.
- Modify `core/discovery_scheduler.py` to trace cycles, searches, queue drain,
  and ingestion outcomes.
- Modify `core/vector_store.py`, `core/embeddings.py`, and `vault/writer.py`
  only at their operation boundaries for safe spans/metrics.
- Modify `config.py`, `requirements.txt`, `.env.example`, and `README.md` for
  dependency and environment configuration.
- Add focused observability tests and extend existing pipeline/discovery/API
  tests where behavior is already covered.

No UI changes, discovery logger redesign, model-client changes, or new public
telemetry endpoint are part of this work.

## Non-Goals

- Removing or refactoring MiniMax support.
- Instrumenting model/provider-specific request payloads or token data.
- Exporting OpenTelemetry logs.
- Adding Prometheus scraping.
- Building Sentry dashboards, alerts, releases, or deployment automation.
- Sending raw vault content, uploads, URLs, or credentials to any backend.

## Acceptance Criteria

The work is complete when:

1. `SENTRY_DSN` alone sends errors and OpenTelemetry traces to Sentry through
   one OTel provider.
2. `OTEL_EXPORTER_OTLP_ENDPOINT` alone sends OTel traces and metrics to that
   endpoint without requiring Sentry.
3. Both settings send one correlated trace graph to both destinations and do
   not create duplicate FastAPI or HTTP spans.
4. No settings preserve current application behavior and produce no telemetry
   network traffic.
5. Telemetry payload tests prove raw content, bodies, headers, URLs, query
   values, API keys, and exception messages are absent.
6. Pipeline and discovery traces/metrics cover success, skip, and failure
   paths with bounded attributes.
7. Shutdown flushes pending telemetry within a bounded interval.
8. `python -m pytest -q --disable-warnings -m "not integration and not slow"`,
   repository lint, and compile checks pass.

## Alternatives Considered

### Sentry-first instrumentation

Use Sentry FastAPI and HTTP integrations, then add OTel only for custom
pipeline spans and metrics. This is less code initially but creates two
instrumentation models, risks duplicate HTTP spans, and makes an external OTel
backend harder to add consistently.

### Independent Sentry and OpenTelemetry trees

Run native Sentry tracing beside an independent OTel provider. This gives each
backend broad data but splits trace identity and increases export overhead. It
also conflicts with the strict single-instrumentation requirement.

### Selected: OTel-first with Sentry OTLP integration

One OTel provider owns instrumentation, propagation, sampling, and metrics.
Sentry's supported OTLP integration adds Sentry trace export and event linking;
an optional second OTLP exporter keeps traces and metrics vendor-neutral. This
matches current Sentry guidance and the requested privacy/portability boundary.

## References

- Sentry Python OTLP integration:
  `https://docs.sentry.io/platforms/python/integrations/otlp/`
- Sentry OpenTelemetry concepts:
  `https://docs.sentry.io/concepts/otlp/`
- Sentry with OpenTelemetry:
  `https://docs.sentry.io/concepts/otlp/sentry-with-otel/`
- OpenTelemetry Python instrumentation:
  `https://opentelemetry.io/docs/languages/python/instrumentation/`
- OpenTelemetry Python exporters:
  `https://opentelemetry.io/docs/languages/python/exporters/`
