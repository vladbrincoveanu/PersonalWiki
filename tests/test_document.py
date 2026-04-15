from ingesters import Document


def test_document_defaults():
    doc = Document(raw_text="hello", content_type="article")
    assert doc.raw_text == "hello"
    assert doc.content_type == "article"
    assert doc.images == []


def test_document_with_images():
    doc = Document(raw_text="text", content_type="paper", images=[b"png1", b"png2"])
    assert len(doc.images) == 2
