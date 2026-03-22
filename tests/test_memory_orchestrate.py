"""Tests for memory_orchestrate.py -- Phase 1.5 deterministic CUD resolution pipeline."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import (
    make_decision_memory,
    make_tech_debt_memory,
    make_constraint_memory,
    write_memory_file,
    write_index,
)

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
ORCHESTRATE_SCRIPT = str(SCRIPTS_DIR / "memory_orchestrate.py")
PYTHON = sys.executable

# Direct imports for unit tests of pure functions
sys.path.insert(0, str(SCRIPTS_DIR))
from memory_orchestrate import (
    collect_intents,
    resolve_cud,
    build_manifest,
    CUD_TABLE,
)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def write_intent(staging_dir, category, intent_data):
    """Write an intent JSON file to staging directory."""
    path = staging_dir / f"intent-{category}.json"
    path.write_text(json.dumps(intent_data, indent=2))
    return path


def make_save_intent(category, title="Test Memory", intended_action="create"):
    """Build a valid SAVE intent dict."""
    return {
        "category": category,
        "new_info_summary": f"New info about {title.lower()}",
        "intended_action": intended_action,
        "partial_content": {
            "title": title,
            "tags": ["test", category],
            "confidence": 0.8,
            "change_summary": "Initial creation from test",
            "content": _category_content(category),
        },
    }


def make_noop_intent(category):
    """Build a NOOP intent dict."""
    return {
        "category": category,
        "action": "noop",
        "noop_reason": "No relevant information found",
    }


def _category_content(category):
    """Return minimal valid content for a category."""
    contents = {
        "decision": {
            "status": "accepted",
            "context": "Test context",
            "decision": "Test decision",
            "rationale": ["Test reason"],
            "alternatives": [],
            "consequences": [],
        },
        "tech_debt": {
            "status": "open",
            "priority": "low",
            "description": "Test debt",
            "reason_deferred": "Testing",
            "impact": ["None"],
            "suggested_fix": ["Fix it"],
            "acceptance_criteria": ["Fixed"],
        },
        "constraint": {
            "kind": "technical",
            "rule": "Test rule",
            "impact": ["Test impact"],
            "workarounds": [],
            "severity": "low",
            "active": True,
        },
        "preference": {
            "topic": "Testing",
            "value": "pytest",
            "reason": "Standard",
            "strength": "moderate",
            "examples": {"prefer": [], "avoid": []},
        },
        "session_summary": {
            "goal": "Test session",
            "outcome": "success",
            "completed": ["Tests"],
            "in_progress": [],
            "blockers": [],
            "next_actions": [],
            "key_changes": [],
        },
        "runbook": {
            "trigger": "Test trigger",
            "symptoms": ["Test symptom"],
            "steps": ["Step 1"],
            "verification": "Check it",
            "root_cause": "Test cause",
            "environment": "Test env",
        },
    }
    return contents.get(category, {"description": "Test"})


def run_orchestrate(staging_dir, memory_root=None, extra_args=None):
    """Run memory_orchestrate.py and return (returncode, stdout, stderr)."""
    cmd = [PYTHON, ORCHESTRATE_SCRIPT, "--staging-dir", str(staging_dir)]
    if memory_root:
        cmd.extend(["--memory-root", str(memory_root)])
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------
# Unit tests: collect_intents
# ---------------------------------------------------------------

class TestCollectIntents:
    def test_skips_noop_intents(self, tmp_path):
        write_intent(tmp_path, "decision", make_noop_intent("decision"))
        write_intent(tmp_path, "constraint", make_noop_intent("constraint"))
        intents = collect_intents(str(tmp_path))
        assert intents == {}

    def test_collects_save_intents(self, tmp_path):
        write_intent(tmp_path, "decision", make_save_intent("decision"))
        intents = collect_intents(str(tmp_path))
        assert "decision" in intents
        assert intents["decision"]["category"] == "decision"

    def test_skips_missing_required_fields(self, tmp_path):
        # Intent missing partial_content
        bad_intent = {
            "category": "decision",
            "new_info_summary": "Some info",
            # no partial_content
        }
        write_intent(tmp_path, "decision", bad_intent)
        intents = collect_intents(str(tmp_path))
        assert intents == {}

    def test_skips_partial_content_missing_fields(self, tmp_path):
        # partial_content missing 'content' field
        intent = make_save_intent("decision")
        del intent["partial_content"]["content"]
        write_intent(tmp_path, "decision", intent)
        intents = collect_intents(str(tmp_path))
        assert intents == {}

    def test_skips_invalid_json(self, tmp_path):
        path = tmp_path / "intent-decision.json"
        path.write_text("not valid json {{{")
        intents = collect_intents(str(tmp_path))
        assert intents == {}

    def test_mixed_noop_and_save(self, tmp_path):
        write_intent(tmp_path, "decision", make_noop_intent("decision"))
        write_intent(tmp_path, "tech_debt", make_save_intent("tech_debt"))
        intents = collect_intents(str(tmp_path))
        assert "decision" not in intents
        assert "tech_debt" in intents


# ---------------------------------------------------------------
# Unit tests: CUD resolution table
# ---------------------------------------------------------------

class TestCUDResolutionTable:
    """Verify all CUD table entries produce correct actions."""

    def test_create_create(self):
        assert CUD_TABLE[("CREATE", "CREATE")] == "CREATE"

    def test_update_or_delete_update(self):
        assert CUD_TABLE[("UPDATE_OR_DELETE", "UPDATE")] == "UPDATE"

    def test_update_or_delete_delete(self):
        assert CUD_TABLE[("UPDATE_OR_DELETE", "DELETE")] == "DELETE"

    def test_create_update(self):
        # No candidate exists, so CREATE even if intent says UPDATE
        assert CUD_TABLE[("CREATE", "UPDATE")] == "CREATE"

    def test_create_delete(self):
        # Cannot DELETE with 0 candidates
        assert CUD_TABLE[("CREATE", "DELETE")] == "NOOP"

    def test_update_or_delete_create(self):
        # Subagent says new despite candidate existing
        assert CUD_TABLE[("UPDATE_OR_DELETE", "CREATE")] == "CREATE"

    def test_update_only_delete_becomes_update(self):
        # When structural_cud is UPDATE (DELETE not allowed), DELETE -> UPDATE
        assert CUD_TABLE[("UPDATE", "DELETE")] == "UPDATE"

    def test_update_only_update(self):
        assert CUD_TABLE[("UPDATE", "UPDATE")] == "UPDATE"

    def test_update_only_create(self):
        assert CUD_TABLE[("UPDATE", "CREATE")] == "CREATE"


# ---------------------------------------------------------------
# Unit tests: resolve_cud
# ---------------------------------------------------------------

class TestResolveCUD:
    def test_candidate_failed_produces_skip(self):
        intents = {"decision": make_save_intent("decision")}
        candidates = {"decision": None}
        resolved = resolve_cud(intents, candidates)
        assert resolved["decision"]["action"] == "SKIP"
        assert "candidate_failed" in resolved["decision"]["reason"]

    def test_pre_action_noop(self):
        intents = {"decision": make_save_intent("decision")}
        candidates = {
            "decision": {
                "pre_action": "NOOP",
                "structural_cud": "NOOP",
                "vetoes": [],
                "candidate": None,
            }
        }
        resolved = resolve_cud(intents, candidates)
        assert resolved["decision"]["action"] == "NOOP"

    def test_create_with_no_candidate(self):
        intents = {"decision": make_save_intent("decision", intended_action="create")}
        candidates = {
            "decision": {
                "pre_action": "CREATE",
                "structural_cud": "CREATE",
                "vetoes": [],
                "candidate": None,
            }
        }
        resolved = resolve_cud(intents, candidates)
        assert resolved["decision"]["action"] == "CREATE"

    def test_veto_blocks_action(self):
        intents = {"decision": make_save_intent("decision", intended_action="delete")}
        candidates = {
            "decision": {
                "pre_action": None,
                "structural_cud": "UPDATE_OR_DELETE",
                "vetoes": ["Cannot DELETE decision (triage-initiated)"],
                "candidate": {"path": "some/path.json"},
            }
        }
        resolved = resolve_cud(intents, candidates)
        assert resolved["decision"]["action"] == "NOOP"
        assert "vetoed" in resolved["decision"]["reason"]

    def test_veto_does_not_block_different_action(self):
        intents = {"tech_debt": make_save_intent("tech_debt", intended_action="update")}
        candidates = {
            "tech_debt": {
                "pre_action": None,
                "structural_cud": "UPDATE_OR_DELETE",
                "vetoes": ["Cannot CREATE tech_debt"],
                "candidate": {"path": "some/path.json"},
            }
        }
        resolved = resolve_cud(intents, candidates)
        # UPDATE is not vetoed, only CREATE is
        assert resolved["tech_debt"]["action"] == "UPDATE"

    def test_unrecognized_intended_action_defaults_update(self):
        intent = make_save_intent("decision", intended_action="merge")
        intents = {"decision": intent}
        candidates = {
            "decision": {
                "pre_action": "CREATE",
                "structural_cud": "CREATE",
                "vetoes": [],
                "candidate": None,
            }
        }
        resolved = resolve_cud(intents, candidates)
        # L1=CREATE, L2=UPDATE(default) -> CREATE
        assert resolved["decision"]["action"] == "CREATE"

    def test_missing_intended_action_defaults_update(self):
        intent = make_save_intent("decision")
        del intent["intended_action"]  # remove it
        intents = {"decision": intent}
        candidates = {
            "decision": {
                "pre_action": None,
                "structural_cud": "UPDATE_OR_DELETE",
                "vetoes": [],
                "candidate": {"path": "some/path.json"},
            }
        }
        resolved = resolve_cud(intents, candidates)
        # L1=UPDATE_OR_DELETE, L2=UPDATE(default) -> UPDATE
        assert resolved["decision"]["action"] == "UPDATE"


# ---------------------------------------------------------------
# Unit tests: build_manifest
# ---------------------------------------------------------------

class TestBuildManifest:
    def test_actionable_status(self):
        resolved = {"decision": {"action": "CREATE"}}
        manifest = build_manifest(resolved)
        assert manifest["status"] == "actionable"

    def test_all_noop_status(self):
        resolved = {
            "decision": {"action": "NOOP", "reason": "test"},
            "tech_debt": {"action": "SKIP", "reason": "test"},
        }
        manifest = build_manifest(resolved)
        assert manifest["status"] == "all_noop"

    def test_mixed_actions(self):
        resolved = {
            "decision": {"action": "CREATE"},
            "tech_debt": {"action": "NOOP", "reason": "test"},
        }
        manifest = build_manifest(resolved)
        assert manifest["status"] == "actionable"
        assert manifest["categories"]["decision"]["action"] == "CREATE"
        assert manifest["categories"]["tech_debt"]["action"] == "NOOP"


# ---------------------------------------------------------------
# Integration tests (subprocess)
# ---------------------------------------------------------------

class TestAllNoopIntents:
    """All intents are noop -> manifest status is 'all_noop'."""

    def test_all_noop(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        write_intent(staging, "decision", make_noop_intent("decision"))
        write_intent(staging, "constraint", make_noop_intent("constraint"))

        rc, stdout, stderr = run_orchestrate(staging)
        assert rc == 0

        output = json.loads(stdout)
        assert output["status"] == "all_noop"
        assert output["categories"] == {}

    def test_manifest_file_written(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        write_intent(staging, "decision", make_noop_intent("decision"))

        rc, stdout, stderr = run_orchestrate(staging)
        assert rc == 0

        manifest_path = staging / "orchestration-result.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["status"] == "all_noop"


class TestSingleCreate:
    """One valid intent with no existing candidates -> CREATE + draft."""

    def test_create_decision(self, tmp_path):
        # Set up a memory root with an empty index (no existing memories)
        memory_root = tmp_path / ".claude" / "memory"
        memory_root.mkdir(parents=True)
        for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
            (memory_root / folder).mkdir()
        write_index(memory_root)  # empty index

        # Staging directory
        staging = tmp_path / "staging"
        staging.mkdir()

        intent = make_save_intent("decision", title="Use PostgreSQL for storage")
        write_intent(staging, "decision", intent)

        rc, stdout, stderr = run_orchestrate(staging, memory_root=memory_root)
        assert rc == 0, f"stderr: {stderr}"

        output = json.loads(stdout)
        assert output["status"] == "actionable"
        assert "decision" in output["categories"]
        assert output["categories"]["decision"]["action"] == "CREATE"
        assert output["categories"]["decision"].get("draft_path")

        # Verify draft file exists
        draft_path = output["categories"]["decision"]["draft_path"]
        assert os.path.isfile(draft_path)

        # Verify draft contents
        draft = json.loads(Path(draft_path).read_text())
        assert draft["category"] == "decision"
        assert draft["title"] == "Use PostgreSQL for storage"

    def test_manifest_written_for_create(self, tmp_path):
        memory_root = tmp_path / ".claude" / "memory"
        memory_root.mkdir(parents=True)
        for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
            (memory_root / folder).mkdir()
        write_index(memory_root)

        staging = tmp_path / "staging"
        staging.mkdir()
        write_intent(staging, "decision", make_save_intent("decision", title="Test Decision"))

        rc, stdout, stderr = run_orchestrate(staging, memory_root=memory_root)
        assert rc == 0

        manifest_path = staging / "orchestration-result.json"
        assert manifest_path.exists()


class TestUpdateWithCandidate:
    """Intent + existing memory -> UPDATE + draft."""

    def test_update_existing_decision(self, tmp_path):
        # Set up memory root with existing decision
        memory_root = tmp_path / ".claude" / "memory"
        memory_root.mkdir(parents=True)
        for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
            (memory_root / folder).mkdir()

        existing = make_decision_memory(
            id_val="use-jwt",
            title="Use JWT for authentication",
            tags=["auth", "jwt", "security"],
        )
        write_memory_file(memory_root, existing)
        # Write index with path_prefix matching the actual tmp_path structure
        write_index(memory_root, existing, path_prefix=str(memory_root))

        staging = tmp_path / "staging"
        staging.mkdir()

        # Intent that should match the existing JWT memory
        intent = make_save_intent(
            "decision",
            title="Use JWT for authentication",
            intended_action="update",
        )
        intent["new_info_summary"] = "JWT authentication token expiry changed to 2 hours"
        write_intent(staging, "decision", intent)

        rc, stdout, stderr = run_orchestrate(staging, memory_root=memory_root)
        assert rc == 0, f"stderr: {stderr}"

        output = json.loads(stdout)
        assert output["status"] == "actionable"
        cat_result = output["categories"]["decision"]
        assert cat_result["action"] in ("UPDATE", "CREATE")
        # Regardless of whether candidate matched, we should have a draft
        assert cat_result.get("draft_path")


class TestInvalidIntentSkipped:
    """Missing required fields -> category skipped entirely."""

    def test_missing_partial_content(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()

        bad_intent = {
            "category": "decision",
            "new_info_summary": "Some info",
            # missing partial_content entirely
        }
        write_intent(staging, "decision", bad_intent)

        rc, stdout, stderr = run_orchestrate(staging)
        assert rc == 0

        output = json.loads(stdout)
        assert output["status"] == "all_noop"
        assert "decision" not in output["categories"]

    def test_missing_content_in_partial(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()

        intent = make_save_intent("decision")
        del intent["partial_content"]["content"]
        write_intent(staging, "decision", intent)

        rc, stdout, stderr = run_orchestrate(staging)
        assert rc == 0

        output = json.loads(stdout)
        assert output["status"] == "all_noop"

    def test_valid_intent_alongside_invalid(self, tmp_path):
        """Valid intent should still be processed even if another is invalid."""
        memory_root = tmp_path / ".claude" / "memory"
        memory_root.mkdir(parents=True)
        for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
            (memory_root / folder).mkdir()
        write_index(memory_root)

        staging = tmp_path / "staging"
        staging.mkdir()

        # Invalid intent
        bad_intent = {"category": "decision", "new_info_summary": "info"}
        write_intent(staging, "decision", bad_intent)

        # Valid intent
        write_intent(staging, "tech_debt", make_save_intent("tech_debt", title="Fix legacy API"))

        rc, stdout, stderr = run_orchestrate(staging, memory_root=memory_root)
        assert rc == 0

        output = json.loads(stdout)
        assert "decision" not in output["categories"]
        assert "tech_debt" in output["categories"]


class TestManifestWritten:
    """Verify orchestration-result.json is written correctly."""

    def test_manifest_has_correct_structure(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        write_intent(staging, "decision", make_noop_intent("decision"))

        rc, stdout, stderr = run_orchestrate(staging)
        assert rc == 0

        manifest_path = staging / "orchestration-result.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert "status" in manifest
        assert "categories" in manifest
        assert isinstance(manifest["categories"], dict)

    def test_manifest_matches_stdout(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        write_intent(staging, "decision", make_noop_intent("decision"))

        rc, stdout, stderr = run_orchestrate(staging)
        assert rc == 0

        manifest_path = staging / "orchestration-result.json"
        manifest_file = json.loads(manifest_path.read_text())
        manifest_stdout = json.loads(stdout)

        assert manifest_file["status"] == manifest_stdout["status"]
        assert manifest_file["categories"] == manifest_stdout["categories"]

    def test_empty_staging_produces_all_noop(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        # No intent files at all

        rc, stdout, stderr = run_orchestrate(staging)
        assert rc == 0

        output = json.loads(stdout)
        assert output["status"] == "all_noop"


class TestCUDResolutionIntegration:
    """Integration: verify CUD resolution with mocked candidate data."""

    def test_create_delete_produces_noop(self):
        """CREATE + DELETE = NOOP (cannot delete with 0 candidates)."""
        intents = {"decision": make_save_intent("decision", intended_action="delete")}
        candidates = {
            "decision": {
                "pre_action": "CREATE",
                "structural_cud": "CREATE",
                "vetoes": [],
                "candidate": None,
            }
        }
        resolved = resolve_cud(intents, candidates)
        assert resolved["decision"]["action"] == "NOOP"

    def test_update_or_delete_delete_produces_delete(self):
        """UPDATE_OR_DELETE + DELETE = DELETE."""
        intents = {"tech_debt": make_save_intent("tech_debt", intended_action="delete")}
        candidates = {
            "tech_debt": {
                "pre_action": None,
                "structural_cud": "UPDATE_OR_DELETE",
                "vetoes": [],
                "candidate": {"path": ".claude/memory/tech-debt/test.json"},
            }
        }
        resolved = resolve_cud(intents, candidates)
        assert resolved["tech_debt"]["action"] == "DELETE"

    def test_update_or_delete_create_produces_create(self):
        """UPDATE_OR_DELETE + CREATE = CREATE (subagent says new despite candidate)."""
        intents = {"tech_debt": make_save_intent("tech_debt", intended_action="create")}
        candidates = {
            "tech_debt": {
                "pre_action": None,
                "structural_cud": "UPDATE_OR_DELETE",
                "vetoes": [],
                "candidate": {"path": ".claude/memory/tech-debt/test.json"},
            }
        }
        resolved = resolve_cud(intents, candidates)
        assert resolved["tech_debt"]["action"] == "CREATE"
