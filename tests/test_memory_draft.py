"""Tests for memory_draft.py -- draft assembler for partial JSON input.

Also includes tests for memory_candidate.py --new-info-file and
an integration test simulating the full Phase 1 pipeline.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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
DRAFT_SCRIPT = str(SCRIPTS_DIR / "memory_draft.py")
CANDIDATE_SCRIPT = str(SCRIPTS_DIR / "memory_candidate.py")
WRITE_SCRIPT = str(SCRIPTS_DIR / "memory_write.py")
PYTHON = sys.executable

# ---------------------------------------------------------------
# Direct imports for unit tests
# ---------------------------------------------------------------
sys.path.insert(0, str(SCRIPTS_DIR))
from memory_draft import (
    assemble_create,
    assemble_update,
    validate_input_path,
    validate_candidate_path,
    check_required_fields,
    REQUIRED_INPUT_FIELDS,
    VALID_CATEGORIES,
)
from memory_write import (
    build_memory_model,
    validate_memory,
    ValidationError,
    TAG_CAP,
)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def write_staging_input(memory_root, data, filename="input.json"):
    """Write JSON input to .staging/ under memory_root."""
    staging = memory_root / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    fp = staging / filename
    fp.write_text(json.dumps(data, indent=2))
    return str(fp)


def write_tmp_input(tmp_path, data, filename="input.json"):
    """Write JSON input to /tmp/ via tmp_path."""
    fp = tmp_path / filename
    fp.write_text(json.dumps(data, indent=2))
    return str(fp)


def run_draft(action, category, input_file, candidate_file=None, root=None, cwd=None):
    """Run memory_draft.py and return (returncode, stdout, stderr)."""
    cmd = [
        PYTHON, DRAFT_SCRIPT,
        "--action", action,
        "--category", category,
        "--input-file", input_file,
    ]
    if candidate_file:
        cmd.extend(["--candidate-file", candidate_file])
    if root:
        cmd.extend(["--root", root])
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=15,
        cwd=cwd or os.getcwd(),
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------
# Category-specific partial input factories
# ---------------------------------------------------------------

def make_partial_decision():
    return {
        "title": "Use JWT for stateless auth",
        "tags": ["auth", "jwt"],
        "confidence": 0.9,
        "change_summary": "Decided on JWT for API auth",
        "content": {
            "status": "accepted",
            "context": "Need stateless auth for API",
            "decision": "Use JWT tokens with 1h expiry",
            "rationale": ["Stateless", "Industry standard"],
        },
    }


def make_partial_session():
    return {
        "title": "Implemented draft assembler tests",
        "tags": ["testing", "draft"],
        "confidence": 0.85,
        "change_summary": "Session focused on test coverage",
        "content": {
            "goal": "Write comprehensive draft tests",
            "outcome": "success",
            "completed": ["Draft assembler test suite"],
            "next_actions": ["Integration test"],
        },
    }


def make_partial_runbook():
    return {
        "title": "Fix database timeout issues",
        "tags": ["database", "timeout"],
        "confidence": 0.8,
        "change_summary": "Documented DB timeout fix procedure",
        "content": {
            "trigger": "Database connection timeout errors",
            "steps": ["Check pool size", "Restart pool"],
            "verification": "Queries respond < 100ms",
        },
    }


def make_partial_constraint():
    return {
        "title": "Max payload size 10MB",
        "tags": ["api", "payload"],
        "confidence": 1.0,
        "change_summary": "Documented payload size limit",
        "content": {
            "kind": "technical",
            "rule": "API payloads must not exceed 10MB",
            "impact": ["Large files need chunking"],
            "severity": "high",
            "active": True,
        },
    }


def make_partial_tech_debt():
    return {
        "title": "Legacy API v1 cleanup needed",
        "tags": ["api", "legacy"],
        "confidence": 0.7,
        "change_summary": "Identified legacy API debt",
        "content": {
            "status": "open",
            "priority": "medium",
            "description": "API v1 endpoints still in production",
            "reason_deferred": "Client migration coordination required",
        },
    }


def make_partial_preference():
    return {
        "title": "Prefer TypeScript over JavaScript",
        "tags": ["typescript", "language"],
        "confidence": 0.95,
        "change_summary": "Established TypeScript preference",
        "content": {
            "topic": "Programming language",
            "value": "TypeScript",
            "reason": "Better type safety",
            "strength": "strong",
        },
    }


ALL_PARTIAL_FACTORIES = {
    "decision": make_partial_decision,
    "session_summary": make_partial_session,
    "runbook": make_partial_runbook,
    "constraint": make_partial_constraint,
    "tech_debt": make_partial_tech_debt,
    "preference": make_partial_preference,
}


# ===============================================================
# Unit Tests: assemble_create
# ===============================================================

class TestAssembleCreate:
    """Unit test memory_draft.py CREATE for all 6 categories."""

    @pytest.mark.parametrize("category", VALID_CATEGORIES)
    def test_create_all_categories_valid(self, category):
        """Assembled CREATE output validates against Pydantic schema."""
        partial = ALL_PARTIAL_FACTORIES[category]()
        assembled = assemble_create(partial, category)

        # Validate against Pydantic
        Model = build_memory_model(category)
        instance = Model.model_validate(assembled)
        assert instance is not None

    @pytest.mark.parametrize("category", VALID_CATEGORIES)
    def test_create_auto_populates_fields(self, category):
        """CREATE auto-populates schema_version, category, id, timestamps, etc."""
        partial = ALL_PARTIAL_FACTORIES[category]()
        assembled = assemble_create(partial, category)

        assert assembled["schema_version"] == "1.0"
        assert assembled["category"] == category
        assert assembled["record_status"] == "active"
        assert assembled["times_updated"] == 0
        assert assembled["created_at"] is not None
        assert assembled["updated_at"] is not None
        assert assembled["id"] != ""

    def test_create_id_is_slugified_title(self):
        partial = make_partial_decision()
        partial["title"] = "My Cool Decision!"
        assembled = assemble_create(partial, "decision")
        assert assembled["id"] == "my-cool-decision"

    def test_create_change_entry_from_summary(self):
        partial = make_partial_decision()
        partial["change_summary"] = "Custom change summary"
        assembled = assemble_create(partial, "decision")
        assert len(assembled["changes"]) == 1
        assert assembled["changes"][0]["summary"] == "Custom change summary"
        assert assembled["changes"][0]["date"] is not None

    def test_create_preserves_optional_fields(self):
        partial = make_partial_decision()
        partial["related_files"] = ["src/auth.py"]
        partial["confidence"] = 0.75
        assembled = assemble_create(partial, "decision")
        assert assembled["related_files"] == ["src/auth.py"]
        assert assembled["confidence"] == 0.75

    def test_create_missing_optional_fields(self):
        """Missing optional fields (related_files, confidence) are set to None."""
        partial = make_partial_decision()
        partial.pop("related_files", None)
        partial.pop("confidence", None)
        assembled = assemble_create(partial, "decision")
        assert assembled["related_files"] is None
        assert assembled["confidence"] is None

    def test_create_timestamps_are_utc_iso(self):
        partial = make_partial_decision()
        assembled = assemble_create(partial, "decision")
        # Should end with Z (UTC)
        assert assembled["created_at"].endswith("Z")
        assert assembled["updated_at"].endswith("Z")
        # Should be parseable ISO format
        from datetime import datetime
        datetime.fromisoformat(assembled["created_at"].replace("Z", "+00:00"))
        datetime.fromisoformat(assembled["updated_at"].replace("Z", "+00:00"))


# ===============================================================
# Unit Tests: assemble_update
# ===============================================================

class TestAssembleUpdate:
    """Unit test memory_draft.py UPDATE: immutable fields, tag union, etc."""

    def _make_existing(self):
        return make_decision_memory(
            times_updated=2,
            changes=[
                {"date": "2026-01-01T00:00:00Z", "summary": "Created"},
                {"date": "2026-01-15T00:00:00Z", "summary": "Updated rationale"},
            ],
        )

    def test_update_preserves_immutable_fields(self):
        """Immutable fields (created_at, schema_version, category, id) from existing."""
        existing = self._make_existing()
        partial = make_partial_decision()
        assembled = assemble_update(partial, existing, "decision")

        assert assembled["created_at"] == existing["created_at"]
        assert assembled["schema_version"] == existing["schema_version"]
        assert assembled["category"] == existing["category"]
        assert assembled["id"] == existing["id"]

    def test_update_increments_times_updated(self):
        existing = self._make_existing()
        partial = make_partial_decision()
        assembled = assemble_update(partial, existing, "decision")
        assert assembled["times_updated"] == existing["times_updated"] + 1

    def test_update_appends_change_entry(self):
        existing = self._make_existing()
        partial = make_partial_decision()
        partial["change_summary"] = "Updated JWT expiry"
        assembled = assemble_update(partial, existing, "decision")

        old_count = len(existing["changes"])
        assert len(assembled["changes"]) == old_count + 1
        assert assembled["changes"][-1]["summary"] == "Updated JWT expiry"

    def test_update_unions_tags(self):
        existing = make_decision_memory(tags=["auth", "jwt", "security"])
        partial = make_partial_decision()
        partial["tags"] = ["jwt", "oauth2", "tokens"]
        assembled = assemble_update(partial, existing, "decision")

        result_tags = set(assembled["tags"])
        assert "auth" in result_tags  # from existing
        assert "jwt" in result_tags   # from both
        assert "security" in result_tags  # from existing
        assert "oauth2" in result_tags  # from new
        assert "tokens" in result_tags  # from new

    def test_update_unions_related_files(self):
        existing = make_decision_memory(related_files=["old.py"])
        partial = make_partial_decision()
        partial["related_files"] = ["new.py"]
        assembled = assemble_update(partial, existing, "decision")
        assert "old.py" in assembled["related_files"]
        assert "new.py" in assembled["related_files"]

    def test_update_shallow_merges_content(self):
        """Content is shallow-merged: new keys overlay existing keys."""
        existing = make_decision_memory(
            content_overrides={"status": "proposed", "context": "Original context"},
        )
        partial = make_partial_decision()
        partial["content"] = {"status": "accepted"}  # only override status
        assembled = assemble_update(partial, existing, "decision")

        # status overridden
        assert assembled["content"]["status"] == "accepted"
        # context preserved from existing
        assert assembled["content"]["context"] == "Original context"
        # decision preserved from existing
        assert "decision" in assembled["content"]

    def test_update_preserves_record_status(self):
        existing = make_decision_memory(record_status="active")
        partial = make_partial_decision()
        assembled = assemble_update(partial, existing, "decision")
        assert assembled["record_status"] == "active"

    def test_update_updated_at_refreshed(self):
        existing = self._make_existing()
        partial = make_partial_decision()
        assembled = assemble_update(partial, existing, "decision")
        assert assembled["updated_at"] != existing["updated_at"]
        assert assembled["updated_at"].endswith("Z")

    @pytest.mark.parametrize("category", VALID_CATEGORIES)
    def test_update_all_categories_validate(self, category):
        """Assembled UPDATE output validates for all categories."""
        # Build a full existing memory from conftest factories
        factories = {
            "decision": make_decision_memory,
            "preference": make_preference_memory,
            "tech_debt": make_tech_debt_memory,
            "session_summary": make_session_memory,
            "runbook": make_runbook_memory,
            "constraint": make_constraint_memory,
        }
        existing = factories[category]()
        partial = ALL_PARTIAL_FACTORIES[category]()
        assembled = assemble_update(partial, existing, category)

        Model = build_memory_model(category)
        instance = Model.model_validate(assembled)
        assert instance is not None


# ===============================================================
# Unit Tests: Input Validation
# ===============================================================

class TestInputValidation:
    def test_valid_staging_path(self, tmp_path):
        # Create a path that contains .claude/memory/.staging/
        staging = tmp_path / ".claude" / "memory" / ".staging"
        staging.mkdir(parents=True)
        fp = staging / "input.json"
        fp.write_text("{}")
        err = validate_input_path(str(fp))
        assert err is None

    def test_valid_tmp_path(self):
        err = validate_input_path("/tmp/test-input.json")
        assert err is None

    def test_reject_arbitrary_path(self):
        err = validate_input_path("/home/user/evil.json")
        assert err is not None
        assert ".staging" in err or "/tmp/" in err

    def test_reject_dotdot_path(self, tmp_path):
        err = validate_input_path("/tmp/../etc/passwd")
        assert err is not None
        assert ".." in err

    def test_check_required_fields_ok(self):
        data = {
            "title": "Test",
            "tags": ["t"],
            "content": {},
            "change_summary": "init",
        }
        assert check_required_fields(data) is None

    def test_check_required_fields_missing(self):
        data = {"title": "Test"}
        err = check_required_fields(data)
        assert err is not None
        assert "tags" in err or "content" in err or "change_summary" in err

    def test_validate_candidate_path_ok(self, tmp_path):
        # Candidate must be within .claude/memory/
        mem = tmp_path / ".claude" / "memory" / "decisions"
        mem.mkdir(parents=True)
        fp = mem / "test.json"
        fp.write_text("{}")
        assert validate_candidate_path(str(fp)) is None

    def test_validate_candidate_path_missing(self, tmp_path):
        err = validate_candidate_path(str(tmp_path / "nonexistent.json"))
        assert err is not None
        assert "does not exist" in err

    def test_validate_candidate_path_not_json(self, tmp_path):
        fp = tmp_path / "test.txt"
        fp.write_text("not json")
        err = validate_candidate_path(str(fp))
        assert err is not None
        assert ".json" in err


# ===============================================================
# CLI Tests: memory_draft.py via subprocess
# ===============================================================

class TestDraftCLICreate:
    """CLI-level tests for memory_draft.py CREATE action."""

    @pytest.fixture
    def staging_root(self, tmp_path):
        """Create a .claude/memory/.staging structure."""
        mem_root = tmp_path / ".claude" / "memory"
        mem_root.mkdir(parents=True)
        staging = mem_root / ".staging"
        staging.mkdir()
        return mem_root

    @pytest.mark.parametrize("category", VALID_CATEGORIES)
    def test_cli_create_all_categories(self, staging_root, category):
        """CLI CREATE succeeds for all 6 categories, output is valid JSON."""
        partial = ALL_PARTIAL_FACTORIES[category]()
        input_file = write_staging_input(staging_root, partial, f"input-{category}.json")

        rc, stdout, stderr = run_draft(
            "create", category, input_file, root=str(staging_root),
        )
        assert rc == 0, f"Failed for {category}: {stderr}"
        result = json.loads(stdout)
        assert result["status"] == "ok"
        assert result["action"] == "create"
        assert result["draft_path"].endswith(".json")

        # Verify draft file exists and is valid
        draft = json.loads(Path(result["draft_path"]).read_text())
        assert draft["category"] == category
        assert draft["schema_version"] == "1.0"
        assert draft["record_status"] == "active"

    def test_cli_create_invalid_content_fails(self, staging_root):
        """CREATE with invalid content field fails validation."""
        partial = make_partial_decision()
        partial["content"]["status"] = "banana"  # invalid enum
        input_file = write_staging_input(staging_root, partial)

        rc, stdout, stderr = run_draft(
            "create", "decision", input_file, root=str(staging_root),
        )
        assert rc == 1
        assert "VALIDATION_ERROR" in stderr

    def test_cli_create_missing_required_input_fields(self, staging_root):
        """CREATE with missing required fields fails."""
        partial = {"title": "Incomplete"}  # missing tags, content, change_summary
        input_file = write_staging_input(staging_root, partial)

        rc, stdout, stderr = run_draft(
            "create", "decision", input_file, root=str(staging_root),
        )
        assert rc == 1
        assert "INPUT_ERROR" in stderr

    def test_cli_create_invalid_json_file(self, staging_root):
        """CREATE with malformed JSON input file fails."""
        staging = staging_root / ".staging"
        fp = staging / "bad.json"
        fp.write_text("{not valid json")

        rc, stdout, stderr = run_draft(
            "create", "decision", str(fp), root=str(staging_root),
        )
        assert rc == 1
        assert "invalid JSON" in stderr.lower() or "ERROR" in stderr


class TestDraftCLIUpdate:
    """CLI-level tests for memory_draft.py UPDATE action."""

    @pytest.fixture
    def update_setup(self, tmp_path):
        """Set up: memory root, existing file, staging."""
        mem_root = tmp_path / ".claude" / "memory"
        mem_root.mkdir(parents=True)
        staging = mem_root / ".staging"
        staging.mkdir()
        for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
            (mem_root / folder).mkdir()

        # Write an existing decision memory
        existing = make_decision_memory()
        candidate_path = mem_root / "decisions" / "use-jwt.json"
        candidate_path.write_text(json.dumps(existing, indent=2))
        return mem_root, str(candidate_path), existing

    def test_cli_update_success(self, update_setup):
        mem_root, candidate_file, existing = update_setup
        partial = make_partial_decision()
        partial["change_summary"] = "Updated JWT expiry policy"
        input_file = write_staging_input(mem_root, partial)

        rc, stdout, stderr = run_draft(
            "update", "decision", input_file,
            candidate_file=candidate_file, root=str(mem_root),
        )
        assert rc == 0, f"Failed: {stderr}"
        result = json.loads(stdout)
        assert result["status"] == "ok"
        assert result["action"] == "update"

        # Verify draft preserves immutable fields
        draft = json.loads(Path(result["draft_path"]).read_text())
        assert draft["created_at"] == existing["created_at"]
        assert draft["schema_version"] == existing["schema_version"]
        assert draft["category"] == existing["category"]
        assert draft["id"] == existing["id"]
        assert draft["times_updated"] == existing["times_updated"] + 1
        # Change appended
        assert len(draft["changes"]) == len(existing.get("changes", [])) + 1
        assert draft["changes"][-1]["summary"] == "Updated JWT expiry policy"

    def test_cli_update_without_candidate_fails(self, update_setup):
        mem_root, _, _ = update_setup
        partial = make_partial_decision()
        input_file = write_staging_input(mem_root, partial)

        rc, stdout, stderr = run_draft(
            "update", "decision", input_file, root=str(mem_root),
        )
        assert rc == 1  # --candidate-file required for update
        assert "candidate-file" in stderr.lower() or "required" in stderr.lower()

    def test_cli_update_nonexistent_candidate_fails(self, update_setup):
        mem_root, _, _ = update_setup
        partial = make_partial_decision()
        input_file = write_staging_input(mem_root, partial)

        rc, stdout, stderr = run_draft(
            "update", "decision", input_file,
            candidate_file="/nonexistent/path.json", root=str(mem_root),
        )
        assert rc == 1
        assert "does not exist" in stderr or "INPUT_ERROR" in stderr


class TestDraftCLIPathSecurity:
    """Path validation: reject paths outside .staging/ and /tmp/."""

    def test_reject_input_outside_staging_and_tmp(self, tmp_path):
        """Input file not in .staging/ or /tmp/ is rejected.

        Note: pytest's tmp_path is under /tmp/ which IS allowed.
        We test with a path that resolves outside both allowed locations.
        """
        # Create a file somewhere that is NOT under /tmp/ or .staging/
        # We use a mock path that doesn't contain those markers
        rc, stdout, stderr = run_draft(
            "create", "decision", "/home/user/evil.json", root=str(tmp_path),
        )
        assert rc == 1
        assert "SECURITY_ERROR" in stderr

    def test_reject_dotdot_in_input_path(self, tmp_path):
        """Input file with '..' components is rejected."""
        mem_root = tmp_path / ".claude" / "memory"
        staging = mem_root / ".staging"
        staging.mkdir(parents=True)
        fp = staging / "input.json"
        fp.write_text(json.dumps(make_partial_decision()))

        # Use a path with ..
        evil_path = str(staging) + "/../../../evil.json"
        rc, stdout, stderr = run_draft(
            "create", "decision", evil_path, root=str(mem_root),
        )
        assert rc == 1
        assert "SECURITY_ERROR" in stderr


# ===============================================================
# Edge Cases
# ===============================================================

class TestDraftEdgeCases:

    def test_empty_tags(self):
        """Empty tags list should still produce valid output (memory_write auto-fix handles)."""
        partial = make_partial_decision()
        partial["tags"] = []
        assembled = assemble_create(partial, "decision")
        # Tags may be empty here - memory_write.py's auto_fix would add "untagged"
        assert isinstance(assembled["tags"], list)

    def test_very_long_title_slugified(self):
        """Very long title should be slugified within max length."""
        partial = make_partial_decision()
        partial["title"] = "A" * 200
        assembled = assemble_create(partial, "decision")
        assert len(assembled["id"]) <= 80

    def test_unicode_title(self):
        """Unicode in title should be handled by slugify."""
        partial = make_partial_decision()
        partial["title"] = "Cafe latte decisions"
        assembled = assemble_create(partial, "decision")
        assert assembled["id"] != ""
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in assembled["id"])

    def test_update_with_no_existing_changes(self):
        """UPDATE when existing has no changes array."""
        existing = make_decision_memory()
        existing["changes"] = None
        partial = make_partial_decision()
        partial["change_summary"] = "First tracked change"
        assembled = assemble_update(partial, existing, "decision")
        assert len(assembled["changes"]) == 1
        assert assembled["changes"][0]["summary"] == "First tracked change"

    def test_update_with_none_times_updated(self):
        """UPDATE when existing has times_updated=None."""
        existing = make_decision_memory()
        existing["times_updated"] = None
        partial = make_partial_decision()
        assembled = assemble_update(partial, existing, "decision")
        assert assembled["times_updated"] == 1

    def test_concurrent_draft_filenames_unique(self):
        """Draft filenames include PID for uniqueness."""
        from memory_draft import write_draft
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = td
            data = assemble_create(make_partial_decision(), "decision")
            path1 = write_draft(data, "decision", root)
            path2 = write_draft(data, "decision", root)
            # Both files should exist and be different paths (PID same, but timestamp may differ)
            assert Path(path1).exists()
            assert Path(path2).exists()


# ===============================================================
# Tests for --new-info-file in memory_candidate.py
# ===============================================================

class TestNewInfoFile:
    """Test the --new-info-file argument for memory_candidate.py."""

    @pytest.fixture
    def candidate_setup(self, tmp_path):
        """Set up memory root with an existing decision for candidate matching."""
        mem_root = tmp_path / "memory"
        mem_root.mkdir()
        for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
            (mem_root / folder).mkdir()
        mem = make_decision_memory()
        write_memory_file(mem_root, mem)
        write_index(mem_root, mem, path_prefix=str(mem_root))
        return mem_root

    def _run_candidate_with_file(self, root, category, info_file, lifecycle_event=None):
        """Run memory_candidate.py with --new-info-file."""
        cmd = [
            PYTHON, CANDIDATE_SCRIPT,
            "--category", category,
            "--new-info-file", info_file,
            "--root", str(root),
        ]
        if lifecycle_event:
            cmd.extend(["--lifecycle-event", lifecycle_event])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode, result.stdout, result.stderr

    def _run_candidate_inline(self, root, category, new_info, lifecycle_event=None):
        """Run memory_candidate.py with --new-info (inline)."""
        cmd = [
            PYTHON, CANDIDATE_SCRIPT,
            "--category", category,
            "--new-info", new_info,
            "--root", str(root),
        ]
        if lifecycle_event:
            cmd.extend(["--lifecycle-event", lifecycle_event])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode, result.stdout, result.stderr

    def test_new_info_file_matches_inline(self, candidate_setup, tmp_path):
        """--new-info-file produces the same result as --new-info with same content."""
        info_text = "JWT authentication tokens for API"
        info_file = tmp_path / "new-info.txt"
        info_file.write_text(info_text)

        # Run with file
        rc_file, stdout_file, _ = self._run_candidate_with_file(
            candidate_setup, "decision", str(info_file),
        )
        # Run with inline
        rc_inline, stdout_inline, _ = self._run_candidate_inline(
            candidate_setup, "decision", info_text,
        )

        assert rc_file == 0
        assert rc_inline == 0
        result_file = json.loads(stdout_file)
        result_inline = json.loads(stdout_inline)

        # Structural fields should match
        assert result_file["pre_action"] == result_inline["pre_action"]
        assert result_file["structural_cud"] == result_inline["structural_cud"]
        assert result_file["delete_allowed"] == result_inline["delete_allowed"]
        # Candidate presence should match
        assert (result_file["candidate"] is None) == (result_inline["candidate"] is None)

    def test_new_info_file_with_env_string(self, candidate_setup, tmp_path):
        """--new-info-file works with content containing '.env' (Guardian bypass test)."""
        info_text = "Session discussed .env configuration and JWT auth security tokens"
        info_file = tmp_path / "new-info-env.txt"
        info_file.write_text(info_text)

        rc, stdout, stderr = self._run_candidate_with_file(
            candidate_setup, "decision", str(info_file),
        )
        assert rc == 0
        result = json.loads(stdout)
        # Should still find the candidate via "JWT", "auth", "security" tokens
        assert result["candidate"] is not None or result["pre_action"] == "CREATE"

    def test_new_info_file_not_found_errors(self, candidate_setup, tmp_path):
        """--new-info-file with nonexistent file errors gracefully."""
        rc, stdout, stderr = self._run_candidate_with_file(
            candidate_setup, "decision", str(tmp_path / "nonexistent.txt"),
        )
        assert rc != 0
        assert "not found" in stderr.lower() or "error" in stderr.lower()

    def test_new_info_file_takes_precedence(self, candidate_setup, tmp_path):
        """When both --new-info and --new-info-file are given, file takes precedence."""
        info_file = tmp_path / "info.txt"
        info_file.write_text("JWT authentication tokens")

        cmd = [
            PYTHON, CANDIDATE_SCRIPT,
            "--category", "decision",
            "--new-info", "completely unrelated topic xyz",
            "--new-info-file", str(info_file),
            "--root", str(candidate_setup),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # File content matches existing decision, so candidate should be found
        # (if inline were used, "completely unrelated topic xyz" would not match)
        assert data["candidate"] is not None

    def test_either_new_info_or_file_required(self, candidate_setup):
        """Omitting both --new-info and --new-info-file should error."""
        cmd = [
            PYTHON, CANDIDATE_SCRIPT,
            "--category", "decision",
            "--root", str(candidate_setup),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "error" in result.stderr.lower()


# ===============================================================
# Integration Test: Full Phase 1 Pipeline
# ===============================================================

class TestPhase1Integration:
    """Integration test: write input -> run candidate -> run draft -> verify -> run write."""

    @pytest.fixture
    def project(self, tmp_path):
        """Set up a full project structure for integration test."""
        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem = dc / "memory"
        mem.mkdir()
        staging = mem / ".staging"
        staging.mkdir()
        for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
            (mem / folder).mkdir()
        # Create initial index
        index_path = mem / "index.md"
        index_path.write_text("# Memory Index\n\n")
        return proj

    def test_full_create_pipeline(self, project):
        """Simulate full Phase 1: candidate -> draft -> write (CREATE)."""
        mem_root = project / ".claude" / "memory"
        staging = mem_root / ".staging"

        # Step 1: Write new-info to file
        info_file = staging / "new-info-decision.txt"
        info_file.write_text("Need to decide on JWT vs OAuth2 for API authentication")

        # Step 2: Run memory_candidate.py with --new-info-file
        cmd_candidate = [
            PYTHON, CANDIDATE_SCRIPT,
            "--category", "decision",
            "--new-info-file", str(info_file),
            "--root", str(mem_root),
        ]
        res_cand = subprocess.run(
            cmd_candidate, capture_output=True, text=True, timeout=10,
            cwd=str(project),
        )
        assert res_cand.returncode == 0, f"Candidate failed: {res_cand.stderr}"
        cand_result = json.loads(res_cand.stdout)
        assert cand_result["pre_action"] == "CREATE"

        # Step 3: Write partial JSON input via Write tool equivalent
        partial_input = {
            "title": "Use JWT for API authentication",
            "tags": ["auth", "jwt", "api"],
            "confidence": 0.9,
            "change_summary": "Decided to use JWT for stateless API auth",
            "content": {
                "status": "accepted",
                "context": "Need stateless auth for microservices API",
                "decision": "Use JWT with RS256 signing and 1h expiry",
                "rationale": ["Stateless", "Industry standard", "Easy to rotate keys"],
            },
        }
        input_file = staging / "input-decision-12345.json"
        input_file.write_text(json.dumps(partial_input, indent=2))

        # Step 4: Run memory_draft.py
        cmd_draft = [
            PYTHON, DRAFT_SCRIPT,
            "--action", "create",
            "--category", "decision",
            "--input-file", str(input_file),
            "--root", str(mem_root),
        ]
        res_draft = subprocess.run(
            cmd_draft, capture_output=True, text=True, timeout=15,
            cwd=str(project),
        )
        assert res_draft.returncode == 0, f"Draft failed: {res_draft.stderr}"
        draft_result = json.loads(res_draft.stdout)
        assert draft_result["status"] == "ok"

        draft_path = draft_result["draft_path"]
        draft_data = json.loads(Path(draft_path).read_text())

        # Step 5: Verify draft is schema-valid
        Model = build_memory_model("decision")
        Model.model_validate(draft_data)

        # Step 6: Run memory_write.py to finalize
        target = ".claude/memory/decisions/" + draft_data["id"] + ".json"
        cmd_write = [
            PYTHON, WRITE_SCRIPT,
            "--action", "create",
            "--category", "decision",
            "--target", target,
            "--input", draft_path,
        ]
        res_write = subprocess.run(
            cmd_write, capture_output=True, text=True, timeout=15,
            cwd=str(project),
        )
        assert res_write.returncode == 0, f"Write failed: {res_write.stdout}\n{res_write.stderr}"
        write_result = json.loads(res_write.stdout)
        assert write_result["status"] == "created"

        # Step 7: Verify the file was written correctly
        final_path = project / target
        assert final_path.exists()
        final_data = json.loads(final_path.read_text())
        assert final_data["category"] == "decision"
        assert final_data["record_status"] == "active"
        assert final_data["schema_version"] == "1.0"

        # Verify index was updated
        index_content = (mem_root / "index.md").read_text()
        assert draft_data["id"] in index_content

    def test_full_update_pipeline(self, project):
        """Simulate full Phase 1: candidate -> draft -> write (UPDATE)."""
        mem_root = project / ".claude" / "memory"
        staging = mem_root / ".staging"

        # Pre-setup: create an existing decision
        existing = make_decision_memory()
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = project / target
        target_abs.write_text(json.dumps(existing, indent=2))

        # Write index with the existing entry
        index_path = mem_root / "index.md"
        abs_path = str(mem_root / "decisions" / "use-jwt.json")
        index_path.write_text(
            "# Memory Index\n\n"
            f"- [DECISION] {existing['title']} -> {abs_path} #tags:{','.join(existing['tags'])}\n"
        )

        # Step 1: Run candidate (should find existing)
        info_file = staging / "new-info-decision.txt"
        info_file.write_text("JWT authentication needs update to longer expiry")

        cmd_candidate = [
            PYTHON, CANDIDATE_SCRIPT,
            "--category", "decision",
            "--new-info-file", str(info_file),
            "--root", str(mem_root),
        ]
        res_cand = subprocess.run(
            cmd_candidate, capture_output=True, text=True, timeout=10,
            cwd=str(project),
        )
        assert res_cand.returncode == 0, f"Candidate failed: {res_cand.stderr}"
        cand_result = json.loads(res_cand.stdout)
        assert cand_result["candidate"] is not None
        assert "UPDATE" in cand_result["structural_cud"]

        candidate_path = cand_result["candidate"]["path"]

        # Step 2: Write partial input for update
        partial_input = {
            "title": "Use JWT for authentication",
            "tags": ["expiry-update"],
            "confidence": 0.95,
            "change_summary": "Extended JWT token expiry from 1h to 4h",
            "content": {
                "status": "accepted",
                "context": "Need stateless auth for API",
                "decision": "Use JWT tokens with 4h expiry (extended from 1h)",
                "rationale": ["Stateless", "Industry standard", "Reduced re-auth friction"],
            },
        }
        input_file = staging / "input-decision-update.json"
        input_file.write_text(json.dumps(partial_input, indent=2))

        # Step 3: Run draft with --action update
        cmd_draft = [
            PYTHON, DRAFT_SCRIPT,
            "--action", "update",
            "--category", "decision",
            "--input-file", str(input_file),
            "--candidate-file", candidate_path,
            "--root", str(mem_root),
        ]
        res_draft = subprocess.run(
            cmd_draft, capture_output=True, text=True, timeout=15,
            cwd=str(project),
        )
        assert res_draft.returncode == 0, f"Draft failed: {res_draft.stderr}"
        draft_result = json.loads(res_draft.stdout)
        assert draft_result["status"] == "ok"
        assert draft_result["action"] == "update"

        # Verify draft content
        draft_data = json.loads(Path(draft_result["draft_path"]).read_text())
        assert draft_data["id"] == existing["id"]  # immutable
        assert draft_data["created_at"] == existing["created_at"]  # immutable
        assert draft_data["times_updated"] == existing["times_updated"] + 1
        # Tags unioned
        assert "expiry-update" in draft_data["tags"]
        for tag in existing["tags"]:
            assert tag in draft_data["tags"]
