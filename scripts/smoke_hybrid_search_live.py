#!/usr/bin/env python3
"""
Live hybrid search smoke test against real internet content.
Ingests 5-8 URLs via the pipeline, then runs hybrid_search queries.
"""
import asyncio
import json
import logging
import traceback
from datetime import date

from ingesters.router import extract
from core.minimax_client import enrich
from core.embeddings import embed
from core.vector_store import get_store
from vault.writer import write_note

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# URLs to ingest
# -------------------------------------------------------------------
URLS = [
    # 1. arXiv paper — vLLM paper (use PDF URL to avoid HTML redirect issue)
    "https://arxiv.org/pdf/2307.09288",
    # 2. News article
    "https://www.techcrunch.com/2024/01/01/openai-launches-new-model/",
    # 3. YouTube video (tech talk)
    "https://www.youtube.com/watch?v=zduSFxNJkeg",
    # 4. Tweet/X post (AI researcher) — updated URL
    "https://twitter.com/karpathy/status/1726878466819535373",
    # 5. Second news/article (AI research news)
    "https://arstechnica.com/ai/2024/01/google-deepmind-alphafold-3",
    # 6. Another tweet
    "https://twitter.com/ylech__/status/1751828859903500288",
]

INGESTED = []  # list of (url, path) that succeeded


def content_type_from_ingester(ingester: str) -> str:
    mapping = {
        "tweet": "tweet",
        "youtube": "video",
        "pdf": "paper",
        "news": "article",
        "web": "article",
    }
    return mapping.get(ingester, "article")


def ingest_one(url: str) -> tuple[bool, str]:
    """Extract, enrich, write, and upsert one URL. Returns (success, message)."""
    try:
        print(f"\n{'='*60}")
        print(f"Ingesting: {url}")

        # Step 1: Extract
        doc = asyncio.run(extract(url))
        raw_text = doc.raw_text
        content_type = doc.content_type or "article"
        images = doc.images
        print(f"  Extracted {len(raw_text)} chars, type={content_type}, images={len(images)}")

        if not raw_text or len(raw_text) < 50:
            return False, f"Extracted text too short ({len(raw_text)} chars)"

        # Step 2: Enrich (content_type routing lives in pipeline.py)
        enriched = enrich(
            raw_text=raw_text,
            similar_titles=[],
            source=url,
        )
        print(f"  Enriched: title='{enriched.get('title', 'N/A')}'")
        if enriched.get("error"):
            print(f"  [WARN] Enrich returned error flag")

        # Step 3: Write note
        note_path = write_note(
            note=enriched,
            source=url,
            ingested_date=str(date.today()),
            images=images,
        )
        print(f"  Written to: {note_path}")

        # Step 4: Upsert to vector store
        store = get_store()
        vector = embed(raw_text[:6000])
        cross_links = enriched.get("cross_links", [])
        metadata = {
            "title": enriched.get("title", ""),
            "type": enriched.get("type", content_type),
            "source": url,
            "ingested": str(date.today()),
        }
        store.upsert(
            path=url,
            text=raw_text,
            vector=vector,
            links=cross_links,
            metadata=metadata,
        )
        print(f"  Upserted to vector store")
        return True, note_path

    except Exception as e:
        tb = traceback.format_exc()
        print(f"  [ERROR] {e}")
        print(tb)
        return False, str(e)


def run_ingestion():
    """Ingest all URLs, collecting successes."""
    print("\n" + "=" * 70)
    print("PHASE 1: INGESTION")
    print("=" * 70)

    for url in URLS:
        success, msg = ingest_one(url)
        if success:
            INGESTED.append((url, msg))
            print(f"  --> SUCCESS")
        else:
            print(f"  --> FAILED: {msg}")

    print(f"\nIngestion complete: {len(INGESTED)}/{len(URLS)} succeeded")
    for url, path in INGESTED:
        print(f"  {url} -> {path}")


# -------------------------------------------------------------------
# PHASE 2: Hybrid search
# -------------------------------------------------------------------
QUERIES = [
    ("vLLM", "should match the vLLM paper on vLLM inference engine"),
    ("large language model", "should match multiple (vLLM paper, news articles)"),
    ("attention mechanism transformer", "should match papers with attention"),
    ("model inference optimization GPU", "spans multiple signals: vector + BM25 + graph hop"),
    ("scaling laws", "BM25-friendly technical term; good chance of exact match in papers"),
    ("xyzzznonexistentquery12345", "should return zero results"),
]


def run_searches():
    """Run all hybrid search queries and print results."""
    print("\n" + "=" * 70)
    print("PHASE 2: HYBRID SEARCH")
    print("=" * 70)

    store = get_store()

    for query, rationale in QUERIES:
        print(f"\n--- Query: '{query}' ---")
        print(f"Rationale: {rationale}")
        try:
            results = store.hybrid_search(query, top_k=3)
            if not results:
                print("  No results found.")
            for i, r in enumerate(results, 1):
                title = r.get("metadata", {}).get("title", "?")
                score = r.get("score", 0)
                path = r.get("path", "?")
                rank = r.get("rank", "?")
                # Heuristic: guess stream from score magnitude and rank
                # Vector scores tend to be cosine similarities ~0.5-0.9
                # BM25 scores vary widely but rank is key
                # Graph hop weights are 0.5 or 0.25
                stream_guess = "?"
                if score >= 0.6:
                    stream_guess = "vector"
                elif score == 0.5 or score == 0.25:
                    stream_guess = "graph_hop"
                else:
                    stream_guess = "bm25"
                print(f"  {i}. [rank={rank} score={score:.4f} stream={stream_guess}]")
                print(f"     title: {title}")
                print(f"     path:  {path}")
        except Exception as e:
            print(f"  [ERROR] {e}")
            traceback.print_exc()


def main():
    print("LIVE HYBRID SEARCH SMOKE TEST")
    print(f"Run at: {date.today()}")
    print(f"Target: {len(URLS)} URLs")

    run_ingestion()
    run_searches()

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
