"""Performance benchmarks for FTS5 search engine.

Verifies that 500-doc FTS5 index build + query completes under 100ms.
Uses the bulk_memories fixture from conftest.py.
"""

import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from memory_search_engine import (
    HAS_FTS5,
    apply_threshold,
    build_fts_index,
    build_fts_query,
    query_fts,
    tokenize,
)
from conftest import FOLDER_MAP

pytestmark = pytest.mark.skipif(not HAS_FTS5, reason="FTS5 not available")

# Generous threshold -- should pass on any CI runner
PERF_LIMIT_MS = 100


def _memories_to_entries(memories):
    """Convert bulk_memories dicts to parsed index entries (parse_index_line format)."""
    entries = []
    for m in memories:
        cat = m["category"]
        folder = FOLDER_MAP[cat]
        entries.append({
            "category": cat.upper().replace(" ", "_"),
            "title": m["title"],
            "path": f".claude/memory/{folder}/{m['id']}.json",
            "tags": set(m.get("tags", [])),
            "raw": f"- [{cat.upper()}] {m['title']} -> .claude/memory/{folder}/{m['id']}.json",
        })
    return entries


class TestFTS5Benchmark:
    """Performance benchmarks for FTS5 search."""

    def test_500_doc_index_build_under_limit(self, bulk_memories):
        """Building FTS5 index from 500 docs should be fast."""
        entries = _memories_to_entries(bulk_memories)
        assert len(entries) == 500

        start = time.perf_counter()
        conn = build_fts_index(entries, include_body=False)
        elapsed_ms = (time.perf_counter() - start) * 1000

        conn.close()
        assert elapsed_ms < PERF_LIMIT_MS, (
            f"Index build took {elapsed_ms:.1f}ms, limit is {PERF_LIMIT_MS}ms"
        )

    def test_500_doc_query_under_limit(self, bulk_memories):
        """Querying 500-doc FTS5 index should be fast."""
        entries = _memories_to_entries(bulk_memories)
        conn = build_fts_index(entries, include_body=False)

        tokens = list(tokenize("authentication database migration"))
        fts_query = build_fts_query(tokens)
        assert fts_query is not None

        start = time.perf_counter()
        results = query_fts(conn, fts_query, limit=15)
        elapsed_ms = (time.perf_counter() - start) * 1000

        conn.close()
        assert elapsed_ms < PERF_LIMIT_MS, (
            f"Query took {elapsed_ms:.1f}ms, limit is {PERF_LIMIT_MS}ms"
        )
        assert len(results) > 0, "Query should return results"

    def test_500_doc_full_cycle_under_limit(self, bulk_memories):
        """Full cycle (build + tokenize + query + threshold) under 100ms."""
        entries = _memories_to_entries(bulk_memories)

        start = time.perf_counter()
        conn = build_fts_index(entries, include_body=False)
        tokens = list(tokenize("authentication encryption protocol"))
        fts_query = build_fts_query(tokens)
        assert fts_query is not None
        results = query_fts(conn, fts_query, limit=15)
        filtered = apply_threshold(results, mode="auto", max_inject=5)
        elapsed_ms = (time.perf_counter() - start) * 1000

        conn.close()
        assert elapsed_ms < PERF_LIMIT_MS, (
            f"Full cycle took {elapsed_ms:.1f}ms, limit is {PERF_LIMIT_MS}ms"
        )
        # Verify correctness alongside performance
        assert len(results) > 0, "Raw results should be non-empty"
        assert len(filtered) <= 5, "Threshold should respect max_inject"
        for r in filtered:
            assert "title" in r
            assert "path" in r
            assert "score" in r

    def test_500_doc_results_are_correct(self, bulk_memories):
        """Verify result quality: known keywords should match expected categories."""
        entries = _memories_to_entries(bulk_memories)
        conn = build_fts_index(entries, include_body=False)

        # "timeout" appears in runbook keywords
        tokens = list(tokenize("timeout crash"))
        fts_query = build_fts_query(tokens)
        results = query_fts(conn, fts_query, limit=15)
        conn.close()

        assert len(results) > 0, "Should find entries matching 'timeout crash'"
        categories = {r["category"] for r in results}
        assert "RUNBOOK" in categories, (
            f"Expected RUNBOOK in results for 'timeout crash', got {categories}"
        )

    def test_500_doc_with_body_under_limit(self, bulk_memories):
        """Full cycle with body content should still be under 100ms."""
        entries = _memories_to_entries(bulk_memories)
        # Add synthetic body text
        for i, e in enumerate(entries):
            e["body"] = f"Body text for entry {i} with some searchable content"

        start = time.perf_counter()
        conn = build_fts_index(entries, include_body=True)
        tokens = list(tokenize("searchable content"))
        fts_query = build_fts_query(tokens)
        assert fts_query is not None
        results = query_fts(conn, fts_query, limit=15)
        elapsed_ms = (time.perf_counter() - start) * 1000

        conn.close()
        assert elapsed_ms < PERF_LIMIT_MS, (
            f"Full cycle with body took {elapsed_ms:.1f}ms, limit is {PERF_LIMIT_MS}ms"
        )
        assert len(results) > 0, "Body search should return results"
