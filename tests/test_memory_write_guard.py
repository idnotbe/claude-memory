"""Tests for memory_write_guard.py -- PreToolUse guard against direct writes."""

import json
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
