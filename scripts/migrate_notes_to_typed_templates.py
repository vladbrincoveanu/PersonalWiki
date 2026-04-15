#!/usr/bin/env python3
"""
Re-enrich existing notes to apply typed templates.
Reads all .md files in VAULT_PATH/notes, extracts type from frontmatter,
and re-runs enrichment to fill typed template fields.
"""
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
_logger = logging.getLogger(__name__)


async def migrate_note(file_path: Path, dry_run: bool = True):
    """Re-enrich one note."""
    import frontmatter
    from pipeline import run_pipeline

    post = frontmatter.loads(file_path.read_text(encoding="utf-8"))
    source = post.get("source", "")

    if not source:
        _logger.info("SKIP %s: no source", file_path.name)
        return

    if dry_run:
        _logger.info("DRY RUN: would re-enrich %s", file_path.name)
        return

    _logger.info("Re-enriching %s...", file_path.name)
    try:
        async for msg in run_pipeline(url=source):
            _logger.debug("  %s", msg)
    except Exception as e:
        _logger.warning("Failed to re-enrich %s: %s", file_path.name, e)


async def main(dry_run: bool = True):
    from config import NOTES_DIR
    notes_dir = Path(NOTES_DIR)

    md_files = list(notes_dir.glob("*.md"))
    _logger.info("Found %d notes. %s", len(md_files), "DRY RUN" if dry_run else "LIVE RUN")

    for f in md_files:
        await migrate_note(f, dry_run=dry_run)

    _logger.info("Done.")


if __name__ == "__main__":
    dry = "--dry" in sys.argv or "-n" in sys.argv
    asyncio.run(main(dry_run=dry))
