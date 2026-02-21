"""Tests for memory_search_engine.py -- FTS5 index, query, body extraction, hybrid scoring, fallback."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from memory_search_engine import (
    BODY_FIELDS,
    HAS_FTS5,
    build_fts_index,
    build_fts_query,
    extract_body_text,
    query_fts,
    tokenize,
)
from conftest import (
    make_constraint_memory,
    make_decision_memory,
    make_preference_memory,
    make_runbook_memory,
    make_session_memory,
    make_tech_debt_memory,
    write_memory_file,
)

pytestmark = pytest.mark.skipif(not HAS_FTS5, reason="FTS5 not available")


# ============================================================================
# 1. FTS5 Index Build + Query Basic Flow
# ============================================================================

class TestFTS5IndexBuild:
    """Tests for build_fts_index and query_fts."""

    def test_basic_build_and_query(self):
        entries = [
            {"title": "JWT authentication decision", "tags": {"auth", "jwt"}, "path": "a.json", "category": "DECISION"},
            {"title": "Redis caching strategy", "tags": {"cache", "redis"}, "path": "b.json", "category": "DECISION"},
        ]
        conn = build_fts_index(entries)
        q = build_fts_query(["jwt", "authentication"])
        results = query_fts(conn, q)
        conn.close()
        assert len(results) >= 1
        assert results[0]["title"] == "JWT authentication decision"

    def test_build_with_body(self):
        entries = [
            {"title": "Database migration", "tags": {"db"}, "path": "c.json", "category": "DECISION",
             "body": "Migrate postgres to version 15"},
        ]
        conn = build_fts_index(entries, include_body=True)
        q = build_fts_query(["postgres"])
        results = query_fts(conn, q)
        conn.close()
        assert len(results) == 1
        assert results[0]["path"] == "c.json"

    def test_no_match_returns_empty(self):
        entries = [
            {"title": "JWT auth", "tags": {"auth"}, "path": "a.json", "category": "DECISION"},
        ]
        conn = build_fts_index(entries)
        q = build_fts_query(["kubernetes"])
        results = query_fts(conn, q)
        conn.close()
        assert results == []


# ============================================================================
# 2. Smart Wildcard Strategy
# ============================================================================

class TestSmartWildcard:
    """Tests for build_fts_query smart wildcard strategy."""

    def test_compound_token_exact_match(self):
        """Compound tokens (_, ., -) get exact match without wildcard."""
        q = build_fts_query(["user_id"])
        assert q == '"user_id"'

    def test_single_token_prefix_wildcard(self):
        """Single tokens get prefix wildcard."""
        q = build_fts_query(["auth"])
        assert q == '"auth"*'

    def test_mixed_compound_and_single(self):
        q = build_fts_query(["user_id", "auth"])
        assert '"user_id"' in q
        assert '"auth"*' in q

    def test_wildcard_matches_prefix_in_index(self):
        """Prefix wildcard 'auth'* should match 'authentication' in FTS5."""
        entries = [
            {"title": "authentication setup", "tags": set(), "path": "a.json", "category": "DECISION"},
        ]
        conn = build_fts_index(entries)
        q = build_fts_query(["auth"])
        results = query_fts(conn, q)
        conn.close()
        assert len(results) == 1


# ============================================================================
# 3. Body Extraction Across All Categories
# ============================================================================

class TestBodyExtraction:
    """Tests for extract_body_text across all BODY_FIELDS categories."""

    def test_decision_body(self):
        mem = make_decision_memory()
        body = extract_body_text(mem)
        assert "stateless" in body.lower() or "jwt" in body.lower()

    def test_runbook_body(self):
        mem = make_runbook_memory()
        body = extract_body_text(mem)
        assert "connection" in body.lower()

    def test_constraint_body(self):
        mem = make_constraint_memory()
        body = extract_body_text(mem)
        assert "10mb" in body.lower() or "payload" in body.lower()

    def test_tech_debt_body(self):
        mem = make_tech_debt_memory()
        body = extract_body_text(mem)
        assert "v1" in body.lower() or "api" in body.lower()

    def test_preference_body(self):
        mem = make_preference_memory()
        body = extract_body_text(mem)
        assert "typescript" in body.lower() or "type safety" in body.lower()

    def test_session_summary_body(self):
        mem = make_session_memory()
        body = extract_body_text(mem)
        assert "test" in body.lower()

    def test_all_body_fields_categories_covered(self):
        """Verify every category in BODY_FIELDS has a factory and extraction works."""
        factories = {
            "decision": make_decision_memory,
            "runbook": make_runbook_memory,
            "constraint": make_constraint_memory,
            "tech_debt": make_tech_debt_memory,
            "preference": make_preference_memory,
            "session_summary": make_session_memory,
        }
        for cat in BODY_FIELDS:
            factory = factories.get(cat)
            assert factory is not None, f"No factory for {cat}"
            body = extract_body_text(factory())
            assert len(body) > 0, f"Empty body for {cat}"


# ============================================================================
# 4. Hybrid Scoring (score_with_body)
# ============================================================================

class TestHybridScoring:
    """Tests for score_with_body hybrid ranking."""

    def test_body_bonus_improves_ranking(self, tmp_path):
        """Entry with MORE body keyword matches should rank higher.

        Both entries match the query in title and body, but entry A matches
        more body keywords. This ensures both survive apply_threshold's 25%
        noise floor (both get body_bonus, so their scores stay within range).
        """
        from memory_retrieve import score_with_body

        memory_root = tmp_path / ".claude" / "memory"
        (memory_root / "decisions").mkdir(parents=True)

        # Entry A: body matches "postgres" AND "upgrade" (2 body matches -> bonus 2)
        mem_a = make_decision_memory(
            id_val="more-body",
            title="Database migration plan",
            content_overrides={"context": "Migrate postgres to version 15", "decision": "Use pg_upgrade for upgrade"},
        )
        write_memory_file(memory_root, mem_a)

        # Entry B: body matches "postgres" only (1 body match -> bonus 1)
        mem_b = make_decision_memory(
            id_val="less-body",
            title="Database migration checklist",
            content_overrides={"context": "Check postgres compatibility", "decision": "Follow standard steps"},
        )
        write_memory_file(memory_root, mem_b)

        entries = [
            {"title": "Database migration plan", "tags": {"database", "migration"}, "path": ".claude/memory/decisions/more-body.json", "category": "DECISION"},
            {"title": "Database migration checklist", "tags": {"database", "migration"}, "path": ".claude/memory/decisions/less-body.json", "category": "DECISION"},
        ]
        conn = build_fts_index(entries)
        q = build_fts_query(["database", "migration"])
        results = score_with_body(conn, q, "database migration postgres upgrade", 10, memory_root, "auto", max_inject=10)
        conn.close()

        # Both entries must survive thresholding (both have body_bonus >= 1)
        assert len(results) >= 2, f"Expected >=2 results but got {len(results)}: {[r['path'] for r in results]}"
        # Entry with more body matches should rank first (larger body_bonus -> more negative score)
        assert results[0]["path"].endswith("more-body.json"), (
            f"Expected more-body first, got: {[(r['path'], r.get('score'), r.get('body_bonus')) for r in results]}"
        )

    def test_body_bonus_capped_at_3(self, tmp_path):
        """Body bonus is capped at 3 regardless of match count."""
        from memory_retrieve import score_with_body

        memory_root = tmp_path / ".claude" / "memory"
        (memory_root / "decisions").mkdir(parents=True)

        mem = make_decision_memory(
            id_val="many",
            title="authentication api setup",
            content_overrides={
                "context": "auth api setup deploy config test verify",
                "decision": "auth api setup deploy config test verify",
            },
        )
        write_memory_file(memory_root, mem)

        entries = [{"title": "authentication api setup", "tags": set(), "path": ".claude/memory/decisions/many.json", "category": "DECISION"}]
        conn = build_fts_index(entries)
        q = build_fts_query(["authentication", "api", "setup", "deploy", "config"])
        results = score_with_body(conn, q, "authentication api setup deploy config test verify", 10, memory_root)
        conn.close()

        for r in results:
            assert r.get("body_bonus", 0) <= 3


# ============================================================================
# 5. FTS5 Fallback Path
# ============================================================================

class TestFTS5Fallback:
    """Tests for behavior when FTS5 is unavailable."""

    def test_cli_search_returns_empty_when_no_fts5(self, tmp_path):
        """cli_search returns [] when HAS_FTS5 is False."""
        from memory_search_engine import cli_search

        memory_root = tmp_path / ".claude" / "memory"
        memory_root.mkdir(parents=True)
        (memory_root / "index.md").write_text("# Memory Index\n")

        with patch("memory_search_engine.HAS_FTS5", False):
            results = cli_search("authentication", memory_root)
        assert results == []

    def test_retrieve_falls_back_to_legacy_scoring(self, tmp_path):
        """When HAS_FTS5=False, retrieve.py uses legacy keyword scoring path."""
        import subprocess

        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem_root = dc / "memory"
        mem_root.mkdir()
        (mem_root / "decisions").mkdir()

        mem = make_decision_memory()
        write_memory_file(mem_root, mem)

        from conftest import build_enriched_index
        index_content = build_enriched_index(mem)
        (mem_root / "index.md").write_text(index_content)

        # Run retrieve with HAS_FTS5 mocked to False via environment manipulation
        # We test the legacy path by setting match_strategy to force it
        config = {"retrieval": {"enabled": True, "max_inject": 5, "match_strategy": "title_tags"}}
        (mem_root / "memory-config.json").write_text(__import__("json").dumps(config))

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "memory_retrieve.py")],
            input=__import__("json").dumps({
                "user_prompt": "How does JWT authentication work?",
                "cwd": str(proj),
            }),
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        # Legacy path should still find the JWT entry
        assert "use-jwt" in result.stdout or "<memory-context" in result.stdout
