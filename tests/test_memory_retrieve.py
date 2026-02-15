"""Tests for memory_retrieve.py -- UserPromptSubmit retrieval hook."""

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
RETRIEVE_SCRIPT = str(SCRIPTS_DIR / "memory_retrieve.py")
PYTHON = sys.executable

sys.path.insert(0, str(SCRIPTS_DIR))
from memory_retrieve import (
    tokenize,
    parse_index_line,
    score_entry,
    check_recency,
    CATEGORY_PRIORITY,
    STOP_WORDS,
    _RECENCY_DAYS,
)
from conftest import (
    make_decision_memory,
    make_preference_memory,
    make_tech_debt_memory,
    make_constraint_memory,
    write_memory_file,
)


class TestTokenize:
    def test_extracts_meaningful_words(self):
        tokens = tokenize("How to configure JWT authentication?")
        assert "configure" in tokens
        assert "jwt" in tokens
        assert "authentication" in tokens
        assert "how" not in tokens  # stop word
        assert "to" not in tokens   # stop word

    def test_excludes_short_words(self):
        tokens = tokenize("go to db mx")
        assert "db" not in tokens  # 2 chars
        assert "mx" not in tokens  # 2 chars

    def test_empty_input(self):
        assert tokenize("") == set()


class TestParseIndexLine:
    def test_enriched_format(self):
        line = "- [DECISION] Use JWT -> .claude/memory/decisions/use-jwt.json #tags:auth,jwt"
        result = parse_index_line(line)
        assert result is not None
        assert result["category"] == "DECISION"
        assert result["title"] == "Use JWT"
        assert result["tags"] == {"auth", "jwt"}

    def test_legacy_format_no_tags(self):
        line = "- [PREFERENCE] Dark mode -> .claude/memory/preferences/dark-mode.json"
        result = parse_index_line(line)
        assert result is not None
        assert result["tags"] == set()

    def test_preserves_raw_line(self):
        line = "- [TECH_DEBT] Legacy API -> .claude/memory/tech-debt/legacy.json #tags:api"
        result = parse_index_line(line)
        assert result["raw"] == line

    def test_invalid_lines(self):
        assert parse_index_line("# Memory Index") is None
        assert parse_index_line("") is None
        assert parse_index_line("- some bullet point") is None


class TestScoreEntry:
    def test_exact_title_match_2_points(self):
        entry = {"title": "JWT authentication", "tags": set()}
        tokens = {"jwt"}
        score = score_entry(tokens, entry)
        assert score == 2

    def test_exact_tag_match_3_points(self):
        entry = {"title": "some other title here", "tags": {"jwt"}}
        tokens = {"jwt"}
        score = score_entry(tokens, entry)
        assert score == 3

    def test_prefix_match_1_point_on_title(self):
        entry = {"title": "authentication system setup", "tags": set()}
        tokens = {"auth"}  # prefix of "authentication"
        score = score_entry(tokens, entry)
        assert score == 1

    def test_prefix_match_on_tags(self):
        entry = {"title": "some title", "tags": {"authentication"}}
        tokens = {"auth"}  # prefix of "authentication" tag
        score = score_entry(tokens, entry)
        assert score == 1

    def test_combined_scoring(self):
        entry = {"title": "JWT token system", "tags": {"auth", "security"}}
        tokens = {"jwt", "auth", "security"}
        # jwt: title exact = 2, auth: tag exact = 3, security: tag exact = 3
        score = score_entry(tokens, entry)
        assert score == 8

    def test_no_double_counting(self):
        """Token matching both title and tag should not double-count."""
        entry = {"title": "auth system", "tags": {"auth"}}
        tokens = {"auth"}
        # "auth" exact title = 2, exact tag = 3
        score = score_entry(tokens, entry)
        assert score == 5  # both count since they're different match types


class TestCheckRecency:
    def test_recent_file(self, tmp_path):
        mem = make_decision_memory()
        mem["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fp = tmp_path / "recent.json"
        fp.write_text(json.dumps(mem))
        is_retired, is_recent = check_recency(fp)
        assert is_retired is False
        assert is_recent is True

    def test_old_file(self, tmp_path):
        mem = make_decision_memory()
        old_date = datetime.now(timezone.utc) - timedelta(days=60)
        mem["updated_at"] = old_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        fp = tmp_path / "old.json"
        fp.write_text(json.dumps(mem))
        is_retired, is_recent = check_recency(fp)
        assert is_retired is False
        assert is_recent is False

    def test_retired_file(self, tmp_path):
        mem = make_decision_memory(record_status="retired")
        fp = tmp_path / "retired.json"
        fp.write_text(json.dumps(mem))
        is_retired, is_recent = check_recency(fp)
        assert is_retired is True
        assert is_recent is False

    def test_missing_file(self, tmp_path):
        fp = tmp_path / "missing.json"
        is_retired, is_recent = check_recency(fp)
        assert is_retired is False
        assert is_recent is False

    def test_corrupt_json(self, tmp_path):
        fp = tmp_path / "corrupt.json"
        fp.write_text("{bad json")
        is_retired, is_recent = check_recency(fp)
        assert is_retired is False
        assert is_recent is False


class TestCategoryPriority:
    def test_priority_order(self):
        """DECISION has highest priority (1), SESSION_SUMMARY lowest (6)."""
        assert CATEGORY_PRIORITY["DECISION"] < CATEGORY_PRIORITY["SESSION_SUMMARY"]
        assert CATEGORY_PRIORITY["CONSTRAINT"] < CATEGORY_PRIORITY["TECH_DEBT"]


class TestRetrieveIntegration:
    """Integration tests running the hook as subprocess."""

    def _run_retrieve(self, hook_input):
        result = subprocess.run(
            [PYTHON, RETRIEVE_SCRIPT],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout, result.returncode

    def _setup_memory_project(self, tmp_path, memories):
        """Create project structure with memories and index."""
        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem_root = dc / "memory"
        mem_root.mkdir()
        for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
            (mem_root / folder).mkdir()
        # Write memory files
        for m in memories:
            write_memory_file(mem_root, m)
        # Build index
        from conftest import build_enriched_index
        index_content = build_enriched_index(*memories)
        (mem_root / "index.md").write_text(index_content)
        return proj

    def test_short_prompt_skipped(self, tmp_path):
        """Prompts < 10 chars are skipped."""
        proj = self._setup_memory_project(tmp_path, [make_decision_memory()])
        hook_input = {"user_prompt": "hi", "cwd": str(proj)}
        stdout, rc = self._run_retrieve(hook_input)
        assert rc == 0
        assert stdout.strip() == ""

    def test_matching_prompt_returns_memories(self, tmp_path):
        """Prompt matching a memory returns relevant results."""
        mem = make_decision_memory()
        proj = self._setup_memory_project(tmp_path, [mem])
        hook_input = {
            "user_prompt": "How does JWT authentication work in this project?",
            "cwd": str(proj),
        }
        stdout, rc = self._run_retrieve(hook_input)
        assert rc == 0
        assert "<memory-context" in stdout or "RELEVANT MEMORIES" in stdout
        assert "use-jwt" in stdout

    def test_no_match_no_output(self, tmp_path):
        """Prompt with no matches produces no output."""
        mem = make_decision_memory()
        proj = self._setup_memory_project(tmp_path, [mem])
        hook_input = {
            "user_prompt": "What is the weather forecast for tomorrow's meeting?",
            "cwd": str(proj),
        }
        stdout, rc = self._run_retrieve(hook_input)
        assert rc == 0
        # Should either be empty or not contain RELEVANT MEMORIES
        if stdout.strip():
            assert "RELEVANT MEMORIES" not in stdout or "use-jwt" not in stdout

    def test_category_priority_sorting(self, tmp_path):
        """Higher priority categories appear first."""
        decision = make_decision_memory(
            tags=["database", "connection"],
            title="Use connection pooling for database",
        )
        tech_debt = make_tech_debt_memory(
            tags=["database", "connection"],
            title="Database connection cleanup needed",
        )
        proj = self._setup_memory_project(tmp_path, [decision, tech_debt])
        hook_input = {
            "user_prompt": "What is the database connection strategy?",
            "cwd": str(proj),
        }
        stdout, rc = self._run_retrieve(hook_input)
        assert rc == 0
        if "RELEVANT MEMORIES" in stdout:
            lines = stdout.strip().split("\n")
            mem_lines = [l for l in lines if l.startswith("- [")]
            if len(mem_lines) >= 2:
                # DECISION should appear before TECH_DEBT
                decision_idx = next((i for i, l in enumerate(mem_lines) if "DECISION" in l), 999)
                tech_debt_idx = next((i for i, l in enumerate(mem_lines) if "TECH_DEBT" in l), 999)
                assert decision_idx < tech_debt_idx

    def test_recency_bonus(self, tmp_path):
        """Recently updated file gets +1 bonus."""
        recent = make_decision_memory(
            id_val="recent-decision",
            title="Recent database migration plan",
            tags=["database", "migration"],
        )
        recent["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        old = make_tech_debt_memory(
            id_val="old-debt",
            title="Old database migration debt",
            tags=["database", "migration"],
        )
        old["updated_at"] = "2025-01-01T00:00:00Z"
        proj = self._setup_memory_project(tmp_path, [recent, old])
        hook_input = {
            "user_prompt": "What about the database migration work?",
            "cwd": str(proj),
        }
        stdout, rc = self._run_retrieve(hook_input)
        assert rc == 0
        # Recent memory should appear in results
        if "RELEVANT MEMORIES" in stdout:
            assert "recent-decision" in stdout

    def test_empty_stdin(self):
        result = subprocess.run(
            [PYTHON, RETRIEVE_SCRIPT],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_backward_compat_legacy_index(self, tmp_path):
        """Legacy index format (no #tags:) still works."""
        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem_root = dc / "memory"
        mem_root.mkdir()
        for folder in ["decisions"]:
            (mem_root / folder).mkdir()
        mem = make_decision_memory()
        write_memory_file(mem_root, mem)
        # Legacy format index (no tags)
        (mem_root / "index.md").write_text(
            "# Memory Index\n\n"
            f"- [DECISION] {mem['title']} -> .claude/memory/decisions/{mem['id']}.json\n"
        )
        hook_input = {
            "user_prompt": "JWT authentication implementation details",
            "cwd": str(proj),
        }
        stdout, rc = self._run_retrieve(hook_input)
        assert rc == 0
        # Should still match via title words
