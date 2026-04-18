import pytest
from pathlib import Path
from unittest.mock import patch

def test_write_digest_creates_discovery_folder(tmp_path):
    """Digest note is written to Discovery/ folder."""
    from core.digest_writer import write_daily_digest

    discovery_dir = tmp_path / "Discovery"
    with patch("core.digest_writer.DISCOVERY_DIR", discovery_dir):
        discovery_dir.mkdir(parents=True, exist_ok=True)

        events = [
            {
                "url": "https://pytorch.org/blog/25",
                "title": "PyTorch 2.5 Released",
                "source": "sitemap: pytorch.org",
                "status": "ingested",
                "discovered_at": "2026-04-18T10:00:00Z",
                "ingested_at": "2026-04-18T10:01:00Z",
                "error": None,
            }
        ]

        path = write_daily_digest(events, date_str="2026-04-18")
        assert Path(path).exists()
        assert "2026-04-18" in path


def test_digest_note_contains_events(tmp_path):
    """Digest note lists all events."""
    from core.digest_writer import write_daily_digest

    discovery_dir = tmp_path / "Discovery"
    with patch("core.digest_writer.DISCOVERY_DIR", discovery_dir):
        discovery_dir.mkdir(parents=True, exist_ok=True)

        events = [
            {
                "url": "https://pytorch.org/blog/25",
                "title": "PyTorch 2.5",
                "source": "sitemap: pytorch.org",
                "status": "ingested",
                "discovered_at": "2026-04-18T10:00:00Z",
                "ingested_at": "2026-04-18T10:01:00Z",
                "error": None,
            },
            {
                "url": "https://example.com/old",
                "title": "Old Post",
                "source": "sitemap: example.com",
                "status": "failed",
                "discovered_at": "2026-04-18T10:00:00Z",
                "ingested_at": None,
                "error": "Quality gate rejected",
            },
        ]

        path = write_daily_digest(events, date_str="2026-04-18")
        content = Path(path).read_text()
        assert "PyTorch 2.5" in content
        assert "pytorch.org" in content
        assert "2026-04-18" in content
        # Ingested table has Domain column (not Title|Domain)
        assert "| pytorch.org | PyTorch 2.5 |" in content
        # Failed table has URL column (not title)
        assert "example.com/old" in content
        assert "Quality gate rejected" in content