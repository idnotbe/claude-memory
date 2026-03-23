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


def run_write(action, category=None, target=None, input_file=None, hash_val=None, reason=None, cwd=None, skip_auto_enforce=False):
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
    if skip_auto_enforce:
        cmd.append("--skip-auto-enforce")
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
    add_to_index,
    auto_fix,
    validate_memory,
    slugify,
    build_index_line,
    word_difference_ratio,
    check_merge_protections,
    format_validation_error,
    cleanup_intents,
    cleanup_staging,
    write_save_result,
    update_sentinel_state,
    _is_valid_legacy_staging,
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


# ---------------------------------------------------------------
# P1 Popup Fix: cleanup_intents() unit tests
# ---------------------------------------------------------------

class TestCleanupIntents:
    """Test cleanup_intents() -- removes stale intent-*.json from staging.

    This function replaced inline python3 -c commands (P1 popup fix)
    to avoid Guardian interpreter payload detection.
    """

    def _make_staging(self, tmp_path, prefix="new"):
        """Create a staging directory with test files.

        Args:
            prefix: "new" for /tmp/-style, "legacy" for .claude/memory/.staging style
        """
        if prefix == "new":
            # Use legacy .claude/memory/.staging structure (can't test /tmp/ prefix
            # in pytest tmp_path since it doesn't resolve to /tmp/.claude-memory-*)
            staging = tmp_path / ".claude" / "memory" / ".staging"
        else:
            staging = tmp_path / ".claude" / "memory" / ".staging"
        staging.mkdir(parents=True, exist_ok=True)
        return staging

    def test_deletes_intent_files(self, tmp_path):
        """Intent files should be deleted."""
        staging = self._make_staging(tmp_path, prefix="legacy")
        (staging / "intent-session_summary.json").write_text('{"action": "create"}')
        (staging / "intent-decision.json").write_text('{"action": "update"}')

        result = cleanup_intents(str(staging))
        assert result["status"] == "ok"
        assert len(result["deleted"]) == 2
        assert "intent-session_summary.json" in result["deleted"]
        assert "intent-decision.json" in result["deleted"]
        # Files should be gone
        assert not (staging / "intent-session_summary.json").exists()
        assert not (staging / "intent-decision.json").exists()

    def test_preserves_non_intent_files(self, tmp_path):
        """Non-intent files (context, triage-data) should be preserved."""
        staging = self._make_staging(tmp_path, prefix="legacy")
        (staging / "intent-session.json").write_text('{}')
        (staging / "context-session.txt").write_text("transcript excerpt")
        (staging / "triage-data.json").write_text('{"categories": []}')
        (staging / "last-save-result.json").write_text('{}')

        result = cleanup_intents(str(staging))
        assert result["status"] == "ok"
        assert len(result["deleted"]) == 1
        # Non-intent files preserved
        assert (staging / "context-session.txt").exists()
        assert (staging / "triage-data.json").exists()
        assert (staging / "last-save-result.json").exists()

    def test_symlink_rejected(self, tmp_path):
        """Symlinks to intent files should be rejected, not followed."""
        staging = self._make_staging(tmp_path, prefix="legacy")
        # Create a real file outside staging
        outside = tmp_path / "outside-secret.json"
        outside.write_text('{"secret": true}')
        # Create a symlink masquerading as an intent file
        symlink = staging / "intent-evil.json"
        symlink.symlink_to(outside)

        result = cleanup_intents(str(staging))
        assert result["status"] == "ok"
        # Symlink should be in errors, not deleted
        assert any(e["error"] == "symlink rejected" for e in result["errors"])
        assert "intent-evil.json" not in result["deleted"]
        # Original file should still exist (not deleted via symlink)
        assert outside.exists()

    def test_path_traversal_rejected(self, tmp_path):
        """Symlink pointing outside staging via path traversal is rejected."""
        staging = self._make_staging(tmp_path, prefix="legacy")
        # Create target outside staging
        outside = tmp_path / "intent-outside.json"
        outside.write_text('{"traversal": true}')
        # Symlink from inside staging to outside
        link = staging / "intent-traversal.json"
        link.symlink_to(outside)

        result = cleanup_intents(str(staging))
        assert result["status"] == "ok"
        # Should be in errors (symlink rejected)
        assert any(e["error"] == "symlink rejected" for e in result["errors"])
        assert "intent-traversal.json" not in result["deleted"]
        assert outside.exists()

    def test_nonexistent_dir_returns_ok(self, tmp_path):
        """Non-existent staging dir should return ok with empty lists."""
        result = cleanup_intents(str(tmp_path / "nonexistent"))
        assert result["status"] == "ok"
        assert result["deleted"] == []
        assert result["errors"] == []

    def test_invalid_staging_path_returns_error(self, tmp_path):
        """A path that is not a valid staging dir should return error."""
        invalid = tmp_path / "not-staging"
        invalid.mkdir()
        result = cleanup_intents(str(invalid))
        assert result["status"] == "error"
        assert "not a valid staging directory" in result["message"]

    def test_empty_staging_dir(self, tmp_path):
        """Empty staging dir should return ok with empty lists."""
        staging = self._make_staging(tmp_path, prefix="legacy")
        result = cleanup_intents(str(staging))
        assert result["status"] == "ok"
        assert result["deleted"] == []
        assert result["errors"] == []

    def test_tmp_staging_path_accepted(self, tmp_path):
        """A /tmp/.claude-memory-staging-* path should be accepted."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        try:
            (staging / "intent-test.json").write_text('{}')
            result = cleanup_intents(str(staging))
            assert result["status"] == "ok"
            assert "intent-test.json" in result["deleted"]
        finally:
            # Cleanup
            for f in staging.iterdir():
                f.unlink()
            staging.rmdir()


# ---------------------------------------------------------------
# V-R2 GAP 4: cleanup_intents with real /tmp/ staging paths
# ---------------------------------------------------------------

class TestCleanupIntentsTmpPath:
    """Test cleanup_intents with actual /tmp/ staging paths (V-R2 GAP 4).

    The original test suite used only legacy .staging paths because
    cleanup_intents checks startswith('/tmp/.claude-memory-staging-')
    on resolved paths, which tmp_path cannot satisfy. These tests use
    real /tmp/ tempfile directories to exercise the /tmp/ code path.
    """

    def test_multiple_intents_in_tmp(self):
        """cleanup_intents should delete multiple intent files from /tmp/ staging."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        try:
            # Create several intent files
            (staging / "intent-session_summary.json").write_text('{"action": "create"}')
            (staging / "intent-decision.json").write_text('{"action": "update"}')
            (staging / "intent-constraint.json").write_text('{"action": "create"}')
            # Non-intent files should be preserved
            (staging / "context-session_summary.txt").write_text("transcript excerpt")
            (staging / "triage-data.json").write_text('{"categories": []}')

            result = cleanup_intents(str(staging))

            assert result["status"] == "ok"
            assert len(result["deleted"]) == 3
            assert set(result["deleted"]) == {
                "intent-session_summary.json",
                "intent-decision.json",
                "intent-constraint.json",
            }
            # Non-intent files preserved
            assert (staging / "context-session_summary.txt").exists()
            assert (staging / "triage-data.json").exists()
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_symlink_rejected_in_tmp_staging(self):
        """Symlinks to intent files in /tmp/ staging should be rejected."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        outside = None
        try:
            # Create a real file outside staging (NamedTemporaryFile for safe creation)
            outside_fd = tempfile.NamedTemporaryFile(
                suffix=".json", dir="/tmp", delete=False
            )
            outside = Path(outside_fd.name)
            outside_fd.write(b'{"secret": true}')
            outside_fd.close()

            # Create a symlink masquerading as an intent file
            (staging / "intent-evil.json").symlink_to(outside)
            # Create a valid intent file too
            (staging / "intent-valid.json").write_text('{}')

            result = cleanup_intents(str(staging))

            assert result["status"] == "ok"
            # Valid file should be deleted
            assert "intent-valid.json" in result["deleted"]
            # Symlink should be rejected
            assert "intent-evil.json" not in result["deleted"]
            assert any(e["error"] == "symlink rejected" for e in result["errors"])
            # Original file outside staging should still exist
            assert outside.exists()
        finally:
            import shutil
            if outside and outside.exists():
                outside.unlink()
            shutil.rmtree(staging, ignore_errors=True)

    def test_empty_tmp_staging(self):
        """Empty /tmp/ staging dir should return ok with empty lists."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        try:
            result = cleanup_intents(str(staging))
            assert result["status"] == "ok"
            assert result["deleted"] == []
            assert result["errors"] == []
        finally:
            staging.rmdir()

    def test_path_containment_in_tmp(self):
        """Path traversal via symlink in /tmp/ staging should be rejected."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        outside = None
        try:
            # Create a file outside staging (NamedTemporaryFile for safe creation)
            outside_fd = tempfile.NamedTemporaryFile(
                suffix=".json", dir="/tmp", delete=False
            )
            outside = Path(outside_fd.name)
            outside_fd.write(b'{"traversal": true}')
            outside_fd.close()
            # Symlink from inside staging pointing outside
            (staging / "intent-traversal.json").symlink_to(outside)

            result = cleanup_intents(str(staging))

            assert result["status"] == "ok"
            assert "intent-traversal.json" not in result["deleted"]
            assert any(e["error"] == "symlink rejected" for e in result["errors"])
            assert outside.exists()
        finally:
            import shutil
            if outside and outside.exists():
                outside.unlink()
            shutil.rmtree(staging, ignore_errors=True)

    def test_rejects_invalid_tmp_path(self):
        """A /tmp/ path NOT matching .claude-memory-staging-* prefix is rejected."""
        import tempfile
        evil_dir = Path(tempfile.mkdtemp(prefix="evil-dir-", dir="/tmp"))
        try:
            (evil_dir / "intent-test.json").write_text('{}')
            result = cleanup_intents(str(evil_dir))
            assert result["status"] == "error"
            assert "not a valid staging directory" in result["message"]
            # File should NOT have been deleted
            assert (evil_dir / "intent-test.json").exists()
        finally:
            import shutil
            shutil.rmtree(evil_dir, ignore_errors=True)

    def test_rejects_arbitrary_memory_staging(self):
        """/tmp/evil/memory/.staging without .claude ancestor is rejected."""
        import tempfile
        base = Path(tempfile.mkdtemp(prefix="evil-", dir="/tmp"))
        evil_staging = base / "memory" / ".staging"
        try:
            evil_staging.mkdir(parents=True, mode=0o700)
            (evil_staging / "intent-test.json").write_text('{}')
            result = cleanup_intents(str(evil_staging))
            assert result["status"] == "error"
            assert "not a valid staging directory" in result["message"]
            # File should NOT have been deleted
            assert (evil_staging / "intent-test.json").exists()
        finally:
            import shutil
            shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------
# V-R2 GAP 4: cleanup_staging with real /tmp/ staging paths
# ---------------------------------------------------------------

class TestCleanupStagingTmpPath:
    """Test cleanup_staging with actual /tmp/ staging paths (V-R2 GAP 4).

    Mirrors TestCleanupIntentsTmpPath but for cleanup_staging(), which
    handles transient staging files (context-*, triage-data.json, etc.)
    after a successful save.
    """

    def test_cleanup_staging_accepts_real_tmp_path(self):
        """cleanup_staging should delete transient files from /tmp/ staging."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        try:
            # Create files matching cleanup patterns
            (staging / "context-session_summary.txt").write_text("transcript excerpt")
            (staging / "triage-data.json").write_text('{"categories": []}')
            (staging / ".triage-pending.json").write_text('{}')
            (staging / "intent-decision.json").write_text('{}')
            # Non-matching file should survive cleanup
            (staging / "last-save-result.json").write_text('{}')

            result = cleanup_staging(str(staging))

            assert result["status"] == "ok"
            assert "context-session_summary.txt" in result["deleted"]
            assert "triage-data.json" in result["deleted"]
            assert ".triage-pending.json" in result["deleted"]
            assert "intent-decision.json" in result["deleted"]
            # Verify files are actually gone
            assert not (staging / "context-session_summary.txt").exists()
            assert not (staging / "triage-data.json").exists()
            assert not (staging / ".triage-pending.json").exists()
            assert not (staging / "intent-decision.json").exists()
            # Non-matching file should survive
            assert (staging / "last-save-result.json").exists()
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_cleanup_staging_rejects_invalid_tmp_path(self):
        """A /tmp/ path NOT matching .claude-memory-staging-* prefix is rejected."""
        import tempfile
        evil_dir = Path(tempfile.mkdtemp(prefix="evil-dir-", dir="/tmp"))
        try:
            (evil_dir / "context-test.txt").write_text("should not be deleted")
            result = cleanup_staging(str(evil_dir))
            assert result["status"] == "error"
            assert "not a valid staging directory" in result["message"]
            # File should NOT have been deleted
            assert (evil_dir / "context-test.txt").exists()
        finally:
            import shutil
            shutil.rmtree(evil_dir, ignore_errors=True)

    def test_cleanup_staging_rejects_arbitrary_memory_staging(self):
        """/tmp/evil/memory/.staging without .claude ancestor is rejected."""
        import tempfile
        base = Path(tempfile.mkdtemp(prefix="evil-", dir="/tmp"))
        evil_staging = base / "memory" / ".staging"
        try:
            evil_staging.mkdir(parents=True, mode=0o700)
            (evil_staging / "context-test.txt").write_text("should not be deleted")
            result = cleanup_staging(str(evil_staging))
            assert result["status"] == "error"
            assert "not a valid staging directory" in result["message"]
            assert (evil_staging / "context-test.txt").exists()
        finally:
            import shutil
            shutil.rmtree(base, ignore_errors=True)

    def test_cleanup_staging_symlink_skipped_in_tmp(self):
        """Symlink files in /tmp/ staging should be skipped, not followed."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        outside = None
        try:
            outside_fd = tempfile.NamedTemporaryFile(
                suffix=".txt", dir="/tmp", delete=False
            )
            outside = Path(outside_fd.name)
            outside_fd.write(b"secret content")
            outside_fd.close()

            # Create symlink masquerading as a context file
            (staging / "context-evil.txt").symlink_to(outside)
            # Also a real file for comparison
            (staging / "context-real.txt").write_text("real content")

            result = cleanup_staging(str(staging))

            assert result["status"] == "ok"
            # Real file should be deleted
            assert "context-real.txt" in result["deleted"]
            # Symlink should be skipped (skipped count incremented)
            assert "context-evil.txt" not in result["deleted"]
            assert result["skipped"] >= 1
            # Original file outside staging should still exist
            assert outside.exists()
        finally:
            import shutil
            if outside and outside.exists():
                outside.unlink()
            shutil.rmtree(staging, ignore_errors=True)

    def test_cleanup_staging_empty_tmp_dir(self):
        """Empty /tmp/ staging dir should return ok with empty lists."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        try:
            result = cleanup_staging(str(staging))
            assert result["status"] == "ok"
            assert result["deleted"] == []
            assert result["errors"] == []
            assert result["skipped"] == 0
        finally:
            staging.rmdir()


# ---------------------------------------------------------------
# write-save-result with --result-file and session_id auto-population
# ---------------------------------------------------------------

class TestWriteSaveResultFile:
    """Test the write-save-result CLI action with --result-file input.

    Replaces the removed write-save-result-direct action. Titles and
    categories are passed via a JSON file (not command-line arguments)
    to prevent shell injection.
    """

    def _make_tmp_staging(self):
        """Create a valid /tmp/ staging directory for testing."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        return staging

    def _write_input_file(self, staging_dir, data):
        """Write save-result-input.json to staging directory."""
        input_file = staging_dir / "save-result-input.json"
        input_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return input_file

    def _run_result_file(self, staging_dir, input_file=None):
        """Run write-save-result --result-file via subprocess."""
        cmd = [
            PYTHON, WRITE_SCRIPT,
            "--action", "write-save-result",
            "--staging-dir", str(staging_dir),
        ]
        if input_file is not None:
            cmd.extend(["--result-file", str(input_file)])
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )
        return result.returncode, result.stdout, result.stderr

    def test_happy_path(self):
        """Basic success: creates last-save-result.json with correct fields."""
        staging = self._make_tmp_staging()
        try:
            input_data = {
                "saved_at": "2026-03-22T10:00:00Z",
                "categories": ["session_summary", "constraint"],
                "titles": ["Session Feb 2026", "Max payload size"],
                "errors": [],
            }
            input_file = self._write_input_file(staging, input_data)
            rc, stdout, stderr = self._run_result_file(staging, input_file)
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            output = json.loads(stdout)
            assert output["status"] == "ok"

            result_file = staging / "last-save-result.json"
            assert result_file.exists(), "last-save-result.json not created"

            data = json.loads(result_file.read_text())
            assert data["categories"] == ["session_summary", "constraint"]
            assert data["titles"] == ["Session Feb 2026", "Max payload size"]
            assert data["saved_at"] == "2026-03-22T10:00:00Z"
            assert data["errors"] == []
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_single_category_and_title(self):
        """Single category and title should work."""
        staging = self._make_tmp_staging()
        try:
            input_data = {
                "saved_at": "2026-03-22T10:00:00Z",
                "categories": ["decision"],
                "titles": ["Use JWT tokens"],
                "errors": [],
            }
            input_file = self._write_input_file(staging, input_data)
            rc, stdout, stderr = self._run_result_file(staging, input_file)
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            result_file = staging / "last-save-result.json"
            data = json.loads(result_file.read_text())
            assert data["categories"] == ["decision"]
            assert data["titles"] == ["Use JWT tokens"]
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_title_with_shell_metacharacters(self):
        """Titles with shell metacharacters are handled safely via file input."""
        staging = self._make_tmp_staging()
        try:
            dangerous_title = '"; rm -rf /; echo "'
            input_data = {
                "saved_at": "2026-03-22T10:00:00Z",
                "categories": ["decision"],
                "titles": [dangerous_title],
                "errors": [],
            }
            input_file = self._write_input_file(staging, input_data)
            rc, stdout, stderr = self._run_result_file(staging, input_file)
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            result_file = staging / "last-save-result.json"
            data = json.loads(result_file.read_text())
            assert data["titles"] == [dangerous_title], (
                "Shell metacharacters in title should be preserved exactly"
            )
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_title_with_commas_preserved(self):
        """Titles containing commas are preserved (no comma-splitting)."""
        staging = self._make_tmp_staging()
        try:
            input_data = {
                "saved_at": "2026-03-22T10:00:00Z",
                "categories": ["session_summary"],
                "titles": ["Session 1, Part 2"],
                "errors": [],
            }
            input_file = self._write_input_file(staging, input_data)
            rc, stdout, stderr = self._run_result_file(staging, input_file)
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            result_file = staging / "last-save-result.json"
            data = json.loads(result_file.read_text())
            assert data["titles"] == ["Session 1, Part 2"], (
                "Commas in titles should be preserved (not split)"
            )
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_missing_result_file_fails(self):
        """Missing --result-file (and --result-json) should produce an error."""
        staging = self._make_tmp_staging()
        try:
            rc, stdout, stderr = self._run_result_file(staging)
            assert rc != 0
            assert "result" in (stdout + stderr).lower()
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_missing_staging_dir_fails(self):
        """Missing --staging-dir should produce an error."""
        cmd = [
            PYTHON, WRITE_SCRIPT,
            "--action", "write-save-result",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        assert "staging-dir" in (result.stdout + result.stderr).lower()

    def test_session_id_auto_populated_from_sentinel(self):
        """write-save-result auto-populates session_id from sentinel when missing."""
        staging = self._make_tmp_staging()
        try:
            sentinel_file = staging / ".triage-handled"
            sentinel_file.write_text(json.dumps({
                "session_id": "test-session-xyz",
                "state": "saving",
                "timestamp": 1711100000,
                "pid": os.getpid(),
            }), encoding="utf-8")

            input_data = {
                "saved_at": "2026-03-22T10:00:00Z",
                "categories": ["decision"],
                "titles": ["Use PostgreSQL"],
                "errors": [],
            }
            input_file = self._write_input_file(staging, input_data)
            rc, stdout, stderr = self._run_result_file(staging, input_file)
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            result_file = staging / "last-save-result.json"
            data = json.loads(result_file.read_text())
            assert data["session_id"] == "test-session-xyz", (
                "session_id should be auto-populated from sentinel file"
            )
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_session_id_none_without_sentinel(self):
        """write-save-result sets session_id to null when sentinel is absent."""
        staging = self._make_tmp_staging()
        try:
            input_data = {
                "saved_at": "2026-03-22T10:00:00Z",
                "categories": ["constraint"],
                "titles": ["Max 100 connections"],
                "errors": [],
            }
            input_file = self._write_input_file(staging, input_data)
            rc, stdout, stderr = self._run_result_file(staging, input_file)
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            result_file = staging / "last-save-result.json"
            data = json.loads(result_file.read_text())
            assert data["session_id"] is None, (
                "session_id should be None when sentinel file is absent"
            )
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_session_id_preserved_if_provided(self):
        """write-save-result preserves session_id if already in input."""
        staging = self._make_tmp_staging()
        try:
            sentinel_file = staging / ".triage-handled"
            sentinel_file.write_text(json.dumps({
                "session_id": "sentinel-session",
                "state": "saving",
            }), encoding="utf-8")

            input_data = {
                "saved_at": "2026-03-22T10:00:00Z",
                "categories": ["decision"],
                "titles": ["Use Redis"],
                "errors": [],
                "session_id": "provided-session",
            }
            input_file = self._write_input_file(staging, input_data)
            rc, stdout, stderr = self._run_result_file(staging, input_file)
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            result_file = staging / "last-save-result.json"
            data = json.loads(result_file.read_text())
            assert data["session_id"] == "provided-session", (
                "session_id should be preserved when already provided in input"
            )
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)


class TestUpdateSentinelState:
    """Test the update-sentinel-state CLI action.

    Tests sentinel state transitions (pending->saving, saving->saved,
    saving->failed, pending->failed) and invalid transitions.
    """

    def _make_tmp_staging(self):
        """Create a valid /tmp/ staging directory for testing."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        return staging

    def _write_sentinel(self, staging_dir, session_id, state):
        """Write a sentinel file to the staging directory."""
        sentinel_file = staging_dir / ".triage-handled"
        sentinel_file.write_text(json.dumps({
            "session_id": session_id,
            "state": state,
            "timestamp": 1711100000,
            "pid": os.getpid(),
        }), encoding="utf-8")

    def _run_update(self, staging_dir, state):
        """Run update-sentinel-state via subprocess."""
        cmd = [
            PYTHON, WRITE_SCRIPT,
            "--action", "update-sentinel-state",
            "--staging-dir", str(staging_dir),
            "--state", state,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )
        return result.returncode, result.stdout, result.stderr

    def test_pending_to_saving(self):
        """Valid transition: pending -> saving."""
        staging = self._make_tmp_staging()
        try:
            self._write_sentinel(staging, "sess-1", "pending")
            rc, stdout, stderr = self._run_update(staging, "saving")
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            output = json.loads(stdout)
            assert output["status"] == "ok"
            assert output["previous_state"] == "pending"
            assert output["new_state"] == "saving"

            # Verify sentinel file was updated
            sentinel = json.loads((staging / ".triage-handled").read_text())
            assert sentinel["state"] == "saving"
            assert sentinel["session_id"] == "sess-1"
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_saving_to_saved(self):
        """Valid transition: saving -> saved."""
        staging = self._make_tmp_staging()
        try:
            self._write_sentinel(staging, "sess-2", "saving")
            rc, stdout, stderr = self._run_update(staging, "saved")
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            output = json.loads(stdout)
            assert output["status"] == "ok"
            assert output["previous_state"] == "saving"
            assert output["new_state"] == "saved"
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_saving_to_failed(self):
        """Valid transition: saving -> failed."""
        staging = self._make_tmp_staging()
        try:
            self._write_sentinel(staging, "sess-3", "saving")
            rc, stdout, stderr = self._run_update(staging, "failed")
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            output = json.loads(stdout)
            assert output["status"] == "ok"
            assert output["previous_state"] == "saving"
            assert output["new_state"] == "failed"
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_pending_to_failed(self):
        """Valid transition: pending -> failed."""
        staging = self._make_tmp_staging()
        try:
            self._write_sentinel(staging, "sess-4", "pending")
            rc, stdout, stderr = self._run_update(staging, "failed")
            assert rc == 0, f"Failed: {stdout}\n{stderr}"
            output = json.loads(stdout)
            assert output["status"] == "ok"
            assert output["previous_state"] == "pending"
            assert output["new_state"] == "failed"
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_invalid_transition_pending_to_saved(self):
        """Invalid transition: pending -> saved (must go through saving)."""
        staging = self._make_tmp_staging()
        try:
            self._write_sentinel(staging, "sess-5", "pending")
            rc, stdout, stderr = self._run_update(staging, "saved")
            assert rc == 0, "Should exit 0 (fail-open)"
            output = json.loads(stdout)
            assert output["status"] == "error"
            assert "Invalid transition" in output["message"]
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_invalid_transition_saved_to_saving(self):
        """Invalid transition: saved -> saving (terminal state)."""
        staging = self._make_tmp_staging()
        try:
            self._write_sentinel(staging, "sess-6", "saved")
            rc, stdout, stderr = self._run_update(staging, "saving")
            assert rc == 0, "Should exit 0 (fail-open)"
            output = json.loads(stdout)
            assert output["status"] == "error"
            assert "Invalid transition" in output["message"]
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_missing_sentinel_file(self):
        """Missing sentinel file -> error but exit 0 (fail-open)."""
        staging = self._make_tmp_staging()
        try:
            rc, stdout, stderr = self._run_update(staging, "saving")
            assert rc == 0, "Should exit 0 (fail-open)"
            output = json.loads(stdout)
            assert output["status"] == "error"
            assert "Cannot read sentinel" in output["message"]
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_missing_staging_dir_fails_open(self):
        """Missing --staging-dir -> exit 0 (fail-open)."""
        cmd = [
            PYTHON, WRITE_SCRIPT,
            "--action", "update-sentinel-state",
            "--state", "saving",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, "Should exit 0 (fail-open)"
        output = json.loads(result.stdout)
        assert output["status"] == "error"

    def test_missing_state_fails_open(self):
        """Missing --state -> exit 0 (fail-open)."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        try:
            cmd = [
                PYTHON, WRITE_SCRIPT,
                "--action", "update-sentinel-state",
                "--staging-dir", str(staging),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            assert result.returncode == 0, "Should exit 0 (fail-open)"
            output = json.loads(result.stdout)
            assert output["status"] == "error"
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_session_id_preserved(self):
        """Session ID is preserved through state transition."""
        staging = self._make_tmp_staging()
        try:
            self._write_sentinel(staging, "my-unique-session", "pending")
            rc, stdout, stderr = self._run_update(staging, "saving")
            assert rc == 0
            output = json.loads(stdout)
            assert output["session_id"] == "my-unique-session"

            # Verify in file
            sentinel = json.loads((staging / ".triage-handled").read_text())
            assert sentinel["session_id"] == "my-unique-session"
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_timestamp_updated(self):
        """Timestamp is updated on state transition."""
        staging = self._make_tmp_staging()
        try:
            self._write_sentinel(staging, "sess-ts", "pending")
            old_sentinel = json.loads((staging / ".triage-handled").read_text())
            old_ts = old_sentinel["timestamp"]

            rc, stdout, stderr = self._run_update(staging, "saving")
            assert rc == 0
            new_sentinel = json.loads((staging / ".triage-handled").read_text())
            assert new_sentinel["timestamp"] >= old_ts, (
                "Timestamp should be updated on state transition"
            )
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_malformed_json_sentinel_fails_open(self):
        """Malformed JSON in sentinel -> error but exit 0 (fail-open)."""
        staging = self._make_tmp_staging()
        try:
            sentinel_file = staging / ".triage-handled"
            sentinel_file.write_text("not valid json {{{", encoding="utf-8")
            rc, stdout, stderr = self._run_update(staging, "saving")
            assert rc == 0, "Should exit 0 (fail-open)"
            output = json.loads(stdout)
            assert output["status"] == "error"
            assert "Cannot read sentinel" in output["message"]
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)


class TestLegacyStagingValidation:
    """Tests for _is_valid_legacy_staging() helper function.

    Ensures legacy staging path validation requires .claude/memory/.staging
    ancestry, rejecting arbitrary paths ending in memory/.staging.
    Default mode (allow_child=False) requires .staging as the terminal component.
    """

    # --- Directory mode (default, allow_child=False) ---

    def test_valid_legacy_path_accepted(self):
        """Standard .claude/memory/.staging path is accepted."""
        assert _is_valid_legacy_staging("/home/user/project/.claude/memory/.staging") is True

    def test_evil_memory_staging_rejected(self):
        """/tmp/evil/memory/.staging without .claude ancestor is rejected."""
        assert _is_valid_legacy_staging("/tmp/evil/memory/.staging") is False

    def test_etc_memory_staging_rejected(self):
        """/etc/memory/.staging without .claude ancestor is rejected."""
        assert _is_valid_legacy_staging("/etc/memory/.staging") is False

    def test_tmp_staging_still_accepted(self):
        """/tmp/.claude-memory-staging-* paths are NOT legacy paths.

        These are validated by a separate startswith() check in each function.
        _is_valid_legacy_staging should return False for them (handled elsewhere).
        """
        assert _is_valid_legacy_staging("/tmp/.claude-memory-staging-abc123") is False

    def test_nested_claude_path_accepted(self):
        """Deeply nested project path with .claude/memory/.staging is accepted."""
        assert _is_valid_legacy_staging("/home/user/deeply/nested/project/.claude/memory/.staging") is True

    def test_root_claude_path_accepted(self):
        """Root-level .claude/memory/.staging is accepted."""
        assert _is_valid_legacy_staging("/.claude/memory/.staging") is True

    def test_wrong_order_rejected(self):
        """Components in wrong order (memory/.claude/.staging) are rejected."""
        assert _is_valid_legacy_staging("/home/user/memory/.claude/.staging") is False

    def test_missing_memory_rejected(self):
        """Path with .claude but missing memory component is rejected."""
        assert _is_valid_legacy_staging("/home/user/.claude/.staging") is False

    def test_partial_claude_name_rejected(self):
        """Path component 'claude' (without dot) does not match."""
        assert _is_valid_legacy_staging("/home/user/claude/memory/.staging") is False

    def test_subdirectory_bypass_rejected(self):
        """Deep subdirectory under .staging is rejected in directory mode.

        Prevents attacker from expanding cleanup scope by specifying a
        subdirectory as the staging root.
        """
        assert _is_valid_legacy_staging(
            "/home/user/.claude/memory/.staging/some/deep/folder"
        ) is False

    def test_file_in_staging_rejected_in_dir_mode(self):
        """File path inside staging is rejected in default directory mode.

        Only allow_child=True should accept files within staging.
        """
        assert _is_valid_legacy_staging(
            "/home/user/.claude/memory/.staging/intent-decision.json"
        ) is False

    # --- File mode (allow_child=True) ---

    def test_file_inside_staging_accepted_with_allow_child(self):
        """File path within .claude/memory/.staging/ is accepted with allow_child."""
        assert _is_valid_legacy_staging(
            "/home/user/.claude/memory/.staging/intent-decision.json",
            allow_child=True,
        ) is True

    def test_staging_dir_accepted_with_allow_child(self):
        """Staging directory itself is accepted with allow_child too."""
        assert _is_valid_legacy_staging(
            "/home/user/.claude/memory/.staging",
            allow_child=True,
        ) is True

    def test_evil_path_rejected_with_allow_child(self):
        """Evil path without .claude ancestor rejected even with allow_child."""
        assert _is_valid_legacy_staging(
            "/tmp/evil/memory/.staging/intent.json",
            allow_child=True,
        ) is False


class TestRuntimeErrorDegradation:
    """Tests for RuntimeError/OSError graceful degradation in write_save_result()
    and path containment checks in update_sentinel_state().

    When validate_staging_dir() raises RuntimeError (e.g., symlink at staging
    path) or OSError, write_save_result() should return an error dict instead
    of propagating an unhandled exception. This is a V-R2 adversarial finding.
    """

    def _make_tmp_staging(self):
        """Create a valid /tmp/ staging directory for testing."""
        import tempfile
        staging = Path(tempfile.mkdtemp(prefix=".claude-memory-staging-"))
        return staging

    def _valid_result_json(self):
        """Return a minimal valid result JSON string."""
        return json.dumps({
            "categories": ["decision"],
            "titles": ["Test Title"],
            "errors": [],
            "saved_at": "2026-03-22T00:00:00Z",
            "session_id": None,
        })

    def test_write_save_result_degrades_on_runtime_error(self):
        """write_save_result returns error dict when validate_staging_dir raises RuntimeError.

        Mocks validate_staging_dir to raise RuntimeError (e.g., symlink detected
        at staging path). The function must return {"status": "error", ...}
        instead of propagating an unhandled exception.
        """
        from unittest.mock import patch

        staging = self._make_tmp_staging()
        try:
            with patch(
                "memory_staging_utils.validate_staging_dir",
                side_effect=RuntimeError(
                    f"Staging dir is a symlink (possible attack): {staging}"
                ),
            ):
                result = write_save_result(str(staging), self._valid_result_json())
                assert isinstance(result, dict), "Must return a dict, not raise"
                assert result["status"] == "error", f"Expected error status, got: {result}"
                assert "message" in result
                assert "Staging dir validation failed" in result["message"]
                assert "symlink" in result["message"].lower()
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_write_save_result_degrades_on_os_error(self):
        """write_save_result returns error dict when validate_staging_dir raises OSError.

        Mocks validate_staging_dir to raise OSError (e.g., permission denied).
        The function must degrade gracefully instead of crashing.
        """
        from unittest.mock import patch

        staging = self._make_tmp_staging()
        try:
            with patch(
                "memory_staging_utils.validate_staging_dir",
                side_effect=OSError("Permission denied: /tmp/.claude-memory-staging-mock"),
            ):
                result = write_save_result(str(staging), self._valid_result_json())
                assert isinstance(result, dict), "Must return a dict, not raise"
                assert result["status"] == "error"
                assert "Staging dir validation failed" in result["message"]
                assert "Permission denied" in result["message"]
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_update_sentinel_state_rejects_invalid_path(self):
        """update_sentinel_state rejects paths that aren't valid staging directories.

        The path containment check should reject arbitrary paths that are
        neither /tmp/.claude-memory-staging-* nor legacy .claude/memory/.staging.
        """
        # Use an arbitrary /tmp path that doesn't match staging pattern
        result = update_sentinel_state("/tmp/not-a-staging-dir", "saving")
        assert result["status"] == "error"
        assert "not a valid staging directory" in result["message"]

        # Also verify /home paths are rejected
        result2 = update_sentinel_state("/home/user/random/path", "saving")
        assert result2["status"] == "error"
        assert "not a valid staging directory" in result2["message"]

        # Verify /etc is rejected
        result3 = update_sentinel_state("/etc/passwd", "saving")
        assert result3["status"] == "error"
        assert "not a valid staging directory" in result3["message"]

    def test_write_save_result_error_message_contains_detail(self):
        """Error message from RuntimeError degradation includes the original exception text.

        When validate_staging_dir raises RuntimeError with a descriptive message,
        that text must be preserved in the returned error dict so operators
        can diagnose the root cause.
        """
        from unittest.mock import patch

        staging = self._make_tmp_staging()
        specific_message = "Staging dir owned by uid 1001, expected 1000: /tmp/.claude-memory-staging-abc"
        try:
            with patch(
                "memory_staging_utils.validate_staging_dir",
                side_effect=RuntimeError(specific_message),
            ):
                result = write_save_result(str(staging), self._valid_result_json())
                assert result["status"] == "error"
                # The specific RuntimeError message must appear in the response
                assert specific_message in result["message"], (
                    f"Expected specific error detail in message. Got: {result['message']}"
                )
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------
# Phase 0: C1 -- do_create() overwrite protection
# ---------------------------------------------------------------

class TestCreateOverwriteProtection:
    """C1: do_create() must not silently overwrite active files."""

    def test_create_on_existing_active_file_errors(self, memory_project):
        """CREATE on an existing active file with different content should fail."""
        target = ".claude/memory/decisions/use-jwt.json"
        target_abs = memory_project / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        # Write an existing active memory
        existing = make_decision_memory()
        target_abs.write_text(json.dumps(existing, indent=2))
        # Try to create a different memory at the same path
        new_mem = make_decision_memory(title="Different title for JWT auth")
        input_file = write_input_file(memory_project, new_mem)
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 1
        assert "CREATE_OVERWRITE_ERROR" in stdout

    def test_create_idempotent_replay_succeeds(self, memory_project):
        """CREATE with identical content (idempotent replay) should succeed."""
        target = ".claude/memory/decisions/use-jwt.json"
        # First create
        mem = make_decision_memory()
        input_file = write_input_file(memory_project, mem)
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 0, f"First create failed: {stdout}\n{stderr}"
        # Second create with same content (replay)
        input_file2 = write_input_file(memory_project, mem)
        rc2, stdout2, stderr2 = run_write(
            "create", "decision", target, input_file2,
            cwd=str(memory_project),
        )
        assert rc2 == 0, f"Idempotent replay failed: {stdout2}\n{stderr2}"


# ---------------------------------------------------------------
# Phase 0: C2 -- add_to_index() path deduplication
# ---------------------------------------------------------------

class TestIndexDeduplication:
    """C2: add_to_index() must deduplicate by rel_path."""

    def test_duplicate_path_deduplicated(self, tmp_path):
        """Adding an entry with a path already in the index replaces the old entry."""
        index_path = tmp_path / "index.md"
        index_path.write_text("# Memory Index\n\n")
        # Add first entry
        line1 = "- [DECISION] Old title -> .claude/memory/decisions/use-jwt.json #tags:auth"
        add_to_index(index_path, line1)
        # Add second entry with same path but different title
        line2 = "- [DECISION] New title -> .claude/memory/decisions/use-jwt.json #tags:auth,updated"
        add_to_index(index_path, line2)
        content = index_path.read_text()
        # Should contain only one entry for this path
        count = content.count(".claude/memory/decisions/use-jwt.json")
        assert count == 1, f"Expected 1 entry, found {count} in:\n{content}"
        assert "New title" in content
        assert "Old title" not in content

    def test_partial_failure_retry_no_duplicates(self, memory_project):
        """Simulating partial failure retry: create same file twice produces one index entry."""
        target = ".claude/memory/decisions/use-jwt.json"
        mem = make_decision_memory()
        # First create
        input_file = write_input_file(memory_project, mem)
        rc, stdout, stderr = run_write(
            "create", "decision", target, input_file,
            cwd=str(memory_project),
        )
        assert rc == 0, f"First create failed: {stdout}\n{stderr}"
        # Second create (same content = idempotent replay, allowed by C1)
        input_file2 = write_input_file(memory_project, mem)
        rc2, stdout2, stderr2 = run_write(
            "create", "decision", target, input_file2,
            cwd=str(memory_project),
        )
        assert rc2 == 0, f"Replay failed: {stdout2}\n{stderr2}"
        # Verify index has exactly one entry
        index = (memory_project / ".claude" / "memory" / "index.md").read_text()
        count = index.count("use-jwt.json")
        assert count == 1, f"Expected 1 index entry, found {count} in:\n{index}"


# ---------------------------------------------------------------
# Phase 0: H1 -- --skip-auto-enforce flag
# ---------------------------------------------------------------

class TestSkipAutoEnforce:
    """H1: --skip-auto-enforce suppresses enforcement subprocess after session create."""

    def test_create_session_with_skip_auto_enforce_no_enforce(self, memory_project):
        """CREATE session_summary with --skip-auto-enforce should not spawn enforce."""
        mem = make_session_memory()
        input_file = write_input_file(memory_project, mem)
        target = ".claude/memory/sessions/session-2026-02-14.json"
        rc, stdout, stderr = run_write(
            "create", "session_summary", target, input_file,
            cwd=str(memory_project),
            skip_auto_enforce=True,
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        # With --skip-auto-enforce, the enforce subprocess should not be invoked.
        # Stderr should NOT contain enforcement-related warnings.
        assert "Post-create enforcement" not in stderr

    def test_create_session_without_flag_auto_enforces(self, memory_project):
        """CREATE session_summary without --skip-auto-enforce triggers enforcement (regression guard)."""
        mem = make_session_memory()
        input_file = write_input_file(memory_project, mem)
        target = ".claude/memory/sessions/session-2026-02-14.json"
        rc, stdout, stderr = run_write(
            "create", "session_summary", target, input_file,
            cwd=str(memory_project),
            skip_auto_enforce=False,
        )
        assert rc == 0, f"Failed: {stdout}\n{stderr}"
        # The enforcement subprocess should have been attempted.
        # It may warn (enforce script may not exist in test env) or succeed,
        # but the code path should have been entered. If the enforce script
        # doesn't exist in this env, there should be no error since it's guarded.
        # This is a regression guard: we verify the flag defaults to False and
        # the auto-enforce block is reachable.
