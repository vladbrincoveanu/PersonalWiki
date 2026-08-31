from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.trace import StatusCode


def _span(exporter, name):
    return next(span for span in exporter.get_finished_spans() if span.name == name)


def _metric_points(reader, name):
    data = reader.get_metrics_data()
    return [
        point
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def _fake_store():
    from core.vector_store import VectorStore

    store = object.__new__(VectorStore)
    store._table = MagicMock()
    store._entities_table = MagicMock()
    return store


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

    span = _span(telemetry_runtime.span_exporter, "personalwiki.vector.embed")
    assert span.attributes == {"operation": "embed"}
    assert "secret document content" not in str(span.attributes)
    points = _metric_points(telemetry_runtime.metric_reader, "personalwiki.vector.operations")
    assert {"operation": "embed", "outcome": "success"} in [
        dict(point.attributes) for point in points
    ]


def test_embedding_failure_records_error_without_input_text(telemetry_runtime, monkeypatch):
    from core import embeddings

    monkeypatch.setattr(
        embeddings,
        "_get_model",
        lambda: (_ for _ in ()).throw(RuntimeError("secret document content")),
    )

    with pytest.raises(RuntimeError):
        embeddings.embed("secret document content")

    span = _span(telemetry_runtime.span_exporter, "personalwiki.vector.embed")
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes["error.type"] == "RuntimeError"
    assert "secret document content" not in str(span.events)
    points = _metric_points(telemetry_runtime.metric_reader, "personalwiki.vector.operations")
    assert {"operation": "embed", "outcome": "error"} in [
        dict(point.attributes) for point in points
    ]


def test_vector_operations_emit_safe_spans_and_metrics(telemetry_runtime, monkeypatch):
    store = _fake_store()
    monkeypatch.setattr("core.embeddings.embed", lambda text: [0.1] * 384)

    search_query = MagicMock()
    search_query.limit.return_value.to_list.return_value = [
        {"path": "private/path", "metadata": '{"title": "private title"}'}
    ]
    store._table.search.return_value = search_query
    assert store.search([0.1] * 384, top_k=1)

    store.upsert(
        "private/path",
        "private document text",
        [0.1] * 384,
        ["private/link"],
        {"title": "private title"},
    )

    entity_search_query = MagicMock()
    entity_search_query.where.return_value.limit.return_value.to_list.return_value = []
    store._entities_table.search.return_value = entity_search_query
    assert store.search_entities("private entity query", entity_type="private-type") == []

    store.upsert_entity(
        "private/path",
        "private-type",
        "private entity",
        "private summary",
        {"secret": "private metadata"},
    )

    store.search = MagicMock(return_value=[])
    store._graph_hop = MagicMock(return_value=[])
    with (
        patch("core.bm25_index.ensure_index"),
        patch("core.bm25_index.bm25_search", return_value=[]),
        patch("core.reranker.CrossEncoderReranker.rerank", return_value=[]),
    ):
        assert store.hybrid_search("private hybrid query") == []

    expected_names = {
        "personalwiki.vector.search",
        "personalwiki.vector.upsert",
        "personalwiki.vector.entity_search",
        "personalwiki.vector.entity_upsert",
        "personalwiki.vector.hybrid_search",
    }
    spans = telemetry_runtime.span_exporter.get_finished_spans()
    assert expected_names <= {span.name for span in spans}
    for span in spans:
        if span.name.startswith("personalwiki.vector."):
            assert "private" not in str(span.attributes)
            assert "secret" not in str(span.attributes)

    points = _metric_points(telemetry_runtime.metric_reader, "personalwiki.vector.operations")
    labels = [dict(point.attributes) for point in points]
    assert {"operation": "search", "outcome": "success"} in labels
    assert {"operation": "upsert", "outcome": "success"} in labels
    assert {"operation": "entity_search", "outcome": "success"} in labels
    assert {"operation": "entity_upsert", "outcome": "success"} in labels
    assert {"operation": "hybrid_search", "outcome": "success"} in labels


def test_vector_failure_records_error_without_query_or_path(telemetry_runtime):
    store = _fake_store()
    store._table.search.side_effect = ValueError("private query")

    with pytest.raises(ValueError):
        store.search([0.1] * 384)

    span = _span(telemetry_runtime.span_exporter, "personalwiki.vector.search")
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes["error.type"] == "ValueError"
    assert "private query" not in str(span.events)
    assert "private" not in str(span.attributes)


def test_write_note_records_safe_success_attributes(telemetry_runtime, tmp_path, monkeypatch):
    from vault import writer

    notes_dir = tmp_path / "notes"
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

    span = _span(telemetry_runtime.span_exporter, "personalwiki.vault.write")
    assert span.attributes["discovery"] == "true"
    assert span.attributes["vault.outcome"] == "success"
    assert "private title" not in str(span.attributes)
    assert "raw document" not in str(span.attributes)
    assert "private.example" not in str(span.attributes)
    points = _metric_points(telemetry_runtime.metric_reader, "personalwiki.vault.writes")
    assert {"outcome": "success", "discovery": "true"} in [
        dict(point.attributes) for point in points
    ]


def test_write_note_failure_records_error_without_content_or_source(
    telemetry_runtime, tmp_path, monkeypatch
):
    from vault import writer

    notes_dir = tmp_path / "notes"
    monkeypatch.setattr(writer, "NOTES_DIR", notes_dir)
    monkeypatch.setattr(writer, "VAULT_PATH", tmp_path)
    with patch.object(writer, "_build_body", side_effect=RuntimeError("raw exception")):
        with pytest.raises(RuntimeError):
            writer.write_note(
                {
                    "title": "private title",
                    "type": "article",
                    "summary": "raw document summary",
                    "key_facts": [],
                    "raw_text": "raw document body",
                },
                source="https://private.example/article?token=secret",
            )

    span = _span(telemetry_runtime.span_exporter, "personalwiki.vault.write")
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes["vault.outcome"] == "error"
    assert span.attributes["error.type"] == "RuntimeError"
    assert "raw exception" not in str(span.events)
    assert "private.example" not in str(span.attributes)
    points = _metric_points(telemetry_runtime.metric_reader, "personalwiki.vault.writes")
    assert {"outcome": "error", "discovery": "false"} in [
        dict(point.attributes) for point in points
    ]
