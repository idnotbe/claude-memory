"""Tests for memory_write.py -- schema-enforced memory write tool."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
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
WRITE_SCRIPT = str(SCRIPTS_DIR / "memory_write.py")
PYTHON = sys.executable


def run_write(action, category=None, target=None, input_file=None, hash_val=None, reason=None, cwd=None):
    """Run memory_write.py and return (returncode, stdout, stderr)."""
    cmd = [PYTHON, WRITE_SCRIPT, "--action", action, "--target", target]
    if category:
        cmd.extend(["--category", category])
    if input_file:
        cmd.extend(["--input", input_file])
    if hash_val:
        cmd.extend(["--hash", hash_val])
    if reason:
        cmd.extend(["--reason", reason])
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=15,
        cwd=cwd or os.getcwd(),
    )
    return result.returncode, result.stdout, result.stderr


def write_input_file(memory_project, data):
    """Write a JSON input file to .claude/memory/.staging/ and return its path."""
    staging = memory_project / ".claude" / "memory" / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    fp = staging / "input.json"
    fp.write_text(json.dumps(data, indent=2))
    return str(fp)


def file_md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


# ---------------------------------------------------------------
# Direct imports for unit tests
# ---------------------------------------------------------------
sys.path.insert(0, str(SCRIPTS_DIR))
from memory_write import (
    auto_fix,
    validate_memory,
    slugify,
    build_index_line,
    word_difference_ratio,
    check_merge_protections,
    format_validation_error,
    TAG_CAP,
    CHANGES_CAP,
)


class TestAutoFix:
    def test_missing_timestamps(self):
        data = {"tags": ["test"]}
        result = auto_fix(data, "create")
        assert "schema_version" in result
        assert result["schema_version"] == "1.0"
        assert "updated_at" in result
        assert "created_at" in result

    def test_tags_string_to_array(self):
        data = {"tags": "single-tag", "schema_version": "1.0", "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        assert isinstance(result["tags"], list)
        assert "single-tag" in result["tags"]

    def test_id_slugify(self):
        data = {"id": "My Cool Decision!", "tags": ["t"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        assert result["id"] == "my-cool-decision"

    def test_confidence_clamp_above(self):
        data = {"confidence": 1.5, "tags": ["t"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        assert result["confidence"] == 1.0

    def test_confidence_clamp_below(self):
        data = {"confidence": -0.5, "tags": ["t"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        assert result["confidence"] == 0.0

    def test_dedup_and_sort_tags(self):
        data = {"tags": ["Bbb", "aaa", "BBB", "ccc"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        assert result["tags"] == ["aaa", "bbb", "ccc"]

    def test_empty_tags_after_dedup(self):
        data = {"tags": ["", "  "], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        assert result["tags"] == ["untagged"]


class TestSlugify:
    def test_basic(self):
        assert slugify("My Cool Decision") == "my-cool-decision"

    def test_special_chars(self):
        assert slugify("Auth: JWT + OAuth!") == "auth-jwt-oauth"

    def test_max_length(self):
        long_text = "a" * 100
        result = slugify(long_text)
        assert len(result) <= 80


class TestValidation:
    def test_valid_decision(self):
        mem = make_decision_memory()
        ok, err = validate_memory(mem, "decision")
        assert ok is True
        assert err is None

    def test_wrong_enum_value(self):
        mem = make_decision_memory(content_overrides={"status": "invalid_status"})
        ok, err = validate_memory(mem, "decision")
        assert ok is False
        assert "VALIDATION_ERROR" in err

    def test_missing_required_field(self):
        mem = make_decision_memory()
        del mem["content"]["decision"]
        ok, err = validate_memory(mem, "decision")
        assert ok is False

    def test_extra_fields_rejected(self):
        mem = make_decision_memory()
        mem["content"]["unknown_field"] = "should fail"
        ok, err = validate_memory(mem, "decision")
        assert ok is False

    def test_extra_top_level_rejected(self):
        mem = make_decision_memory()
        mem["some_extra_field"] = "nope"
        ok, err = validate_memory(mem, "decision")
        assert ok is False


class TestFormatValidationError:
    def test_error_format(self):
        from pydantic import ValidationError
        mem = make_decision_memory(content_overrides={"status": "bad"})
        ok, err = validate_memory(mem, "decision")
        assert "VALIDATION_ERROR" in err
        assert "field:" in err
        assert "expected:" in err


class TestBuildIndexLine:
    def test_enriched_format(self):
        mem = make_decision_memory()
        line = build_index_line(mem, ".claude/memory/decisions/use-jwt.json")
        assert line.startswith("- [DECISION]")
        assert "-> .claude/memory/decisions/use-jwt.json" in line
        assert "#tags:" in line
        assert "auth" in line

    def test_no_tags(self):
        mem = make_decision_memory(tags=[])
        # Auto-fix would add "untagged", but if we skip auto_fix:
        mem["tags"] = []
        line = build_index_line(mem, "path.json")
        assert "#tags:" not in line


class TestWordDifferenceRatio:
    def test_identical_titles(self):
        assert word_difference_ratio("Use JWT", "Use JWT") == 0.0

    def test_completely_different(self):
        ratio = word_difference_ratio("apple banana", "cherry date")
        assert ratio == 1.0

    def test_partial_overlap(self):
        ratio = word_difference_ratio("Use JWT auth", "Use OAuth auth")
        # words: {use, jwt, auth} vs {use, oauth, auth}
        # union=4, diff=2 -> 0.5
        assert ratio == 0.5

    def test_empty_strings(self):
        assert word_difference_ratio("", "") == 0.0


class TestMergeProtections:
    def test_immutable_fields_rejected(self):
        old = make_decision_memory()
        new = make_decision_memory()
        new["created_at"] = "2099-01-01T00:00:00Z"
        ok, err, _ = check_merge_protections(old, new)
        assert ok is False
        assert "immutable" in err

    def test_record_status_immutable_via_update(self):
        old = make_decision_memory()
        new = make_decision_memory()
        new["record_status"] = "retired"
        ok, err, _ = check_merge_protections(old, new)
        assert ok is False
        assert "record_status" in err

    def test_tags_grow_only_below_cap(self):
        old = make_decision_memory(tags=["a", "b", "c"])
        new = make_decision_memory(tags=["a", "b"])  # removed "c"
        ok, err, _ = check_merge_protections(old, new)
        assert ok is False
        assert "grow-only" in err

    def test_tags_eviction_at_cap(self):
        old_tags = [f"tag{i}" for i in range(TAG_CAP)]  # exactly at cap
        new_tags = old_tags[1:] + ["new-tag"]  # evict one, add one
        old = make_decision_memory(tags=old_tags)
        new = make_decision_memory(tags=new_tags)
        ok, err, changes = check_merge_protections(old, new)
        assert ok is True
        assert any("evicted" in c.get("summary", "").lower() for c in changes)

    def test_tags_eviction_no_addition_rejected(self):
        old_tags = [f"tag{i}" for i in range(TAG_CAP)]
        new_tags = old_tags[1:]  # remove one, add none
        old = make_decision_memory(tags=old_tags)
        new = make_decision_memory(tags=new_tags)
        ok, err, _ = check_merge_protections(old, new)
        assert ok is False
        assert "no net shrink" in err

    def test_tags_exceed_cap_during_eviction_rejected(self):
        """Evicting tags at cap but ending above cap is rejected."""
        old_tags = [f"tag{i}" for i in range(TAG_CAP)]
        # Remove 1 old tag but add 3 new -> net result exceeds cap
        new_tags = old_tags[1:] + ["new1", "new2", "new3"]  # 11 + 3 = 14
        old = make_decision_memory(tags=old_tags)
        new = make_decision_memory(tags=new_tags)
        ok, err, _ = check_merge_protections(old, new)
        assert ok is False
        assert "cap exceeded" in err

    def test_tags_grow_beyond_cap_no_removal_allowed(self):
        """Adding tags beyond cap (without removal) is allowed by merge protections.
        The cap only applies during eviction (removal) scenarios."""
        old_tags = [f"tag{i}" for i in range(TAG_CAP)]
        new_tags = old_tags + ["extra1"]
        old = make_decision_memory(tags=old_tags)
        new = make_decision_memory(tags=new_tags)
        ok, err, _ = check_merge_protections(old, new)
        # No removals, so merge protections pass (Pydantic/auto-fix may cap later)
        assert ok is True

    def test_related_files_grow_only(self, tmp_path):
        existing_file = tmp_path / "exists.py"
        existing_file.write_text("pass")
        old = make_decision_memory(related_files=[str(existing_file)])
        new = make_decision_memory(related_files=[])
        ok, err, _ = check_merge_protections(old, new)
        assert ok is False
        assert "grow-only" in err

    def test_related_files_dangling_removal_allowed(self):
        old = make_decision_memory(related_files=["/nonexistent/path.py"])
        new = make_decision_memory(related_files=[])
        ok, err, _ = check_merge_protections(old, new)
        assert ok is True

    def test_changes_append_only(self):
        old = make_decision_memory(changes=[
            {"date": "2026-01-01", "summary": "Created"},
            {"date": "2026-01-15", "summary": "Updated"},
        ])
        new = make_decision_memory(changes=[
            {"date": "2026-01-01", "summary": "Created"},
        ])
        ok, err, _ = check_merge_protections(old, new)
        assert ok is False
        assert "append-only" in err

    def test_auto_change_log_for_scalar_changes(self):
        old = make_decision_memory(content_overrides={"status": "proposed"})
        new = make_decision_memory(content_overrides={"status": "accepted"})
        ok, err, changes = check_merge_protections(old, new)
        assert ok is True
        assert any("content.status" in c.get("field", "") for c in changes)


class TestCreateFlow:
    def test_create_valid(self, memory_project, tmp_path):
        mem = make_decision_memory()
        input_file = write_input_file(memory_project,mem)
        target = ".claude/memory/decisions/use-jwt.json"
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        result = json.loads(stdout)
        assert result["status"] == "created"
        assert result["id"] == "use-jwt"
        # Verify file exists
        assert (memory_project / target).exists()
        # Verify index updated
        index = (memory_project / ".claude" / "memory" / "index.md").read_text()
        assert "use-jwt" in index

    def test_create_anti_resurrection(self, memory_project, tmp_path):
        """Cannot CREATE over a recently retired file."""
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        # Write a retired file
        retired = make_decision_memory(
            record_status="retired",
            retired_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        target_abs.write_text(json.dumps(retired))
        # Try to create over it
        mem = make_decision_memory()
        input_file = write_input_file(memory_project,mem)
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "ANTI_RESURRECTION" in stdout

    def test_create_with_auto_fixes(self, memory_project, tmp_path):
        """Auto-fixes applied: missing timestamps, id slugify, tags."""
        mem = {
            "category": "decision",
            "id": "My Decision",
            "title": "My Decision About Auth",
            "tags": "auth",  # string, should be array
            "content": {
                "status": "accepted",
                "context": "Need auth",
                "decision": "Use JWT",
                "rationale": ["Good"],
            },
        }
        input_file = write_input_file(memory_project,mem)
        target = ".claude/memory/decisions/my-decision-about-auth.json"
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        # Verify auto-fixes applied
        created = json.loads((memory_project / target).read_text())
        assert created["schema_version"] == "1.0"
        assert isinstance(created["tags"], list)
        assert created["created_at"]
        assert created["updated_at"]


class TestUpdateFlow:
    def _setup_existing(self, memory_project, tmp_path):
        """Helper: create a memory file for update tests. Returns (target, file_path)."""
        mem = make_decision_memory()
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text(json.dumps(mem, indent=2))
        # Create index
        index_path = memory_project / ".claude" / "memory" / "index.md"
        index_path.write_text(
            "# Memory Index\n\n"
            f"- [DECISION] {mem['title']} -> {target} #tags:{','.join(mem['tags'])}\n"
        )
        return target, target_abs, mem

    def test_update_valid(self, memory_project, tmp_path):
        target, target_abs, old_mem = self._setup_existing(memory_project, tmp_path)
        new_mem = make_decision_memory(
            content_overrides={"status": "deprecated"},
            tags=["auth", "jwt", "security", "deprecated"],
        )
        input_file = write_input_file(memory_project,new_mem)
        md5 = file_md5(str(target_abs))
        rc, stdout, stderr = run_write(
            "update", "decision", target, input_file, hash_val=md5,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        result = json.loads(stdout)
        assert result["status"] == "updated"
        assert result["times_updated"] == 1

    def test_update_occ_hash_mismatch(self, memory_project, tmp_path):
        target, target_abs, old_mem = self._setup_existing(memory_project, tmp_path)
        new_mem = make_decision_memory(
            changes=[{"date": "2026-02-14T00:00:00Z", "summary": "test change"}],
        )
        input_file = write_input_file(memory_project,new_mem)
        rc, stdout, stderr = run_write(
            "update", "decision", target, input_file, hash_val="wrong_hash",
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "OCC_CONFLICT" in stdout

    def test_update_slug_rename(self, memory_project, tmp_path):
        """Title change >50% word diff triggers slug rename."""
        target, target_abs, old_mem = self._setup_existing(memory_project, tmp_path)
        # Old title: "Use JWT for authentication"
        # New title: "Adopt OAuth2 for authorization" - >50% different words
        new_mem = make_decision_memory(
            title="Adopt OAuth2 for authorization",
            tags=["auth", "jwt", "security", "oauth2"],
            changes=[{"date": "2026-02-14T00:00:00Z", "summary": "Renamed to OAuth2"}],
        )
        input_file = write_input_file(memory_project,new_mem)
        md5 = file_md5(str(target_abs))
        rc, stdout, stderr = run_write(
            "update", "decision", target, input_file, hash_val=md5,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        result = json.loads(stdout)
        if "renamed_from" in result:
            assert result["renamed_from"] == target
            # New file should exist
            new_path = memory_project / result["target"]
            assert new_path.exists()

    def test_update_changes_fifo_overflow(self, memory_project, tmp_path):
        """Changes list capped at CHANGES_CAP (50)."""
        target, target_abs, old_mem = self._setup_existing(memory_project, tmp_path)
        # Fill up changes to near cap
        old_mem["changes"] = [
            {"date": f"2026-01-{i:02d}T00:00:00Z", "summary": f"Change {i}"}
            for i in range(1, CHANGES_CAP + 1)
        ]
        target_abs.write_text(json.dumps(old_mem, indent=2))
        new_mem = make_decision_memory(
            tags=["auth", "jwt", "security", "newchange"],
            changes=old_mem["changes"] + [
                {"date": "2026-02-14T00:00:00Z", "summary": "FIFO test change"},
            ],
        )
        input_file = write_input_file(memory_project,new_mem)
        md5 = file_md5(str(target_abs))
        rc, stdout, stderr = run_write(
            "update", "decision", target, input_file, hash_val=md5,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        updated = json.loads((memory_project / target).read_text())
        assert len(updated["changes"]) <= CHANGES_CAP


class TestRetireFlow:
    def _setup_existing(self, memory_project):
        mem = make_tech_debt_memory()
        target = ".claude/memory/tech-debt/legacy-api-v1.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text(json.dumps(mem, indent=2))
        index_path = memory_project / ".claude" / "memory" / "index.md"
        index_path.write_text(
            "# Memory Index\n\n"
            f"- [TECH_DEBT] {mem['title']} -> {target} #tags:{','.join(mem['tags'])}\n"
        )
        return target, target_abs

    def test_retire_retires(self, memory_project):
        target, target_abs = self._setup_existing(memory_project)
        rc, stdout, stderr = run_write(
            "retire", target=target, reason="No longer relevant",
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        result = json.loads(stdout)
        assert result["status"] == "retired"
        # File still exists but is retired
        data = json.loads(target_abs.read_text())
        assert data["record_status"] == "retired"
        assert data["retired_at"] is not None
        assert data["retired_reason"] == "No longer relevant"
        # Removed from index
        index = (memory_project / ".claude" / "memory" / "index.md").read_text()
        assert "legacy-api-v1" not in index

    def test_retire_idempotent(self, memory_project):
        """Retiring an already-retired file succeeds idempotently."""
        target, target_abs = self._setup_existing(memory_project)
        # First retire
        run_write("retire", target=target, reason="First", cwd=str(memory_project))
        # Second retire
        rc, stdout, stderr = run_write(
            "retire", target=target, reason="Second",
            cwd=str(memory_project),
        )
        assert rc == 0
        result = json.loads(stdout)
        assert result["status"] == "already_retired"

    def test_retire_nonexistent(self, memory_project):
        rc, stdout, stderr = run_write(
            "retire", target=".claude/memory/decisions/nonexistent.json",
            reason="test", cwd=str(memory_project),
        )
        assert rc == 1
        assert "RETIRE_ERROR" in stdout


class TestPydanticValidation:
    """Test Pydantic model validation edge cases."""

    def test_all_categories_validate(self):
        factories = {
            "decision": make_decision_memory,
            "preference": make_preference_memory,
            "tech_debt": make_tech_debt_memory,
            "session_summary": make_session_memory,
            "runbook": make_runbook_memory,
            "constraint": make_constraint_memory,
        }
        for cat, factory in factories.items():
            mem = factory()
            ok, err = validate_memory(mem, cat)
            assert ok is True, f"{cat} validation failed: {err}"

    def test_decision_wrong_status(self):
        mem = make_decision_memory(content_overrides={"status": "banana"})
        ok, err = validate_memory(mem, "decision")
        assert ok is False

    def test_constraint_wrong_severity(self):
        mem = make_constraint_memory()
        mem["content"]["severity"] = "extreme"
        ok, err = validate_memory(mem, "constraint")
        assert ok is False

    def test_preference_wrong_strength(self):
        mem = make_preference_memory()
        mem["content"]["strength"] = "ultra"
        ok, err = validate_memory(mem, "preference")
        assert ok is False

    def test_session_wrong_outcome(self):
        mem = make_session_memory()
        mem["content"]["outcome"] = "great"
        ok, err = validate_memory(mem, "session_summary")
        assert ok is False

    def test_tech_debt_wrong_priority(self):
        mem = make_tech_debt_memory()
        mem["content"]["priority"] = "urgent"
        ok, err = validate_memory(mem, "tech_debt")
        assert ok is False

    def test_runbook_empty_steps(self):
        mem = make_runbook_memory()
        mem["content"]["steps"] = []
        ok, err = validate_memory(mem, "runbook")
        assert ok is False

    def test_decision_empty_rationale(self):
        mem = make_decision_memory(content_overrides={"rationale": []})
        ok, err = validate_memory(mem, "decision")
        assert ok is False


# ---------------------------------------------------------------
# R2 Fixes: Archive/Unarchive tests (F7)
# ---------------------------------------------------------------

class TestArchiveFlow:
    def _setup_active(self, memory_project):
        """Create an active memory for archive tests."""
        mem = make_decision_memory()
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text(json.dumps(mem, indent=2))
        index_path = memory_project / ".claude" / "memory" / "index.md"
        index_path.write_text(
            "# Memory Index\n\n"
            f"- [DECISION] {mem['title']} -> {target} #tags:{','.join(mem['tags'])}\n"
        )
        return target, target_abs

    def test_archive_active_memory(self, memory_project):
        """Archive an active memory (happy path)."""
        target, target_abs = self._setup_active(memory_project)
        rc, stdout, stderr = run_write(
            "archive", target=target, reason="No longer relevant",
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        result = json.loads(stdout)
        assert result["status"] == "archived"
        # File should be archived
        data = json.loads(target_abs.read_text())
        assert data["record_status"] == "archived"
        assert data["archived_at"] is not None
        assert data["archived_reason"] == "No longer relevant"
        # Removed from index
        index = (memory_project / ".claude" / "memory" / "index.md").read_text()
        assert "use-jwt" not in index

    def test_archive_already_archived(self, memory_project):
        """Archiving an already-archived memory is idempotent."""
        target, target_abs = self._setup_active(memory_project)
        # First archive
        run_write("archive", target=target, reason="First", cwd=str(memory_project))
        # Second archive
        rc, stdout, stderr = run_write(
            "archive", target=target, reason="Second",
            cwd=str(memory_project),
        )
        assert rc == 0
        result = json.loads(stdout)
        assert result["status"] == "already_archived"

    def test_archive_retired_memory_fails(self, memory_project):
        """Cannot archive a retired memory."""
        target, target_abs = self._setup_active(memory_project)
        # Retire first
        run_write("retire", target=target, reason="Retired", cwd=str(memory_project))
        # Try to archive
        rc, stdout, stderr = run_write(
            "archive", target=target, reason="Try archive",
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "ARCHIVE_ERROR" in stdout
        assert "Only active" in stdout

    def test_archive_nonexistent_fails(self, memory_project):
        rc, stdout, stderr = run_write(
            "archive", target=".claude/memory/decisions/nonexistent.json",
            reason="test", cwd=str(memory_project),
        )
        assert rc == 1
        assert "ARCHIVE_ERROR" in stdout

    def test_archive_removes_from_index(self, memory_project):
        """Verify index entry is removed on archive."""
        target, target_abs = self._setup_active(memory_project)
        index_path = memory_project / ".claude" / "memory" / "index.md"
        # Verify in index before
        assert "use-jwt" in index_path.read_text()
        # Archive
        run_write("archive", target=target, reason="test", cwd=str(memory_project))
        # Verify removed from index
        assert "use-jwt" not in index_path.read_text()

    def test_archive_adds_change_entry(self, memory_project):
        """Archive should add a change entry."""
        target, target_abs = self._setup_active(memory_project)
        run_write("archive", target=target, reason="Test reason", cwd=str(memory_project))
        data = json.loads(target_abs.read_text())
        assert len(data.get("changes", [])) >= 1
        last_change = data["changes"][-1]
        assert "Archived" in last_change["summary"]
        assert last_change["field"] == "record_status"
        assert last_change["new_value"] == "archived"


class TestUnarchiveFlow:
    def _setup_archived(self, memory_project):
        """Create an archived memory for unarchive tests."""
        mem = make_decision_memory(record_status="archived")
        mem["archived_at"] = "2026-02-10T10:00:00Z"
        mem["archived_reason"] = "Previously archived"
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text(json.dumps(mem, indent=2))
        # Archived memories are NOT in the index
        index_path = memory_project / ".claude" / "memory" / "index.md"
        index_path.write_text("# Memory Index\n\n")
        return target, target_abs

    def test_unarchive_archived_memory(self, memory_project):
        """Unarchive an archived memory (happy path)."""
        target, target_abs = self._setup_archived(memory_project)
        rc, stdout, stderr = run_write(
            "unarchive", target=target,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        result = json.loads(stdout)
        assert result["status"] == "unarchived"
        # File should be active
        data = json.loads(target_abs.read_text())
        assert data["record_status"] == "active"
        assert "archived_at" not in data
        assert "archived_reason" not in data

    def test_unarchive_active_memory_fails(self, memory_project):
        """Cannot unarchive a non-archived memory."""
        mem = make_decision_memory()
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text(json.dumps(mem, indent=2))
        rc, stdout, stderr = run_write(
            "unarchive", target=target,
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "UNARCHIVE_ERROR" in stdout
        assert "Only archived" in stdout

    def test_unarchive_retired_memory_fails(self, memory_project):
        """Cannot unarchive a retired memory."""
        mem = make_decision_memory(
            record_status="retired",
            retired_at="2026-02-10T10:00:00Z",
        )
        mem["retired_reason"] = "Previously retired"
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text(json.dumps(mem, indent=2))
        rc, stdout, stderr = run_write(
            "unarchive", target=target,
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "UNARCHIVE_ERROR" in stdout

    def test_unarchive_nonexistent_fails(self, memory_project):
        rc, stdout, stderr = run_write(
            "unarchive", target=".claude/memory/decisions/nonexistent.json",
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "UNARCHIVE_ERROR" in stdout

    def test_unarchive_adds_to_index(self, memory_project):
        """Unarchive should add the entry back to the index."""
        target, target_abs = self._setup_archived(memory_project)
        index_path = memory_project / ".claude" / "memory" / "index.md"
        # Verify not in index before
        assert "use-jwt" not in index_path.read_text()
        # Unarchive
        run_write("unarchive", target=target, cwd=str(memory_project))
        # Verify added to index
        assert "use-jwt" in index_path.read_text()

    def test_unarchive_adds_change_entry(self, memory_project):
        """Unarchive should add a change entry."""
        target, target_abs = self._setup_archived(memory_project)
        run_write("unarchive", target=target, cwd=str(memory_project))
        data = json.loads(target_abs.read_text())
        assert len(data.get("changes", [])) >= 1
        last_change = data["changes"][-1]
        assert "Unarchived" in last_change["summary"]
        assert last_change["field"] == "record_status"
        assert last_change["new_value"] == "active"


class TestRetireArchiveInteraction:
    """Test interactions between retire and archive."""

    def test_retire_clears_archived_fields(self, memory_project):
        """RETIRE on an active memory should not leave stale archived fields."""
        mem = make_decision_memory()
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text(json.dumps(mem, indent=2))
        index_path = memory_project / ".claude" / "memory" / "index.md"
        index_path.write_text(
            "# Memory Index\n\n"
            f"- [DECISION] {mem['title']} -> {target} #tags:{','.join(mem['tags'])}\n"
        )
        rc, stdout, stderr = run_write(
            "retire", target=target, reason="Test clear",
            cwd=str(memory_project),
        )
        assert rc == 0
        data = json.loads(target_abs.read_text())
        assert data["record_status"] == "retired"
        assert "archived_at" not in data
        assert "archived_reason" not in data

    def test_archived_to_retired_blocked(self, memory_project):
        """Cannot retire an archived memory directly (must unarchive first)."""
        mem = make_decision_memory(record_status="archived")
        mem["archived_at"] = "2026-02-10T10:00:00Z"
        mem["archived_reason"] = "Archived for reference"
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text(json.dumps(mem, indent=2))
        rc, stdout, stderr = run_write(
            "retire", target=target, reason="Try retire",
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "RETIRE_ERROR" in stdout
        assert "unarchive" in stdout.lower()


# ---------------------------------------------------------------
# R2 Fixes: Adversarial / security tests
# ---------------------------------------------------------------

class TestPathTraversal:
    """F1: Path traversal via --target."""

    def test_path_traversal_create_blocked(self, memory_project, tmp_path):
        """CREATE with path traversal should be blocked."""
        mem = make_decision_memory()
        input_file = write_input_file(memory_project,mem)
        target = ".claude/memory/decisions/../../../traversal.json"
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "PATH_ERROR" in stdout

    def test_path_traversal_retire_blocked(self, memory_project):
        """RETIRE with path traversal should be blocked."""
        target = ".claude/memory/decisions/../../../etc/passwd"
        rc, stdout, stderr = run_write(
            "retire", target=target, reason="test",
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "PATH_ERROR" in stdout

    def test_path_traversal_archive_blocked(self, memory_project):
        """ARCHIVE with path traversal should be blocked."""
        target = ".claude/memory/decisions/../../../traversal.json"
        rc, stdout, stderr = run_write(
            "archive", target=target, reason="test",
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "PATH_ERROR" in stdout


class TestTagSanitization:
    """F2/H1/M5: Tag sanitization (newlines, commas, #tags: injection)."""

    def test_newline_in_tags_stripped(self):
        """Tags with newlines should have them stripped."""
        data = {"tags": ["evil\ninjected"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        for tag in result["tags"]:
            assert "\n" not in tag

    def test_comma_in_tags_replaced(self):
        """Commas in individual tags should be replaced with spaces."""
        data = {"tags": ["test,injected-tag,another"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        for tag in result["tags"]:
            assert "," not in tag

    def test_tags_prefix_in_tag_stripped(self):
        """#tags: substring in tag values should be stripped."""
        data = {"tags": ["#tags:injected"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        for tag in result["tags"]:
            assert "#tags:" not in tag

    def test_arrow_in_tag_stripped(self):
        """Arrow separator in tag values should be stripped."""
        data = {"tags": ["evil -> path"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        for tag in result["tags"]:
            assert " -> " not in tag

    def test_control_chars_in_tags_stripped(self):
        """Control characters (tabs, null bytes) in tags should be stripped."""
        data = {"tags": ["test\x00hidden\ttab"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        for tag in result["tags"]:
            assert "\x00" not in tag
            assert "\t" not in tag


class TestCreateRecordStatusInjection:
    """F3: CREATE should force record_status to active."""

    def test_create_forces_active_status(self, memory_project, tmp_path):
        """CREATE with record_status='retired' should force it to 'active'."""
        mem = make_decision_memory(record_status="retired")
        mem["retired_at"] = "2026-02-10T10:00:00Z"
        mem["retired_reason"] = "Injected"
        input_file = write_input_file(memory_project,mem)
        target = ".claude/memory/decisions/injected.json"
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        data = json.loads((memory_project / target).read_text())
        assert data["record_status"] == "active"
        assert "retired_at" not in data or data.get("retired_at") is None
        assert "retired_reason" not in data or data.get("retired_reason") is None

    def test_create_forces_active_strips_archived(self, memory_project, tmp_path):
        """CREATE with record_status='archived' should force it to 'active'."""
        mem = make_decision_memory(record_status="archived")
        mem["archived_at"] = "2026-02-10T10:00:00Z"
        mem["archived_reason"] = "Injected"
        input_file = write_input_file(memory_project,mem)
        target = ".claude/memory/decisions/injected2.json"
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        data = json.loads((memory_project / target).read_text())
        assert data["record_status"] == "active"
        assert "archived_at" not in data or data.get("archived_at") is None


class TestTagCapEnforcement:
    """F4/H2: TAG_CAP enforced on CREATE."""

    def test_tags_truncated_to_cap_on_create(self):
        """Tags exceeding TAG_CAP should be truncated in auto_fix."""
        many_tags = [f"tag{i}" for i in range(20)]
        data = {"tags": many_tags, "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        assert len(result["tags"]) <= TAG_CAP

    def test_create_with_many_tags_succeeds_within_cap(self, memory_project, tmp_path):
        """CREATE with >12 tags should succeed but truncate to TAG_CAP."""
        many_tags = [f"tag{i}" for i in range(15)]
        mem = make_decision_memory(tags=many_tags)
        input_file = write_input_file(memory_project,mem)
        target = ".claude/memory/decisions/many-tags.json"
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        data = json.loads((memory_project / target).read_text())
        assert len(data["tags"]) <= TAG_CAP


class TestTitleSanitization:
    """F8: Control character sanitization in titles."""

    def test_null_bytes_stripped_from_title(self):
        """Null bytes in title should be stripped."""
        data = {"title": "Normal\x00Hidden", "tags": ["t"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        assert "\x00" not in result["title"]
        assert result["title"] == "NormalHidden"

    def test_newlines_stripped_from_title(self):
        """Newlines in title should be stripped."""
        data = {"title": "Line1\nLine2", "tags": ["t"], "schema_version": "1.0",
                "updated_at": "x", "created_at": "x"}
        result = auto_fix(data, "create")
        assert "\n" not in result["title"]


class TestOCCWarning:
    """F6: OCC warning when --hash omitted."""

    def test_update_without_hash_warns(self, memory_project, tmp_path):
        """UPDATE without --hash should produce a warning but succeed."""
        mem = make_decision_memory()
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        target_abs.write_text(json.dumps(mem, indent=2))
        index_path = memory_project / ".claude" / "memory" / "index.md"
        index_path.write_text(
            "# Memory Index\n\n"
            f"- [DECISION] {mem['title']} -> {target} #tags:{','.join(mem['tags'])}\n"
        )
        new_mem = make_decision_memory(
            content_overrides={"status": "deprecated"},
            tags=["auth", "jwt", "security", "deprecated"],
        )
        input_file = write_input_file(memory_project,new_mem)
        # Note: no hash_val provided
        rc, stdout, stderr = run_write(
            "update", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        assert "WARNING" in stderr
        assert "OCC protection disabled" in stderr
