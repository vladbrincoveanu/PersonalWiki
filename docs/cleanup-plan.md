# personalWiki — Recovery, Correctness & Cleanup Plan

Audit 2026-08-31, revised after a grilling pass that invalidated three of the
original plan's premises. Scope: `core/`, `vault/`, `ingesters/`, `app.py`,
`pipeline.py`, plus the runtime state (vault + LanceDB index).

## What the grilling changed

The first draft was written for a system that needed tuning. Inspecting the
*artifacts* rather than only the source showed a system that has not produced a
note in over four months. Three corrections, all material:

1. **"The vector stream is keyed by URL" was wrong.** It is keyed by both.
   `pipeline.py:231` upserts under the URL; `vault/scanner.py:41` upserts the
   same note under its filesystem path, on every app boot. Two keyspaces in one
   column, two embeddings per note, double the rows.
2. **"BM25 can never fuse with the vector stream" was wrong.** BM25's filesystem
   paths *do* match the scanner-written rows. The genuinely orphaned rows are the
   URL-keyed ones from the pipeline.
3. **Search was the wrong first priority.** `hybrid_search` has exactly one
   production caller — `core/mcp_server.py:29` — and that server does not start
   (no `.venv`). The web UI has no search at all. Three of six original stages
   targeted a code path nothing executes.

## Runtime state (measured, not inferred)

| Fact | Evidence |
|---|---|
| Configured vault has **0 notes** | `.env` → iCloud `PersonalWiki`; `notes/` holds only an empty `discovered/` |
| Real corpus is **60 notes** in an unconfigured vault | `~/Documents/ObsidianVault/notes/`, newest 2026-04-20 |
| Index holds **10 rows**, 9 pointing at the old vault path | `.vke_index` read directly |
| Index is **61M for those 10 rows** | 1,425 versions, 689 data fragments, 53M of version + transaction log |
| Compaction is **never called** | no `compact_files` / `cleanup_old_versions` anywhere in the source |
| BM25 always returns `[]` | `NOTES_DIR` is empty, so the index has no documents |
| `personal_entities` has **0 rows** and no writer | `VectorStore.upsert_entity` has zero callers |

Net: note production has been dead since the `VAULT_PATH` switch. Everything
downstream — scanner, BM25, search, digests — has been operating on nothing.

## Decisions taken

- **Store:** `./.vault` inside the repo — already the project's own default
  (`.env.example:5`, `docker-compose.yml` mount, `.gitignore`). The iCloud path
  in `.env` is the deviation. Cloud/AWS is a later move, explicitly out of scope.
- **OpenKnowledge:** `ok init` inside `.vault`. OK is a local-first, file-backed
  CRDT layer with a watcher — additive, not a storage backend swap. Because
  `.vault/` is gitignored, OK's `.ok/` and git shadow repo nest invisibly to the
  outer repo.
- **Write path:** unchanged. `write_note` only ever creates new files (slug
  collision counter, never overwrite), so the watcher picks them up with no
  conflict risk. Zero code change; reversible via `ok deinit`.
- **Primary key:** the vault file path, everywhere. `pipeline.py:228` already
  computes it as `_file_path`, so the pipeline change is nearly one line. URL
  moves to metadata.
- **Stale index:** deleted and rebuilt. Nothing in it is reachable.
- **Old vaults:** 60 notes copied in, then both directories *renamed* to
  `.retired-<date>` — not deleted. User deletes once satisfied.

---

## Stage 0 — Make it run, and watch it work

No production code changes. This stage exists because a green unit suite proves
nothing here: the reranker tests pass against provably broken code (see 2.2).

1. Recreate `.venv`, `pip install -r requirements.txt`. This also fixes the
   `personalWiki` MCP server, which currently fails with ENOENT on `.venv/bin/python`.
2. Point `.env` at `VAULT_PATH=./.vault`. Copy the 60 notes and `attachments/`
   from `~/Documents/ObsidianVault` into `.vault/notes/`.
3. Delete `.vke_index` and rebuild via `scan_vault()`.
4. `ok init` in `.vault`.
5. Run the 45 test files; **record what actually passes**. That is the baseline.
6. Ingest one real URL end to end. Confirm a note file appears, is indexed, and
   is retrievable by `hybrid_search` through the MCP tool.

*Done when:* one note has gone URL → vault file → index → search result, observed,
and the test baseline is written down.

Everything below is re-validated against what Stage 0 observes. Findings marked
**(inferred)** have not been executed and may not survive contact.

## Stage 1 — One identity per note

Fixes the dual-keyspace bug, which is the root cause of the double-indexing and
the orphan rows.

- `pipeline.py:231` — upsert under the written file path, not `source`. Put the
  URL in metadata.
- This also fixes uploads: `source` for a PDF/DOCX is the **temp file**
  (`app.py:80`), which `app.py:118` unlinks. Every uploaded file is currently
  indexed under a path that no longer exists.
- `store.exists(url)` dedupe (`pipeline.py:104`) moves to a metadata lookup.

*Done when:* ingesting the same URL twice produces one row, and an uploaded PDF
is indexed under a path that exists on disk.

## Stage 2 — `notes/discovered/` is invisible to half the codebase

`bm25_index.py:49`, `scanner.py:20`, `junk_cleaner.py:33` use `glob`.
`keywords_manager.py:104,165`, `gap_detector.py:17`, `doctor.py:116` use `rglob`.
`writer.py:300` writes discovery output to `NOTES_DIR/discovered/`.

Auto-discovered notes are never indexed, never scanned, never junk-cleaned — but
*are* counted by the doctor. `app.py:152` also resolves `/note/{slug}` only under
`notes/`, so discovered notes 404 in the UI.

*Done when:* a discovered note is searchable and openable in the UI.

## Stage 3 — Compact the index, and keep it compacted

61M for 10 rows. Every `upsert` is delete+add, creating a version; nothing ever
compacts. This is both unbounded disk growth and a query cost — every scan reads
689 fragments.

Add `compact_files()` / `cleanup_old_versions()` on a schedule or a write count.
`DoctorScheduler` already exists as a home for it.

*Done when:* index size is proportional to row count, and stays that way after
100 ingests.

## Stage 4 — Search correctness *(inferred — confirm in Stage 0)*

Now worth doing, because Stage 0 made the MCP server real.

- **4.1 The reranker scores empty strings.** `reranker.py:33` reads
  `r.get("text","")`; `_rrf_merge` returns only `{path, score, rank}` and
  `hybrid_search` attaches `metadata` — never `text`. Final ordering of every
  search is the cross-encoder's opinion about empty documents. Not inert: it
  actively reshuffles good RRF ordering into noise.
  Every reranker test hand-feeds a `"text"` key (`tests/test_reranker.py:13-15`,
  `test_reranker_integration.py:22-23`) — a shape production never emits. Rule 9
  failure. Fix the code, then rewrite the tests at the `hybrid_search` seam.
- **4.2 Graph-hop emits wikilink titles** into a path-keyed merge
  (`vector_store.py:246`), so hop-2 always resolves empty and hop results carry
  no metadata. Resolve titles → paths via a title index.
- **4.3** `vector_store.py:263` assigns `{}` metadata to every non-vector result,
  so BM25 hits reach the UI with no title.

## Stage 5 — Leaks, fan-out, and remaining correctness

- `app.py:24` — `_PREVIEW_TTL` is defined and **never read**. `_preview_cache`
  grows unbounded and leaks a temp file per abandoned preview.
- `app.py:30-42` — the double-checked lock builds `_doctor_scheduler` outside the
  inner re-check; two concurrent first-requests start two 24h crons.
- `pipeline.py:174` — unbounded `asyncio.gather` over video chunks: N
  simultaneous paid MiniMax calls, scaling with transcript length. Add a semaphore.
- `vector_store.py:136` — `embed("test")` per `upsert()`: a full model forward
  pass to read a constant. Use `_detect_table_dim`.
- `vector_store.py:288` — `CrossEncoderReranker()` per search; its lazy cache is
  per-instance, so the model reloads on every query. Module singleton.
- `vector_store.py:182,220` — `to_list()` full-table scans to return 5 rows.
- `vector_store.py:182` — `get_all_paths` returns SQL-*escaped* values as data.
- `vector_store.py:196` — `upsert_entity` escapes `path` but not `entity_name`.
- `interest_domain_matcher.py:664` — `_refresh(vault_path)` ignores its argument;
  `InterestDomainMatcher(vault_path=...)` is a silent no-op.

## Stage 6 — Dead code *(decide after Stage 0)*

Whether this is unfinished or abandoned depends on whether you want the MCP
entity tools once the server is actually running.

- `VectorStore.upsert_entity` — no callers. `personal_entities` is permanently
  empty, so `mcp_server.py:98,115` are guaranteed to return nothing.
- `vault/entities.py::upsert_entity_notes` — no production callers, kept alive by
  a 7-case test file.
- `discovery_scheduler.py:45` `_measure_prose` — pure pass-through wrapper around
  `core.prose.measure_prose`, existing only so tests can patch it.

## Stage 7 — Simplification

| Finding | Location |
|---|---|
| **605 of 699 lines (86%) is one dict literal.** Move to a data file. Entries with paths (`"jax": "github.com/google/jax"`) can never match, since matching compares bare netlocs. | `interest_domain_matcher.py:22-624` |
| `enrich` / `enrich_with_images` / `enrich_video_synthesis` each repeat the same header/payload/POST/`base_resp`/fence-strip/`setdefault` block (~40 lines × 3). | `minimax_client.py:238,303,394` |
| Three near-identical body renderers. | `writer.py:79,140,227` |
| Two parallel queue dicts `stream()` must check in turn. | `app.py:21-22,127` |
| Ext→kwarg mapping duplicated across two endpoints **and they disagree**: `.txt` → `txt_path` in one, `md_path` in the other. Behaviour fix, not cosmetic. | `app.py:88-95` vs `:349-354` |
| `__import__("base64")` inline inside a loop. | `minimax_client.py:296` |
| Four search backends inline in a 788-line class; `_search_minimax` alone is 130 lines. | `discovery_scheduler.py:374-638` |
| Function-level imports as a circular-import workaround (6 in `vector_store.py`, 8+ in `app.py`/`pipeline.py`). | pervasive |
| `_migrate_if_needed` nulls the module singleton from inside a constructor. | `vector_store.py:131` |

---

## Out of scope

- Moving the store to AWS. Explicitly deferred.
- Routing writes through OK's MCP. Direct writes are correct here; revisit only
  if a second concurrent writer appears.
- Rethinking the discovery heuristics. Stage 7 moves the topic table out of
  Python; whether a hardcoded topic→domain map is the right design is a bigger,
  separate question.

## Loose end

`.claude/settings.local.json` has two permission entries using
`iCloud~md~md~obsidian` (double `md`); the real directory is `iCloud~md~obsidian`.
Those entries have never matched anything. Moot once `VAULT_PATH` is `./.vault`.
