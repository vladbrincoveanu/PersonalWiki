# Correctness, Performance & Simplification Plan

Audit date: 2026-08-31. Scope: `core/`, `vault/`, `ingesters/`, `app.py`, `pipeline.py`.
Excludes `.worktrees/`, `tests/`, `docs/superpowers/`.

**Caveat stated up front:** the test suite was NOT run for this audit — `.venv` does not
exist in this checkout. Every finding below is from reading source and is cited by
file:line. Nothing here is "verified green". Stage 0 fixes that.

---

## Headline

Hybrid search is broken in three independent ways that compound, and the tests pass
anyway because they fabricate input shapes production never emits. Optimising it before
fixing it would be optimising the wrong thing, so correctness is sequenced first.

Separately, `notes/discovered/` — the entire output of the background discovery feature —
is invisible to the search index, the vault scanner, and the junk cleaner, because three
modules use `glob` where three others use `rglob`.

---

## Tier 0 — Correctness (search is silently broken)

### 0.1 RRF fuses three disjoint keyspaces
`core/vector_store.py:271`

`_rrf_merge` merges three ranked lists keyed on `path`, but each stream produces a
different kind of string:

| Stream | Key produced | Source |
|---|---|---|
| vector | `https://example.com/article` (URL) | `pipeline.py:231` `upsert(path=source)` |
| BM25 | `/vault/notes/foo.md` (filesystem path) | `core/bm25_index.py:56` |
| graph hop | `Some Note Title` (wikilink title) | `note["cross_links"]` |

No path can ever appear in two streams. Consequences:
- `multi_signal_boost` (`vector_store.py:74`) never fires — dead code in practice.
- `_graph_hop` hop-2 (`vector_store.py:345`) looks up titles in the `path` column and
  always returns empty.
- `metadata_map` (`vector_store.py:263`) assigns `{}` to every BM25 and hop result, so
  those results reach the UI with no title.

**Fix:** canonicalise on the URL, which `write_note` already persists as `source:` in
frontmatter (`vault/writer.py:318`). BM25 emits `post.metadata["source"]` instead of
`str(md_file)`. Graph hop resolves cross-link titles to URLs via a title→path index.

### 0.2 Cross-encoder reranks empty strings
`core/reranker.py:33`, `core/vector_store.py:289`

`rerank()` builds pairs from `r.get("text", "")`. `_rrf_merge` returns only
`{path, score, rank}`, and `hybrid_search` then attaches `metadata` — **never `text`**.
So every pair is `(query, "")` and the final ordering of every search is the
cross-encoder's opinion about empty documents. Reranking is not merely inert; it
actively reshuffles good RRF ordering into noise.

Every reranker test hand-feeds dicts containing `"text"`
(`tests/test_reranker.py:13-15`, `tests/test_reranker_integration.py:22-23`) — a shape
`hybrid_search` never produces. This is the Rule 9 failure exactly: the tests cannot
fail when the business logic is wrong.

**Fix:** carry `text` through `_rrf_merge` alongside `metadata`. Add a test at the real
`hybrid_search` seam, not at the `rerank()` unit seam.

### 0.3 `notes/discovered/` is invisible to half the codebase
`core/bm25_index.py:49`, `vault/scanner.py:20`, `vault/junk_cleaner.py:33` use `glob`.
`core/keywords_manager.py:104,165`, `core/gap_detector.py:17`, `vault/doctor.py:116`
use `rglob`. `vault/writer.py:300` writes discovery output to `NOTES_DIR/discovered/`.

Auto-discovered notes are therefore never indexed for BM25, never scanned at startup,
never junk-cleaned — but *are* counted by the doctor and keyword manager. Also
`app.py:152` resolves `/note/{slug}` only under `notes/`, so discovered notes 404 in the UI.

**Fix:** `rglob` in all six, and make `/note/` search both directories.

### 0.4 `get_all_paths()` returns SQL-escaped data
`core/vector_store.py:182` — returns `_escape_path(row["path"])`, doubling apostrophes in
values handed to callers. Escaping belongs at query construction, not on the return path.
Any URL containing `'` silently fails downstream comparison.

### 0.5 `_refresh(vault_path)` ignores its argument
`core/interest_domain_matcher.py:664-666` — the parameter is accepted and never read;
the method always reads module-level `_KEYWORDS_FILE`, itself frozen at import time from
`VAULT_PATH` (line 17). `InterestDomainMatcher(vault_path=...)` is a silent no-op.

### 0.6 Unmatchable entries in the topic map
`core/interest_domain_matcher.py` — entries whose values carry a path
(`"jax": "github.com/google/jax"`, `"waas": "faa.gov/go/waas"`, `"egnos"`, `"ssl"`)
can never match, because `is_interest_domain` compares against a bare netloc from
`_parse_domain`. Dead data masquerading as coverage.

### 0.7 Double-checked lock leaks a second DoctorScheduler
`app.py:30-42` — the `_doctor_scheduler` construction sits inside the outer
`if _scheduler is None` but outside the inner re-check. Two concurrent first-requests
both reach it, and the second overwrites the global with a second running 24h cron.

---

## Tier 1 — Performance

### 1.1 A full embedding inference to learn a constant
`core/vector_store.py:136-137` — every `upsert()` calls `embed("test")` purely to read
`len()` of the result. That is one model forward pass per note written. Same pattern at
line 110 on construction. Replace with `_detect_table_dim(self._table)` or a cached
module constant.

### 1.2 The reranker model is reloaded on every search
`core/vector_store.py:288` constructs `CrossEncoderReranker()` per call. The lazy-load
cache in `reranker.py:19` is *per instance*, so the instance-per-call defeats it entirely
and `CrossEncoder(...)` is re-instantiated on every single query. Module-level singleton.

### 1.3 Full-table scans to fetch five rows
`core/vector_store.py:220` (`get_recent_notes`) and `:182` (`get_all_paths`) call
`self._table.to_list()`, materialising the whole LanceDB table into Python, then sorting
it in Python to take the top 5. Push the projection and limit into LanceDB.

### 1.4 Unbounded fan-out of paid API calls
`pipeline.py:174-177` — `asyncio.gather` over every semantic chunk of a video with no
concurrency cap. A long transcript issues N simultaneous MiniMax requests. Cost and
rate-limit exposure both scale with input length. Add a semaphore.

### 1.5 Preview cache never evicts, and leaks temp files
`app.py:24` defines `_PREVIEW_TTL = 300` and **nothing ever reads it**. `_preview_cache`
(line 23) grows without bound, and each entry may own a `NamedTemporaryFile` that is only
unlinked if `/ingest/run` is later called with that `preview_id`. Abandoned previews leak
the file forever.

### 1.6 BM25 re-reads the whole vault from disk every 5 minutes
`core/bm25_index.py:44-63` — reparses frontmatter for every note on each rebuild, and
retains `_corpus` which no caller uses after construction. Consider mtime-based
incremental rebuild and dropping the retained corpus.

---

## Tier 2 — Simplification & garbage

| # | Finding | Location |
|---|---|---|
| 2.1 | **605 of 699 lines (86%) is one dict literal.** A data table living in a `.py`. Move to CSV/JSON. | `core/interest_domain_matcher.py:22-624` |
| 2.2 | `enrich`, `enrich_with_images`, `enrich_video_synthesis` each repeat the same header/payload/POST/`base_resp` check/fence-strip/`json.loads`/`setdefault` block (~40 lines × 3). Extract one `_call_minimax`. | `core/minimax_client.py:238,303,394` |
| 2.3 | `_build_video_body`, `_build_paper_body`, `_build_article_body` are three near-identical renderers. | `vault/writer.py:79,140,227` |
| 2.4 | Two parallel queue dicts (`_job_queues`, `_ingest_run_queues`) that `stream()` must check in turn. Collapse to one. | `app.py:21-22,127` |
| 2.5 | Extension→kwarg mapping duplicated between `/ingest` and `/ingest/run`, and **they disagree**: `.txt` maps to `txt_path` in one and `md_path` in the other. | `app.py:88-95` vs `:349-354` |
| 2.6 | `_measure_prose` is a pure pass-through wrapper around `core.prose.measure_prose`, kept only so tests can patch it. Delete; point tests at the real function. | `core/discovery_scheduler.py:45` |
| 2.7 | `__import__("base64")` inline inside a loop. | `core/minimax_client.py:296` |
| 2.8 | Four search backends (`_search_arxiv`, `_search_hn`, `_search_minimax`, `_search_desprebursa`) inline in a 788-line class; `_search_minimax` alone is 130 lines. Extract to `core/discovery_sources/`. | `core/discovery_scheduler.py:374-638` |
| 2.9 | Function-level imports used throughout as a circular-import workaround (6 in `vector_store.py`, 8+ in `app.py`/`pipeline.py`). Symptom of a dependency cycle worth breaking properly. | pervasive |
| 2.10 | `_migrate_if_needed` sets the module singleton `_store = None` from inside a constructor. No-op on the `get_store()` path, confusing everywhere else. | `core/vector_store.py:131` |
| 2.11 | `upsert_entity` escapes `path` but not `entity_name` in the same delete predicate. | `core/vector_store.py:196` |

---

## Sequencing

Each stage is a thin vertical slice: it changes a behaviour end to end and is demoable on
its own. TDD throughout — the test comes first and must fail for the right reason.

**Stage 0 — Make the suite trustworthy.** Recreate `.venv`, install, run the 45 test
files, record what actually passes today. Everything after this is measured against that
baseline. No production code in this stage.
*Done when:* a green/red baseline is written down.

**Stage 1 — One search key.** Fix 0.1 + 0.3 together; they are the same bug wearing two
hats. Write a `hybrid_search` test asserting a note ingested from a URL is retrievable by
a term appearing only in its body — this fails today because the BM25 hit carries a
filesystem path that never fuses.
*Done when:* that test passes and `multi_signal_boost` can be observed firing.

**Stage 2 — Make reranking real.** Fix 0.2. Carry `text` through the merge. Add the seam
test; delete or rewrite the tests that fabricate `text`.
*Done when:* reranking measurably reorders on real content, and the old tests can no
longer pass against broken code.

**Stage 3 — Stop paying for nothing.** 1.1, 1.2, 1.3. Pure speedups, no behaviour change,
protected by Stages 1–2. Measure before and after on a real query.
*Done when:* a timed hybrid_search and a timed upsert both improve, with numbers recorded.

**Stage 4 — Leaks and fan-out.** 1.4, 1.5, 0.7. Bounded concurrency, TTL eviction with
temp-file cleanup, corrected lock.
*Done when:* an abandoned preview's temp file is gone after the TTL, proven by test.

**Stage 5 — Remaining correctness.** 0.4, 0.5, 0.6, 2.11. Small, independent, each with
its own test.

**Stage 6 — Simplification.** 2.1 through 2.10, mechanical and low-risk once the suite is
trustworthy. 2.5 (`.txt` divergence) is a behaviour fix, not cosmetic — treat it as such
and decide which mapping is correct before unifying.

Stages 1, 2 and 5 change behaviour; 3, 4 and 6 should not. Each stage is one commit on a
feature branch, revertible in isolation.

## Deliberately not in scope

- `.vke_index/` (61M) and `.worktrees/` (96M) — you asked to keep both.
- `core/mcp_server.py` has zero importers but is an MCP entrypoint, not dead code.
- Reworking the discovery *heuristics* themselves. 2.1 moves the topic table out of
  Python; whether a hardcoded topic→domain map is the right design at all is a separate
  question, and a bigger one.
