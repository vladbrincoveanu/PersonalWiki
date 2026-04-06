# Obsidian Graph Index Design

## Overview

Add a unified Obsidian-compatible graph index to the VKE system that:
1. Scans and indexes files from `/openclaw/research/{raw,interesting,trusted}` folders
2. Generates wiki-links between all pages for proper Obsidian graph view
3. Auto-updates an `index.md` after every ingest

## Architecture

### Data Flow
1. `ingest` command ingests a source
2. Claims extracted and stored in DuckDB
3. WikiGenerator creates entity/source markdown pages with `[[wiki-links]]`
4. Scanner indexes any new files from {raw,interesting,trusted} folders
5. `index.md` regenerated with full graph overview

### Components

#### 1. FileScanner
Scans `/openclaw/research/{raw,interesting,trusted}` and registers files in DuckDB.

```
ScanFolder(path, folderType) → List<FileEntry>
  - id, path, filename, folder (raw|interesting|trusted), size, modified
```

#### 2. WikiGenerator Enhancements
- **Source pages** link to raw files: `[[raw/document.pdf|document.pdf]]`
- **Entity pages** link to source pages: `[[sources/sec-10k.md|SEC 10-K]]`
- **Source pages** link to entities found: `[[entities/apple-inc.md|Apple Inc]]`

#### 3. IndexGenerator
Creates `/openclaw/research/index.md` with sections:
- Entities by tier
- Sources by type
- Raw files (unprocessed)
- Interesting files (curated)
- Trusted files (verified)

```markdown
# Research Vault Index
_Last updated: 2024-01-15 10:30:00 UTC_

## Entities (15 total)

| Entity | Tier | Claims | Last Updated |
|--------|------|--------|--------------|
| [[entities/apple-inc.md|Apple Inc]] | 1 | 15 verified | 2024-01-15 |

## Sources (8 total)

| Source | Type | Domain | Claims |
|--------|------|--------|--------|
| [[sources/sec-10k-aapl-2024.md|SEC 10-K AAPL 2024]] | sec_10k | financial | 12 |

## Raw Files (pending)

| File | Folder | Modified |
|------|--------|----------|
| [[raw/report.pdf|report.pdf]] | raw | 2024-01-14 |

## Interesting

| File | Claims |
|------|--------|
| [[interesting/article.md|article]] | 5 |

## Trusted

| File | Status |
|------|--------|
| [[trusted/peer-reviewed.md|peer-reviewed]] | verified |

## Graph Connections

- [[entities/apple-inc.md]] ←→ [[sources/sec-10k-aapl-2024.md]]
- [[sources/sec-10k-aapl-2024.md]] ←→ [[raw/report.pdf]]
```

## Database Changes

Add `raw_files` table to DuckDB:
```sql
CREATE TABLE IF NOT EXISTS raw_files (
    id              TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    full_path       TEXT NOT NULL,
    folder          TEXT NOT NULL,  -- 'raw', 'interesting', 'trusted'
    file_type       TEXT,
    size_bytes      BIGINT,
    modified_at     TIMESTAMP,
    indexed_at      TIMESTAMP DEFAULT now(),
    linked_entity   TEXT,
    linked_source   TEXT,
    status          TEXT DEFAULT 'pending'  -- 'pending', 'processed', 'verified'
);
```

## Auto-Update Trigger

Index regenerated after:
- `ingest` command completes
- `lint` command runs
- `correct` command completes

## File Naming Convention

All wiki-links use Obsidian-safe names:
- Lowercase
- Spaces → hyphens
- No special characters except hyphens

## Implementation Tasks

1. Add `raw_files` table to VkeDbContext
2. Create `FileScanner` class to index {raw,interesting,trusted}
3. Enhance `WikiGenerator` to use `[[wiki-links]]`
4. Create `IndexGenerator` to build `index.md`
5. Add `UpdateIndexAsync()` call after ingest/lint/correct commands
6. Add tests for scanner and index generation
