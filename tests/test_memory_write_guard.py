"""Tests for memory_write_guard.py -- PreToolUse guard against direct writes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
GUARD_SCRIPT = str(SCRIPTS_DIR / "memory_write_guard.py")
PYTHON = sys.executable


def run_guard(hook_input):
    """Run memory_write_guard.py with given input, return (stdout, returncode)."""
    result = subprocess.run(
        [PYTHON, GUARD_SCRIPT],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout, result.returncode


def parse_decision(stdout):
    """Parse the hook output and return permissionDecision or None."""
    if not stdout.strip():
        return None  # No output = abstain
    output = json.loads(stdout)
    return output.get("hookSpecificOutput", {}).get("permissionDecision")


class TestWriteGuard:
    def test_blocks_memory_directory_write(self):
        """Writes targeting the memory directory should be denied."""
        hook_input = {
            "tool_input": {
                "file_path": "/home/user/project/.claude/memory/decisions/test.json",
            }
        }
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        if stdout.strip():
            output = json.loads(stdout)
            hook_output = output.get("hookSpecificOutput", {})
            assert hook_output.get("permissionDecision") == "deny"
            assert "memory_write.py" in hook_output.get("permissionDecisionReason", "")

    def test_allows_non_memory_write(self):
        """Writes to non-memory paths should pass through."""
        hook_input = {
            "tool_input": {
                "file_path": "/home/user/project/src/main.py",
            }
        }
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        # Should produce no output (pass through)
        if stdout.strip():
            output = json.loads(stdout)
            assert output.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"

    def test_allows_temp_staging_file(self):
        """Writes to /tmp/.memory-write-pending.json are allowed."""
        hook_input = {
            "tool_input": {
                "file_path": "/tmp/.memory-write-pending.json",
            }
        }
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        # No deny output
        if stdout.strip():
            output = json.loads(stdout)
            assert output.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"

    def test_missing_file_path(self):
        """Missing file_path should pass through gracefully."""
        hook_input = {"tool_input": {}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0

    def test_empty_file_path(self):
        """Empty file_path should pass through gracefully."""
        hook_input = {"tool_input": {"file_path": ""}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0

    def test_empty_input(self):
        """Empty stdin should exit gracefully."""
        result = subprocess.run(
            [PYTHON, GUARD_SCRIPT],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_invalid_json_input(self):
        """Invalid JSON should exit gracefully."""
        result = subprocess.run(
            [PYTHON, GUARD_SCRIPT],
            input="{bad json",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_blocks_memory_path_ending(self):
        """Path ending with /.claude/memory should also be blocked."""
        hook_input = {
            "tool_input": {
                "file_path": "/home/user/project/.claude/memory/preferences/dark-mode.json",
            }
        }
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        if stdout.strip():
            output = json.loads(stdout)
            hook_output = output.get("hookSpecificOutput", {})
            assert hook_output.get("permissionDecision") == "deny"

    def test_missing_tool_input(self):
        """Missing tool_input should pass through gracefully."""
        hook_input = {}
        stdout, rc = run_guard(hook_input)
        assert rc == 0

    # --- Config file exemption tests ---

    def test_allows_config_file_write(self):
        """memory-config.json in .claude/memory/ should be ALLOWED (not a memory record)."""
        hook_input = {
            "tool_input": {
                "file_path": "/home/user/project/.claude/memory/memory-config.json",
            }
        }
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        # Config file should NOT be denied
        if stdout.strip():
            output = json.loads(stdout)
            hook_output = output.get("hookSpecificOutput", {})
            assert hook_output.get("permissionDecision") != "deny"

    def test_blocks_memory_file_but_allows_config(self):
        """Memory files should still be blocked while config file is allowed."""
        # Config file -- allowed
        config_input = {
            "tool_input": {
                "file_path": "/home/user/project/.claude/memory/memory-config.json",
            }
        }
        config_stdout, config_rc = run_guard(config_input)
        assert config_rc == 0
        if config_stdout.strip():
            output = json.loads(config_stdout)
            assert output.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"

        # Memory file -- blocked
        memory_input = {
            "tool_input": {
                "file_path": "/home/user/project/.claude/memory/decisions/test.json",
            }
        }
        memory_stdout, memory_rc = run_guard(memory_input)
        assert memory_rc == 0
        if memory_stdout.strip():
            output = json.loads(memory_stdout)
            assert output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"

    def test_config_file_in_different_project_paths(self):
        """Config file under various project roots should all be allowed."""
        paths = [
            "/home/alice/work/myproject/.claude/memory/memory-config.json",
            "/Users/bob/projects/webapp/.claude/memory/memory-config.json",
            "/tmp/test-project/.claude/memory/memory-config.json",
            "/home/user/.claude/memory/memory-config.json",
        ]
        for path in paths:
            hook_input = {"tool_input": {"file_path": path}}
            stdout, rc = run_guard(hook_input)
            assert rc == 0, f"Non-zero exit for path: {path}"
            if stdout.strip():
                output = json.loads(stdout)
                hook_output = output.get("hookSpecificOutput", {})
                assert hook_output.get("permissionDecision") != "deny", (
                    f"Config file incorrectly blocked at: {path}"
                )

    def test_config_file_in_subdirectory_still_blocked(self):
        """memory-config.json inside a category subfolder should still be blocked."""
        subdirs = ["decisions", "sessions", "runbooks", "constraints", "tech-debt", "preferences"]
        for subdir in subdirs:
            hook_input = {
                "tool_input": {
                    "file_path": f"/home/user/project/.claude/memory/{subdir}/memory-config.json",
                }
            }
            stdout, rc = run_guard(hook_input)
            assert rc == 0
            if stdout.strip():
                output = json.loads(stdout)
                hook_output = output.get("hookSpecificOutput", {})
                assert hook_output.get("permissionDecision") == "deny", (
                    f"memory-config.json in {subdir}/ should be blocked"
                )

    def test_similar_config_filenames_still_blocked(self):
        """Files with names similar to memory-config.json should still be blocked."""
        # These are NOT the config file -- they should go through normal
        # path checking and be blocked because they are in .claude/memory/
        similar_names = [
            "not-memory-config.json",
            "memory-config.json.bak",
            "memory-config.jsonl",
            "memory-config.json.invalid.12345",
            "my-memory-config.json",
            "memory-config-v2.json",
        ]
        for name in similar_names:
            hook_input = {
                "tool_input": {
                    "file_path": f"/home/user/project/.claude/memory/{name}",
                }
            }
            stdout, rc = run_guard(hook_input)
            assert rc == 0, f"Non-zero exit for: {name}"
            if stdout.strip():
                output = json.loads(stdout)
                hook_output = output.get("hookSpecificOutput", {})
                assert hook_output.get("permissionDecision") == "deny", (
                    f"File '{name}' was incorrectly allowed -- should be blocked"
                )


# ============================================================
# Staging Auto-Approve Tests (Phase 1 popup fix)
# ============================================================

class TestStagingAutoApprove:
    """Tests for the staging file auto-approve behavior."""

    def test_staging_intent_json_emits_allow(self, tmp_path):
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "intent-decision.json"
        f.write_text('{"intent": "create"}')
        hook_input = {"tool_input": {"file_path": str(f)}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        assert parse_decision(stdout) == "allow"

    def test_staging_triage_data_emits_allow(self, tmp_path):
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "triage-data.json"
        f.write_text('{"categories": []}')
        hook_input = {"tool_input": {"file_path": str(f)}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        assert parse_decision(stdout) == "allow"

    def test_staging_last_save_result_emits_allow(self, tmp_path):
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "last-save-result.json"
        f.write_text('{"saved_at": "2026-01-01"}')
        hook_input = {"tool_input": {"file_path": str(f)}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        assert parse_decision(stdout) == "allow"

    def test_staging_context_txt_emits_allow(self, tmp_path):
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "context-session.txt"
        f.write_text("session notes")
        hook_input = {"tool_input": {"file_path": str(f)}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        assert parse_decision(stdout) == "allow"

    def test_staging_new_file_emits_allow(self, tmp_path):
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        path = str(staging_dir / "intent-new.json")
        hook_input = {"tool_input": {"file_path": path}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        assert parse_decision(stdout) == "allow"

    def test_staging_unknown_filename_no_allow(self, tmp_path):
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "evil.json"
        f.write_text('{"evil": true}')
        hook_input = {"tool_input": {"file_path": str(f)}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        assert parse_decision(stdout) != "allow"

    def test_staging_wrong_extension_no_allow(self, tmp_path):
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "intent-evil.py"
        f.write_text("print('evil')")
        hook_input = {"tool_input": {"file_path": str(f)}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        assert parse_decision(stdout) != "allow"

    def test_staging_hardlink_no_allow(self, tmp_path):
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        original = other_dir / "target.json"
        original.write_text('{"target": true}')
        hardlink = staging_dir / "intent-evil.json"
        os.link(str(original), str(hardlink))
        assert os.stat(str(hardlink)).st_nlink == 2
        hook_input = {"tool_input": {"file_path": str(hardlink)}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        assert parse_decision(stdout) != "allow"

    def test_staging_traversal_denied(self, tmp_path):
        decisions_dir = tmp_path / ".claude" / "memory" / "decisions"
        decisions_dir.mkdir(parents=True)
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = decisions_dir / "evil.json"
        f.write_text('{"evil": true}')
        traversal_path = str(staging_dir / ".." / "decisions" / "evil.json")
        hook_input = {"tool_input": {"file_path": traversal_path}}
        stdout, rc = run_guard(hook_input)
        assert rc == 0
        assert parse_decision(stdout) == "deny"

    def test_staging_all_known_filenames(self, tmp_path):
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        known_files = [
            "intent-decision.json", "input-session.json",
            "draft-runbook.json", "context-constraint.txt",
            "new-info-tech_debt.txt", "triage-data.json",
            "candidate-preference.json", "last-save-result.json",
            ".triage-pending.json",
        ]
        for fname in known_files:
            f = staging_dir / fname
            f.write_text("{}")
            hook_input = {"tool_input": {"file_path": str(f)}}
            stdout, rc = run_guard(hook_input)
            assert rc == 0
            assert parse_decision(stdout) == "allow", (
                f"Known staging file {fname} should auto-approve"
            )
