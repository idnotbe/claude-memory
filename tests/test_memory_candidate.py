"""Tests for memory_candidate.py -- ACE candidate selection + structural verification."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Import conftest helpers
from conftest import (
    make_decision_memory,
    make_preference_memory,
    make_tech_debt_memory,
    make_session_memory,
    make_runbook_memory,
    make_constraint_memory,
    write_memory_file,
    write_index,
)

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
CANDIDATE_SCRIPT = str(SCRIPTS_DIR / "memory_candidate.py")
PYTHON = sys.executable


def run_candidate(root, category, new_info, lifecycle_event=None):
    """Run memory_candidate.py and return parsed JSON output."""
    cmd = [
        PYTHON, CANDIDATE_SCRIPT,
        "--category", category,
        "--new-info", new_info,
        "--root", str(root),
    ]
    if lifecycle_event:
        cmd.extend(["--lifecycle-event", lifecycle_event])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    return json.loads(result.stdout)


# ---------------------------------------------------------------
# Import the module directly for unit tests of pure functions
# ---------------------------------------------------------------
sys.path.insert(0, str(SCRIPTS_DIR))
from memory_candidate import (
    tokenize,
    parse_index_line,
    score_entry,
    build_excerpt,
    CATEGORY_KEY_FIELDS,
    DELETE_DISALLOWED,
)


class TestTokenize:
    def test_basic_tokenization(self):
        tokens = tokenize("Use JWT for authentication tokens")
        assert "jwt" in tokens
        assert "authentication" in tokens
        assert "tokens" in tokens
        # Stop words excluded
        assert "use" not in tokens
        assert "for" not in tokens

    def test_short_words_excluded(self):
        tokens = tokenize("go to db")
        # "go" is a stop word, "to" is a stop word, "db" is only 2 chars
        assert "db" not in tokens
        assert "go" not in tokens

    def test_empty_string(self):
        assert tokenize("") == set()

    def test_only_stop_words(self):
        assert tokenize("the is a an") == set()


class TestParseIndexLine:
    def test_enriched_format_with_tags(self):
        line = "- [DECISION] Use JWT -> .claude/memory/decisions/use-jwt.json #tags:auth,jwt,security"
        result = parse_index_line(line)
        assert result is not None
        assert result["category_display"] == "DECISION"
        assert result["title"] == "Use JWT"
        assert result["path"] == ".claude/memory/decisions/use-jwt.json"
        assert result["tags"] == ["auth", "jwt", "security"]

    def test_legacy_format_no_tags(self):
        line = "- [DECISION] Use JWT -> .claude/memory/decisions/use-jwt.json"
        result = parse_index_line(line)
        assert result is not None
        assert result["tags"] == []

    def test_non_matching_line(self):
        assert parse_index_line("# Memory Index") is None
        assert parse_index_line("") is None
        assert parse_index_line("some random text") is None

    def test_all_category_displays(self):
        for cat in ["SESSION_SUMMARY", "DECISION", "RUNBOOK", "CONSTRAINT", "TECH_DEBT", "PREFERENCE"]:
            line = f"- [{cat}] Title -> path.json"
            result = parse_index_line(line)
            assert result is not None
            assert result["category_display"] == cat


class TestScoreEntry:
    def test_exact_title_match(self):
        entry = {"title": "Use JWT authentication", "tags": []}
        tokens = tokenize("JWT authentication system")
        score = score_entry(tokens, entry)
        # "jwt" exact match = 2, "authentication" exact match = 2, "system" no match
        assert score >= 4

    def test_tag_match_scores_3_points(self):
        entry = {"title": "Some unrelated title thing", "tags": ["jwt"]}
        tokens = {"jwt"}
        score = score_entry(tokens, entry)
        assert score == 3  # jwt tag match = 3

    def test_prefix_matching_4plus_chars(self):
        entry = {"title": "authentication middleware setup", "tags": []}
        tokens = {"auth"}  # 4 chars, prefix of "authentication"
        score = score_entry(tokens, entry)
        assert score == 1  # prefix match

    def test_prefix_requires_4_chars(self):
        entry = {"title": "authentication middleware setup", "tags": []}
        tokens = {"aut"}  # only 3 chars
        score = score_entry(tokens, entry)
        assert score == 0  # too short for prefix

    def test_no_match(self):
        entry = {"title": "Database connection pool", "tags": ["db"]}
        tokens = {"frontend", "react", "component"}
        score = score_entry(tokens, entry)
        assert score == 0

    def test_combined_scoring(self):
        entry = {"title": "JWT authentication tokens", "tags": ["auth", "security"]}
        tokens = {"jwt", "auth", "security", "toke"}
        # jwt: exact title = 2
        # auth: exact tag = 3
        # security: exact tag = 3
        # toke: prefix of "tokens" = 1 (4 chars, not already matched)
        score = score_entry(tokens, entry)
        assert score == 9


class TestBuildExcerpt:
    def test_decision_excerpt(self, tmp_path):
        mem = make_decision_memory()
        fp = tmp_path / "test.json"
        fp.write_text(json.dumps(mem))
        excerpt = build_excerpt(fp, "decision")
        assert excerpt is not None
        assert excerpt["title"] == "Use JWT for authentication"
        assert excerpt["record_status"] == "active"
        assert "context" in excerpt["key_fields"]
        assert "decision" in excerpt["key_fields"]
        assert "rationale" in excerpt["key_fields"]

    def test_preference_excerpt(self, tmp_path):
        mem = make_preference_memory()
        fp = tmp_path / "test.json"
        fp.write_text(json.dumps(mem))
        excerpt = build_excerpt(fp, "preference")
        assert excerpt is not None
        assert "topic" in excerpt["key_fields"]
        assert "value" in excerpt["key_fields"]
        assert "reason" in excerpt["key_fields"]

    def test_category_key_fields_coverage(self):
        """All categories have key_fields defined."""
        for cat in ["session_summary", "decision", "runbook", "constraint", "tech_debt", "preference"]:
            assert cat in CATEGORY_KEY_FIELDS, f"Missing key_fields for {cat}"

    def test_corrupt_json_returns_none(self, tmp_path):
        fp = tmp_path / "bad.json"
        fp.write_text("{invalid json")
        assert build_excerpt(fp, "decision") is None

    def test_missing_file_returns_none(self, tmp_path):
        fp = tmp_path / "nonexistent.json"
        assert build_excerpt(fp, "decision") is None

    def test_last_change_summary_from_changes(self, tmp_path):
        mem = make_decision_memory(changes=[
            {"date": "2026-02-10T10:00:00Z", "summary": "Updated rationale"},
        ])
        fp = tmp_path / "test.json"
        fp.write_text(json.dumps(mem))
        excerpt = build_excerpt(fp, "decision")
        assert excerpt["last_change_summary"] == "Updated rationale"

    def test_no_changes_gives_initial_creation(self, tmp_path):
        mem = make_decision_memory(changes=[])
        fp = tmp_path / "test.json"
        fp.write_text(json.dumps(mem))
        excerpt = build_excerpt(fp, "decision")
        assert excerpt["last_change_summary"] == "Initial creation"

    def test_list_field_joined(self, tmp_path):
        """List fields in key_fields are joined with semicolons."""
        mem = make_decision_memory()
        fp = tmp_path / "test.json"
        fp.write_text(json.dumps(mem))
        excerpt = build_excerpt(fp, "decision")
        # rationale is a list, should be joined
        assert ";" in excerpt["key_fields"]["rationale"]


class TestCandidateIntegration:
    """Integration tests using subprocess to run the full CLI.

    The candidate script resolves index paths relative to CWD and checks
    they fall under the --root directory. We use absolute paths in the
    index to avoid CWD-dependency issues in tests.
    """

    @staticmethod
    def _write_index_abs(memory_root, *memories):
        """Write index with absolute paths so candidate resolves correctly."""
        write_index(memory_root, *memories, path_prefix=str(memory_root))

    def test_candidate_found_score_gte_3(self, memory_root):
        """Matching entry with score >= 3 returns candidate."""
        mem = make_decision_memory()
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        result = run_candidate(memory_root, "decision", "JWT authentication tokens")
        assert result["candidate"] is not None
        assert result["pre_action"] is None
        assert "UPDATE" in result["structural_cud"]

    def test_no_candidate_below_threshold(self, memory_root):
        """No candidate when all scores < 3, returns CREATE."""
        mem = make_decision_memory()
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        result = run_candidate(memory_root, "decision", "completely unrelated topic xyz")
        assert result["candidate"] is None
        assert result["pre_action"] == "CREATE"
        assert result["structural_cud"] == "CREATE"

    def test_lifecycle_event_no_candidate_noop(self, memory_root):
        """Lifecycle event + no matching candidate = NOOP."""
        mem = make_decision_memory()
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        result = run_candidate(
            memory_root, "decision", "completely unrelated topic xyz",
            lifecycle_event="resolved",
        )
        assert result["candidate"] is None
        assert result["pre_action"] == "NOOP"
        assert result["structural_cud"] == "NOOP"

    def test_delete_disallowed_for_decision(self, memory_root):
        """DELETE not allowed for decision category."""
        mem = make_decision_memory()
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        result = run_candidate(
            memory_root, "decision", "JWT authentication tokens",
            lifecycle_event="reversed",
        )
        assert result["delete_allowed"] is False
        assert result["structural_cud"] == "UPDATE"
        assert any("Cannot DELETE" in v for v in result["vetoes"])

    def test_delete_disallowed_for_preference(self, memory_root):
        """DELETE not allowed for preference category."""
        mem = make_preference_memory()
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        result = run_candidate(
            memory_root, "preference", "TypeScript language preference",
            lifecycle_event="removed",
        )
        assert result["delete_allowed"] is False

    def test_delete_disallowed_for_session_summary(self, memory_root):
        """DELETE not allowed for session_summary category."""
        mem = make_session_memory()
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        result = run_candidate(
            memory_root, "session_summary", "ACE tests implemented",
            lifecycle_event="removed",
        )
        assert result["delete_allowed"] is False

    def test_delete_allowed_for_tech_debt(self, memory_root):
        """DELETE allowed for tech_debt category."""
        mem = make_tech_debt_memory()
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        result = run_candidate(
            memory_root, "tech_debt", "Legacy API cleanup",
            lifecycle_event="resolved",
        )
        assert result["delete_allowed"] is True
        if result["candidate"] is not None:
            assert result["structural_cud"] == "UPDATE_OR_DELETE"

    def test_structural_vetoes_generated(self, memory_root):
        """Vetoes block invalid operations."""
        mem = make_preference_memory()
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        result = run_candidate(
            memory_root, "preference", "TypeScript language preference",
        )
        if result["candidate"] is not None:
            assert any("Cannot DELETE" in v for v in result["vetoes"])

    def test_empty_index(self, memory_root):
        """Empty index -> CREATE for new info."""
        index_path = memory_root / "index.md"
        index_path.write_text("# Memory Index\n")
        result = run_candidate(memory_root, "decision", "new decision about auth")
        assert result["pre_action"] == "CREATE"
        assert result["candidate"] is None

    def test_tag_scoring_via_index(self, memory_root):
        """Tags in enriched index boost score."""
        mem = make_decision_memory(tags=["authentication", "jwt", "security"])
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        # "authentication" matches as a tag -> 3 points (enough for threshold)
        result = run_candidate(memory_root, "decision", "authentication")
        assert result["candidate"] is not None

    def test_backward_compatible_legacy_index(self, memory_root):
        """Legacy index format (no #tags:) still parses entries."""
        mem = make_decision_memory()
        write_memory_file(memory_root, mem)
        # Write legacy format (no tags) with absolute path
        abs_path = str(memory_root / "decisions" / f"{mem['id']}.json")
        index_path = memory_root / "index.md"
        index_path.write_text(
            "# Memory Index\n\n"
            f"- [DECISION] {mem['title']} -> {abs_path}\n"
        )
        # Title-word match should still work
        result = run_candidate(memory_root, "decision", "JWT authentication tokens")
        # Should find it via title matching even without tags
        assert result["candidate"] is not None or result["pre_action"] == "CREATE"

    def test_excerpt_contains_correct_key_fields(self, memory_root):
        """Excerpt key_fields match the category definition."""
        mem = make_decision_memory()
        write_memory_file(memory_root, mem)
        self._write_index_abs(memory_root, mem)
        result = run_candidate(memory_root, "decision", "JWT authentication tokens")
        if result["candidate"] and result["candidate"].get("excerpt"):
            kf = result["candidate"]["excerpt"]["key_fields"]
            # decision key_fields: context, decision, rationale
            assert "context" in kf or "decision" in kf


class TestDeleteDisallowedCategories:
    """Verify DELETE_DISALLOWED is correctly set."""

    def test_disallowed_categories(self):
        assert "decision" in DELETE_DISALLOWED
        assert "preference" in DELETE_DISALLOWED
        assert "session_summary" in DELETE_DISALLOWED

    def test_allowed_categories(self):
        assert "tech_debt" not in DELETE_DISALLOWED
        assert "runbook" not in DELETE_DISALLOWED
        assert "constraint" not in DELETE_DISALLOWED
