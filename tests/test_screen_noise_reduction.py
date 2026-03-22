"""Regression tests for screen noise reduction (SNR) changes.

Tests verify that SKILL.md directives, triage message formatting,
and script output structures remain consistent with noise reduction
goals.

Test coverage:
- 4.1: CUD narration suppression directive in SKILL.md
- 4.2: No inline triage_data JSON when file path is available
- Compact fallback JSON (no newlines/indent)
- Final output rule directive in SKILL.md
- Phase 1.5 silence directive in SKILL.md
- Candidate output includes category field
- Draft output includes category field
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
SKILL_PATH = Path(__file__).parent.parent / "skills" / "memory-management" / "SKILL.md"

sys.path.insert(0, str(SCRIPTS_DIR))

from memory_triage import (
    format_block_message,
    _deep_copy_parallel_defaults,
)

# Re-use conftest helpers for candidate/draft tests
from conftest import (
    make_decision_memory,
    write_memory_file,
    write_index,
)

CANDIDATE_SCRIPT = str(SCRIPTS_DIR / "memory_candidate.py")
DRAFT_SCRIPT = str(SCRIPTS_DIR / "memory_draft.py")
PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_results(category="DECISION", score=0.72, snippet="decided to use PG"):
    """Build a minimal triage results list."""
    return [{"category": category, "score": score, "snippets": [snippet]}]


def _make_parallel_config():
    """Return a fresh parallel config with defaults."""
    return _deep_copy_parallel_defaults()


# ---------------------------------------------------------------------------
# 4.1: SKILL.md CUD resolution suppression directive
# ---------------------------------------------------------------------------

class TestNoCudNarrationInSkill:
    """Verify Phase 1.5 CUD resolution is handled by a single script (inherently silent)."""

    def test_no_cud_narration_in_skill(self):
        """SKILL.md Phase 1.5 must use memory_orchestrate.py (single script, no LLM narration)."""
        content = SKILL_PATH.read_text()
        assert "memory_orchestrate.py" in content
        assert "Single Script" in content or "single script" in content.lower()


# ---------------------------------------------------------------------------
# 4.2: No inline triage_data JSON when file path is available
# ---------------------------------------------------------------------------

class TestTriageMessageNoInlineJson:
    """When triage_data_path is provided, inline <triage_data> must be absent."""

    def test_triage_message_no_inline_json_when_file_available(self):
        """File path tag present, no inline <triage_data> block."""
        results = _make_results()
        parallel_config = _make_parallel_config()

        message = format_block_message(
            results, {}, parallel_config,
            triage_data_path="/tmp/fake/triage-data.json",
        )

        # File reference must be present
        assert "<triage_data_file>/tmp/fake/triage-data.json</triage_data_file>" in message

        # Strip the file reference tags, then verify no inline <triage_data>
        stripped = message.replace("<triage_data_file>", "").replace("</triage_data_file>", "")
        assert "<triage_data>" not in stripped


# ---------------------------------------------------------------------------
# Compact fallback JSON (no indent, no embedded newlines)
# ---------------------------------------------------------------------------

class TestTriageCompactFallbackJson:
    """When triage_data_path=None, inline JSON must be compact."""

    def test_triage_compact_fallback_json(self):
        """Fallback inline <triage_data> JSON has no indent or embedded newlines."""
        results = _make_results()
        parallel_config = _make_parallel_config()

        message = format_block_message(
            results, {}, parallel_config,
            triage_data_path=None,
        )

        # Must have inline triage_data
        assert "<triage_data>" in message
        assert "</triage_data>" in message

        # Extract the JSON between tags
        start = message.index("<triage_data>") + len("<triage_data>")
        end = message.index("</triage_data>")
        json_str = message[start:end].strip()

        # JSON must be compact: no newlines inside the JSON string itself
        assert "\n" not in json_str, (
            f"Inline triage JSON should be compact (no newlines), got:\n{json_str}"
        )

        # Must be valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

        # Must NOT have indent (re-serialize with indent and compare)
        compact = json.dumps(parsed, separators=(",", ":"))
        assert json_str == compact, (
            f"Inline triage JSON should use compact separators.\n"
            f"Expected: {compact}\nGot: {json_str}"
        )


# ---------------------------------------------------------------------------
# SKILL.md Final output rule directive
# ---------------------------------------------------------------------------

class TestSkillFinalOutputRule:
    """Verify SKILL.md contains the Final output rule directive."""

    def test_skill_final_output_rule(self):
        """SKILL.md must instruct single-line save summary after Phase 3."""
        content = SKILL_PATH.read_text()
        assert "Final output rule" in content
        assert "output ONLY the single-line save summary" in content


# ---------------------------------------------------------------------------
# SKILL.md Phase 1.5 silence directive
# ---------------------------------------------------------------------------

class TestSkillPhase15Silence:
    """Verify Phase 1.5 is a single script invocation (inherently no LLM narration)."""

    def test_skill_phase15_silence(self):
        """SKILL.md Phase 1.5 must delegate to memory_orchestrate.py, not multi-step LLM execution."""
        content = SKILL_PATH.read_text()
        # Phase 1.5 is now a single script call -- no intermediate LLM steps to narrate
        assert "memory_orchestrate.py" in content
        assert "orchestration-result.json" in content


# ---------------------------------------------------------------------------
# Candidate output includes category field
# ---------------------------------------------------------------------------

class TestCandidateOutputHasCategory:
    """Verify memory_candidate.py output includes category field."""

    def test_candidate_output_has_category(self, tmp_path):
        """Candidate.py JSON output must include 'category' at top level."""
        # Set up a minimal memory root with an index (no memories)
        root = tmp_path / ".claude" / "memory"
        root.mkdir(parents=True)
        for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
            (root / folder).mkdir()
        write_index(root)

        new_info = "We decided to use PostgreSQL for the database"
        cmd = [
            PYTHON, CANDIDATE_SCRIPT,
            "--category", "decision",
            "--new-info", new_info,
            "--root", str(root),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        output = json.loads(result.stdout)
        assert "category" in output, (
            f"Candidate output must include 'category' field. Keys: {list(output.keys())}"
        )
        assert output["category"] == "decision"


# ---------------------------------------------------------------------------
# Draft output includes category field
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    subprocess.run(
        [sys.executable, "-c", "import pydantic"],
        capture_output=True,
    ).returncode != 0,
    reason="pydantic v2 not installed",
)
class TestDraftOutputHasCategory:
    """Verify memory_draft.py output includes category field."""

    def test_draft_output_has_category(self, tmp_path):
        """Draft.py JSON output must include 'category' at top level."""
        staging = tmp_path / "staging"
        staging.mkdir()

        # Write a minimal valid input file
        input_data = {
            "title": "Use PostgreSQL for database",
            "tags": ["database", "postgresql"],
            "confidence": 0.85,
            "change_summary": "Initial decision to use PostgreSQL",
            "content": {
                "status": "accepted",
                "context": "Needed a relational database with JSONB support",
                "decision": "Use PostgreSQL",
                "alternatives": [],
                "rationale": ["JSONB support", "Community support"],
                "consequences": ["Need PostgreSQL expertise"],
            },
        }
        input_path = staging / "input-decision.json"
        input_path.write_text(json.dumps(input_data))

        cmd = [
            PYTHON, DRAFT_SCRIPT,
            "--action", "create",
            "--category", "decision",
            "--input-file", str(input_path),
            "--root", str(staging),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        output = json.loads(result.stdout)
        assert "category" in output, (
            f"Draft output must include 'category' field. Keys: {list(output.keys())}"
        )
        assert output["category"] == "decision"

        # Also verify the draft file itself has category
        draft_path = output.get("draft_path")
        assert draft_path, "Draft output must include draft_path"
        draft_data = json.loads(Path(draft_path).read_text())
        assert draft_data["category"] == "decision"
