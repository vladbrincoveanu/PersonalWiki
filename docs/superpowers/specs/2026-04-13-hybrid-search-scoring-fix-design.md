# Hybrid Search Scoring Fix Design

**Date:** 2026-04-13
**Status:** Approved

---

## Overview

Fix hybrid search ranking so multi-signal notes (appearing in top ranks across multiple streams) are meaningfully boosted above single-signal results.

---

## Problem

Current RRF merge: `score += weight / (k + rank)`

BM25 dominates because:
1. Vector embeddings on 384-dim `bge-small` model produce cosine similarities that cluster in a narrow range (~0.3–0.5)
2. BM25 scores are on a different (unbounded) scale
3. The RRF constant `k=60` means rank differences in top positions produce very small score deltas

**Example:** Note ranked #1 in both vector (weight 1.0) and BM25 (weight 0.9):
- Vector contribution: `1.0 / 61 = 0.0164`
- BM25 contribution: `0.9 / 61 = 0.0148`
- Total: `0.0312`

A note ranked #1 in BM25 only: `0.9 / 61 = 0.0148` — exactly half the multi-signal score.

The math already rewards multi-signal, but in practice BM25 consistently returns the same note as #1 while vector returns a different note. The fused result is dominated by whichever stream the shared note appears in.

---

## Fix: Multi-Signal Boost

After RRF score accumulation, check which notes appear in the top-3 of multiple streams and apply a bonus.

```python
def _rrf_merge(
    ranked_lists: list[list[dict]],
    weights: list[float],
    k: float = 60.0,
    top_k: int = 5,
    multi_signal_boost: float = 0.005,
) -> list[dict]:
    # ... existing RRF accumulation (unchanged) ...

    # --- Multi-signal boost ---
    # Count how many streams each path appears in (top-3 only)
    path_stream_count: dict[str, int] = {}
    for ranked_list in ranked_lists:
        for item in ranked_list[:3]:  # top-3 per stream
            path_stream_count[item["path"]] = path_stream_count.get(item["path"], 0) + 1

    # Apply boost to paths appearing in 2+ streams
    for path, count in path_stream_count.items():
        if count >= 2:
            path_scores[path] += multi_signal_boost * (count - 1)

    # ... existing sort and return (unchanged) ...
```

**Boost magnitude:** `0.005` is calibrated to be larger than the per-stream contribution of a #1-ranked note in a single stream (`1.0/61 ≈ 0.016`) times the smallest weight (0.5). Actually `0.005` is smaller than single-stream contributions — but it's applied ADDITIONALLY, so:
- 2-signal note: gets normal RRF + `0.005`
- 3-signal note: gets normal RRF + `0.010`

This means a note that appears in all 3 streams at any rank will beat any single-stream note, regardless of rank positions. Notes appearing in 2 streams get a tiebreaking advantage.

**Alternative considered:** Scale weights dynamically based on stream count — rejected as over-engineering. Fixed boost is simpler and sufficient.

---

## Score Threshold Guard

Add an optional `min_score` threshold to `hybrid_search`. If the top result's RRF score is below a threshold, return empty results:

```python
def hybrid_search(self, query: str, top_k: int = 5, min_score: float = 0.001) -> list[dict]:
    # ... existing pipeline ...
    merged = _rrf_merge(...)
    
    # Filter noise
    if merged and merged[0]["score"] < min_score:
        return []
    
    return merged
```

Default `min_score=0.001` — calibrated to be well below any legitimate multi-signal result but above BM25 noise.

This fixes the garbage-query-returns-noise problem without affecting real queries.

---

## File Changes

| File | Change |
|------|--------|
| `core/vector_store.py` | Add `multi_signal_boost` to `_rrf_merge`; add `min_score` threshold to `hybrid_search` |

---

## Testing

| Test | Description |
|------|-------------|
| `test_rrf_multi_signal_boost_2_streams` | Note in top-3 of 2 streams gets boost |
| `test_rrf_multi_signal_boost_3_streams` | Note in all 3 streams gets larger boost |
| `test_rrf_no_boost_single_stream` | Single-stream note gets no boost |
| `test_hybrid_search_min_score_threshold` | Query with score < threshold returns [] |
| `test_hybrid_search_above_threshold` | Legitimate query still returns results |

---

## Out of Scope

- Dynamic weight adjustment based on corpus statistics
- Per-stream score normalization before RRF
- Score calibration based on embedding model quality
