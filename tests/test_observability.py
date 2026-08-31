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
